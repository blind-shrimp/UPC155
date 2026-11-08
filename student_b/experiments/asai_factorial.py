#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exploratory 2x3x2 factorial for the Asai 11 m short-window discrepancy.

Question
--------
Why does the archived manual replay (manual_reference.py, regularised, 0/50/100 ms)
reach ~11.39 cm mean Euclidean (y,z) error at the measured x = 11 m section,
while the canonical short-window physics replay reaches ~50-60 cm?

This script compares MAP to MAP on a frozen, identical input pipeline.  It does
NOT reproduce posterior means and does not touch the frozen P1 network.

Design (frozen before execution)
--------------------------------
Inputs: t = 0.00 / 0.05 / 0.10 s positions only (same `read_trial` as
replay_asai_3kicks.py), forward 11 m section interpolated from the measured
track (same `crossing`).  Score = Euclidean distance in the (y,z) plane, cm.

Factors
  (a) law    'const_cl' : frozen inertial lift vector q, a = k |v| (q x v)
             'canon'    : canonical capped law,
                          CL(t) = min(1.4 R |omega x v(t)| / |v(t)|^2, .30),
                          which equals c v0 / |v(t)| at t = 0 and while omega
                          stays perpendicular to v
         Both laws are parameterised by the same c = (c_vert, c_lat), the
         effective initial transverse CL in a force-referenced frame:
         c_vert > 0 lifts up, c_lat > 0 pushes left, and at t = 0 both laws
         produce exactly the same total initial acceleration.  For the
         canonical law the minimal transverse spin realising c is
         omega = (c_lat z_perp - c_vert y_perp) v0 / (1.4 R), so the initial CL
         equals |c|; saturation at .30 for |c| > .30 is part of the canonical
         law, not of the parameterisation.
  (b) prior  'none'   : position residuals only (no regularisation)
             'iso'    : isotropic magnitude prior |c| ~ N(.24, .08^2)
             'manual' : manual magnitude + signed vertical-component prior,
                        |c| ~ N(.24, .08^2) and c_vert ~ N(.06, .06^2);
                        there is NO prior on the sign of c_lat
  (c) init   'fixed0' : start exactly at the measured first point, fit 50/100 ms
             'free3'  : free initial offset (|dr0| <= 5 cm), fit all three
                        points under sigma = 10 mm position noise

All residuals are explicit and comparable: positions are divided by sigma
(10 mm) and priors are in CL units, so 1 cm of position error costs 1.0 and
0.08 of CL costs 1.0.  Dividing by sigma alone does not move the optimum, but
with a prior it fixes the data-to-prior trade-off; that confounding is what
this script reports instead of hiding.

Multi-start: four (+/-c_vert, +/-c_lat) directions at |c| = .24, the manual's
own start (.06, -.24) and its mirror, an exactly zero-lift start, and two v0
seeds (quadratic / linear).  The best branch is chosen by the TRAINING
objective only.  All branches, costs, convergence flags and predictions are
saved; near-optimal branches are reported so local minima stay visible.

Supplementary (clearly separated cohort): leave-one-trial-out Gaussian prior in
(|c|, c_vert), whose means and SDs come only from the canonical full-track fits
of the OTHER trials; SD floors are fixed in advance at .08 (magnitude) and .06
(vertical).  Held-out prediction uses only that trial's three early points.
This is not an independent test: n = 3 and all three tracks were already seen.

CLI
  python asai_factorial.py --data <xlsx dir> --out <out dir>
  python asai_factorial.py --selftest [--out <out dir>]

Outputs: results.json, results.csv, contrasts.csv, checks.json.
No raw workbook values are exported; only sha256 hashes are stored.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
SB = ROOT / 'integration/student_b'
DEPS = ROOT / 'deliverables/asai_official/read_deps'
for _p in (str(SB), str(DEPS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from physics import Config, derivative  # noqa: E402

FILES = {'Fig3': 'Fig3_Sample data 20261108.xlsx',
         'Sample05': 'Sample 05 data 20261108.xlsx',
         'Sample12': 'Sample 12 data 20261108.xlsx'}
CASES = tuple(FILES)

GOAL = 11.0
SIGMA = .010
CD = .27
OBS_TIMES = (0., .05, .10)
MAX_NFEV = 200
DR0_BOUND = .05
C_BOUND = .80

PRIOR = dict(mag_mean=.24, mag_sd=.08, vert_mean=.06, vert_sd=.06)
LOOCV_FLOOR = dict(mag_sd=.08, vert_sd=.06)

CFG = Config(fixed_cd=CD)
K_AERO = CFG.density * np.pi * CFG.radius ** 2 / (2 * CFG.mass)
GRAV = np.array([0., 0., -CFG.gravity])
LIFT_CAP = .30

LAWS = ('const_cl', 'canon')
PRIORS = ('none', 'iso', 'manual')
INITS = ('fixed0', 'free3')

# c seeds: (label, (c_vert, c_lat)); the manual start is kept verbatim.
C_SEEDS = (
    ('manual', (.06, -.24)),
    ('manual_mirror', (.06, .24)),
    ('pp', (.17, .17)),
    ('pn', (.17, -.17)),
    ('np', (-.17, .17)),
    ('nn', (-.17, -.17)),
    ('zero', (0., 0.)),
)
V_SEEDS = ('quad', 'linear')


# ---------------------------------------------------------------------------
# Input: byte-identical copies of replay_asai_3kicks.read_trial / crossing
# ---------------------------------------------------------------------------
def read_trial(path):
    from openpyxl import load_workbook
    with path.open('rb') as stream:
        book = load_workbook(stream, read_only=True, data_only=True)
        values = np.array(list(book.active.iter_rows(min_row=3, min_col=2, max_col=9,
                                                     values_only=True)), dtype=float)
        book.close()
    xyz = np.isfinite(values[:, :4]).all(axis=1)
    spin = np.isfinite(values[:, 6:8]).all(axis=1)
    time = values[xyz, 0]
    if not np.allclose(time, np.arange(len(time)) * .01):
        raise ValueError(f'{path.name}: inconsistent position clock')
    if not np.array_equal(values[:, 0], values[:, 6]) or not np.all(xyz[spin]):
        raise ValueError(f'{path.name}: spin and position clocks differ')
    positions = values[xyz][:, [2, 1, 3]]
    positions[:, :2] -= positions[0, :2].copy()
    return time, positions, values[spin, 6:8]


def crossing(time, positions):
    indices = np.flatnonzero((positions[:-1, 0] < 11.) & (positions[1:, 0] >= 11.))
    if not len(indices):
        return None, None
    i = indices[0]
    fraction = (11. - positions[i, 0]) / (positions[i + 1, 0] - positions[i, 0])
    point = positions[i] + fraction * (positions[i + 1] - positions[i])
    if point[2] <= .11 or np.any(positions[:i + 1, 2] < .11):
        return None, None
    return float(time[i] + fraction * (time[i + 1] - time[i])), point[1:]


def load_case(name, path):
    time, points, spin = read_trial(path)
    reference_time, reference = crossing(time, points)
    index = np.searchsorted(time, list(OBS_TIMES))
    if not np.allclose(time[index], OBS_TIMES):
        raise ValueError(f'{name}: 10 ms clock does not contain 0/50/100 ms')
    return dict(name=name, workbook=path.name,
                workbook_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                times=time, points=points, spin=spin, obs_index=index,
                reference_time_s=reference_time,
                reference_yz_m=None if reference is None else reference)


def early_window(trial):
    index = trial['obs_index']
    return trial['times'][index], trial['points'][index]


# ---------------------------------------------------------------------------
# Lift parameterisation shared by both laws
# ---------------------------------------------------------------------------
def transverse_frame(velocity):
    """Return (z_perp, y_perp, speed) with z_perp up and y_perp leftward."""
    speed = float(np.linalg.norm(velocity))
    if not np.isfinite(speed) or speed <= 0:
        raise ValueError('degenerate initial velocity')
    u = velocity / speed
    z_perp = np.array([0., 0., 1.]) - u * u[2]
    norm = float(np.linalg.norm(z_perp))
    if norm < 1e-9:
        raise ValueError('vertical launch: transverse frame undefined')
    z_perp = z_perp / norm
    y_perp = np.cross(z_perp, u)
    return z_perp, y_perp, speed


def make_rhs(law, c, v0):
    """ODE right-hand side for one law with the shared initial CL vector c."""
    z_perp, y_perp, speed0 = transverse_frame(v0)
    q = float(c[1]) * z_perp - float(c[0]) * y_perp
    if law == 'canon':
        omega = q * (speed0 / (1.4 * CFG.radius))
        theta = np.r_[np.zeros(3), omega, CD][None]
        return lambda t, y: derivative(y[None], theta, t, CFG)[0]
    if law != 'const_cl':
        raise ValueError(f'unknown law {law!r}')

    def rhs(t, y):
        v = y[3:]
        speed = float(np.linalg.norm(v))
        return np.r_[v, -K_AERO * CD * speed * v
                     + K_AERO * speed * np.cross(q, v) + GRAV]
    return rhs


def initial_acceleration(law, c, v0):
    """Total acceleration at t = 0; both laws must agree for |c| <= .30."""
    z_perp, y_perp, speed = transverse_frame(v0)
    if law == 'const_cl':
        q = float(c[1]) * z_perp - float(c[0]) * y_perp
        return (-K_AERO * CD * speed * v0 + K_AERO * speed * np.cross(q, v0)
                + GRAV)
    if law == 'canon':
        omega = (float(c[1]) * z_perp - float(c[0]) * y_perp) * (speed / (1.4 * CFG.radius))
        theta = np.r_[np.zeros(3), omega, CD][None]
        return derivative(np.r_[np.zeros(3), v0][None], theta, 0., CFG)[0][3:]
    raise ValueError(f'unknown law {law!r}')


def canonical_initial_cl(c, v0):
    """Initial CL produced by the canonical law for the requested |c|."""
    z_perp, y_perp, speed = transverse_frame(v0)
    omega = (float(c[1]) * z_perp - float(c[0]) * y_perp) * (speed / (1.4 * CFG.radius))
    transverse_spin = float(np.linalg.norm(np.cross(omega, v0))) / speed ** 2
    return min(1.4 * CFG.radius * transverse_spin, LIFT_CAP)


# ---------------------------------------------------------------------------
# Fit / prediction
# ---------------------------------------------------------------------------
def make_blocks(law, prior, init, obs_times, obs_points, prior_params, sigma):
    p0 = obs_points[0]

    def decode(x):
        if init == 'free3':
            return np.asarray(x[:3], float), np.asarray(x[3:6], float), np.asarray(x[6:8], float)
        if init == 'fixed0':
            return np.zeros(3), np.asarray(x[:3], float), np.asarray(x[3:5], float)
        raise ValueError(init)

    def prior_block(c):
        if prior == 'none':
            return np.zeros(0)
        magnitude = math.hypot(float(c[0]), float(c[1]))
        if prior == 'iso':
            return np.array([(magnitude - PRIOR['mag_mean']) / PRIOR['mag_sd']])
        if prior == 'manual':
            return np.array([(magnitude - PRIOR['mag_mean']) / PRIOR['mag_sd'],
                             (float(c[0]) - PRIOR['vert_mean']) / PRIOR['vert_sd']])
        if prior == 'loocv':
            p = prior_params or {}
            return np.array([(magnitude - p['mag_mean']) / p['mag_sd'],
                             (float(c[0]) - p['vert_mean']) / p['vert_sd']])
        raise ValueError(prior)

    def integrate(x):
        dr0, v0, c = decode(x)
        rhs = make_rhs(law, c, v0)
        sol = solve_ivp(rhs, (0., obs_times[-1]), np.r_[p0 + dr0, v0],
                        t_eval=obs_times, rtol=1e-9, atol=1e-10)
        if not sol.success or sol.y.shape[1] != len(obs_times):
            raise RuntimeError('prefix integration failed')
        return sol.y[:3].T

    def blocks(x):
        trajectory = integrate(x)
        if init == 'fixed0':
            position = (trajectory[1:] - obs_points[1:]) / sigma
        else:
            position = (trajectory - obs_points) / sigma
        _, _, c = decode(x)
        return position.ravel(), prior_block(c)

    def residual(x):
        position, prior = blocks(x)
        return np.concatenate([position, prior])

    return residual, blocks, decode


def bounds_for(init):
    lower, upper = [], []
    if init == 'free3':
        lower += [-DR0_BOUND] * 3
        upper += [DR0_BOUND] * 3
    lower += [5., -60., -60.]
    upper += [60., 60., 60.]
    lower += [-C_BOUND] * 2
    upper += [C_BOUND] * 2
    return np.array(lower), np.array(upper)


def make_starts(init, obs_points, c_seeds=C_SEEDS, v_seeds=V_SEEDS):
    p0, p1, p2 = obs_points
    acceleration = (p2 - 2 * p1 + p0) / .05 ** 2
    velocity = {'quad': (p1 - p0) / .05 - .025 * acceleration,
                'linear': (p2 - p0) / .10}
    starts = []
    for c_label, c in c_seeds:
        for v_label in v_seeds:
            v0 = np.clip(velocity[v_label], [5., -60., -60.], [60., 60., 60.])
            dr0 = [0., 0., 0.] if init == 'free3' else []
            starts.append((f'{c_label}/{v_label}',
                           np.r_[dr0, v0, np.asarray(c, float)]))
    return starts


def predict_crossing(law, c, v0, dr0, start_point):
    rhs = make_rhs(law, c, v0)
    y0 = np.r_[start_point + dr0, v0]

    def ground(t, y):
        return y[2] - CFG.radius

    def goal(t, y):
        return y[0] - GOAL

    ground.terminal = True
    ground.direction = -1
    goal.terminal = True
    goal.direction = 1
    try:
        sol = solve_ivp(rhs, (0., CFG.horizon), y0, events=(ground, goal),
                        rtol=1e-9, atol=1e-10, max_step=.01)
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        return None, {'note': f'prediction integration failed: {exc}'}
    if not sol.success:
        return None, {'note': f'prediction integration failed: {sol.message}'}
    if not len(sol.t_events[1]):
        return None, {'note': 'no goal-plane crossing before horizon'}
    goal_time = float(sol.t_events[1][0])
    if len(sol.t_events[0]) and float(sol.t_events[0][0]) < goal_time:
        return None, {'note': 'ground contact before goal plane'}
    point = sol.y_events[1][0]
    return point[1:3].astype(float), {'crossing_time_s': goal_time, 'note': 'ok'}


def run_start(label, x0, law, prior, init, prior_params, obs_times, obs_points,
              sigma):
    lower, upper = bounds_for(init)
    x0 = np.clip(np.asarray(x0, float), lower, upper)
    residual, blocks, decode = make_blocks(law, prior, init, obs_times,
                                           obs_points, prior_params, sigma)
    row = dict(start=label, x0=x0.tolist())
    try:
        fit = least_squares(residual, x0, bounds=(lower, upper),
                            x_scale='jac', max_nfev=MAX_NFEV)
    except Exception as exc:  # noqa: BLE001
        row.update(converged=False, status=-1, message=str(exc), cost=None,
                   data_ss=None, prior_ss=None, nfev=0, optimality=None,
                   prediction_yz_m=None, error_cm=None,
                   prediction_note='optimizer failed')
        return row
    converged = bool(fit.success)
    dr0, v0, c = decode(fit.x)
    try:
        position, prior = blocks(fit.x)
    except Exception as exc:  # noqa: BLE001
        row.update(converged=False, status=-2, message=f'post-fit evaluation failed: {exc}',
                   cost=None, data_ss=None, prior_ss=None, nfev=int(fit.nfev),
                   optimality=None, prediction_yz_m=None, error_cm=None,
                   c_vert=float(c[0]), c_lat=float(c[1]),
                   cl_mag=float(math.hypot(c[0], c[1])), v0_m_s=v0.tolist(),
                   dr0_m=dr0.tolist(), prediction_note='post-fit evaluation failed')
        return row
    data_ss = float(position @ position)
    prior_ss = float(prior @ prior)
    row.update(converged=converged, status=int(fit.status), message=str(fit.message),
               cost=float(.5 * (data_ss + prior_ss)), data_ss=data_ss,
               prior_ss=prior_ss, nfev=int(fit.nfev),
               optimality=None if fit.optimality is None
               or not np.isfinite(fit.optimality) else float(fit.optimality),
               c_vert=float(c[0]), c_lat=float(c[1]),
               cl_mag=float(math.hypot(c[0], c[1])),
               v0_m_s=v0.tolist(), dr0_m=dr0.tolist(),
               active_bounds=''.join('L' if m == 1 else 'U' if m == -1 else '.'
                                     for m in fit.active_mask),
               prediction_yz_m=None, prediction_note='prediction deferred to branch selection')
    return row


def evaluate_trial(trial, law, prior, init, prior_params=None, *,
                   c_seeds=C_SEEDS, v_seeds=V_SEEDS, sigma=SIGMA):
    """Public entry point: the held-out future never reaches the fit."""
    early_times, early_points = early_window(trial)
    starts = make_starts(init, early_points, c_seeds, v_seeds)
    rows = [run_start(label, x0, law, prior, init, prior_params,
                      early_times, early_points, sigma) for label, x0 in starts]
    converged = [row for row in rows if row['converged'] and row['cost'] is not None]
    # Fall back to finite-cost starts if no start reported success; the flag is
    # recorded so an unconverged selection can never pass silently.
    usable = converged or [row for row in rows if row['cost'] is not None]
    best = None
    for row in rows:
        row['is_best'] = False
        row['is_near_optimal'] = False
    if usable:
        best = min(usable, key=lambda r: (round(r['cost'], 12),
                                          r['c_vert'], r['c_lat'], *r['v0_m_s']))
        best_cost = best['cost']
        for row in rows:
            row['is_best'] = row is best
            row['is_near_optimal'] = bool(
                row['cost'] is not None
                and row['cost'] <= 1.01 * best_cost + 1e-9)
    # Integrate to x = 11 m only for the selected and near-optimal branches.
    for row in rows:
        if not (row['is_best'] or (row['is_near_optimal'] and row.get('converged'))):
            continue
        if row.get('c_vert') is None:
            continue
        prediction, note = predict_crossing(
            law, np.array([row['c_vert'], row['c_lat']]),
            np.asarray(row['v0_m_s']), np.asarray(row['dr0_m']), early_points[0])
        row['prediction_note'] = note.get('note')
        row['crossing_time_s'] = note.get('crossing_time_s')
        row['prediction_yz_m'] = None if prediction is None else prediction.tolist()
    reference = trial['reference_yz_m']
    prediction = None if best is None else best['prediction_yz_m']
    error = None
    if prediction is not None and reference is not None:
        error = float(100. * np.linalg.norm(np.asarray(prediction) - reference))
    return dict(rows=rows, best=best, reference=reference, prediction=prediction,
                error_cm=error,
                best_converged=None if best is None else bool(best['converged']))


# ---------------------------------------------------------------------------
# Leave-one-trial-out prior from the canonical full-track fits of OTHER trials
# ---------------------------------------------------------------------------
def full_track_fit(times, points):
    """Canonical effective-spin full-track fit (same model as p4_window_residual)."""
    slope, origin = np.polyfit(times, points, 1)
    direction = slope / np.linalg.norm(slope)
    transverse = np.cross(direction, [0., 0., 1.])
    transverse /= np.linalg.norm(transverse)
    basis = np.stack((transverse, np.cross(direction, transverse)))
    guess = np.r_[origin, slope, .22, 0., 0.]
    lower = np.r_[[-np.inf] * 2, .11, [0., -60., -60.], [.15, -60., -60.]]
    upper = np.r_[[np.inf] * 3, [60.] * 3, [.30, 60., 60.]]
    cfg = Config()

    def residual(parameters):
        omega = parameters[7:9] @ basis
        theta = np.r_[np.zeros(3), omega, parameters[6]][None]
        solution = solve_ivp(lambda t, y: derivative(y[None], theta, t, cfg)[0],
                             (0., times[-1]), parameters[:6], t_eval=times,
                             rtol=1e-8, atol=1e-10)
        if not solution.success:
            raise RuntimeError(solution.message)
        return (solution.y[:3].T - points).ravel()

    fit = least_squares(residual, np.clip(guess, lower, upper), bounds=(lower, upper),
                        x_scale='jac', max_nfev=120)
    if not fit.success:
        raise RuntimeError(f'full-track fit failed: {fit.message}')
    v0 = fit.x[3:6]
    speed = float(np.linalg.norm(v0))
    omega = fit.x[7:9] @ basis
    force = np.cross(omega, v0)
    force_norm = float(np.linalg.norm(force))
    cl_mag = (min(1.4 * CFG.radius * force_norm / speed ** 2, LIFT_CAP)
              if speed > 0 and force_norm > 0 else 0.)
    if force_norm > 0:
        z_perp, y_perp, _ = transverse_frame(v0)
        direction = force / force_norm
        c_vert = cl_mag * float(direction @ z_perp)
        c_lat = cl_mag * float(direction @ y_perp)
    else:
        c_vert = c_lat = 0.
    rmse = float(np.sqrt(np.mean(np.sum(fit.fun.reshape(-1, 3) ** 2, axis=1))))
    return dict(c_vert=c_vert, c_lat=c_lat, cl_mag=cl_mag,
                cd=float(fit.x[6]), v0_m_s=v0.tolist(),
                spin_rad_s=omega.tolist(),
                fit_rmse_cm=100. * rmse, converged=True)


def fold_prior(summaries, held_out, floors=LOOCV_FLOOR):
    """Fixed-form diagonal Gaussian in (|c|, c_vert); EXCLUDES the held-out key."""
    others = [summaries[key] for key in summaries if key != held_out]
    if len(others) < 2:
        raise ValueError('leave-one-trial-out prior needs at least two other trials')
    magnitudes = np.array([other['cl_mag'] for other in others], float)
    vertical = np.array([other['c_vert'] for other in others], float)
    return dict(
        members=[key for key in summaries if key != held_out],
        mag_mean=float(np.clip(np.mean(magnitudes), .05, LIFT_CAP)),
        mag_sd=float(max(floors['mag_sd'], np.std(magnitudes, ddof=1))),
        vert_mean=float(np.mean(vertical)),
        vert_sd=float(max(floors['vert_sd'], np.std(vertical, ddof=1))),
        floors=dict(floors))


# ---------------------------------------------------------------------------
# Summary / contrasts
# ---------------------------------------------------------------------------
def _mean(values):
    values = [v for v in values if v is not None]
    return float(np.mean(values)) if values else None


def _median(values):
    values = [v for v in values if v is not None]
    return float(np.median(values)) if values else None


def summarize(rows, config_keys, case_names):
    indexed = {}
    for row in rows:
        indexed.setdefault((row['config'], row['case']), []).append(row)
    out = {}
    for key in config_keys:
        cases, errors, costs = {}, [], []
        for case in case_names:
            sub = indexed.get((key, case), [])
            best = next((row for row in sub if row.get('is_best')), None)
            near = [row for row in sub if row.get('is_near_optimal')]
            with_prediction = [row for row in near
                               if row.get('prediction_yz_m') is not None]
            predictions = [np.asarray(row['prediction_yz_m'], float)
                           for row in with_prediction]
            spread = None
            if len(predictions) > 1:
                spread = 100. * max(float(np.linalg.norm(a - b))
                                    for i, a in enumerate(predictions)
                                    for b in predictions[i + 1:])
            case_entry = dict(
                error_cm=None if best is None else best.get('error_cm'),
                cost=None if best is None else best.get('cost'),
                data_ss=None if best is None else best.get('data_ss'),
                prior_ss=None if best is None else best.get('prior_ss'),
                c_vert=None if best is None else best.get('c_vert'),
                c_lat=None if best is None else best.get('c_lat'),
                cl_mag=None if best is None else best.get('cl_mag'),
                v0_m_s=None if best is None else best.get('v0_m_s'),
                dr0_m=None if best is None else best.get('dr0_m'),
                prediction_yz_m=None if best is None else best.get('prediction_yz_m'),
                target_yz_m=None if best is None else best.get('target_yz_m'),
                n_starts=len(sub),
                n_converged=sum(1 for row in sub if row.get('converged')),
                n_near_optimal=len(near),
                n_near_optimal_with_prediction=len(with_prediction),
                best_converged=None if best is None else best.get('converged'),
                near_optimal_prediction_spread_cm=spread,
                near_optimal_error_cm=[row.get('error_cm') for row in near],
                branches=[dict(start=row['start'], cost=row.get('cost'),
                               converged=row.get('converged'),
                               error_cm=row.get('error_cm'),
                               c_vert=row.get('c_vert'), c_lat=row.get('c_lat'),
                               prediction_yz_m=row.get('prediction_yz_m'))
                          for row in near])
            cases[case] = case_entry
            if case_entry['error_cm'] is not None:
                errors.append(case_entry['error_cm'])
            if case_entry['cost'] is not None:
                costs.append(case_entry['cost'])
        law, prior, init = key.split('|')
        out[key] = dict(config=key, law=law, prior=prior, init=init,
                        n_cases=len(errors), mean_error_cm=_mean(errors),
                        median_error_cm=_median(errors),
                        mean_cost=_mean(costs),
                        per_case=cases)
    return out


def contrast(table, key_a, key_b, field='error_cm'):
    per_case = {}
    for case in CASES:
        a = table[key_a]['per_case'].get(case, {}).get(field)
        b = table[key_b]['per_case'].get(case, {}).get(field)
        per_case[case] = None if a is None or b is None else float(a - b)
    values = [v for v in per_case.values() if v is not None]
    return dict(a=key_a, b=key_b, field=field, per_case=per_case,
                mean=None if not values else float(np.mean(values)),
                median=None if not values else float(np.median(values)))


def main_effects(table, keys):
    out = {}
    for index, (factor, levels) in enumerate((('law', LAWS), ('prior', PRIORS),
                                              ('init', INITS))):
        for level in levels:
            errors = []
            for key in keys:
                if key.split('|')[index] != level:
                    continue
                for case in CASES:
                    value = table[key]['per_case'].get(case, {}).get('error_cm')
                    if value is not None:
                        errors.append(value)
            out[f'{factor}:{level}'] = dict(mean_error_cm=_mean(errors),
                                            median_error_cm=_median(errors),
                                            n_case_config=len(errors))
    return out


# ---------------------------------------------------------------------------
# Self-checks (no workbook required for the first block)
# ---------------------------------------------------------------------------
def algebra_checks():
    v0 = np.array([31., 2.5, 1.2])
    z_perp, y_perp, speed = transverse_frame(v0)
    checks = {}
    total = {}
    for law in LAWS:
        total[law] = initial_acceleration(law, np.array([.18, -.12]), v0)
    checks['initial_acceleration_law_identity'] = dict(
        passed=bool(np.allclose(total['const_cl'], total['canon'], rtol=0, atol=1e-9)),
        max_abs_delta=float(np.max(np.abs(total['const_cl'] - total['canon']))),
        note='same c gives the same total t=0 acceleration in both laws for |c| <= .30')
    c = np.array([.21, .09])
    checks['canonical_cl0_identity'] = dict(
        passed=bool(abs(canonical_initial_cl(c, v0) - float(np.hypot(*c))) < 1e-9),
        cl0=canonical_initial_cl(c, v0), requested=float(np.hypot(*c)))
    checks['canonical_cap'] = dict(
        passed=bool(abs(canonical_initial_cl(np.array([.5, .0]), v0) - LIFT_CAP) < 1e-12),
        cl0=canonical_initial_cl(np.array([.5, .0]), v0),
        note='|c| > .30 saturates the canonical law; the constant law does not cap')
    up = initial_acceleration('const_cl', np.array([.10, .10]), v0)
    down = initial_acceleration('const_cl', np.array([.10, -.10]), v0)
    checks['lateral_sign_symmetry'] = dict(
        passed=bool(np.allclose((up - down) / 2.,
                                K_AERO * speed ** 2 * .10 * y_perp, rtol=0, atol=1e-9)),
        note='flipping c_lat mirrors exactly the lateral lift; no sign is inherited '
             'from the manual start')
    return all(item['passed'] for item in checks.values()), checks


def synthetic_trial():
    times = np.arange(0., 1.0, .01)
    points = np.column_stack((30. * times, .30 * times + .20 * times ** 2,
                              .45 + 3.2 * times - 4.0 * times ** 2))
    index = np.searchsorted(times, list(OBS_TIMES))
    reference_time, reference = crossing(times, points)
    if reference is None:
        raise RuntimeError('synthetic trial does not cross x = 11 m')
    return dict(name='synthetic', workbook='synthetic', workbook_sha256='0' * 64,
                times=times, points=points, spin=np.zeros((len(times), 2)),
                obs_index=index, reference_time_s=reference_time,
                reference_yz_m=reference)


def structural_checks(cases, table=None, rows=None):
    checks = {}
    if cases:
        trial = next(iter(cases.values()))
        base = evaluate_trial(trial, 'const_cl', 'manual', 'free3', None)
        altered = {key: (value.copy() if isinstance(value, np.ndarray) else value)
                   for key, value in trial.items()}
        altered['points'] = trial['points'].copy()
        altered['points'][trial['times'] > .10 + 1e-9] += np.array([0., .50, .35])
        altered['reference_yz_m'] = trial['reference_yz_m'] + np.array([.50, .35])
        moved = evaluate_trial(altered, 'const_cl', 'manual', 'free3', None)
        same_fit = json.dumps(jsonable(base['rows']), sort_keys=True) == json.dumps(
            jsonable(moved['rows']), sort_keys=True)
        checks['future_invariance'] = dict(
            passed=bool(same_fit and base['prediction'] is not None),
            fit_and_prediction_unchanged=bool(same_fit),
            score_changed=bool(base['error_cm'] != moved['error_cm']),
            error_before_cm=base['error_cm'], error_after_cm=moved['error_cm'],
            note='only the measured frames after 0.10 s and the 11 m reference were altered')
        early_times, _ = early_window(trial)
        checks['early_window_is_0_50_100ms'] = dict(
            passed=bool(np.allclose(early_times, OBS_TIMES)),
            times=early_times.tolist())

    summaries = {'A': dict(cl_mag=.24, c_vert=.05), 'B': dict(cl_mag=.19, c_vert=.10),
                 'C': dict(cl_mag=.27, c_vert=.03)}
    a = fold_prior(summaries, 'A')
    perturbed = {k: dict(v) for k, v in summaries.items()}
    perturbed['A'] = dict(cl_mag=.99, c_vert=.99)
    b = fold_prior(perturbed, 'A')
    changed = {k: dict(v) for k, v in summaries.items()}
    changed['B'] = dict(cl_mag=.02, c_vert=-.40)
    c = fold_prior(changed, 'A')
    checks['loocv_prior_isolation'] = dict(
        passed=bool(a == b and a != c and 'A' not in a['members']),
        held_out_perturbation_leaves_prior_unchanged=bool(a == b),
        other_trial_perturbation_changes_prior=bool(a != c),
        members=a['members'], prior=a)

    if table is not None and 'const_cl|manual|free3' in table:
        per_case = {case: table['const_cl|manual|free3']['per_case'][case]['error_cm']
                    for case in CASES}
        archived = {'Fig3': 12.66, 'Sample05': 9.74, 'Sample12': 11.76}
        deltas = {case: None if per_case[case] is None else per_case[case] - archived[case]
                  for case in CASES}
        mean = table['const_cl|manual|free3']['mean_error_cm']
        checks['manual_11_39_baseline'] = dict(
            passed=bool(mean is not None and abs(mean - 11.39) <= 2.0
                        and all(value is None or abs(value) <= 3.0
                                for value in deltas.values())),
            archived_per_case_cm=archived, archived_mean_cm=11.39,
            reproduced_per_case_cm=per_case, reproduced_mean_cm=mean,
            delta_cm=deltas,
            note='factorial uses canonical constants (rho 1.20, g 9.81) and rtol 1e-9; '
                 'the manual uses rho 1.225, g 9.80665, rtol 1e-7. The closest '
                 'analogue is const_cl/manual/free3, not a bit-exact rerun.')
    if rows:
        errors_ok = True
        for row in rows:
            if row.get('prediction_yz_m') is None or row.get('target_yz_m') is None:
                errors_ok &= row.get('error_cm') is None
                continue
            expected = 100. * float(np.linalg.norm(
                np.asarray(row['prediction_yz_m']) - np.asarray(row['target_yz_m'])))
            errors_ok &= abs(expected - row['error_cm']) <= 1e-9
        checks['score_arithmetic'] = dict(passed=bool(errors_ok))
    return checks


def aggregation_check():
    """Exercise summarize/contrast/main_effects on fabricated rows (no data needed)."""
    rows = []
    keys = [f'{law}|{prior}|{init}' for law in LAWS for prior in PRIORS
            for init in INITS]
    for key in keys:
        for case in CASES:
            rows.append(dict(config=key, case=case, start='manual/quad',
                             converged=True, cost=.5, data_ss=1., prior_ss=0.,
                             c_vert=.10, c_lat=.20, cl_mag=.2236,
                             v0_m_s=[30., 0., 0.], dr0_m=[0., 0., 0.],
                             prediction_yz_m=[.10, .20], target_yz_m=[.10, .20],
                             error_cm=1.0, is_best=True, is_near_optimal=True))
    table = summarize(rows, keys, CASES)
    item = contrast(table, 'canon|none|fixed0', 'const_cl|manual|free3')
    effects = main_effects(table, keys)
    return dict(passed=bool(table['canon|none|fixed0']['mean_error_cm'] == 1.0
                            and item['mean'] == 0.0 and 'law:canon' in effects),
                mean=table['canon|none|fixed0']['mean_error_cm'],
                contrast_mean=item['mean'], effect_keys=sorted(effects))


def jsonable(obj):
    if isinstance(obj, dict):
        return {str(key): jsonable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(value) for value in obj]
    if isinstance(obj, np.ndarray):
        return jsonable(obj.tolist())
    if isinstance(obj, (np.floating, float)):
        value = float(obj)
        return value if math.isfinite(value) else None
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def save_json(path, payload):
    path.write_text(json.dumps(jsonable(payload), ensure_ascii=False, indent=2,
                                allow_nan=False), encoding='utf-8')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
ROW_FIELDS = ('cohort', 'case', 'law', 'prior', 'init', 'config', 'start',
              'converged', 'status', 'message', 'nfev', 'optimality', 'cost',
              'objective', 'data_ss', 'prior_ss', 'c_vert', 'c_lat', 'cl_mag',
              'v0_m_s', 'dr0_m', 'prediction_yz_m', 'target_yz_m', 'error_cm',
              'pred_y_m', 'pred_z_m', 'target_y_m', 'target_z_m',
              'crossing_time_s', 'prediction_note', 'is_best', 'is_near_optimal',
              'active_bounds', 'x0', 'prior_params')


def write_csv(path, records, fields):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for record in records:
            row = {}
            for field in fields:
                value = record.get(field)
                if isinstance(value, (list, tuple)):
                    value = ' '.join(f'{float(v):.6g}' for v in value)
                elif isinstance(value, dict):
                    value = json.dumps(jsonable(value), sort_keys=True)
                elif isinstance(value, float):
                    value = f'{value:.6g}'
                elif value is None:
                    value = ''
                row[field] = value
            writer.writerow(row)


def annotate(rows, result, cohort, case, law, prior, init, prior_params=None):
    target = result['reference']
    for row in rows:
        prediction = row.get('prediction_yz_m')
        row.update(cohort=cohort, case=case, law=law, prior=prior, init=init,
                   config=f'{law}|{prior}|{init}',
                   objective=row.get('cost'),
                   error_cm=None if prediction is None or target is None else float(100. * np.linalg.norm(np.asarray(prediction) - np.asarray(target))),
                   target_yz_m=None if target is None
                   else np.asarray(target).tolist(),
                   target_y_m=None if target is None else float(target[0]),
                   target_z_m=None if target is None else float(target[1]),
                   pred_y_m=None if prediction is None else float(prediction[0]),
                   pred_z_m=None if prediction is None else float(prediction[1]),
                   prior_params=prior_params)


def run_factorial(cases):
    rows = []
    keys = [f'{law}|{prior}|{init}' for law in LAWS for prior in PRIORS
            for init in INITS]
    for law, prior, init in [(law, prior, init) for law in LAWS
                             for prior in PRIORS for init in INITS]:
        per_case = {}
        for case in CASES:
            result = evaluate_trial(cases[case], law, prior, init)
            annotate(result['rows'], result, 'factorial', case, law, prior, init)
            rows.extend(result['rows'])
            per_case[case] = result['error_cm']
        print(f'{law}|{prior}|{init}'.ljust(26),
              {case: None if value is None else round(value, 2)
               for case, value in per_case.items()}, flush=True)
    table = summarize(rows, keys, CASES)
    contrasts = []
    for prior in PRIORS:
        for init in INITS:
            contrasts.append(contrast(table, f'canon|{prior}|{init}',
                                      f'const_cl|{prior}|{init}'))
    for law in LAWS:
        for init in INITS:
            contrasts.append(contrast(table, f'{law}|iso|{init}', f'{law}|none|{init}'))
            contrasts.append(contrast(table, f'{law}|manual|{init}', f'{law}|iso|{init}'))
            contrasts.append(contrast(table, f'{law}|manual|{init}', f'{law}|none|{init}'))
    for law in LAWS:
        for prior in PRIORS:
            contrasts.append(contrast(table, f'{law}|{prior}|free3',
                                      f'{law}|{prior}|fixed0'))
    contrasts.append(contrast(table, 'canon|none|fixed0', 'const_cl|manual|free3'))
    contrasts.append(contrast(table, 'canon|manual|free3', 'const_cl|manual|free3'))
    return rows, table, contrasts


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--data', type=Path, help='directory with the three workbooks')
    parser.add_argument('--out', type=Path, default=SB / 'runs/asai_factorial')
    parser.add_argument('--selftest', action='store_true',
                        help='run workbook-free checks and exit')
    parser.add_argument('--sigma-sensitivity', action='store_true',
                        help='add prespecified sigma = .005/.020 for iso+manual, '
                             'both laws, free3')
    args = parser.parse_args(argv)

    if args.selftest:
        passed, algebra = algebra_checks()
        trial = synthetic_trial()
        checks = dict(algebra_all=dict(passed=bool(passed), detail=algebra))
        checks.update(structural_checks({'synthetic': trial}))
        checks['aggregation'] = aggregation_check()
        summary = dict(passed=bool(passed and all(item.get('passed')
                                                  for item in checks.values())),
                       checks=checks)
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            save_json(args.out / 'checks_selftest.json', summary)
        print(json.dumps(jsonable(summary), ensure_ascii=False, indent=2))
        return 0 if summary['passed'] else 1

    if not args.data:
        parser.error('--data is required unless --selftest is used')
    cases = {}
    for name, filename in FILES.items():
        path = args.data / filename
        if not path.exists():
            raise FileNotFoundError(f'{path} not found; pass the workbook directory')
        cases[name] = load_case(name, path)
    args.out.mkdir(parents=True, exist_ok=True)

    started = time.time()
    rows, table, contrasts = run_factorial(cases)

    full_fits = {}
    for case in CASES:
        full_fits[case] = full_track_fit(cases[case]['times'], cases[case]['points'])
        print('full', case, 'cl', round(full_fits[case]['cl_mag'], 4),
              'rmse_cm', round(full_fits[case]['fit_rmse_cm'], 2), flush=True)

    loocv_priors = {case: fold_prior(full_fits, case) for case in CASES}
    loocv_rows = []
    loocv_keys = [f'{law}|loocv|{init}' for law in LAWS for init in INITS]
    for law in LAWS:
        for init in INITS:
            for case in CASES:
                result = evaluate_trial(cases[case], law, 'loocv', init,
                                        prior_params=loocv_priors[case])
                annotate(result['rows'], result, 'loocv', case, law, 'loocv', init,
                         prior_params=loocv_priors[case])
                loocv_rows.extend(result['rows'])
    loocv_table = summarize(loocv_rows, loocv_keys, CASES)

    sensitivity = {}
    if args.sigma_sensitivity:
        for sigma in (.005, .020):
            for law in LAWS:
                for prior in ('iso', 'manual'):
                    key = f'{law}|{prior}|free3|sigma{sigma:.3f}'
                    per_case = {}
                    for case in CASES:
                        result = evaluate_trial(cases[case], law, prior, 'free3',
                                                sigma=sigma)
                        best = result['best']
                        per_case[case] = dict(
                            error_cm=result['error_cm'],
                            prediction_yz_m=result['prediction'],
                            cost=None if best is None else best['cost'],
                            c_vert=None if best is None else best['c_vert'],
                            c_lat=None if best is None else best['c_lat'])
                    values = [item['error_cm'] for item in per_case.values()
                              if item['error_cm'] is not None]
                    sensitivity[key] = dict(sigma_m=sigma, law=law, prior=prior,
                                            per_case=per_case,
                                            mean_error_cm=_mean(values),
                                            median_error_cm=_median(values))

    passed_algebra, algebra = algebra_checks()
    checks = dict(algebra_all=dict(passed=bool(passed_algebra), detail=algebra))
    checks.update(structural_checks(cases, table, rows))
    checks['completeness'] = dict(
        passed=bool(all(table[key]['n_cases'] == len(CASES) for key in table)
                    and all(loocv_table[key]['n_cases'] == len(CASES)
                            for key in loocv_table)))
    archived_full = {'Fig3': 1.486, 'Sample05': 1.765, 'Sample12': 1.630}
    checks['full_track_fit'] = dict(
        passed=bool(all(fit['converged'] and abs(fit['fit_rmse_cm']
                                                - archived_full[case]) <= 0.30
                        for case, fit in full_fits.items())),
        fits=full_fits,
        archived_rmse_cm=archived_full,
        tolerance_cm=0.30,
        note='our replication of the canonical full-track fit must agree with the '
             'archived RMSE within 0.30 cm; a larger gap means it is not the same fit')
    first = CASES[0]
    repeat = dict(c_seeds=C_SEEDS[:2], v_seeds=('quad',))
    once = evaluate_trial(cases[first], 'const_cl', 'manual', 'free3', **repeat)
    twice = evaluate_trial(cases[first], 'const_cl', 'manual', 'free3', **repeat)
    checks['determinism'] = dict(
        passed=bool(json.dumps(jsonable(once['rows']), sort_keys=True)
                    == json.dumps(jsonable(twice['rows']), sort_keys=True)),
        note='no RNG; multi-start seeds are fixed; scipy fit is deterministic')
    unconverged = [(key, case) for key in table for case in CASES
                   if table[key]['per_case'][case]['n_converged'] == 0]
    checks['convergence_summary'] = dict(
        config_case_without_converged_start=len(unconverged),
        examples=[[key, case] for key, case in unconverged[:12]],
        note='recorded only; a case without any converged start is flagged here and '
             'also by best_converged=false in the table')
    checks['passed'] = bool(all(item.get('passed', True) for item in checks.values()))

    payload = dict(
        study='asai_11m_short_window_factorial',
        label='exploratory; n = 3; all three tracks were previously inspected; '
              'no independent final test',
        deterministic=dict(rng='none', starts=[list(seed) for seed in C_SEEDS],
                           v0_seeds=list(V_SEEDS), max_nfev=MAX_NFEV),
        constants=dict(mass=CFG.mass, radius=CFG.radius, density=CFG.density,
                       gravity=CFG.gravity, cd=CD, aero_k=K_AERO,
                       lift_cap=LIFT_CAP, goal_m=GOAL, sigma_m=SIGMA,
                       observation_times_s=list(OBS_TIMES),
                       dr0_bound_m=DR0_BOUND, c_bound=C_BOUND,
                       sigma_sensitivity_used=bool(args.sigma_sensitivity)),
        hashes=dict(script_sha256=hashlib.sha256(HERE.read_bytes()).hexdigest(),
                    workbooks={case: cases[case]['workbook_sha256'] for case in CASES}),
        inputs={case: dict(workbook=cases[case]['workbook'],
                           frames=len(cases[case]['times']),
                           reference_time_s=cases[case]['reference_time_s'],
                           reference_yz_m=None if cases[case]['reference_yz_m'] is None
                           else cases[case]['reference_yz_m'].tolist())
                for case in CASES},
        table=table, contrasts=contrasts,
        main_effects=main_effects(table, list(table)),
        loocv=dict(priors=loocv_priors, table=loocv_table,
                   note='prior means/SDs come from canonical full-track fits of the '
                        'OTHER trials only; the held-out fit uses only its own '
                        '0/50/100 ms points; those full-track fits are retrospective'),
        sigma_sensitivity=sensitivity,
        checks=checks,
        runtime_s=time.time() - started,
    )
    save_json(args.out / 'results.json', payload)
    write_csv(args.out / 'results.csv', rows + loocv_rows, ROW_FIELDS)
    contrast_rows = []
    for item in contrasts:
        row = dict(kind='contrast', a=item['a'], b=item['b'], field=item['field'],
                   mean=item['mean'], median=item['median'])
        for case in CASES:
            row[f'per_case_{case}'] = item['per_case'][case]
        contrast_rows.append(row)
    write_csv(args.out / 'contrasts.csv', contrast_rows,
              ('kind', 'a', 'b', 'field', 'mean', 'median',
               *[f'per_case_{case}' for case in CASES]))
    save_json(args.out / 'checks.json', checks)

    def show(value):
        return '  -  ' if value is None else f'{value:5.2f}'

    print('\nconfig                          Fig3  S05   S12   mean   median')
    for key in table:
        entry = table[key]
        values = [entry['per_case'][case]['error_cm'] for case in CASES]
        print(f'{key:30s} ' + ' '.join(show(value) for value in values)
              + f" {show(entry['mean_error_cm'])} {show(entry['median_error_cm'])}")
    print('\nLOOCV prior per fold:')
    for case in CASES:
        prior = loocv_priors[case]
        print(f"  {case:8s} members={prior['members']} "
              f"mag={prior['mag_mean']:.3f}+-{prior['mag_sd']:.3f} "
              f"vert={prior['vert_mean']:.3f}+-{prior['vert_sd']:.3f}")
    print('\nchecks:', {key: item.get('passed') for key, item in checks.items()
                        if isinstance(item, dict)})
    print(f'\nwrote {args.out}/results.json, results.csv, contrasts.csv, checks.json '
          f'in {payload["runtime_s"]:.1f} s')
    return 0 if checks['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
