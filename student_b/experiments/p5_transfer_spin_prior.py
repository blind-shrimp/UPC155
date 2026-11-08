"""Learn effective spin from other DFL matches and forecast held-out prefixes."""
from collections import defaultdict
import json
import sys
from pathlib import Path

import numpy as np

SB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SB))
from p4_window_residual import fit_and_forecast
from physics import Config
from validate_real_penalties import CASES, coordinates, read_csv, save_json
from validate_real_spin import forecast, sample_prefix


def spin_basis(positions):
    direction = positions[2]-positions[0]
    direction /= np.linalg.norm(direction)
    side = np.cross(direction, [0., 0., 1.])
    side /= np.linalg.norm(side)
    return np.stack((side, np.cross(direction, side)))


def align(positions):
    forward = positions[2, :2]-positions[0, :2]
    forward /= np.linalg.norm(forward)
    rotation = np.stack((forward, [-forward[1], forward[0]]), axis=1)
    return np.column_stack(((positions[:, :2]-positions[0, :2]) @ rotation, positions[:, 2]))


def learn(training):
    # Each training match has equal weight. Shrink both moments toward the
    # broad control to limit the effect of a handful of effective-spin fits.
    by_match = defaultdict(list)
    for row in training:
        by_match[row['match']].append(row['components'])
    mean = np.mean([np.mean(values, axis=0) for values in by_match.values()], axis=0)
    variance = np.mean([np.mean((np.array(values)-mean)**2, axis=0)
                        for values in by_match.values()], axis=0)
    return .5*mean, np.sqrt(.5*variance+.5*(60**2/3))


def draws(count, seed, basis, learned):
    rng = np.random.default_rng(seed)
    theta = np.zeros((count, 7))
    theta[:, 6] = rng.uniform(.15, .30, count)
    if learned is None:
        components = rng.uniform(-60., 60., (count, 2))
    else:
        mean, scale = learned
        components = rng.normal(mean, scale, (count, 2))
        invalid = (np.abs(components) > 60.).any(axis=1)
        while invalid.any():
            components[invalid] = rng.normal(mean, scale, (invalid.sum(), 2))
            invalid = (np.abs(components) > 60.).any(axis=1)
    theta[:, 3:6] = components @ basis
    return theta


def main():
    data = SB.parent/'student-a'
    groups = defaultdict(list)
    for row in read_csv(data/'additional_flight_data_2026-11-07/positions.csv'):
        groups[row['case_id']].append(row)
    cases = {}
    source_fits = []
    for case, rows in groups.items():
        times, points = coordinates(sorted(rows, key=lambda row: float(row['t_s'])))
        points = align(points)
        match = rows[0]['match_id']
        fit, _, aero = fit_and_forecast(times, points, 1e6, 'effective_spin')
        source_fits.append(dict(case=case, match=match, components=(spin_basis(points) @ aero[3:6]).tolist(),
                                fit_rmse_m=float(np.sqrt(np.mean(np.sum(fit.fun.reshape(-1, 3)**2, axis=1)))),
                                active_bounds=fit.active_mask.tolist()))
        cases[case] = dict(match=match, times=times[:3], points=points[:3], target=None,
                           future_t=times[3:], future=points[3:])
    penalty = data/'flight_trajectory_validation_2026-11-07'
    config = json.loads((penalty/'case_config.json').read_text(encoding='utf-8-sig'))
    prefix = read_csv(penalty/'inputs_only.csv')
    for case in CASES:
        times, points = coordinates([row for row in prefix if row['case_id'] == case])
        cases[case] = dict(match=case, times=times, points=points, target=config[case]['target_local_x_m'])
    cfg = Config(dt=.005)
    results = []
    fitted_goals = {}
    for case, spec in cases.items():
        training = [row for row in source_fits if row['match'] != spec['match']]
        prior = learn(training)
        print(case, 'training segments', len(training), 'mean', np.round(prior[0], 1), flush=True)
        for seed in (8047, 20261107):
            for method in ('broad', 'learned'):
                aero = draws(6000, seed, spin_basis(spec['points']), prior if method == 'learned' else None)
                state, theta, weights = sample_prefix(
                    spec['times'], spec['points'], np.arange(3), .015, len(aero), seed+1, True, cfg,
                    aero_draws=aero)
                target = spec['target']
                times = [1.5] if target is not None else spec['future_t']
                predictions, goals = forecast(state, theta, weights, spec['times'][-1], times, target, cfg)
                row = dict(case=case, match=spec['match'], seed=seed, method=method,
                           training_cases=[r['case'] for r in training],
                           prior_mean_rad_s=prior[0].tolist() if method=='learned' else [0., 0.],
                           prior_untruncated_sd_rad_s=prior[1].tolist() if method=='learned' else None,
                           ess=float(1/(weights @ weights)))
                if target is None:
                    available = [p for p in predictions if p['mean_xyz_m'] is not None]
                    # Six fixed lead times, 0.12–0.32 s, available in every clip.
                    chosen = predictions[:6]
                    if len(chosen) != 6 or not all(p['mean_xyz_m'] is not None for p in chosen):
                        row['early_rmse_m'] = None
                    else:
                        delta = np.array([p['mean_xyz_m'] for p in chosen])-spec['future'][:6]
                        row['early_rmse_m'] = float(np.sqrt(np.mean(np.sum(delta**2, axis=1))))
                    row.update(available_frames=len(available), early_min_airborne=min(p['airborne_mass'] for p in chosen))
                else:
                    crossed = np.isfinite(goals[:, 0]) & (weights > 0)
                    row['airborne_plane_probability'] = float(weights[crossed].sum())
                    fitted_goals[case, seed, method] = (
                        np.average(goals[crossed], axis=0, weights=weights[crossed]) if crossed.any() else None)
                results.append(row)
    held = read_csv(penalty/'held_out.csv')
    for row in results:
        case = row['case']
        if case not in CASES:
            continue
        _, points = coordinates([r for r in held if r['case_id'] == case])
        target = cases[case]['target']
        i, = np.flatnonzero((points[:-1, 0] < target) & (points[1:, 0] >= target))
        fraction = (target-points[i, 0])/(points[i+1, 0]-points[i, 0])
        ref = ((1-fraction)*points[i]+fraction*points[i+1])[1:]
        estimate = fitted_goals[case, row['seed'], row['method']]
        row['goal_error_m'] = float(np.linalg.norm(estimate-ref)) if estimate is not None else None
    out = SB/'runs/p5_transfer_spin_prior'
    out.mkdir(parents=True, exist_ok=True)
    save_json(out/'scores.json', dict(sigma_m=.015, samples=6000, source_fits=source_fits, records=results))


if __name__ == '__main__':
    main()
