"""Compare three fixed spin scenarios on the two DFL penalties."""
import argparse
import json
from pathlib import Path

import numpy as np

from diagnose_spin_prior import PRIORS, SEEDS, draw_parameters, endpoint_summary
from physics import Config
from validate_real_penalties import CASES, coordinates, read_csv, save_json
from validate_real_spin import forecast, sample_prefix


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=12000)
    parser.add_argument('--out', type=Path, default=root/'student_b/runs/real_spin_comparison')
    args = parser.parse_args()
    if args.samples < 2:
        parser.error('Require at least two samples')
    data = root/'student-a/flight_trajectory_validation_2026-11-07'
    specs = json.loads((data/'case_config.json').read_text(encoding='utf-8-sig'))
    inputs = read_csv(data/'inputs_only.csv')
    cfg = Config(dt=.005)
    forecasts = []
    for case in CASES:
        times, positions = coordinates([row for row in inputs if row['case_id'] == case])
        if not np.allclose(times, [0., .04, .08]):
            raise ValueError(f'{case}: unexpected prefix times')
        target = specs[case]['target_local_x_m']
        centre = specs[case]['target_local_center_y_m']
        for seed in SEEDS:
            for prior in PRIORS:
                draws = draw_parameters(np.random.default_rng(seed), args.samples, prior)
                for sigma in (.015, .030):
                    state, theta, weights = sample_prefix(
                        times, positions, np.arange(3), sigma, args.samples, seed+1,
                        prior != 'zero', cfg, aero_draws=draws)
                    _, goals = forecast(state, theta, weights, times[-1], [cfg.horizon], target, cfg)
                    goals[:, 0] -= centre
                    summary = endpoint_summary(goals, weights) if np.isfinite(goals[:, 0]).any() else {
                        'airborne_plane_probability': 0., 'airborne_goal_mouth_probability': 0.}
                    forecasts.append(dict(case=case, prior=prior, seed=seed, sigma_m=sigma,
                                          ess=float(1/(weights @ weights)), **summary))
                print(case, seed, prior, flush=True)
    # Held-out points are first accessed after all forecasts have been computed.
    held = read_csv(data/'held_out.csv')
    for case in CASES:
        times, positions = coordinates([row for row in held if row['case_id'] == case])
        target = specs[case]['target_local_x_m']
        centre = specs[case]['target_local_center_y_m']
        index, = np.flatnonzero((positions[:-1, 0] < target) & (positions[1:, 0] >= target))
        fraction = (target-positions[index, 0])/(positions[index+1, 0]-positions[index, 0])
        reference = ((1-fraction)*positions[index, 1:]+fraction*positions[index+1, 1:]
                     - np.array([centre, 0.]))
        for row in forecasts:
            if row['case'] != case:
                continue
            row['reference_yz_m'] = reference.tolist()
            row['reference_time_s'] = float((1-fraction)*times[index]+fraction*times[index+1])
            rectangle = row.get('crossing_joint_95_rectangle_yz_m')
            if rectangle is None:
                row.update(goal_mean_error_m=None, joint_rectangle_contains_reference=False,
                           joint_rectangle_area_m2=None)
                continue
            lower, upper = np.array(rectangle).T
            row.update(goal_mean_error_m=float(np.linalg.norm(row['crossing_mean_yz_m']-reference)),
                       joint_rectangle_contains_reference=bool(((lower <= reference) & (reference <= upper)).all()),
                       joint_rectangle_area_m2=float(np.prod(upper-lower)))
    args.out.mkdir(parents=True, exist_ok=True)
    save_json(args.out/'scores.json', dict(samples_per_fit=args.samples, dt_s=cfg.dt, records=forecasts))


if __name__ == '__main__':
    main()
