"""Compare short-prefix trajectory forecasts on A's two ISSIA arcs."""
import argparse
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares

from experiment import dump
from physics import Config, derivative


def check_arc(source, last_frame):
    data = np.genfromtxt(source, delimiter=",", names=True, encoding="utf-8-sig")
    data = data[data["frame_id"] <= last_frame]
    frames = data["frame_id"].astype(int)
    time = (frames-frames[0])/25
    observed = np.column_stack([data[name] for name in ("x_m", "y_m", "z_up_m")])
    count = 6
    if len(time) <= count or np.any(np.diff(frames) != 1) or not np.isfinite(observed).all():
        raise ValueError(f"Expected a continuous finite arc with held-out frames in {source}")
    slope, intercept = np.polyfit(time[:count], observed[:count], 1)
    initial = np.r_[intercept, slope]
    models = {}
    for cd in (0., .22, .45):
        cfg = Config(fixed_cd=cd)
        # Zero spin isolates the drag sensitivity. Fit only the initial state.
        parameters = np.zeros((1, 7))

        def trajectory(state, times):
            result = solve_ivp(lambda t, state: derivative(state[None], parameters, t, cfg)[0],
                (0., times[-1]), state, t_eval=times, rtol=1e-8, atol=1e-9)
            if not result.success:
                raise RuntimeError(result.message)
            return result.y[:3].T

        fit = least_squares(lambda state: (trajectory(state,time[:count])-observed[:count]).ravel(), initial)
        if not fit.success:
            raise RuntimeError(fit.message)
        residual = trajectory(fit.x,time)-observed
        error = np.linalg.norm(residual,axis=1)
        models[str(cd)] = dict(prefix_rmse_m=float(np.sqrt(np.mean(error[:count]**2))),
            forecast_rmse_m=float(np.sqrt(np.mean(error[count:]**2))),
            final_error_m=float(error[-1]))
    return dict(prefix_frames=frames[:count].tolist(), forecast_frames=frames[count:].tolist(),
        models=models, note="Conditional on A's segmentation. No spin measurements, goal or contact labels.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = [check_arc(args.directory/"seg_0608_0627.csv",622),
              check_arc(args.directory/"seg_1144_1172.csv",1172)]
    dump(args.directory/"arc_forecasts.json", result)
