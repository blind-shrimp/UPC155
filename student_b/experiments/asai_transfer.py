#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Directional-prior transfer to external DFL/ISSIA tracks + matched MAP/Bayes on Asai.

Two stages share one frozen physical model (canonical capped law, Cd = .27):

transfer
    Fit the early prefix with a free initial offset (|dr0| <= 5 cm) under three
    prior blocks and score the held-out future:
      none    position residuals only
      manual  |c| ~ N(.24, .08^2) and c_vert ~ N(.06, .06^2)   (no c_lat sign)
      pooled  same two-component form, means/SDs from the three archived Asai
              full-track fits, SD floors fixed at .08/.06.  The pooled prior
              never sees a DFL/ISSIA outcome; no external outcome enters any fit.
    Prefixes: DFL 0/.04/.08 s against the case_config target plane, ISSIA
    0/0.04/0.08 s (25 fps) against a forward plane only if the OBSERVED track
    actually reaches it, 11 extra DFL clips (no target plane) as a supplementary
    cohort.  Noise is 15 mm for DFL and an explicitly hypothetical 30 mm for
    ISSIA.  The local forward axis is taken from the first three points for the
    global-frame clips only (extra DFL, ISSIA) and applied to the whole clip, so
    the reference is transformed identically.  Observed initial height is kept.

estimators
    Same Asai model, but the spin vector is generated from a FIXED early
    velocity/basis for BOTH estimators, so the latent MAP and the importance
    sampler share the state bounds, the prior density (w.r.t. dc_vert dc_lat,
    i.e. exp(-0.5 * penalty^2) with no radial Jacobian), Cd, sigma and bounds.
    The sampler uses uniform draws of c on [-.3, .3]^2 plus a Gaussian
    conditional state proposal; the proposal correction 0.5*|z|^2 is included.
    Reports the latent MAP, the predictive mean and a weighted KDE mode of the
    11 m crossing, plus ESS, crossing mass and predictive intervals.

Scoring is separate from fitting: `fit_prefix` only ever receives the prefix
arrays, and the future is opened by `score_case` after every prediction has
been fixed.

CLI
  python asai_transfer.py --stage all --out integration/student_b/runs/asai_transfer
  python asai_transfer.py --stage transfer
  python asai_transfer.py --selftest

Only per-case scalars, model predictions and sha256 hashes are written; no raw
observation table is exported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.ndimage import gaussian_filter
from scipy.optimize import least_squares

HERE = Path(__file__).resolve()
EXPERIMENTS = HERE.parent                 # integration/student_b/experiments
SB = HERE.parents[1]                      # integration/student_b
ROOT = HERE.parents[3]                    # repository root
DEPS = ROOT / 'deliverables/asai_official/read_deps'
for _p in (str(EXPERIMENTS), str(SB), str(DEPS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import asai_factorial as AF                              # noqa: E402
from physics import Config, derivative, rk4              # noqa: E402
from validate_real_penalties import read_csv             # noqa: E402
from validate_real_spin import advance                   # noqa: E402

# ---------------------------------------------------------------------------
# Frozen constants
# ---------------------------------------------------------------------------
GOAL = AF.GOAL
SIGMA_DFL = .015
SIGMA_ISSIA = .030                 # explicitly hypothetical for ISSIA
CL_BOUND = .30                     # estimator support, both coordinates
DR0_BOUND = AF.DR0_BOUND           # .05 m, shared by MAP and sampler
KDE_BW = .025                      # metres, fixed Gaussian bandwidth
KDE_STEP = .01                     # metres, fixed KDE grid step
V_LOW = np.array([5., -60., -60.])
V_HIGH = np.array([60., 60., 60.])
ESTIMATOR_SEEDS = ((0., 0.), (.21, .21), (.21, -.21), (-.21, .21),
                   (-.21, -.21), (.06, -.24), (.24, 0.))
TRANSFER_METHODS = ('none', 'manual', 'pooled')

TRANSFER_FIELDS = (
    'method', 'prior', 'case', 'cohort', 'sigma_m', 'target_x_m', 'error_cm',
    'heldout_rmse_cm', 'last_frame_error_cm', 'plane_error_cm',
    'plane_time_error_s', 'frames_eligible', 'frames_scored',
    'post_plane_frames_excluded', 'excluded_observed_frames', 'missing_frames',
    'n_starts', 'n_converged', 'best_converged', 'cost', 'data_ss', 'prior_ss',
    'c_vert', 'c_lat', 'cl_mag', 'v0_m_s', 'dr0_m', 'pred_plane_yz_m',
    'crossing_time_s', 'ground_time_s', 'prediction_note', 'note_score')

CASE_ENTRY_FIELDS = (
    'error_cm', 'heldout_rmse_cm', 'last_frame_error_cm', 'plane_error_cm',
    'plane_time_error_s', 'frames_eligible', 'frames_scored',
    'post_plane_frames_excluded', 'excluded_observed_frames', 'missing_frames',
    'cost', 'data_ss', 'prior_ss', 'c_vert', 'c_lat', 'cl_mag', 'v0_m_s',
    'dr0_m', 'pred_plane_yz_m', 'crossing_time_s', 'ground_time_s',
    'n_starts', 'n_converged', 'best_converged', 'prediction_note', 'note_score',
    'branches')


def mean_or_none(values):
    vals = [float(v) for v in values if v is not None]
    return None if not vals else float(np.mean(vals))


def _fmt(value, digits=2):
    if value is None:
        return '—'
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return f'{float(value):.{digits}f}'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Geometry / case construction
# ---------------------------------------------------------------------------
def align_track(points, prefix=3):
    """Rotate x,y so that the early forward axis is +x; z is untouched.

    The rotation uses only points[0] and points[prefix-1]; every row (prefix and
    future, hence the reference) goes through the same map.
    """
    raw = np.asarray(points, float)
    if raw.ndim != 2 or raw.shape[1] != 3 or len(raw) < prefix:
        raise ValueError('align_track needs an (n>=prefix, 3) array')
    forward = raw[prefix - 1, :2] - raw[0, :2]
    norm = float(np.linalg.norm(forward))
    if norm < 1e-9:
        raise ValueError('degenerate early forward axis')
    forward = forward / norm
    rotation = np.stack((forward, np.array([-forward[1], forward[0]])), axis=1)
    return np.column_stack(((raw[:, :2] - raw[0, :2]) @ rotation, raw[:, 2]))


def plane_reference(times, points, target):
    """Interpolated (y,z) where the OBSERVED track crosses x = target, or None."""
    if target is None:
        return None, None
    pts = np.asarray(points, float)
    times = np.asarray(times, float)
    hit = np.flatnonzero((pts[:-1, 0] < target) & (pts[1:, 0] >= target))
    if not len(hit):
        return None, None
    i = int(hit[0])
    span = pts[i + 1, 0] - pts[i, 0]
    if abs(span) < 1e-12:
        return None, None
    fraction = (target - pts[i, 0]) / span
    return (pts[i] + fraction * (pts[i + 1] - pts[i]))[1:], \
        float(times[i] + fraction * (times[i + 1] - times[i]))


def build_case(name, cohort, times, points, sigma, target=None, align=False,
               prefix=3, source=None, note=''):
    times = np.asarray(times, float)
    points = np.asarray(points, float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError(f'{name}: points must be (n, 3)')
    if len(times) != len(points):
        raise ValueError(f'{name}: times and points disagree')
    if len(times) <= prefix:
        raise ValueError(f'{name}: need more than {prefix} frames')
    if not np.all(np.diff(times) > 0):
        raise ValueError(f'{name}: times must increase')
    if not np.isfinite(points).all():
        raise ValueError(f'{name}: non-finite observation')
    local = align_track(points, prefix) if align else points.copy()
    ref, ref_time = plane_reference(times, local, target)
    future = local[prefix:]
    return dict(
        case=name, cohort=cohort, sigma=float(sigma),
        target_x=None if target is None else float(target),
        spacing=float(times[1] - times[0]),
        fit_times=times[:prefix].copy(), fit_points=local[:prefix].copy(),
        future_times=times[prefix:].copy(), future_points=future.copy(),
        reference_yz_m=ref, reference_time_s=ref_time,
        observed_start_height_m=float(local[0, 2]),
        forward_reach_m=float(np.max(future[:, 0])),
        alignment='early_forward_axis' if align else 'identity_local_frame',
        n_future=int(len(future)), source=dict(source or {}), note=note)


def case_meta(case):
    """Public, observation-free description of one case."""
    return dict(case=case['case'], cohort=case['cohort'], sigma_m=case['sigma'],
                target_x_m=case['target_x'], spacing_s=case['spacing'],
                n_future=case['n_future'],
                observed_start_height_m=case['observed_start_height_m'],
                forward_reach_m=case['forward_reach_m'],
                plane_defined=bool(case['target_x'] is not None),
                reference_yz_m=None if case['reference_yz_m'] is None
                else np.asarray(case['reference_yz_m'], float).tolist(),
                reference_time_s=case['reference_time_s'],
                alignment=case['alignment'], note=case['note'], source=case['source'])


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def load_dfl_penalty(data_dir, names=('J03WOH', 'J03WR9')):
    data_dir = Path(data_dir)
    specs = json.loads((data_dir / 'case_config.json').read_text(encoding='utf-8-sig'))
    inputs = read_csv(data_dir / 'inputs_only.csv')
    held = read_csv(data_dir / 'held_out.csv')
    cases = []
    for name in names:
        prefix = sorted((r for r in inputs if r['case_id'] == name),
                        key=lambda r: float(r['t_s']))
        future = sorted((r for r in held if r['case_id'] == name),
                        key=lambda r: float(r['t_s']))
        if len(prefix) != 3 or not future:
            raise ValueError(f'{name}: expected 3 input rows and a non-empty held-out block')
        rows = prefix + future
        times = np.array([float(r['t_s']) for r in rows])
        points = np.array([[float(r['x_m']), float(r['y_m']), float(r['z_m'])]
                           for r in rows])
        target = specs[name]['target_local_x_m']
        if target is None:
            raise ValueError(f'{name}: missing target_local_x_m')
        cases.append(build_case(
            name, 'dfl_penalty', times, points, SIGMA_DFL, target=target,
            align=False,
            source=dict(kind='dfl_penalty', observation_type=rows[0]['observation_type'],
                        target_local_center_y_m=specs[name].get('target_local_center_y_m'),
                        n_input=len(prefix))))
    return cases


def load_issia(seg_dir, names=('seg_0608_0627', 'seg_1144_1172'), fps=25.0):
    seg_dir = Path(seg_dir)
    cases = []
    for name in names:
        path = seg_dir / f'{name}.csv'
        if not path.is_file():
            raise FileNotFoundError(f'{path} missing')
        rows = read_csv(path)
        rows = sorted(rows, key=lambda r: float(r['frame_id']))
        if not rows:
            raise ValueError(f'{name}: empty segment')
        good = [str(r['has_3d']).strip().lower() in ('true', '1') for r in rows]
        if not all(good):
            raise ValueError(f'{name}: has_3d is false in {good.count(False)} rows')
        frames = np.array([float(r['frame_id']) for r in rows])
        times = (frames - frames[0]) / fps
        points = np.array([[float(r['x_m']), float(r['y_m']), float(r['z_up_m'])]
                           for r in rows])
        cases.append(build_case(
            name, 'issia', times, points, SIGMA_ISSIA, target=GOAL, align=True,
            source=dict(kind='issia_segment', fps=fps, frames=int(len(rows)),
                        file=path.name, run_id=rows[0].get('continuity_run_id'))))
    return cases


def load_extra_dfl(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f'{path} missing')
    groups = {}
    for row in read_csv(path):
        groups.setdefault(row['case_id'], []).append(row)
    cases = []
    for name in sorted(groups):
        rows = sorted(groups[name], key=lambda r: float(r['t_s']))
        roles = [str(r['role']).strip() for r in rows]
        if roles.count('input') != 3 or roles[:3] != ['input', 'input', 'input']:
            raise ValueError(f'{name}: expected three leading input rows, got {roles[:4]}')
        times = np.array([float(r['t_s']) for r in rows])
        points = np.array([[float(r['x_m']), float(r['y_m']), float(r['z_m'])]
                           for r in rows])
        cases.append(build_case(
            name, 'dfl_extra', times, points, SIGMA_DFL, target=None, align=True,
            source=dict(kind='dfl_extra', match_id=rows[0]['match_id'],
                        n_input=3, n_held_out=int(len(rows) - 3))))
    return cases


# ---------------------------------------------------------------------------
# Transfer: fit (prefix only) and predict
# ---------------------------------------------------------------------------
def start_grid(points, spacing, c_seeds=None):
    """Multi-starts with the ACTUAL prefix spacing (the factorial used .05)."""
    c_seeds = AF.C_SEEDS if c_seeds is None else c_seeds
    points = np.asarray(points, float)
    p0, p1, p2 = points[:3]
    dt = float(spacing)
    if not dt > 0:
        raise ValueError('positive prefix spacing required')
    acceleration = (p2 - 2. * p1 + p0) / dt ** 2
    velocities = {'quad': (p1 - p0) / dt - .5 * dt * acceleration,
                  'linear': (p2 - p0) / (2. * dt)}
    starts = []
    for c_label, c in c_seeds:
        for v_label, velocity in velocities.items():
            x0 = np.r_[np.zeros(3), np.clip(velocity, V_LOW, V_HIGH),
                       np.asarray(c, float)]
            starts.append((f'{c_label}/{v_label}', x0))
    return starts


def fit_prefix(times, points, sigma, prior, prior_params=None, c_seeds=None):
    """Branch selection uses the TRAINING cost only; no future is accepted here."""
    times = np.asarray(times, float)
    points = np.asarray(points, float)
    starts = start_grid(points, float(times[1] - times[0]), c_seeds)
    rows = [AF.run_start(label, x0, 'canon', prior, 'free3', prior_params,
                         times, points, float(sigma))
            for label, x0 in starts]
    converged = [r for r in rows if r.get('converged') and r.get('cost') is not None]
    usable = converged or [r for r in rows if r.get('cost') is not None]
    best = None
    if usable:
        best = min(usable, key=lambda r: (round(r['cost'], 12), r['c_vert'],
                                          r['c_lat'], *r['v0_m_s']))
    for row in rows:
        row['is_best'] = row is best
    return dict(rows=rows, best=best, n_converged=len(converged),
                best_converged=None if best is None else bool(best['converged']))


def predict_track(c, v0, dr0, start_point, query_times, target=None, cfg=None):
    """Integrate the fitted branch and sample it at query_times, stopping at ground."""
    cfg = AF.CFG if cfg is None else cfg
    query = np.asarray(query_times, float)
    empty = dict(times=[], xyz=[], available=0, n_query=int(len(query)),
                 ground_time_s=None, crossing_yz_m=None, crossing_time_s=None,
                 note='no query time')
    if not len(query):
        return empty
    t_end = float(np.max(query))
    if not np.isfinite(t_end) or t_end <= 0:
        return empty
    rhs = AF.make_rhs('canon', np.asarray(c, float), np.asarray(v0, float))
    y0 = np.r_[np.asarray(start_point, float) + np.asarray(dr0, float),
               np.asarray(v0, float)]

    def ground(t, y):
        return y[2] - cfg.radius

    ground.terminal = True
    ground.direction = -1
    try:
        sol = solve_ivp(rhs, (0., t_end), y0, events=(ground,), dense_output=True,
                        rtol=1e-9, atol=1e-10, max_step=.01)
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        return {**empty, 'note': f'integration failed: {exc}'}
    if not sol.success:
        return {**empty, 'note': f'integration failed: {sol.message}'}
    ground_time = float(sol.t_events[0][0]) if len(sol.t_events[0]) else None
    horizon = t_end if ground_time is None else min(t_end, ground_time)
    keep = query <= horizon + 1e-12
    if keep.any():
        xyz = np.atleast_2d(sol.sol(query[keep])[:3].T)
    else:
        xyz = np.zeros((0, 3))
    crossing_yz, crossing_time, note = None, None, 'ok'
    if target is not None:
        grid = np.arange(0., horizon + 1e-12, .002)
        if len(grid) >= 2:
            traj = np.atleast_2d(sol.sol(grid)[:3].T)
            hit = np.flatnonzero((traj[:-1, 0] < target) & (traj[1:, 0] >= target))
            if len(hit):
                i = int(hit[0])
                span = traj[i + 1, 0] - traj[i, 0]
                fraction = (target - traj[i, 0]) / span
                crossing_yz = traj[i] + fraction * (traj[i + 1] - traj[i])
                crossing_time = float(grid[i] + fraction * (grid[i + 1] - grid[i]))
            else:
                note = ('ground contact before the target plane' if ground_time is not None
                        else 'no target-plane crossing before the query horizon')
    return dict(times=query[keep].tolist(), xyz=xyz.tolist(),
                available=int(keep.sum()), n_query=int(len(query)),
                ground_time_s=ground_time,
                crossing_yz_m=None if crossing_yz is None else crossing_yz[1:3].tolist(),
                crossing_time_s=crossing_time, note=note)


def predict_case(case, fit):
    best = fit.get('best')
    if best is None:
        return dict(times=[], xyz=[], available=0, n_query=case['n_future'],
                    ground_time_s=None, crossing_yz_m=None, crossing_time_s=None,
                    note='no fitted branch')
    return predict_track(np.array([best['c_vert'], best['c_lat']]),
                         np.asarray(best['v0_m_s'], float),
                         np.asarray(best['dr0_m'], float),
                         np.asarray(case['fit_points'], float)[0],
                         case['future_times'], case['target_x'])


def score_case(case, pred):
    """The only function that opens the held-out block; never called by a fit."""
    future_times = np.asarray(case['future_times'], float)
    future_points = np.asarray(case['future_points'], float)
    n_avail = int(pred.get('available') or 0)
    xyz = np.asarray(pred.get('xyz') or [], float).reshape(-1, 3)
    if n_avail != len(xyz):
        raise RuntimeError('predicted time/position length mismatch')
    if n_avail > len(future_times):
        raise RuntimeError('prediction is longer than the held-out track')
    below_ground = future_points[:, 2] <= AF.CFG.radius
    out = dict(prediction_available=bool(n_avail > 0), frames_total=int(len(future_times)),
               frames_predicted=n_avail,
               missing_frames=int(len(future_times) - n_avail),
               observed_frames_at_or_below_radius=int(below_ground.sum()))
    if n_avail == 0:
        out.update(heldout_rmse_cm=None, last_frame_error_cm=None, frames_eligible=0,
                   frames_scored=0, post_plane_frames_excluded=0,
                   excluded_observed_frames=int(below_ground.sum()),
                   plane_error_cm=None, plane_time_error_s=None,
                   note_score='no predicted frame')
        return out
    times = future_times[:n_avail]
    obs = future_points[:n_avail]
    geometric = ~below_ground[:n_avail]
    pre_plane = geometric.copy()
    reference_time = case['reference_time_s']
    if reference_time is not None:
        pre_plane &= times < float(reference_time) - 1e-12
    used = pre_plane
    out.update(frames_eligible=int(geometric.sum()), frames_scored=int(used.sum()),
               post_plane_frames_excluded=int((geometric & ~pre_plane).sum()),
               excluded_observed_frames=int((~geometric).sum()))
    if not used.any():
        out.update(heldout_rmse_cm=None, last_frame_error_cm=None,
                   plane_error_cm=None, plane_time_error_s=None,
                   note_score='all held-out frames excluded')
        return out
    residual = xyz[used] - obs[used]
    plane_cm, plane_dt = None, None
    if case['reference_yz_m'] is not None and pred.get('crossing_yz_m') is not None:
        plane_cm = 100. * float(np.linalg.norm(
            np.asarray(pred['crossing_yz_m'], float)
            - np.asarray(case['reference_yz_m'], float)))
        if pred.get('crossing_time_s') is not None and reference_time is not None:
            plane_dt = float(pred['crossing_time_s'] - reference_time)
    out.update(
        heldout_rmse_cm=100. * float(np.sqrt(np.mean(np.sum(residual ** 2, axis=1)))),
        last_frame_error_cm=100. * float(np.linalg.norm(residual[-1])),
        plane_error_cm=plane_cm, plane_time_error_s=plane_dt,
        note_score='ok' if (plane_cm is not None
                            or case['reference_yz_m'] is None) else 'no plane estimate')
    return out


def evaluate_transfer(cases, prior_specs, c_seeds=None):
    rows = []
    for method in prior_specs:
        prior_name, params = prior_specs[method]
        for case in cases:
            fit = fit_prefix(case['fit_times'], case['fit_points'], case['sigma'],
                             prior_name, params, c_seeds)
            pred = predict_case(case, fit)
            score = score_case(case, pred)
            best = fit['best']
            row = dict(method=method, prior=prior_name, case=case['case'],
                       cohort=case['cohort'], sigma_m=case['sigma'],
                       target_x_m=case['target_x'],
                       n_starts=len(fit['rows']), n_converged=fit['n_converged'],
                       best_converged=fit['best_converged'],
                       cost=None if best is None else best['cost'],
                       data_ss=None if best is None else best['data_ss'],
                       prior_ss=None if best is None else best['prior_ss'],
                       c_vert=None if best is None else best['c_vert'],
                       c_lat=None if best is None else best['c_lat'],
                       cl_mag=None if best is None else best['cl_mag'],
                       v0_m_s=None if best is None else best['v0_m_s'],
                       dr0_m=None if best is None else best['dr0_m'],
                       pred_plane_yz_m=pred.get('crossing_yz_m'),
                       crossing_time_s=pred.get('crossing_time_s'),
                       ground_time_s=pred.get('ground_time_s'),
                       prediction_note=pred.get('note'),
                       # Every multi-start branch is kept; selection used training cost only.
                       branches=[dict(start=row.get('start'), cost=row.get('cost'),
                                      converged=row.get('converged'),
                                      c_vert=row.get('c_vert'), c_lat=row.get('c_lat'))
                                 for row in fit['rows']])
            row.update(score)
            # Primary metric, kept in the same `error_cm` slot as the factorial.
            row['error_cm'] = row['heldout_rmse_cm']
            rows.append(row)
    return rows, summarize_transfer(rows, cases, list(prior_specs))


def summarize_transfer(rows, cases, methods):
    names = [c['case'] for c in cases]
    primary = [c['case'] for c in cases if c['cohort'] in ('dfl_penalty', 'issia')]
    extra = [c['case'] for c in cases if c['cohort'] == 'dfl_extra']
    table = {}
    for method in methods:
        per_case = {}
        for name in names:
            match = next((r for r in rows if r['method'] == method and r['case'] == name), None)
            per_case[name] = None if match is None else {
                field: match.get(field) for field in CASE_ENTRY_FIELDS}

        def agg(field, subset):
            return mean_or_none(per_case[n].get(field) for n in subset
                                if per_case.get(n))
        table[method] = dict(
            method=method, per_case=per_case, cases=names,
            primary_cases=primary, extra_cases=extra,
            n_primary=len(primary), n_extra=len(extra),
            mean_error_cm=agg('error_cm', primary),
            mean_heldout_rmse_cm=agg('heldout_rmse_cm', primary),
            mean_last_frame_error_cm=agg('last_frame_error_cm', primary),
            mean_plane_error_cm=agg('plane_error_cm', primary),
            n_plane_error=sum(1 for name in primary
                              if (per_case.get(name) or {}).get('plane_error_cm') is not None),
            extra_mean_heldout_rmse_cm=agg('heldout_rmse_cm', extra),
            extra_mean_plane_error_cm=agg('plane_error_cm', extra),
            cohort_means={cohort: agg('heldout_rmse_cm',
                                      [n for n in names
                                       if next(c for c in cases if c['case'] == n)['cohort'] == cohort])
                          for cohort in sorted({c['cohort'] for c in cases})},
            n_cases=len(names))
    return table


def transfer_contrasts(table, cases, methods):
    pairs = [('manual', 'none'), ('pooled', 'none'), ('manual', 'pooled')]
    out = []
    for a, b in pairs:
        if a not in table or b not in table:
            continue
        for field in ('heldout_rmse_cm', 'plane_error_cm'):
            per_case = {}
            for case in cases:
                va = (table[a]['per_case'].get(case['case']) or {}).get(field)
                vb = (table[b]['per_case'].get(case['case']) or {}).get(field)
                per_case[case['case']] = None if va is None or vb is None else float(va - vb)
            out.append(dict(a=a, b=b, field=field, per_case=per_case,
                            mean=mean_or_none(per_case.values())))
    return out


# ---------------------------------------------------------------------------
# Asai source reference (original factorial evaluator, unmodified)
# ---------------------------------------------------------------------------
def load_pooled_prior(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f'{path} not found; the pooled prior needs the archived fits')
    payload = json.loads(path.read_text(encoding='utf-8'))
    fits = payload['checks']['full_track_fit']['fits']
    if set(fits) != set(AF.CASES):
        raise ValueError('archived full-track fits do not match the three Asai cases')
    prior = AF.fold_prior(fits, '__pooled__', AF.LOOCV_FLOOR)
    if prior['members'] != list(fits):
        raise RuntimeError('pooled prior membership mismatch')
    keep = ('cl_mag', 'c_vert', 'c_lat', 'cd', 'fit_rmse_cm')
    return prior, dict(
        source=str(path), sha256=sha256(path),
        members=list(fits),
        fits={key: {field: float(fits[key][field]) for field in keep} for key in fits},
        archived_rmse_cm=payload['checks']['full_track_fit'].get('archived_rmse_cm'),
        note='pooled prior uses all three Asai full-track fits; SD floors .08/.06; '
             'the held-out external clips never enter it')


def asai_cases(data_dir):
    data_dir = Path(data_dir)
    cases = {}
    for name, filename in AF.FILES.items():
        path = data_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f'{path} missing (--data-asai must hold the workbooks)')
        cases[name] = AF.load_case(name, path)
    return cases


def asai_reproduction(data_dir, pooled):
    """Archived factorial pipeline, unchanged, for continuity with 10.63/26.00."""
    cases = asai_cases(data_dir)
    specs = {'none': ('none', None), 'manual': ('manual', None),
             'pooled': ('loocv', pooled)}
    out = {}
    for method, (prior_name, params) in specs.items():
        per_case = {}
        for name in AF.CASES:
            result = AF.evaluate_trial(cases[name], 'canon', prior_name, 'free3', params)
            per_case[name] = dict(error_cm=result['error_cm'],
                                  prediction_yz_m=result['prediction'],
                                  best_cost=None if result['best'] is None
                                  else result['best']['cost'],
                                  best_converged=result['best_converged'],
                                  c_vert=None if result['best'] is None
                                  else result['best']['c_vert'],
                                  c_lat=None if result['best'] is None
                                  else result['best']['c_lat'])
        out[method] = dict(per_case=per_case,
                           mean_error_cm=mean_or_none(v['error_cm']
                                                      for v in per_case.values()),
                           n_cases=len(per_case))
    return dict(table=out, inputs={name: dict(workbook=cases[name]['workbook'],
                                              sha256=cases[name]['workbook_sha256'],
                                              reference_time_s=cases[name]['reference_time_s'],
                                              reference_yz_m=None
                                              if cases[name]['reference_yz_m'] is None
                                              else cases[name]['reference_yz_m'].tolist())
                                  for name in AF.CASES},
                archived=dict(none=26.00, manual=10.63, loocv=22.45),
                note='in-sample source reference, not external transfer; the same '
                     'evaluator that produced the archived 10.63/22.45/26.00 cm')


# ---------------------------------------------------------------------------
# Matched estimators: fixed early velocity/basis for BOTH algorithms
# ---------------------------------------------------------------------------
def early_velocity(times, points):
    points = np.asarray(points, float)
    dt = float(times[1] - times[0])
    if not dt > 0:
        raise ValueError('positive prefix spacing required')
    acceleration = (points[2] - 2. * points[1] + points[0]) / dt ** 2
    velocity = (points[1] - points[0]) / dt - .5 * dt * acceleration
    clipped = np.clip(velocity, V_LOW, V_HIGH)
    return clipped, bool(np.any(np.abs(clipped - velocity) > 1e-12))


def omega_from_c(c, frame):
    """Canonical spin for c = (c_vert, c_lat) in the FIXED early transverse frame."""
    c = np.atleast_2d(np.asarray(c, float))
    z_perp, y_perp, speed0 = frame
    omega = c[:, 1:2] * z_perp[None, :] - c[:, 0:1] * y_perp[None, :]
    return omega * (speed0 / (1.4 * AF.CFG.radius))


def prior_penalty(c, prior, params=None):
    """Residual form; exp(-.5*|p|^2) is the density w.r.t. dc_vert dc_lat."""
    if prior == 'none':
        return np.zeros(0)
    p = AF.PRIOR if params is None else params
    c = np.asarray(c, float)
    magnitude = math.hypot(float(c[0]), float(c[1]))
    if prior == 'iso':
        return np.array([(magnitude - p['mag_mean']) / p['mag_sd']])
    if prior in ('manual', 'pooled'):
        return np.array([(magnitude - p['mag_mean']) / p['mag_sd'],
                         (float(c[0]) - p['vert_mean']) / p['vert_sd']])
    raise ValueError(f'unknown prior {prior!r}')


def prior_logp(c, prior, params=None):
    c = np.atleast_2d(np.asarray(c, float))
    if prior == 'none':
        return np.zeros(len(c))
    p = AF.PRIOR if params is None else params
    magnitude = np.hypot(c[:, 0], c[:, 1])
    if prior == 'iso':
        return -.5 * ((magnitude - p['mag_mean']) / p['mag_sd']) ** 2
    if prior in ('manual', 'pooled'):
        return -.5 * (((magnitude - p['mag_mean']) / p['mag_sd']) ** 2
                      + ((c[:, 0] - p['vert_mean']) / p['vert_sd']) ** 2)
    raise ValueError(f'unknown prior {prior!r}')


def map_starts(times, points):
    points = np.asarray(points, float)
    dt = float(times[1] - times[0])
    acceleration = (points[2] - 2. * points[1] + points[0]) / dt ** 2
    velocities = {'quad': (points[1] - points[0]) / dt - .5 * dt * acceleration,
                  'linear': (points[2] - points[0]) / (2. * dt)}
    starts = []
    for c_vert, c_lat in ESTIMATOR_SEEDS:
        for label, velocity in velocities.items():
            starts.append((f'c({c_vert:+.2f},{c_lat:+.2f})/{label}',
                           np.r_[np.zeros(3), np.clip(velocity, V_LOW, V_HIGH),
                                 np.array([c_vert, c_lat])]))
    return starts


def map_estimator(times, points, sigma, prior, params, frame):
    """Latent MAP on the same support and density the sampler targets."""
    times = np.asarray(times, float)
    points = np.asarray(points, float)
    p0 = points[0]
    n_position = 3 * len(times)

    def residual(x):
        dr0, v0, c = x[:3], x[3:6], x[6:8]
        theta = np.r_[np.zeros(3), omega_from_c(c, frame)[0], AF.CD][None]
        sol = solve_ivp(lambda t, y: derivative(y[None], theta, t, AF.CFG)[0],
                        (0., times[-1]), np.r_[p0 + dr0, v0], t_eval=times,
                        rtol=1e-9, atol=1e-10)
        if not sol.success or sol.y.shape[1] != len(times):
            raise RuntimeError('prefix integration failed')
        position = (sol.y[:3].T - points) / sigma
        return np.r_[position.ravel(), prior_penalty(c, prior, params)]

    lower = np.r_[[-DR0_BOUND] * 3, V_LOW, -CL_BOUND, -CL_BOUND]
    upper = np.r_[[DR0_BOUND] * 3, V_HIGH, CL_BOUND, CL_BOUND]
    rows = []
    for label, x0 in map_starts(times, points):
        row = dict(start=label)
        try:
            fit = least_squares(residual, np.clip(x0, lower, upper),
                                bounds=(lower, upper), x_scale='jac', max_nfev=200)
        except Exception as exc:  # noqa: BLE001
            rows.append({**row, 'converged': False, 'cost': None,
                         'message': str(exc), 'status': -1, 'nfev': 0})
            continue
        fun = np.asarray(fit.fun, float)
        row.update(converged=bool(fit.success), status=int(fit.status),
                   message=str(fit.message), nfev=int(fit.nfev),
                   cost=float(.5 * (fun @ fun)),
                   data_ss=float(fun[:n_position] @ fun[:n_position]),
                   prior_ss=float(fun[n_position:] @ fun[n_position:]),
                   dr0_m=fit.x[:3].tolist(), v0_m_s=fit.x[3:6].tolist(),
                   c_vert=float(fit.x[6]), c_lat=float(fit.x[7]),
                   cl_mag=float(math.hypot(fit.x[6], fit.x[7])),
                   active_bounds=''.join('L' if m == 1 else 'U' if m == -1 else '.'
                                         for m in fit.active_mask),
                   x=fit.x.tolist())
        rows.append(row)
    converged = [r for r in rows if r.get('converged') and r.get('cost') is not None]
    usable = converged or [r for r in rows if r.get('cost') is not None]
    best = None
    if usable:
        best = min(usable, key=lambda r: (round(r['cost'], 12), r['c_vert'], r['c_lat']))
    return dict(rows=rows, best=best, n_starts=len(rows),
                n_converged=len(converged))


def posterior(times, points, sigma, prior, params, frame, count, seed, cfg):
    """Prior draw of c + Gaussian conditional state proposal -> importance weights.

    q(c) = uniform on the CL box, q(state | c) = N(linear conditional mean,
    sigma^2 (X'X)^-1); the weight is L * pi(c) * pi(state) / q, with the
    pi(state) constant dropped and the proposal correction .5*|z|^2 kept.
    """
    if count < 2:
        raise ValueError('need at least two draws')
    rng = np.random.default_rng(seed)
    times = np.asarray(times, float)
    points = np.asarray(points, float)
    c = rng.uniform(-CL_BOUND, CL_BOUND, (count, 2))
    omega = omega_from_c(c, frame)
    theta = np.column_stack((np.zeros((count, 3)), omega, np.full(count, AF.CD)))
    design = np.column_stack((np.ones(len(times)), times))
    inverse = np.linalg.pinv(design)
    linear = inverse @ points
    initial = np.zeros((count, 6))
    initial[:, :3] = linear[0]
    initial[:, 3:] = linear[1]
    nominal = initial.copy()
    offsets = []
    previous = 0.
    for t in times:
        nominal = advance(nominal, theta, previous, t, cfg)
        offsets.append(nominal[:, :3] - initial[:, :3] - t * initial[:, 3:])
        previous = t
    offsets = np.stack(offsets, axis=1)
    mean = np.einsum('ij,njk->nik', inverse, points - offsets)
    covariance = sigma ** 2 * np.linalg.inv(design.T @ design)
    chol = np.linalg.cholesky(covariance)
    standard = rng.normal(size=mean.shape)
    proposed = mean + np.einsum('ij,njk->nik', chol, standard)
    state = np.column_stack((proposed[:, 0], proposed[:, 1]))
    ok = (np.abs(state[:, :3] - points[0]) <= DR0_BOUND + 1e-12).all(axis=1)
    ok &= (state[:, 3] >= V_LOW[0]) & (state[:, 3] <= V_HIGH[0])
    ok &= (np.abs(state[:, 4:]) <= V_HIGH[1:]).all(axis=1)
    ok &= state[:, 2] > cfg.radius
    rss = np.zeros(count)
    current = state.copy()
    previous = 0.
    for t, observed in zip(times, points):
        current = advance(current, theta, previous, t, cfg)
        ok &= current[:, 2] > cfg.radius
        rss += np.sum((current[:, :3] - observed) ** 2, axis=1)
        previous = t
    log_weight = (-.5 * rss / sigma ** 2
                  + .5 * np.sum(standard ** 2, axis=(1, 2))
                  + prior_logp(c, prior, params))
    log_weight = np.where(ok, log_weight, -np.inf)
    if not np.isfinite(log_weight).any():
        raise ValueError('no accepted draw; check bounds or sigma')
    log_weight -= float(np.max(log_weight))
    weight = np.exp(log_weight)
    weight /= float(weight.sum())
    return dict(state=state, theta=theta, c=c, weights=weight,
                sigma=float(sigma), samples=int(count), seed=int(seed),
                accepted_fraction=float(ok.mean()),
                max_weight=float(weight.max()),
                ess=float(1. / float(weight @ weight)))


def endpoint_draws(r0, v0, theta, target, cfg):
    """Fixed-step vectorised rk4 to x = target; NaN when ground contact wins."""
    r0 = np.atleast_2d(np.asarray(r0, float))
    v0 = np.atleast_2d(np.asarray(v0, float))
    theta = np.atleast_2d(np.asarray(theta, float))
    n = len(r0)
    goal = np.full((n, 2), np.nan)
    if n == 0:
        return goal
    state = np.column_stack((r0, v0))
    alive = np.ones(n, bool)
    t = 0.
    while t < cfg.horizon - 1e-12 and alive.any():
        h = min(cfg.dt, cfg.horizon - t)
        index = np.flatnonzero(alive)
        old = state[index]
        new = rk4(old, theta[index], t, h, cfg)
        cross = (old[:, 0] < target) & (new[:, 0] >= target)
        ground = (new[:, 2] <= cfg.radius) & (new[:, 2] < old[:, 2])
        fraction = np.zeros(len(index))
        span = new[:, 0] - old[:, 0]
        np.divide(target - old[:, 0], span, out=fraction,
                  where=np.abs(span) > 1e-12)
        ground_fraction = np.full(len(index), np.inf)
        drop = new[:, 2] - old[:, 2]
        np.divide(cfg.radius - old[:, 2], drop, out=ground_fraction,
                  where=np.abs(drop) > 1e-12)
        wins = cross & (fraction <= ground_fraction)
        goal[index[wins]] = (old[wins, 1:3]
                             + fraction[wins, None] * (new[wins, 1:3] - old[wins, 1:3]))
        state[index] = new
        alive[index[ground | cross]] = False
        t += h
    return goal


def marginal_intervals(points, weights):
    levels = (.025, .975)
    out = []
    for coordinate in points.T:
        order = np.argsort(coordinate)
        cumulative = np.cumsum(weights[order])
        cumulative = cumulative / cumulative[-1]
        out.append(np.interp(levels, cumulative, coordinate[order]))
    return np.asarray(out)


def joint_rectangle(points, weights):
    mean = weights @ points
    sd = np.sqrt(weights @ (points - mean) ** 2)
    score = np.max(np.abs(points - mean) / np.maximum(sd, 1e-12), axis=1)
    order = np.argsort(score)
    cumulative = np.cumsum(weights[order])
    cumulative = cumulative / cumulative[-1]
    index = min(int(np.searchsorted(cumulative, .95)), len(order) - 1)
    radius = float(score[order][index])
    half = radius * sd
    return (np.column_stack((mean - half, mean + half)),
            float(weights[score <= radius].sum()))


def kde_mode(points, weights, bandwidth=KDE_BW, step=KDE_STEP):
    low = points.min(axis=0) - 3. * bandwidth
    high = points.max(axis=0) + 3. * bandwidth
    edges = [np.arange(low[i], high[i] + step, step) for i in (0, 1)]
    if len(edges[0]) < 2 or len(edges[1]) < 2:
        return points[np.argmax(weights)]
    counts = np.histogram2d(points[:, 0], points[:, 1], bins=edges,
                            weights=weights)[0]
    density = gaussian_filter(counts, sigma=bandwidth / step, mode='nearest')
    i, j = np.unravel_index(int(np.argmax(density)), density.shape)
    return np.array([edges[0][i] + step / 2., edges[1][j] + step / 2.])


def weighted_median(values, weights):
    values = np.asarray(values, float)
    order = np.argsort(values)
    cumulative = np.cumsum(np.asarray(weights, float)[order])
    cumulative = cumulative / cumulative[-1]
    return float(np.interp(.5, cumulative, values[order]))


def summarise_draws(draws, target, reference, cfg, bandwidth=KDE_BW):
    goal = endpoint_draws(draws['state'][:, :3], draws['state'][:, 3:],
                          draws['theta'], target, cfg)
    weight = draws['weights']
    crossing = np.isfinite(goal[:, 0]) & (weight > 0)
    mass = float(weight[crossing].sum())
    out = dict(samples=draws['samples'], seed=draws['seed'],
               ess=draws['ess'], max_weight=draws['max_weight'],
               accepted_fraction=draws['accepted_fraction'],
               n_crossing=int(crossing.sum()), crossing_mass=mass,
               ess_crossing=None, predictive_mean_yz_m=None,
               predictive_mean_error_cm=None, kde_mode_yz_m=None,
               kde_mode_error_cm=None, kde_bandwidth_m=float(bandwidth),
               kde_grid_m=KDE_STEP, interval95_yz_m=None,
               joint95_rectangle_yz_m=None, joint95_mass=None,
               post_mean_c=(weight @ draws['c']).tolist(),
               post_median_cl_mag=weighted_median(np.hypot(draws['c'][:, 0],
                                                           draws['c'][:, 1]), weight))
    if mass <= 0:
        return out
    points = goal[crossing]
    normalised = weight[crossing] / mass
    mean = normalised @ points
    mode = kde_mode(points, normalised, bandwidth)
    rectangle, rectangle_mass = joint_rectangle(points, normalised)
    out.update(ess_crossing=float(1. / float(normalised @ normalised)),
               predictive_mean_yz_m=mean.tolist(),
               kde_mode_yz_m=np.asarray(mode, float).tolist(),
               interval95_yz_m=marginal_intervals(points, normalised).tolist(),
               joint95_rectangle_yz_m=rectangle.tolist(),
               joint95_mass=rectangle_mass)
    if reference is not None:
        ref = np.asarray(reference, float)
        out['predictive_mean_error_cm'] = 100. * float(np.linalg.norm(mean - ref))
        out['kde_mode_error_cm'] = 100. * float(np.linalg.norm(mode - ref))
    return out


def estimator_stage(args, pooled, cfg):
    cases = asai_cases(args.data_asai)
    params = {'none': None, 'manual': AF.PRIOR, 'pooled': pooled}
    maps, records, notes = [], [], []
    for name in AF.CASES:
        trial = cases[name]
        index = trial['obs_index']
        times = np.asarray(trial['times'][index], float)
        points = np.asarray(trial['points'][index], float)
        reference = trial['reference_yz_m']
        velocity, clipped = early_velocity(times, points)
        frame = AF.transverse_frame(velocity)
        if clipped:
            notes.append(f'{name}: early velocity clipped to the state bounds')
        for method in args.estimator_priors:
            fit = map_estimator(times, points, AF.SIGMA, method, params[method], frame)
            best = fit['best']
            if best is None:
                maps.append(dict(case=name, prior=method, failed=True,
                                 n_starts=fit['n_starts'],
                                 n_converged=fit['n_converged']))
                continue
            c_map = np.array([best['c_vert'], best['c_lat']])
            omega = omega_from_c(c_map, frame)[0]
            goal = endpoint_draws(points[0] + np.asarray(best['dr0_m'], float),
                                  np.asarray(best['v0_m_s'], float),
                                  np.r_[np.zeros(3), omega, AF.CD][None],
                                  GOAL, cfg)[0]
            crossing = None if not np.isfinite(goal[0]) else goal
            maps.append(dict(
                case=name, prior=method, failed=False,
                c_vert=best['c_vert'], c_lat=best['c_lat'], cl_mag=best['cl_mag'],
                dr0_m=best['dr0_m'], v0_m_s=best['v0_m_s'], cost=best['cost'],
                prior_ss=best['prior_ss'], active_bounds=best.get('active_bounds'),
                n_starts=fit['n_starts'], n_converged=fit['n_converged'],
                branches=[dict(start=row.get('start'), cost=row.get('cost'),
                               converged=row.get('converged'),
                               c_vert=row.get('c_vert'), c_lat=row.get('c_lat'))
                          for row in fit['rows']],
                map_crossing_yz_m=None if crossing is None else crossing.tolist(),
                map_error_cm=None if crossing is None or reference is None
                else 100. * float(np.linalg.norm(crossing - reference)),
                cl0_capped=bool(abs(AF.canonical_initial_cl(c_map, velocity)
                                    - float(np.hypot(*c_map))) > 1e-9)))
            for seed in args.seeds:
                draws = posterior(times, points, AF.SIGMA, method, params[method],
                                  frame, args.samples, seed, cfg)
                entry = summarise_draws(draws, GOAL, reference, cfg)
                if (entry['ess'] < args.ess_floor
                        and args.escalate_to > args.samples):
                    draws = posterior(times, points, AF.SIGMA, method, params[method],
                                      frame, args.escalate_to, seed, cfg)
                    entry = summarise_draws(draws, GOAL, reference, cfg)
                    entry['escalated'] = True
                else:
                    entry['escalated'] = False
                entry.update(case=name, prior=method)
                records.append(entry)
            print(f'{name} {method}: MAP cost '
                  f'{None if best is None else round(best["cost"], 3)}', flush=True)
    comparison = compare_estimators(maps, records, args)
    return dict(
        cases={name: dict(reference_yz_m=None if cases[name]['reference_yz_m'] is None
                          else cases[name]['reference_yz_m'].tolist(),
                          reference_time_s=cases[name]['reference_time_s'],
                          observed_start_height_m=float(cases[name]['points'][0, 2]),
                          n_frames=int(len(cases[name]['times'])),
                          workbook=cases[name]['workbook'],
                          workbook_sha256=cases[name]['workbook_sha256'])
               for name in AF.CASES},
        latent_map=maps, posterior=records, comparison=comparison,
        warnings=notes,
        settings=dict(sigma_m=AF.SIGMA, cd=AF.CD, dr0_bound_m=DR0_BOUND,
                      cl_bound=CL_BOUND, target_m=GOAL,
                      priors=list(args.estimator_priors),
                      samples=args.samples, seeds=list(args.seeds),
                      escalate_to=args.escalate_to, ess_floor=args.ess_floor,
                      kde_bandwidth_m=KDE_BW, kde_grid_m=KDE_STEP,
                      integrator='rk4 dt=.005 for endpoints; solve_ivp rtol 1e-9 '
                                 'for the MAP prefix fit',
                      parameterisation='FIXED early velocity/basis for both '
                                       'estimators (differs from the previous '
                                       'batch velocity-dependent mapping)',
                      prior_measure='density w.r.t. dc_vert dc_lat; '
                                    'exp(-.5|penalty|^2), no radial Jacobian'))


def compare_estimators(maps, records, args):
    out = {}
    for name in AF.CASES:
        for method in [m['prior'] for m in maps if m['case'] == name]:
            mapping = next((m for m in maps if m['case'] == name and m['prior'] == method),
                           None)
            seeds = [r for r in records if r['case'] == name and r['prior'] == method]
            entry = dict(case=name, prior=method, map=mapping, seeds=seeds)
            means = [r['predictive_mean_yz_m'] for r in seeds
                     if r.get('predictive_mean_yz_m') is not None]
            modes = [r['kde_mode_yz_m'] for r in seeds
                     if r.get('kde_mode_yz_m') is not None]
            entry['seed_mean_gap_cm'] = (None if len(means) < 2 else
                                         100. * float(np.linalg.norm(
                                             np.asarray(means[0]) - np.asarray(means[1]))))
            entry['seed_mode_gap_cm'] = (None if len(modes) < 2 else
                                         100. * float(np.linalg.norm(
                                             np.asarray(modes[0]) - np.asarray(modes[1]))))
            map_yz = None if mapping is None else mapping.get('map_crossing_yz_m')
            entry['map_vs_mean_cm'] = (
                None if map_yz is None or not means else
                100. * float(np.linalg.norm(
                    np.mean([np.asarray(m, float) for m in means], axis=0)
                    - np.asarray(map_yz, float))))
            mean_errors = [r['predictive_mean_error_cm'] for r in seeds
                           if r.get('predictive_mean_error_cm') is not None]
            mode_errors = [r['kde_mode_error_cm'] for r in seeds
                           if r.get('kde_mode_error_cm') is not None]
            map_error = None if mapping is None else mapping.get('map_error_cm')
            entry['mean_minus_map_error_cm'] = (
                None if map_error is None or not mean_errors
                else float(np.mean(mean_errors) - map_error))
            entry['mode_minus_map_error_cm'] = (
                None if map_error is None or not mode_errors
                else float(np.mean(mode_errors) - map_error))
            min_ess = min((r['ess'] for r in seeds), default=None)
            entry['min_ess'] = min_ess
            seed_gap = entry['seed_mean_gap_cm']
            entry['stable'] = bool(min_ess is not None
                                   and min_ess >= args.ess_floor
                                   and seed_gap is not None and seed_gap <= 2.)
            entry['flag'] = ('ok' if entry['stable'] else
                             'unstable: low ESS' if (min_ess is None
                                                     or min_ess < args.ess_floor)
                             else 'unstable: seed-dependent mean')
            out[f'{name}|{method}'] = entry
    return out


# ---------------------------------------------------------------------------
# Checks (workbook-free)
# ---------------------------------------------------------------------------
def synth_track(v0, c, times):
    frame = AF.transverse_frame(np.asarray(v0, float))
    omega = omega_from_c(c, frame)[0]
    theta = np.r_[np.zeros(3), omega, AF.CD][None]
    start = np.r_[np.array([0., 0., .30]), np.asarray(v0, float)]
    sol = solve_ivp(lambda t, y: derivative(y[None], theta, t, AF.CFG)[0],
                    (0., float(times[-1])), start, t_eval=times,
                    rtol=1e-10, atol=1e-12)
    if not sol.success:
        raise RuntimeError('synthetic integration failed')
    return np.asarray(sol.y[:3].T)


def synth_case(name='synth', cohort='dfl_penalty', v0=(28., 1.2, 2.4),
               c=(.15, -.10), target=6.5, sigma=.01, n=22, align=False):
    times = np.arange(n) * .04
    points = synth_track(v0, c, times)
    if align:
        angle = .7
        rotation = np.array([[np.cos(angle), -np.sin(angle)],
                             [np.sin(angle), np.cos(angle)]])
        points = np.column_stack((points[:, :2] @ rotation.T + np.array([3., -2.]),
                                  points[:, 2]))
    return build_case(name, cohort, times, points, sigma, target=target,
                      align=align, prefix=3,
                      source=dict(kind='synthetic', note='generated, not measured'))


def check_algebra():
    v0 = np.array([30., 2.5, 1.2])
    frame = AF.transverse_frame(v0)
    c = np.array([.18, -.12])
    omega = omega_from_c(c, frame)[0]
    theta = np.r_[np.zeros(3), omega, AF.CD][None]
    fixed = derivative(np.r_[np.zeros(3), v0][None], theta, 0., AF.CFG)[0][3:]
    reference = AF.initial_acceleration('canon', c, v0)
    identity = bool(np.allclose(fixed, reference, rtol=0, atol=1e-9))
    capped = bool(abs(AF.canonical_initial_cl(np.array([.30, 0.]), v0) - .30) < 1e-12)
    return dict(passed=bool(identity and capped),
                fixed_frame_matches_velocity_dependent=identity,
                fixed_velocity_frame=identity,
                cap_respected=capped,
                max_abs_delta=float(np.max(np.abs(fixed - reference))),
                note='at t=0 the fixed early velocity/basis reproduces the canonical '
                     'acceleration of the factorial velocity-dependent mapping')


def check_future_invariance():
    case = synth_case()
    fit = fit_prefix(case['fit_times'], case['fit_points'], case['sigma'], 'none')
    base = predict_case(case, fit)
    base_score = score_case(case, base)
    altered = dict(case)
    moved = np.array(case['future_points'], float).copy()
    moved += np.array([.25, -.18, .12])
    altered['future_points'] = moved
    if altered['reference_yz_m'] is not None:
        altered['reference_yz_m'] = (np.asarray(case['reference_yz_m'], float)
                                     + np.array([-.18, .12]))
    refit = fit_prefix(altered['fit_times'], altered['fit_points'], altered['sigma'], 'none')
    after = predict_case(altered, refit)
    after_score = score_case(altered, after)
    same_fit = json.dumps(AF.jsonable(fit['rows']), sort_keys=True) \
        == json.dumps(AF.jsonable(refit['rows']), sort_keys=True)
    same_prediction = json.dumps(AF.jsonable(base), sort_keys=True) \
        == json.dumps(AF.jsonable(after), sort_keys=True)
    return dict(passed=bool(same_fit and same_prediction
                            and base_score['prediction_available']
                            and base_score['heldout_rmse_cm']
                            != after_score['heldout_rmse_cm']),
                fits_identical=same_fit,
                predictions_identical=same_prediction,
                score_changed=bool(base_score['heldout_rmse_cm']
                                   != after_score['heldout_rmse_cm']),
                error_before_cm=base_score['heldout_rmse_cm'],
                error_after_cm=after_score['heldout_rmse_cm'],
                note='only held-out positions and the interpolated reference moved; '
                     'every fitted branch and the prediction are bit-identical')


def check_alignment_invariance():
    local = synth_case(name='local', align=False)
    global_case = synth_case(name='global', align=True)
    angle = .7
    rotation = np.array([[np.cos(angle), -np.sin(angle)],
                         [np.sin(angle), np.cos(angle)]])
    raw_prefix = np.column_stack((local['fit_points'][:, :2] @ rotation.T
                                  + np.array([3., -2.]), local['fit_points'][:, 2]))
    raw_future = np.column_stack((local['future_points'][:, :2] @ rotation.T
                                  + np.array([3., -2.]), local['future_points'][:, 2]))
    recovered = align_track(np.vstack((raw_prefix, raw_future)), 3)
    expected = np.vstack((local['fit_points'], local['future_points']))
    geometry = bool(np.allclose(recovered, expected, rtol=0, atol=1e-9))
    fit_a = fit_prefix(global_case['fit_times'], global_case['fit_points'],
                       global_case['sigma'], 'none')
    fit_b = fit_prefix(local['fit_times'], local['fit_points'],
                       local['sigma'], 'none')
    same_fit = json.dumps(AF.jsonable(fit_a['rows']), sort_keys=True) \
        == json.dumps(AF.jsonable(fit_b['rows']), sort_keys=True)
    score_a = score_case(global_case, predict_case(global_case, fit_a))
    score_b = score_case(local, predict_case(local, fit_b))
    same_score = (score_a['heldout_rmse_cm'] == score_b['heldout_rmse_cm']
                  and score_a['plane_error_cm'] == score_b['plane_error_cm'])
    return dict(passed=bool(geometry and same_fit and same_score),
                geometry_recovered=geometry, fits_identical=same_fit,
                scores_identical=same_score,
                rmse_cm=score_a['heldout_rmse_cm'],
                note='arbitrary yaw+translation of the measurement frame recovers '
                     'the same local track, fit and score')



def check_score_arithmetic():
    case = dict(case='synthetic', cohort='dfl_penalty', sigma=.01, target_x=6.5,
                reference_time_s=.40, reference_yz_m=np.array([.50, 1.50]),
                future_times=np.array([.12, .16, .20, .24]),
                future_points=np.array([[3., .50, 1.50], [4., .52, 1.60],
                                        [5., .54, 1.55], [6., .56, 1.50]]),
                n_future=4)
    prediction = dict(available=3, xyz=[[3., .55, 1.45], [4., .57, 1.55],
                                        [5., .59, 1.50]],
                      crossing_yz_m=[.60, 1.52], crossing_time_s=.42)
    score = score_case(case, prediction)
    expected_rmse = 100. * float(np.sqrt(np.mean(
        np.sum(np.array(prediction['xyz']) - case['future_points'][:3], axis=1) ** 2)))
    expected_plane = 100. * float(np.linalg.norm(
        np.array([.60, 1.52]) - np.array([.50, 1.50])))
    return dict(passed=bool(abs(score['heldout_rmse_cm'] - expected_rmse) < 1e-9
                            and abs(score['plane_error_cm'] - expected_plane) < 1e-9
                            and score['frames_scored'] == 3
                            and score['post_plane_frames_excluded'] == 0),
                rmse_cm=score['heldout_rmse_cm'], expected_rmse_cm=expected_rmse,
                plane_error_cm=score['plane_error_cm'],
                expected_plane_error_cm=expected_plane,
                frames_scored=score['frames_scored'],
                note='error_cm/plane arithmetic and the time-based plane cut')


def check_aggregate_end_to_end():
    cases = [synth_case(name='synth_a', target=6.5),
             synth_case(name='synth_b', target=7.5, v0=(26., -1.0, 3.0), c=(.10, .12))]
    specs = {'none': ('none', None), 'manual': ('manual', None)}
    seeds = (('truth', (.15, -.10)),)
    rows, table = evaluate_transfer(cases, specs, c_seeds=seeds)
    ok_fields = all(row.get('error_cm') is not None
                    and row['error_cm'] == row['heldout_rmse_cm'] for row in rows)
    recomputed = {}
    for method in specs:
        values = [row['error_cm'] for row in rows if row['method'] == method]
        recomputed[method] = float(np.mean(values)) if values else None
    means_ok = all(table[m]['mean_error_cm'] is not None
                   and abs(table[m]['mean_error_cm'] - recomputed[m]) < 1e-12
                   for m in specs)
    coverage = all(table[m]['per_case'].get(c['case']) is not None
                   for m in specs for c in cases)
    return dict(passed=bool(ok_fields and means_ok and coverage),
                rows_carry_error_cm=ok_fields, means_match_rows=means_ok,
                every_case_present=coverage, n_rows=len(rows),
                means=recomputed,
                note='rows -> per-case entries -> method means agree end to end')


def check_estimator_plumbing():
    case = synth_case(name='estimator_synth', target=6.5, sigma=.01, n=26)
    times = case['fit_times']
    points = case['fit_points']
    velocity, _ = early_velocity(times, points)
    frame = AF.transverse_frame(velocity)
    fit = map_estimator(times, points, .01, 'none', None, frame)
    cfg = Config(dt=.005)
    best = fit['best']
    if best is None:
        return dict(passed=False, note='MAP failed on the synthetic case')
    omega = omega_from_c(np.array([best['c_vert'], best['c_lat']]), frame)[0]
    goal = endpoint_draws(points[0] + np.asarray(best['dr0_m'], float),
                          np.asarray(best['v0_m_s'], float),
                          np.r_[np.zeros(3), omega, AF.CD][None], 6.5, cfg)[0]
    true_yz, _ = plane_reference(np.arange(26) * .04,
                                 synth_track((28., 1.2, 2.4), (.15, -.10),
                                             np.arange(26) * .04), 6.5)
    map_gap = None if not np.isfinite(goal[0]) or true_yz is None else \
        100. * float(np.linalg.norm(goal - true_yz))
    draws = posterior(times, points, .01, 'manual', AF.PRIOR, frame, 800, 8047, cfg)
    summary = summarise_draws(draws, 6.5, true_yz, cfg)
    repeat = posterior(times, points, .01, 'manual', AF.PRIOR, frame, 800, 8047, cfg)
    same = bool(np.allclose(draws['weights'], repeat['weights'], rtol=0, atol=0))
    positive = draws['weights'] > 0
    in_box = bool(positive.any()
                  and (np.abs(draws['state'][positive, :3] - points[0])
                       <= DR0_BOUND + 1e-12).all()
                  and (np.abs(draws['c'][positive]) <= CL_BOUND + 1e-12).all()
                  and (draws['state'][positive, 3] >= V_LOW[0]).all()
                  and (draws['state'][positive, 3] <= V_HIGH[0]).all())
    return dict(passed=bool(best['cost'] < 1e-6
                            and map_gap is not None and map_gap < 50.
                            and abs(float(draws['weights'].sum()) - 1.) < 1e-12
                            and 0. <= summary['crossing_mass'] <= 1.
                            and summary['predictive_mean_yz_m'] is not None
                            and summary['kde_mode_yz_m'] is not None
                            and same and in_box),
                map_cost=best['cost'],
                map_gap_to_truth_cm=map_gap,
                ess=draws['ess'], max_weight=draws['max_weight'],
                crossing_mass=summary['crossing_mass'],
                mean_error_cm=summary['predictive_mean_error_cm'],
                mode_error_cm=summary['kde_mode_error_cm'],
                same_seed_weights_identical=same,
                draws_inside_shared_bounds=in_box,
                note='MAP recovers the synthetic lift, weights are normalised, and '
                     'MAP and draws share the same state/CL bounds')


def selftest_checks(include_estimator=True):
    checks = {
        'algebra': check_algebra(),
        'future_invariance': check_future_invariance(),
        'alignment_invariance': check_alignment_invariance(),
        'score_arithmetic': check_score_arithmetic(),
        'aggregate_end_to_end': check_aggregate_end_to_end(),
    }
    if include_estimator:
        checks['estimator_plumbing'] = check_estimator_plumbing()
    return checks


# ---------------------------------------------------------------------------
# Chinese report (generated from the actual results)
# ---------------------------------------------------------------------------
def write_readme(path, transfer, estimators, checks, settings):
    lines = []
    add = lines.append
    add('# Asai 方向先验外推与 MAP/后验均值匹配对照')
    add('')
    add(f'本文件由 `asai_transfer.py` 依据实际运行结果自动生成（{settings["generated_utc"]}，'
        f'运行 {settings["runtime_s"]:.1f} s）。脚本 sha256 前缀 `{settings["script_sha256"][:12]}`。'
        f'正式 P1、训练集与论文均未改动。')
    add('')
    add('固定模型：canonical 升力律、Cd=0.27、自由首点 ±5 cm。'
        '迁移阶段沿用上一批按拟合初速 v0 生成升力向量的参数化（与 10.63 cm 可比）；'
        '估计器阶段改为固定早期速度/基，MAP 与后验抽样共用，两者不可混用。')
    add('')
    if transfer is not None:
        table = transfer['table']
        primary = transfer['primary_cases']
        add('## 1. 外部迁移（优先 1，MAP 点估计）')
        add('')
        add('主指标：留出帧三维 RMSE（cm），只统计目标面之前、且观测仍在球半径以上的帧。'
            'DFL 噪声 15 mm；ISSIA 噪声 30 mm 为显式假设值，不是实测标定。')
        add('')
        add('| 方法 | ' + ' | '.join(primary) + f' | {len(primary)} 例均值 |')
        add('|' + '---|' * (len(primary) + 2))
        for method in TRANSFER_METHODS:
            if method not in table:
                continue
            row = table[method]['per_case']
            add('| ' + method + ' | '
                + ' | '.join(_fmt((row.get(case) or {}).get('heldout_rmse_cm'))
                             for case in primary)
                + f" | {_fmt(table[method]['mean_heldout_rmse_cm'])} |")
        add('')
        add('目标面截面误差（cm，仅观测轨迹确实越过目标面的案例；未越过的案例不伪造 11 m 真值）：')
        add('')
        first_method = next((m for m in TRANSFER_METHODS if m in table), None)
        header = [] if first_method is None else [
            case for case in primary
            if (table[first_method]['per_case'].get(case) or {})
            .get('plane_error_cm') is not None]
        if header:
            add('| 方法 | ' + ' | '.join(header) + ' | 均值 |')
            add('|' + '---|' * (len(header) + 2))
            for method in TRANSFER_METHODS:
                if method not in table:
                    continue
                row = table[method]['per_case']
                add('| ' + method + ' | '
                    + ' | '.join(_fmt((row.get(case) or {}).get('plane_error_cm'))
                                 for case in header)
                    + f" | {_fmt(table[method]['mean_plane_error_cm'])} |")
        else:
            add('（无可用目标面参考）')
        add('')
        add('补充 11 例 DFL 片段（无目标面，仅留出帧 RMSE）：'
            + '；'.join(f"{m} {_fmt(table[m]['extra_mean_heldout_rmse_cm'])} cm"
                        for m in TRANSFER_METHODS if m in table) + '。')
        add('')
        cases_meta = transfer['cases']
        add('起始高度与可达性（观测首帧高度、观测轨迹前向覆盖）：')
        add('')
        add('| 案例 | 队列 | 起始高度 m | 前向覆盖 m | 目标面 | 参考 yz m |')
        add('|---|---|---:|---:|---|---|')
        for case in [c['case'] for c in transfer['case_list']]:
            meta = cases_meta[case]
            ref = meta['reference_yz_m']
            add(f"| {case} | {meta['cohort']} | {_fmt(meta['observed_start_height_m'], 3)} "
                f"| {_fmt(meta['forward_reach_m'])} | "
                f"{_fmt(meta['target_x_m'])} | "
                + ('—' if ref is None else f"{ref[0]:.3f}, {ref[1]:.3f}") + ' |')
        add('')
    else:
        add('## 1. 外部迁移（优先 1）')
        add('')
        add('本轮未运行 `--stage transfer`。')
        add('')
    if estimators is not None:
        add('## 2. MAP 与后验均值（优先 2，Asai 11 m 截面）')
        add('')
        add(f'两算法共用：σ={estimators["settings"]["sigma_m"]*1000:.0f} mm、Cd='
            f'{estimators["settings"]["cd"]}、|dr0|≤{estimators["settings"]["dr0_bound_m"]*100:.0f} cm、'
            f'c∈[-{estimators["settings"]["cl_bound"]}, +{estimators["settings"]["cl_bound"]}]²，'
            f'先验密度定义为对 dc_vert dc_lat 的 exp(-0.5·penalty²)（不加径向 Jacobian）。'
            f'每次后验 {estimators["settings"]["samples"]} 抽样，种子 '
            + '/'.join(str(s) for s in estimators["settings"]["seeds"])
            + f'；KDE 带宽 {estimators["settings"]["kde_bandwidth_m"]*100:.0f} cm、'
            f'网格 {estimators["settings"]["kde_grid_m"]*100:.0f} cm。')
        add('')
        add('| 案例 | 先验 | MAP cm | 后验均值 cm | KDE 众数 cm | 均值−MAP cm | ESS | 跨面质量 | 稳定性 |')
        add('|---|---|---:|---:|---:|---:|---:|---:|---|')
        for case in AF.CASES:
            for method in estimators['settings']['priors']:
                entry = estimators['comparison'].get(f'{case}|{method}')
                if entry is None or entry['map'] is None or entry['map'].get('failed'):
                    add(f'| {case} | {method} | 失败 | — | — | — | — | — | — |')
                    continue
                record = entry['seeds'][0] if entry['seeds'] else {}
                add(f"| {case} | {method} | {_fmt(entry['map'].get('map_error_cm'))} "
                    f"| {_fmt(record.get('predictive_mean_error_cm'))} "
                    f"| {_fmt(record.get('kde_mode_error_cm'))} "
                    f"| {_fmt(entry.get('map_vs_mean_cm'))} "
                    f"| {_fmt(entry.get('min_ess'), 0)} "
                    f"| {_fmt(record.get('crossing_mass'), 3)} "
                    f"| {entry.get('flag')} |")
        add('')
        add('跨面质量是后验中真正越过 11 m 截面的权重和；ESS 按全部有效抽样计算。'
            '稳定性判据：两个种子的 ESS 均不低于 '
            f'{estimators["settings"]["ess_floor"]:.0f}，且均值间距 ≤2 cm；'
            '不满足时如实标注，不据此宣称概率优势。')
        add('')
    else:
        add('## 2. MAP 与后验均值（优先 2）')
        add('')
        add('本轮未运行 `--stage estimators`。')
        add('')
    add('## 3. 判读（由上述数值机械生成）')
    add('')
    if transfer is not None:
        table = transfer['table']
        primary = transfer['primary_cases']
        for a, b in (('manual', 'none'), ('pooled', 'none')):
            if a in table and b in table:
                diffs = []
                wins = 0
                for case in primary:
                    va = (table[a]['per_case'].get(case) or {}).get('heldout_rmse_cm')
                    vb = (table[b]['per_case'].get(case) or {}).get('heldout_rmse_cm')
                    if va is None or vb is None:
                        continue
                    diffs.append(va - vb)
                    wins += int(va < vb)
                if diffs:
                    add(f'- 外部 {len(diffs)} 例：{a} 相对 {b} 在 {wins}/{len(diffs)} 例更低，'
                        f'平均差 {_fmt(float(np.mean(diffs)))} cm（负值=更低）。')
        add(f'- 迁移方向是否一致须逐例看表；仅 {len(primary)} 例主案例 + '
            f'{len(transfer["extra_cases"])} 例补充片段，'
            '不能估计总体准确率，也不据此回调 Asai 参数。')
    if estimators is not None:
        gaps = {}
        for method in estimators['settings']['priors']:
            values = [e.get('map_vs_mean_cm') for key, e in estimators['comparison'].items()
                      if key.endswith('|' + method) and e.get('map_vs_mean_cm') is not None]
            gaps[method] = mean_or_none(values)
        add('- 估计器：' + '；'.join(
            f'{m} 先验下 |后验均值−MAP| 平均 {_fmt(gaps[m])} cm'
            for m in estimators['settings']['priors'] if gaps.get(m) is not None) + '。')
        add('- 若均匀先验下均值与 MAP 差距大、而方向先验下两者接近，则旧表“MAP vs 后验均值”'
            '的估计量差异是差异来源之一；本轮 n=3，只作归因证据，不作概率优越性结论。')
        add('- 参数化提醒：本阶段固定早期速度/基，与上一批按 v0 生成的升力向量不同，'
            '数值不可与 10.63 cm 直接相减。')
    add('')
    add('## 4. 边界与失败处理')
    add('')
    add('- 全部尝试保留：未收敛分支、触地提前终止、未越过目标面的预测都写入 JSON，'
        '不静默丢弃；观测帧若落在球半径以下会被排除并计数。')
    add('- 评分与拟合分离：`fit_prefix` 只接受前段数组，留出帧由 `score_case` 在预测固定后打开；'
        '测试用扰动未来帧验证拟合与预测不变、分数改变。')
    add('- DFL 前段为 0/0.04/0.08 s，目标面来自 case_config；ISSIA 为 25 fps 连续片段，'
        '前向轴只由前三点确定并同变换整条轨迹（含参考）。')
    add('- 三球数据此前均已查看，属探索性归因，不是独立盲评；不与冻结 P1 的分布均值直接比较。')
    add('')
    add('## 5. 复现')
    add('')
    add('```powershell')
    add('& C:/Users/pc/miniconda3/envs/mujoco/python.exe '
        'integration/student_b/experiments/asai_transfer.py --stage all '
        '--out integration/student_b/runs/asai_transfer')
    add('& C:/Users/pc/miniconda3/envs/mujoco/python.exe -m unittest '
        'deliverables/asai_transfer/test_asai_transfer.py -v')
    add('```')
    add('')
    add('检查项：' + '；'.join(f'{key}={"通过" if value.get("passed") else "未通过"}'
                              for key, value in checks.items()) + '。')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


# ---------------------------------------------------------------------------
# Stages / CLI
# ---------------------------------------------------------------------------
def transfer_priors(pooled):
    return {'none': ('none', None), 'manual': ('manual', None),
            'pooled': ('loocv', pooled)}


def transfer_stage(args, pooled, checks):
    cases = load_dfl_penalty(args.dfl)
    cases += load_issia(args.issia)
    extra = [] if args.no_extra_dfl else load_extra_dfl(args.extra_dfl)
    cases += extra
    rows, table = evaluate_transfer(cases, transfer_priors(pooled))
    payload = dict(
        stage='transfer',
        primary_cases=[c['case'] for c in cases
                       if c['cohort'] in ('dfl_penalty', 'issia')],
        extra_cases=[c['case'] for c in extra],
        case_list=[case_meta(c) for c in cases],
        cases={c['case']: case_meta(c) for c in cases},
        table=table,
        contrasts=transfer_contrasts(table, cases, list(TRANSFER_METHODS)),
        priors=dict(none='position residuals only',
                    manual=dict(AF.PRIOR),
                    pooled=pooled),
        note='MAP point estimates; the pooled prior comes from the three archived '
             'Asai full-track fits and never sees a DFL/ISSIA outcome')
    if not args.no_asai_reference:
        try:
            payload['asai_source_reference'] = asai_reproduction(args.data_asai, pooled)
        except FileNotFoundError as exc:
            payload['asai_source_reference'] = dict(skipped=str(exc))
    extra_rows = [r for r in rows if r['cohort'] == 'dfl_extra']
    if extra_rows:
        payload['extra_note'] = ('the 11 supplementary clips have no target plane, so '
                                 'only held-out frame RMSE and last-frame error are scored')
    return payload, rows


def estimator_stage_entry(args, pooled, checks):
    payload = estimator_stage(args, pooled, Config(dt=.005))
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--stage', choices=('transfer', 'estimators', 'all'), default='all')
    parser.add_argument('--out', type=Path, default=SB / 'runs/asai_transfer')
    parser.add_argument('--data-asai', type=Path, default=Path('C:/Users/pc/Desktop'),
                        help='directory holding the three Asai workbooks')
    parser.add_argument('--asai-results', type=Path,
                        default=SB / 'runs/asai_factorial/results.json')
    parser.add_argument('--dfl', type=Path,
                        default=ROOT / 'integration/student-a/flight_trajectory_validation_2026-11-07')
    parser.add_argument('--extra-dfl', type=Path,
                        default=ROOT / 'integration/student-a/additional_flight_data_2026-11-07/positions.csv')
    parser.add_argument('--no-extra-dfl', action='store_true',
                        help='skip the 11 supplementary DFL clips')
    parser.add_argument('--no-asai-reference', action='store_true',
                        help='skip the in-sample Asai reproduction block')
    parser.add_argument('--issia', type=Path, default=SB / 'runs/issia_A')
    parser.add_argument('--samples', type=int, default=8000)
    parser.add_argument('--escalate-to', type=int, default=32000)
    parser.add_argument('--ess-floor', type=float, default=200.)
    parser.add_argument('--seeds', type=int, nargs='+', default=[8047, 20261107])
    parser.add_argument('--estimator-priors', nargs='+',
                        choices=('none', 'manual', 'pooled'),
                        default=['none', 'manual', 'pooled'])
    parser.add_argument('--skip-checks', action='store_true')
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args(argv)

    started = time.time()
    if args.selftest:
        checks = selftest_checks()
        passed = all(item.get('passed') for item in checks.values())
        args.out.mkdir(parents=True, exist_ok=True)
        AF.save_json(args.out / 'checks_selftest.json', dict(passed=passed, checks=checks))
        print(json.dumps({'passed': passed,
                          'checks': {key: item.get('passed')
                                     for key, item in checks.items()}},
                         ensure_ascii=False, indent=2))
        return 0 if passed else 1
    if args.samples < 2:
        parser.error('--samples must be at least 2')
    if args.escalate_to < args.samples:
        parser.error('--escalate-to must not be smaller than --samples')

    args.out.mkdir(parents=True, exist_ok=True)
    pooled, pooled_meta = load_pooled_prior(args.asai_results)
    checks = {} if args.skip_checks else selftest_checks()
    transfer = None
    estimators = None
    rows = []
    if args.stage in ('transfer', 'all'):
        transfer, rows = transfer_stage(args, pooled, checks)
    if args.stage in ('estimators', 'all'):
        estimators = estimator_stage_entry(args, pooled, checks)
    if not args.skip_checks:
        if transfer is not None:
            reproduction = transfer.get('asai_source_reference') or {}
            table = reproduction.get('table')
            archived = reproduction.get('archived') or {}
            if table:
                deltas = {}
                for method in ('none', 'manual'):
                    if method in table and archived.get(method) is not None:
                        deltas[method] = (table[method]['mean_error_cm']
                                          - archived[method])
                checks['asai_reproduction'] = dict(
                    passed=bool(deltas and all(abs(v) <= 0.5 for v in deltas.values()
                                               if v is not None)),
                    reproduced={m: table[m]['mean_error_cm'] for m in table},
                    archived=archived, deltas=deltas, tolerance_cm=.5,
                    note='re-runs the archived factorial pipeline on the three '
                         'workbooks; a larger gap means the environment differs')
        else:
            checks['asai_reproduction'] = dict(passed=None, note='transfer stage skipped')

    settings = dict(
        generated_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'),
        runtime_s=time.time() - started,
        script_sha256=sha256(HERE),
        law='canon', cd=AF.CD, sigma_dfl_m=SIGMA_DFL,
        sigma_issia_m=SIGMA_ISSIA, sigma_asai_m=AF.SIGMA,
        dr0_bound_m=DR0_BOUND, c_bound_transfer=AF.C_BOUND,
        c_bound_estimator=CL_BOUND, goal_m=GOAL,
        asai_observation_times_s=list(AF.OBS_TIMES),
        pooled_prior=pooled_meta,
        stage=args.stage,
        samples=args.samples, seeds=list(args.seeds),
        escalate_to=args.escalate_to, ess_floor=args.ess_floor,
        estimator_priors=list(args.estimator_priors),
        selected_by_held_out=False)
    hashes = {}
    for candidate in (args.dfl / 'inputs_only.csv', args.dfl / 'held_out.csv',
                      args.dfl / 'case_config.json', args.extra_dfl,
                      args.issia / 'seg_0608_0627.csv',
                      args.issia / 'seg_1144_1172.csv', args.asai_results):
        if Path(candidate).is_file():
            hashes[str(candidate)] = sha256(candidate)
    payload = dict(
        study='asai_transfer_and_matched_estimators',
        label='exploratory; external n = 4 primary clips (+11 supplementary); '
              'Asai n = 3; no independent final test, no held-out selection',
        settings=settings, hashes=hashes,
        checks=checks,
        transfer=transfer, estimators=estimators)

    if transfer is not None:
        AF.save_json(args.out / 'results_transfer.json',
                     dict(**{k: v for k, v in payload.items() if k != 'estimators'}))
        AF.write_csv(args.out / 'rows_transfer.csv', rows, TRANSFER_FIELDS)
    if estimators is not None:
        AF.save_json(args.out / 'results_estimators.json',
                     dict(**{k: v for k, v in payload.items() if k != 'transfer'}))
    AF.save_json(args.out / 'checks.json', checks)
    AF.save_json(args.out / 'settings.json', dict(settings=settings, hashes=hashes))
    write_readme(args.out / 'README.md', transfer, estimators, checks, settings)

    passed = all(item.get('passed') for item in checks.values()
                 if item.get('passed') is not None)
    print(f'wrote {args.out}/README.md, checks.json and stage JSON in '
          f'{settings["runtime_s"]:.1f} s')
    if transfer is not None:
        for method in TRANSFER_METHODS:
            if method in transfer['table']:
                entry = transfer['table'][method]
                print(f"  {method:7s} primary RMSE {_fmt(entry['mean_heldout_rmse_cm'])} cm "
                      f"plane {_fmt(entry['mean_plane_error_cm'])} cm "
                      f"extra {_fmt(entry['extra_mean_heldout_rmse_cm'])} cm")
    if estimators is not None:
        for key, entry in estimators['comparison'].items():
            print(f"  {key}: map {_fmt(entry['map'].get('map_error_cm') if entry['map'] else None)} "
                  f"mean {_fmt(entry['seeds'][0].get('predictive_mean_error_cm') if entry['seeds'] else None)} "
                  f"ess {_fmt(entry['min_ess'], 0)} {entry['flag']}")
    print('checks:', {key: item.get('passed') for key, item in checks.items()
                      if item.get('passed') is not None})
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
