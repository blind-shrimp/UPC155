"""Information limits for predicting a penalty-kick goal-plane crossing from two
early noisy positions.

Two bounds are computed and compared with the measured errors of the committed
kinematic baseline and the frozen P1 network:

1. Kinematic (unregularised) extrapolation bound.
   With a fixed start r(0) and two positions observed at Delta t and 2 Delta t,
   the second-order Lagrange extrapolation to the crossing time T = n Delta t
   assigns weights L1 = -n(n-2) and L2 = n(n-1)/2 to the two observations.
   A per-axis Gaussian error sigma therefore arrives at the goal plane with
   standard deviation Lambda(n) sigma, Lambda = sqrt(L1^2 + L2^2).  For a 2D
   isotropic error the median Euclidean error is sqrt(2 ln 2) Lambda sigma
   ~= 1.1774 Lambda sigma.

2. Local Bayesian (linearised) floor.
   Treat theta = (v0, omega, C_D) as random with the simulator's independent
   uniform prior, the observations as Gaussian with covariance sigma^2 I, and
   the goal-plane crossing (Y, Z) as a function g(theta).  Linearising the
   observation map h(theta) and g(theta) around each sampled true trajectory
   gives the posterior covariance

       Sigma_post = (J_h^T Sigma_obs^{-1} J_h + Sigma_prior^{-1})^{-1},
       Cov(g)     = J_g Sigma_post J_g^T,

   and the median Euclidean crossing error of that Gaussian.  This is a
   *local* bound under a Gaussian approximation of the uniform prior; it is
   reported with that caveat, not as a proof of global optimality.

Also computed: the same floor when a third high-precision position at 0.15 s is
available (a measurement-design thought experiment), and a figure comparing the
bounds with the committed baseline and P1 errors.

Outputs go to student_b/runs/information_limit/.

Run:
    python student_b/experiments/information_limit.py --n 4000
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
SB = HERE.parents[1]
if str(SB) not in sys.path:
    sys.path.insert(0, str(SB))

from physics import Config, HIGH, LOW, acceleration, sample_prior, simulate  # noqa: E402

DELTA_T = .05
LEVELS_MM = (2, 5, 10, 15)
RAYLEIGH_MEDIAN = float(np.sqrt(2. * np.log(2.)))  # 1.17741
CFG = Config(dt=.002)
EXTRA_OBS_TIME = .15

# Finite-difference steps: velocities m/s, angular rates rad/s, C_D dimensionless.
STEPS = np.array([1e-3, 1e-3, 1e-3, 1e-2, 1e-2, 1e-2, 1e-4])

# Independent uniform priors: variance = (high - low)^2 / 12.
PRIOR_VAR = (HIGH - LOW) ** 2 / 12.
PRIOR_INFO = np.diag(1. / PRIOR_VAR)


def _sim(theta, times):
    return simulate(theta, CFG, observation_times=times)


def _observables(out2, out15=None):
    """Observations as (m, 6) for 2 positions and (m, 9) for 3 positions."""
    h2 = out2['observations'].reshape(len(out2['observations']), -1)
    if out15 is None:
        return h2
    return np.column_stack((h2, out15['observations'][:, 1, :]))


def _flat_obs(out, times):
    return out['observations'].reshape(len(out['observations']), -1)


def compute(n=4000, seed=155107, out_dir=Path('student_b/runs/information_limit')):
    rng = np.random.default_rng(seed)
    theta = sample_prior(n, rng)
    times2 = (.05, .10)
    times15 = (.05, EXTRA_OBS_TIME)
    base = _sim(theta, times2)
    keep = (base['status'] == 1) & np.isfinite(base['endpoint']).all(axis=1) \
        & np.isfinite(base['arrival'])
    theta = theta[keep]
    base = {k: v[keep] for k, v in base.items()}
    m = len(theta)
    h2 = _flat_obs(base, times2)                       # (m, 6)
    h15 = _sim(theta, times15)['observations'][:, 1, :]  # position at 0.15 s
    h3 = np.column_stack((h2, h15))                    # (m, 9)
    g = base['endpoint']                               # (m, 2)
    T = base['arrival']                                # (m,)

    # Finite-difference Jacobians of observations and crossing point.
    jh2 = np.zeros((m, 6, 7))
    jh15 = np.zeros((m, 3, 7))
    jg = np.zeros((m, 2, 7))
    valid = np.ones(m, bool)
    for k in range(7):
        plus = theta.copy(); plus[:, k] += STEPS[k]
        minus = theta.copy(); minus[:, k] -= STEPS[k]
        sp2, sm2 = _sim(plus, times2), _sim(minus, times2)
        sp15, sm15 = _sim(plus, times15), _sim(minus, times15)
        ok = (sp2['status'] == 1) & (sm2['status'] == 1) \
            & np.isfinite(sp2['endpoint']).all(axis=1) \
            & np.isfinite(sm2['endpoint']).all(axis=1)
        valid &= ok
        denom = 2. * STEPS[k]
        jh2[:, :, k] = np.where(ok[:, None],
                                (_flat_obs(sp2, times2) - _flat_obs(sm2, times2)) / denom, 0.)
        jh15[:, :, k] = np.where(ok[:, None],
                                 (sp15['observations'][:, 1, :]
                                  - sm15['observations'][:, 1, :]) / denom, 0.)
        jg[:, :, k] = np.where(ok[:, None],
                               (sp2['endpoint'] - sm2['endpoint']) / denom, 0.)
    theta, h2, h3, g, T = theta[valid], h2[valid], h3[valid], g[valid], T[valid]
    jh2, jh15, jg = jh2[valid], jh15[valid], jg[valid]
    m = len(theta)

    # Prior spread of the aerodynamic acceleration at t = 0 (lateral/vertical
    # components, gravity removed): the denominator of the observability ratio.
    a_total = acceleration(theta[:, :3], theta, 0., CFG)
    a_aero = a_total - np.array([0., 0., -CFG.gravity])
    aero_sd = np.std(a_aero[:, 1:3], axis=0, ddof=1)   # (y, z) components
    aero_sd_total = float(np.sqrt(np.mean(aero_sd ** 2)))

    step = T / DELTA_T
    l1 = -step * (step - 2.)
    l2 = step * (step - 1.) / 2.
    lam = np.hypot(l1, l2)

    level_sigmas = [v * 1e-3 for v in LEVELS_MM]
    levels = {}
    mc_rng = np.random.default_rng(seed + 1)
    for sigma_mm, sigma in zip(LEVELS_MM, level_sigmas):
        noise_info = np.eye(6) / sigma ** 2
        noise_info3 = np.eye(9) / sigma ** 2
        kin = RAYLEIGH_MEDIAN * lam * sigma
        bayes2 = np.empty(m)
        bayes3 = np.empty(m)
        floor_kin_free = np.empty(m)
        for i in range(m):
            lik = jh2[i].T @ noise_info @ jh2[i]
            post = np.linalg.inv(lik + PRIOR_INFO)
            cov = jg[i] @ post @ jg[i].T
            bayes2[i] = _median_norm(cov, mc_rng)
            jh3 = np.vstack((jh2[i], jh15[i]))
            lik3 = jh3.T @ noise_info3 @ jh3
            post3 = np.linalg.inv(lik3 + PRIOR_INFO)
            cov3 = jg[i] @ post3 @ jg[i].T
            bayes3[i] = _median_norm(cov3, mc_rng)
            pinv_lik = np.linalg.pinv(lik)
            cov0 = jg[i] @ pinv_lik @ jg[i].T
            floor_kin_free[i] = float(np.sqrt(max(np.trace(cov0), 0.)))
        levels[str(sigma_mm)] = dict(
            sigma_m=sigma,
            n_observations_2=6,
            n_observations_3=9,
            kinematic_median_m=float(np.median(kin)),
            kinematic_mean_m=float(kin.mean()),
            bayes_floor_median_m=float(np.median(bayes2)),
            bayes_floor_mean_m=float(bayes2.mean()),
            bayes_floor_p10_m=float(np.percentile(bayes2, 10)),
            bayes_floor_p90_m=float(np.percentile(bayes2, 90)),
            bayes_floor_three_positions_median_m=float(np.median(bayes3)),
            likelihood_only_rms_m=float(np.median(floor_kin_free)),
        )

    reference = {
        'kinematic_baseline_median_m': {'2': .1897, '5': .4317, '15': 1.2169},
        'literature50k_mdn_median_m': {'2': .1631, '5': .3222, '15': .5562},
        'p1_median_m': {'2': .130, '5': .290, '10': .466, '15': .566},
        'note': 'baseline/literature50k from student_b/runs/literature50k/evaluation.json; '
                'P1 from student-c/P1/final/tables/tab_p1_fresh.tex (fresh_test, phys, k=3).',
    }
    payload = dict(
        study='information_limits_penalty_crossing',
        settings=dict(n=n, seed=seed, delta_t_s=DELTA_T, extra_observation_time_s=EXTRA_OBS_TIME,
                      levels_mm=list(LEVELS_MM), prior_var=PRIOR_VAR.tolist(),
                      finite_difference_steps=STEPS.tolist(), n_airborne=int(m)),
        summary=dict(
            n_sampled=int(n), n_airborne=int(m),
            mean_arrival_s=float(T.mean()), median_arrival_s=float(np.median(T)),
            lambda_median=float(np.median(lam)), lambda_mean=float(lam.mean()),
            lambda_range=[float(lam.min()), float(lam.max())],
            rayleigh_median=RAYLEIGH_MEDIAN,
            aero_acceleration_prior_sd_m_s2=dict(
                y=float(aero_sd[0]), z=float(aero_sd[1]),
                rms=float(aero_sd_total)),
            observability_ratio=dict(
                definition='(sqrt(5) sigma / Delta t^2) / sigma_aero',
                values={str(mm): float(np.sqrt(5.) * mm * 1e-3 / DELTA_T ** 2
                                       / aero_sd_total) for mm in LEVELS_MM}),
            caveat=('Kinematic bound is exact for second-order extrapolation of two '
                    'positions. Bayesian floor is a local linearised bound with a '
                    'Gaussian approximation of the uniform prior; it is conditional '
                    'on the simulator being the true model.')),
        levels=levels, reference_measured=reference,
        per_flight=dict(arrival_s=T.tolist(), lambda_weights=lam.tolist()))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'information_limit.json').write_text(
        json.dumps(payload, indent=1, ensure_ascii=False), encoding='utf-8')
    _plot(levels, reference, out_dir / 'error_limits.png')
    print(json.dumps({k: v for k, v in payload['summary'].items() if k != 'caveat'},
                     indent=1, ensure_ascii=False))
    for k, v in levels.items():
        print(k, json.dumps({kk: round(vv, 4) for kk, vv in v.items()
                             if kk not in ('sigma_m', 'n_observations_2', 'n_observations_3')}))
    return payload


def _median_norm(cov, rng, samples=64):
    cov = .5 * (cov + cov.T)
    vals, vecs = np.linalg.eigh(cov)
    vals = np.maximum(vals, 0.)
    z = rng.standard_normal((samples, 2)) * np.sqrt(vals)
    return float(np.median(np.linalg.norm(z @ vecs.T, axis=1)))


def _plot(levels, reference, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    sig = [levels[k]['sigma_m'] * 1e3 for k in levels]
    kin = [levels[k]['kinematic_median_m'] for k in levels]
    bay2 = [levels[k]['bayes_floor_median_m'] for k in levels]
    bay3 = [levels[k]['bayes_floor_three_positions_median_m'] for k in levels]
    fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.2))
    ax = axes[0]
    ax.loglog(sig, kin, 'o-', color='tab:gray', lw=1.6, label='kinematic bound, 2 positions')
    ax.loglog(sig, bay2, 's-', color='tab:blue', lw=1.6, label='Bayesian floor, 2 positions')
    ax.loglog(sig, bay3, 'd--', color='tab:cyan', lw=1.4,
              label='Bayesian floor, 3 positions (design variant)')
    base = reference['kinematic_baseline_median_m']
    p1 = reference['p1_median_m']
    lit = reference['literature50k_mdn_median_m']
    ax.loglog([float(k) for k in base], [base[k] for k in base], 'x', ms=8,
              color='tab:red', label='measured kinematic baseline')
    ax.loglog([float(k) for k in p1], [p1[k] for k in p1], '^', ms=7,
              color='tab:green', label='P1 (frozen, fresh test)')
    ax.loglog([float(k) for k in lit], [lit[k] for k in lit], 'v', ms=7,
              color='tab:orange', label='earlier 50k MDN (reference)')
    ax.set_xlabel(r'position noise $\sigma$ (mm)', fontsize=10)
    ax.set_ylabel('median Euclidean crossing error (m)', fontsize=10)
    ax.grid(True, which='both', ls=':', alpha=.5)
    ax.legend(fontsize=8, loc='lower right')
    ax.set_title('(a) error scale versus observation noise', fontsize=11)
    ax2 = axes[1]
    ratios = []
    for k in levels:
        p = reference['p1_median_m'].get(k)
        ratios.append(None if p is None else p / levels[k]['bayes_floor_median_m'])
    xs = np.arange(len(sig))
    vals = [r if r is not None else np.nan for r in ratios]
    ax2.bar(xs, vals, color='tab:green', alpha=.8)
    ax2.axhline(1.0, color='k', ls='--', lw=.9)
    ax2.set_xticks(xs)
    ax2.set_xticklabels([f'{s:.0f} mm' for s in sig])
    ax2.set_ylabel('P1 median / Bayesian floor', fontsize=10)
    ax2.set_title('(b) distance to the linearised information floor', fontsize=11)
    ax2.tick_params(labelsize=9)
    for x, v in zip(xs, vals):
        if np.isfinite(v):
            ax2.text(x, v + .01, f'{v:.2f}', ha='center', fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--n', type=int, default=4000)
    parser.add_argument('--seed', type=int, default=155107)
    parser.add_argument('--out', type=Path, default=SB / 'runs/information_limit')
    args = parser.parse_args()
    t0 = time.time()
    compute(args.n, args.seed, args.out)
    print(f'done in {time.time() - t0:.1f}s -> {args.out}')
