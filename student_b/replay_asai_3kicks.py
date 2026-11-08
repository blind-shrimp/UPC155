"""Replay author-provided tracks without exporting their workbooks."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares

from physics import Config, derivative
from validate_real_spin import forecast, sample_prefix
from validate_real_penalties import save_json

SB = Path(__file__).resolve().parent
sys.path.append(str(SB/'experiments'))
from p4_window_residual import fit_and_forecast

FILES = {'Fig3': 'Fig3_Sample data 20261108.xlsx',
         'Sample05': 'Sample 05 data 20261108.xlsx',
         'Sample12': 'Sample 12 data 20261108.xlsx'}
SIGMA = .010
COUNT = 16000


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
    if not np.allclose(time, np.arange(len(time))*.01):
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
    fraction = (11.-positions[i, 0])/(positions[i+1, 0]-positions[i, 0])
    point = positions[i]+fraction*(positions[i+1]-positions[i])
    if point[2] <= .11 or np.any(positions[:i+1, 2] < .11):
        return None, None
    return float(time[i]+fraction*(time[i+1]-time[i])), point[1:]


def fixed_start_fit(times, points, grid):
    velocity = (points[-1]-points[0])/times[-1]
    direction = velocity/np.linalg.norm(velocity)
    e1 = np.cross(direction, [0., 0., 1.])
    e1 /= np.linalg.norm(e1)
    basis = np.stack((e1, np.cross(direction, e1)))
    cfg = Config(fixed_cd=.27)

    def trajectory(p, query):
        theta = np.r_[np.zeros(3), p[3:] @ basis, .27][None]
        sol = solve_ivp(lambda t, y: derivative(y[None], theta, t, cfg)[0],
                        (0., query[-1]), np.r_[points[0], p[:3]], t_eval=query,
                        rtol=1e-9, atol=1e-10)
        if not sol.success:
            raise RuntimeError(sol.message)
        return sol.y[:3].T

    fit = least_squares(lambda p: (trajectory(p, times)-points)[1:].ravel(),
                        np.r_[velocity, 0., 0.], bounds=([-60.]*5, [60.]*5))
    if not fit.success:
        raise RuntimeError(fit.message)
    return trajectory(fit.x, grid)


def posterior(times, points, future, rps=None):
    rng = np.random.default_rng(8047)
    theta = np.zeros((COUNT, 7))
    theta[:, 6] = rng.uniform(.15, .30, COUNT)
    if rps is None:
        theta[:, 3:6] = rng.uniform(-60., 60., (COUNT, 3))
    else:
        axes = rng.normal(size=(COUNT, 3))
        theta[:, 3:6] = axes/np.linalg.norm(axes, axis=1, keepdims=True)*(2*np.pi*rps)
    cfg = Config(dt=.005)
    state, theta, weights = sample_prefix(times, points, np.arange(3), SIGMA, COUNT, 20261107, True,
                                          cfg, aero_draws=theta)
    predictions, goals = forecast(state, theta, weights, times[-1], np.r_[future, 1.5], 11., cfg)
    good = np.isfinite(goals[:, 0]) & (weights > 0)
    mass = float(weights[good].sum())
    if not good.any():
        raise RuntimeError('No airborne crossing in posterior')
    trace = np.array([p['mean_xyz_m'] if p['mean_xyz_m'] is not None else [np.nan]*3
                      for p in predictions[:-1]])
    return np.average(goals[good], axis=0, weights=weights[good]), trace, dict(
        airborne_plane_probability=mass, ess=float(1/(weights @ weights)))


def load_p1(directory):
    import importlib.util
    import torch
    spec = importlib.util.spec_from_file_location('published_p1_common', directory/'common.py')
    common = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common)
    config = json.loads((directory/'best_config.json').read_text(encoding='utf-8'))
    name = 'phys_reduced_k3_11'
    path = directory/(name+'.pt')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if config['checkpoint_sha256'][name] != digest:
        raise ValueError('Published P1 checkpoint hash mismatch')
    checkpoint = torch.load(path, map_location='cpu', weights_only=False)
    stats = {k: np.asarray(v) for k, v in checkpoint['stats'].items()}
    model = common.build_mdn(len(stats['xm']), k=3, hidden=config['width'], **checkpoint['architecture'])
    model.load_state_dict(checkpoint['state'])
    model.eval()
    return model, stats, common, config['calibration'][name]['10'], digest


def p1_distribution(frozen, points):
    import torch
    model, stats, common, calibration, _ = frozen
    shift = np.array([0., points[0, 2]-.11])
    aligned = points[1:].copy()
    aligned[:, 2] -= shift[1]
    raw = common.make_inputs('phys_reduced', aligned[None], SIGMA)
    x = torch.as_tensor(np.nan_to_num((raw-stats['xm'])/stats['xs'], nan=0., posinf=0., neginf=0.),
                        dtype=torch.float32)
    with torch.no_grad():
        initial = model(x)
        components = initial.component_distribution
        scaled = torch.distributions.MultivariateNormal(
            components.loc, scale_tril=components.scale_tril*calibration['scale_sd'])
        dist = torch.distributions.MixtureSameFamily(initial.mixture_distribution, scaled)
        torch.manual_seed(4108)
        sample_lp = dist.log_prob(dist.sample((32768,)))[:, 0]
        thresholds = {key: float(torch.quantile(sample_lp, 1-mass))
                      for key, mass in calibration['hdr_mass'].items()}
    return aligned, shift, dist, thresholds


def record(estimate, reference, **extra):
    return dict(prediction_yz_m=estimate.tolist() if estimate is not None else None,
                error_cm=float(100*np.linalg.norm(estimate-reference)) if estimate is not None else None,
                **extra)


def plot(trials, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 3, figsize=(12, 9), layout='constrained')
    for i, (name, data) in enumerate(trials.items()):
        pos, traces, scores, ref, hdr = data
        for j, label in ((1, 'Lateral (m)'), (2, 'Height (m)')):
            ax = axes[i, j-1]
            ax.plot(pos[:, 0], pos[:, j], 'k', lw=1.6, label='Measured')
            for method, trace in traces.items():
                ax.plot(trace[:, 0], trace[:, j], '--', lw=1.1, label=method)
            ax.axvline(11., color='.5', lw=.7)
            ax.set(xlim=(0, 13), xlabel='Forward (m)', ylabel=label, title=name)
            if i == j-1 == 0:
                ax.legend(fontsize=7)
        ax = axes[i, 2]
        yy, zz, lp, thresholds = hdr
        ax.contour(yy, zz, lp, levels=sorted(thresholds.values()), colors=['#8a79be', '#552a9e'], linewidths=.9)
        ax.scatter(*ref, c='black', s=35, label='Measured')
        for method, color in [('quadratic', '#aa5533'), ('physics', '#007894'), ('p1', '#552a9e')]:
            estimate = scores[method]['prediction_yz_m']
            if estimate is not None:
                ax.scatter(*estimate, color=color, s=24, label=method)
        ax.set(xlabel='Lateral (m)', ylabel='Height (m)', title='Virtual 11 m section')
        if i == 0:
            ax.legend(fontsize=7)
    fig.savefig(output, dpi=210)
    plt.close(fig)


def main():
    import torch
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--published-p1', required=True, type=Path)
    parser.add_argument('--out', type=Path, default=SB/'runs/asai_replay')
    args = parser.parse_args()
    torch.set_num_threads(2)
    frozen = load_p1(args.published_p1)
    _, stats, _, _, digest = frozen
    cases, plots = {}, {}
    for name, filename in FILES.items():
        path = args.data/filename
        t, xyz, spin = read_trial(path)
        prefix = np.searchsorted(t, [.0, .05, .10])
        times, points = t[prefix], xyz[prefix]
        ref_time, ref = crossing(t, xyz)
        if ref is None:
            raise ValueError(f'{name}: no observed reference crossing')
        acceleration = (points[2]-2*points[1]+points[0])/.05**2
        v0 = (points[1]-points[0])/.05-.025*acceleration
        grid = np.linspace(0, 1.5, 751)
        quadratic = points[0]+grid[:, None]*v0+.5*grid[:, None]**2*acceleration
        strict = fixed_start_fit(times, points, grid)
        # Use a fixed evaluation clock. Later measured positions never enter the prefix models.
        future = np.arange(11, 71)*.01
        unknown, curve, diagnostics = posterior(times, points, future)
        rps = float(spin[0, 1])
        aided, _, aided_diag = posterior(times, points, future, rps)
        fit, full, _ = fit_and_forecast(t, xyz, 11., 'effective_spin')
        full_goal = full.y_events[1][0, 1:3] if len(full.y_events[1]) else None
        aligned, shift, dist, thresholds = p1_distribution(frozen, points)
        with torch.no_grad():
            mean = dist.mean.numpy()[0]*stats['ys']+stats['ym']+shift
            q = torch.as_tensor(((ref-shift-stats['ym'])/stats['ys'])[None], dtype=torch.float32)
            ref_lp = float(dist.log_prob(q)[0])
            lower = np.minimum(ref, mean)-1.4
            upper = np.maximum(ref, mean)+1.4
            yy, zz = np.meshgrid(np.linspace(lower[0], upper[0], 241), np.linspace(lower[1], upper[1], 241))
            yz = np.column_stack((yy.ravel(), zz.ravel()))
            lp = dist.log_prob(torch.as_tensor(((yz-shift-stats['ym'])/stats['ys'])[:, None], dtype=torch.float32))
            lp = lp.numpy().reshape(yy.shape)
            mode = yz[int(np.argmax(lp))]
        scores = dict(quadratic=record(crossing(grid, quadratic)[1], ref),
                      fixed_start_physics=record(crossing(grid, strict)[1], ref),
                      physics=record(unknown, ref, **diagnostics),
                      spin_retrospective=record(aided, ref, **aided_diag, first_spin_s=float(spin[0, 0]), rps=rps),
                      full_fit=record(full_goal, ref, fit_rmse_cm=float(100*np.sqrt(np.mean(
                          np.sum(fit.fun.reshape(-1, 3)**2, axis=1))))),
                      p1=record(mean, ref, density_grid_mode_yz_m=mode.tolist(),
                                hdr_covers_reference={k: bool(ref_lp >= v) for k, v in thresholds.items()}))
        cases[name] = dict(workbook_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), frames=len(t),
                           reference_time_s=ref_time, reference_yz_m=ref.tolist(),
                           p1_aligned_input_6d=aligned.ravel().tolist(), z_shift_m=float(shift[1]), scores=scores)
        plots[name] = (xyz, {'Quadratic': quadratic[grid <= .7], 'Physics': curve,
                            'Full fit': full.sol(t[t <= full.t[-1]])[:3].T},
                       scores, ref, (yy, zz, lp, thresholds))
        print(name, {k: (round(v['error_cm'], 2) if v['error_cm'] is not None else None)
                     for k, v in scores.items()}, 'P1 region coverage', scores['p1']['hdr_covers_reference'], flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    save_json(args.out/'asai_replay_summary.json', dict(sigma_m=SIGMA, posterior_samples=COUNT,
        published_p1_checkpoint_sha256=digest, cases=cases))
    plot(plots, args.out/'asai_3kicks_overlay.png')


if __name__ == '__main__':
    main()
