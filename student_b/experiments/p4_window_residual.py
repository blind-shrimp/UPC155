"""Compare DFL prefix forecasts and retrospective full-flight residuals."""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares

SB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SB))
from physics import Config, derivative
from validate_real_penalties import CASES, coordinates, read_csv, save_json


def fit_and_forecast(times, points, target, model):
    slope, origin = np.polyfit(times, points, 1)
    direction = slope/np.linalg.norm(slope)
    transverse = np.cross(direction, [0., 0., 1.])
    transverse /= np.linalg.norm(transverse)
    basis = np.stack((transverse, np.cross(direction, transverse)))
    free_drag = model != 'fixed_drag'
    spinning = model == 'effective_spin'
    guess = np.r_[origin, slope, [.22] if free_drag else [], [0., 0.] if spinning else []]
    lower = np.r_[[-np.inf]*2, .11, [0., -60., -60.], [.15] if free_drag else [],
                  [-60., -60.] if spinning else []]
    upper = np.r_[[np.inf]*3, [60.]*3, [.30] if free_drag else [], [60., 60.] if spinning else []]
    cfg = Config()

    def aero(parameters):
        omega = parameters[7:9] @ basis if spinning else np.zeros(3)
        cd = parameters[6] if free_drag else .22
        return np.r_[np.zeros(3), omega, cd][None]

    def rhs(parameters):
        theta = aero(parameters)
        return lambda t, y: derivative(y[None], theta, t, cfg)[0]

    def residual(parameters):
        solution = solve_ivp(rhs(parameters), (0., times[-1]), parameters[:6],
                             t_eval=times, rtol=1e-8, atol=1e-10)
        return (solution.y[:3].T-points).ravel()

    fit = least_squares(residual, np.clip(guess, lower, upper), bounds=(lower, upper),
                        x_scale='jac', max_nfev=120)
    if not fit.success:
        raise RuntimeError(f'{model}: {fit.message}')

    def ground(t, y):
        return y[2]-cfg.radius

    def goal(t, y):
        return y[0]-target

    ground.terminal = True
    ground.direction = -1
    goal.direction = 1
    sol = solve_ivp(rhs(fit.x), (0., 1.5), fit.x[:6], dense_output=True,
                    events=(ground, goal), rtol=1e-9, atol=1e-10, max_step=.01)
    if not sol.success:
        raise RuntimeError(sol.message)
    return fit, sol, aero(fit.x)[0]


def summarize(residual):
    return dict(rmse_m=float(np.sqrt(np.mean(np.sum(residual**2, axis=1)))),
                axis_rmse_m=np.sqrt(np.mean(residual**2, axis=0)).tolist())


def main():
    data = SB.parent/'student-a/flight_trajectory_validation_2026-11-07'
    config = json.loads((data/'case_config.json').read_text(encoding='utf-8-sig'))
    rows = read_csv(data/'inputs_only.csv')+read_csv(data/'held_out.csv')
    records = []
    for case in CASES:
        times, points = coordinates(sorted((r for r in rows if r['case_id'] == case),
                                            key=lambda r: float(r['t_s'])))
        target = config[case]['target_local_x_m']
        i, = np.flatnonzero((points[:-1, 0] < target) & (points[1:, 0] >= target))
        ratio = (target-points[i, 0])/(points[i+1, 0]-points[i, 0])
        reference = ((1-ratio)*points[i]+ratio*points[i+1])[1:]
        eligible = (np.arange(len(times)) >= 6) & (np.arange(len(times)) <= i)
        fits = {}
        for label, n in (('short', 3), ('long', 6), ('full', i+2)):
            for model in ('fixed_drag', 'free_drag', 'effective_spin'):
                if n == 3 and model == 'effective_spin':
                    continue
                fits[label, model] = fit_and_forecast(times[:n], points[:n], target, model)
        common = eligible & (times <= min(sol.t[-1] for _, sol, _ in fits.values())+1e-12)
        if not common.any():
            raise ValueError(f'{case}: no common late frames')
        for (label, model), (fit, sol, aero) in fits.items():
            offset = sol.y_events[1][0, 1:3]-reference if len(sol.y_events[1]) else None
            row = dict(case=case, window=label, model=model,
                       fitted_frames=len(fit.fun)//3, common_late_frames=int(common.sum()),
                       eligible_late_frames=int(eligible.sum()),
                       available_late_frames=int(np.sum(eligible & (times <= sol.t[-1]+1e-12))),
                       fit=summarize(fit.fun.reshape(-1, 3)),
                       late=summarize(sol.sol(times[common])[:3].T-points[common]),
                       goal_error_m=float(np.linalg.norm(offset)) if offset is not None else None,
                       goal_offset_yz_m=offset.tolist() if offset is not None else None,
                       initial_v_m_s=fit.x[3:6].tolist(), cd=float(aero[6]),
                       spin_rad_s=aero[3:6].tolist(), active_bounds=fit.active_mask.tolist())
            records.append(row)
            print(case, label, model, 'fit/late/late_y/goal',
                  *(round(v, 3) if v is not None else None for v in
                    (row['fit']['rmse_m'], row['late']['rmse_m'], row['late']['axis_rmse_m'][1],
                     row['goal_error_m'])), 'goal_offset', np.round(offset, 3) if offset is not None else None,
                  'cd/spin', round(row['cd'], 3), np.round(aero[3:6], 1))
    out = SB/'runs/p4_window_residual'
    out.mkdir(parents=True, exist_ok=True)
    save_json(out/'scores.json', dict(records=records))


if __name__ == '__main__':
    main()
