"""Sensitivity of the UPC example to spin priors with an exact launch position."""
import argparse
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter
from scipy.special import softmax

from physics import Config
from validate_real_penalties import save_json
from validate_real_spin import advance, forecast


ORIGIN = np.array([0., 0., .11])
TIMES = np.array([.05, .10])
OBS = np.array([[1.50, .45, .44], [2.96, .86, .74]])
PRIORS = ('zero', 'component_uniform', 'magnitude_mixture')
SIGMAS = (.005, .015, .030)
SEEDS = (8047, 20261107)


def draw_parameters(rng, count, prior):
    theta = np.zeros((count, 7))
    theta[:, 6] = rng.uniform(.15, .30, count)
    if prior == 'component_uniform':
        theta[:, 3:6] = rng.uniform(-60., 60., (count, 3))
    elif prior == 'magnitude_mixture':
        # Scenario weights, not measured penalty frequencies.
        regime = rng.choice(3, size=count, p=(.45, .40, .15))
        bounds = np.array([0., 15., 70., 110.])
        magnitude = rng.uniform(bounds[regime], bounds[regime+1])
        axis = rng.normal(size=(count, 3))
        axis /= np.linalg.norm(axis, axis=1, keepdims=True)
        theta[:, 3:6] = magnitude[:, None]*axis
    return theta


def prefix(initial, theta, cfg):
    middle = advance(initial, theta, 0., TIMES[0], cfg)
    end = advance(middle, theta, TIMES[0], TIMES[1], cfg)
    return np.stack((middle[:, :3], end[:, :3]), axis=1), end


def update(theta, normal_draw, sigma, cfg):
    # Fix the origin and integrate out launch velocity by importance sampling.
    # The proposal uses nominal nonlinear offsets to centre its velocity draws.
    projection = TIMES/(TIMES @ TIMES)
    initial = np.zeros((len(theta), 6))
    initial[:, :3] = ORIGIN
    initial[:, 3:] = projection @ (OBS-ORIGIN)
    nominal, _ = prefix(initial, theta, cfg)
    initial[:, 3:] += np.einsum('t,ntc->nc', projection, OBS-nominal)
    initial[:, 3:] += sigma/np.linalg.norm(TIMES)*normal_draw
    observed, end = prefix(initial, theta, cfg)
    rss = np.sum((observed-OBS)**2, axis=(1, 2))
    vx = initial[:, 3]
    valid = ((vx > 0.) & (vx <= 60.) & (initial[:, 5] > 0.)
             & (np.abs(initial[:, 4:]) <= 60.).all(axis=1)
             & (observed[:, :, 2] > cfg.radius).all(axis=1))
    if not valid.any():
        raise ValueError('No valid proposal')
    weights = softmax(np.where(valid, -.5*rss/sigma**2 + .5*np.sum(normal_draw**2, axis=1), -np.inf))
    return end, weights


def spin_summary(theta, weights):
    omega = theta[:, 3:6]
    magnitude = np.linalg.norm(omega, axis=1)
    bins = [0., 15., 70., np.inf]
    before = np.histogram(magnitude, bins=bins)[0]/len(weights)
    after = np.histogram(magnitude, bins=bins, weights=weights)[0]
    return dict(prior_bins=before.tolist(), posterior_bins=after.tolist(),
                magnitude_bin_tv=float(.5*np.abs(after-before).sum()),
                prior_mean_omega=omega.mean(axis=0).tolist(),
                posterior_mean_omega=(weights @ omega).tolist(),
                prior_prob_omega_z_positive=float(np.mean(omega[:, 2] > 0)),
                posterior_prob_omega_z_positive=float(weights[omega[:, 2] > 0].sum()))


def endpoint_summary(goals, weights):
    cross = np.isfinite(goals[:, 0]) & (weights > 0)
    probability = weights[cross].sum()
    if probability == 0:
        raise ValueError('No positive-weight crossing')
    points = goals[cross]
    w = weights[cross]/probability
    mean = w @ points
    sd = np.sqrt(w @ (points-mean)**2)
    score = np.max(np.abs(points-mean)/np.maximum(sd, 1e-12), axis=1)
    order = np.argsort(score)
    radius = score[order[np.searchsorted(np.cumsum(w[order]), .95)]]
    halfwidth = radius*sd
    inside = ((np.abs(points[:, 0]) < 3.66) & (points[:, 1] > 0.) & (points[:, 1] < 2.44))
    # Fixed grid and bandwidth across scenarios for the conditional density mode.
    step = .01
    edges = [np.arange(np.floor(axis.min()/step)*step-step,
                       np.ceil(axis.max()/step)*step+2*step, step) for axis in points.T]
    density = gaussian_filter(np.histogram2d(*points.T, bins=edges, weights=w)[0],
                              sigma=.04/step, mode='constant')
    iy, iz = np.unravel_index(density.argmax(), density.shape)
    return dict(airborne_plane_probability=float(probability),
                airborne_goal_mouth_probability=float(weights[cross][inside].sum()),
                crossing_ess=float(1/(w @ w)), crossing_mean_yz_m=mean.tolist(),
                crossing_smoothed_mode_yz_m=[float(edges[0][iy]+step/2), float(edges[1][iz]+step/2)],
                crossing_joint_95_rectangle_yz_m=np.column_stack((mean-halfwidth, mean+halfwidth)).tolist(),
                crossing_joint_rectangle_mass=float(w[score <= radius].sum()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parent/'runs/spin_prior')
    parser.add_argument('--samples', type=int, default=24000)
    parser.add_argument('--step', type=float, default=.005)
    args = parser.parse_args()
    if args.samples < 2 or args.step <= 0:
        parser.error('Require at least two samples and a positive step')
    cfg = Config(dt=args.step)
    records = []
    for seed in SEEDS:
        normal_draw = np.random.default_rng(seed+1).standard_normal((args.samples, 3))
        for prior in PRIORS:
            theta = draw_parameters(np.random.default_rng(seed), args.samples, prior)
            for sigma in SIGMAS:
                state, weights = update(theta, normal_draw, sigma, cfg)
                _, goals = forecast(state, theta, weights, TIMES[-1], [cfg.horizon], cfg.goal, cfg)
                row = dict(seed=seed, prior=prior, sigma_m=sigma, ess=float(1/(weights @ weights)),
                           **spin_summary(theta, weights), **endpoint_summary(goals, weights))
                records.append(row)
                print(seed, prior, sigma, 'ESS', round(row['ess']),
                      'spin TV', round(row['magnitude_bin_tv'], 3),
                      'mean', np.round(row['crossing_mean_yz_m'], 3),
                      'P(goal mouth)', round(row['airborne_goal_mouth_probability'], 3), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    save_json(args.out/'scores.json', dict(samples_per_fit=args.samples, step_s=args.step,
        origin_m=ORIGIN.tolist(), times_s=TIMES.tolist(), observed_m=OBS.tolist(),
        priors={'zero': 'zero spin', 'component_uniform': 'each axis U[-60,60] rad/s',
                'magnitude_mixture': 'isotropic axis, magnitude U[0,15]/U[15,70]/U[70,110] rad/s, weights 45/40/15%'},
        velocity_prior='uniform vx,vz in (0,60], vy in [-60,60] m/s',
        drag_prior='U[0.15,0.30]', noise='iid Gaussian on the two positions; exact origin',
        records=records))


if __name__ == '__main__':
    main()
