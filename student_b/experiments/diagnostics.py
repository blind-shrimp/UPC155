"""P0 diagnostics (todo.md sections 1.1-1.8).

Runs against the canonical simulator dataset and B's existing MDN checkpoint.
Every number is written to experiments/results/.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SB = HERE.parent
sys.path.insert(0, str(SB))

from common import (ARMS, DT, LEVELS, R0, RHO, AREA, MASS, RADIUS,  # noqa: E402
                    baseline_endpoint, ece, evaluate_distribution,
                    load_legacy_mdn, physics_features, summarize_errors)

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

DATA = SB / "runs" / "canonical50k" / "data.npz"
CKPT = SB / "runs" / "literature50k" / "mdn.pt"
OUT = HERE / "results"
FIG = OUT / "figures"
GOAL = (3.66, 0.0, 2.44)


def dump(path, obj):
    def clean(x):
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [clean(v) for v in x]
        if isinstance(x, (np.floating, np.integer)):
            return x.item()
        if isinstance(x, float) and not np.isfinite(x):
            return None
        return x
    Path(path).write_text(json.dumps(clean(obj), indent=2, ensure_ascii=False),
                          encoding="utf-8")


def main():
    import torch
    torch.set_num_threads(6)
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)

    d = np.load(DATA)
    theta, split, status = d["theta"], d["split"], d["status"]
    obs, endpoint = d["observations"], d["endpoint"]
    n = len(theta)
    finite = np.isfinite(obs).all(axis=(1, 2))
    valid = (status == 1) & finite

    stats = dict(
        n=int(n),
        status_counts={str(k): int((status == k).sum()) for k in (0, 1, 2)},
        finite_observations=int(finite.sum()),
        valid_airborne=int(valid.sum()),
        split_counts={str(k): int((split == k).sum()) for k in (0, 1, 2)},
        valid_by_split={str(k): int((valid & (split == k)).sum()) for k in (0, 1, 2)},
        nan_observations=int((~finite).sum()),
        manifest=json.loads((SB / "runs" / "canonical50k" / "data_manifest.json")
                            .read_text(encoding="utf-8")),
    )
    print("data", stats["n"], stats["status_counts"], stats["valid_by_split"])

    test = np.flatnonzero(valid & (split == 2))
    obs_te, y_te = obs[test], endpoint[test]
    theta_te = theta[test]
    rng = np.random.default_rng(20261107)

    # ---------------------------------------------------------------- 1.5 baseline residuals
    base_clean = baseline_endpoint(obs_te)
    good = np.isfinite(base_clean).all(axis=1)
    res = y_te[good] - base_clean[good]
    norm = np.linalg.norm(res, axis=1)
    residual = dict(
        n=int(good.sum()), invalid=int((~good).sum()),
        dy_mean=float(res[:, 0].mean()), dy_std=float(res[:, 0].std()),
        dz_mean=float(res[:, 1].mean()), dz_std=float(res[:, 1].std()),
        norm_median=float(np.median(norm)), norm_p90=float(np.quantile(norm, .9)),
        norm_p99=float(np.quantile(norm, .99)),
        frac_norm_gt_0_5m=float((norm > .5).mean()),
        frac_norm_gt_1m=float((norm > 1.).mean()),
        corr_dy_dz=float(np.corrcoef(res[:, 0], res[:, 1])[0, 1]),
        dy_quantiles={f"q{q:02d}": float(np.quantile(res[:, 0], q / 100))
                      for q in (1, 5, 25, 50, 75, 95, 99)},
        dz_quantiles={f"q{q:02d}": float(np.quantile(res[:, 1], q / 100))
                      for q in (1, 5, 25, 50, 75, 95, 99)},
    )
    print("baseline residual", residual["norm_median"])

    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    ax[0].hist(res[:, 0], bins=80, color="C0", alpha=.8)
    ax[0].set(xlabel="dY = Y_true - Y_const (m)", ylabel="count",
              title="Baseline residual dY (clean observations)")
    ax[1].hist(res[:, 1], bins=80, color="C1", alpha=.8)
    ax[1].set(xlabel="dZ = Z_true - Z_const (m)", ylabel="count",
              title="Baseline residual dZ (clean observations)")
    fig.tight_layout()
    fig.savefig(FIG / "baseline_residuals.png", dpi=150)
    plt.close(fig)

    # ---------------------------------------------------------------- 1.4 existing MDN on same test set
    model, mstats = load_legacy_mdn(CKPT)
    model.eval()
    xm, xs = mstats["xm"], mstats["xs"]
    ym, ys = mstats["ym"], mstats["ys"]

    def mdn_dist(noisy, sigma):
        z = np.column_stack([noisy.reshape(len(noisy), -1),
                             np.full(len(noisy), sigma)])
        return model(torch.tensor((z - xm) / xs, dtype=torch.float32))

    # forward-only latency
    with torch.no_grad():
        one = torch.tensor(((np.r_[obs_te[0].ravel(), .005] - xm) / xs)[None, :],
                           dtype=torch.float32)
        for _ in range(20):
            model(one)
        t0 = time.perf_counter()
        for _ in range(200):
            model(one)
        latency_ms = (time.perf_counter() - t0) / 200 * 1e3

    mdn_reports = {}
    pred_rows = []
    for sigma in LEVELS:
        rng_s = np.random.default_rng(9000 + int(sigma * 1e6))
        noisy = obs_te + rng_s.normal(size=obs_te.shape) * sigma
        t0 = time.perf_counter()
        errs, nll, cov50, cov95, a50, a95, pgoal, energy = [], [], [], [], [], [], [], []
        preds = []
        with torch.no_grad():
            for j in range(0, len(noisy), 512):
                sl = slice(j, j + 512)
                dist = mdn_dist(noisy[sl], sigma)
                pred = dist.mean.numpy() * ys + ym
                preds.append(pred)
                errs.append(np.linalg.norm(pred - y_te[sl], axis=1))
                y_std = (y_te[sl] - ym) / ys
                base = y_te[sl]
                met = evaluate_distribution(dist, y_std, mstats, "abs", base, GOAL)
                nll.append(met["nll"])
                cov50.append(met["coverage"][0.5])
                cov95.append(met["coverage"][0.95])
                a50.append(met["area"][0.5])
                a95.append(met["area"][0.95])
                pgoal.append(met["p_goal"])
                energy.append(met["energy"])
        err = np.concatenate(errs)
        pred_all = np.concatenate(preds)
        p_goal = np.concatenate(pgoal)
        goal_true = ((np.abs(y_te[:, 0]) < GOAL[0]) & (y_te[:, 1] > GOAL[1])
                     & (y_te[:, 1] < GOAL[2])).astype(float)
        mdn_reports[f"{sigma*1000:g}mm"] = dict(
            sigma_m=sigma,
            n=int(len(err)),
            seconds=float(time.perf_counter() - t0),
            latency_forward_ms=float(latency_ms),
            error=summarize_errors(err, p_goal, goal_true),
            nll_mean=float(np.concatenate(nll).mean()),
            coverage50=float(np.concatenate(cov50).mean()),
            coverage95=float(np.concatenate(cov95).mean()),
            area50=float(np.concatenate(a50).mean()),
            area95=float(np.concatenate(a95).mean()),
            energy_mean=float(np.concatenate(energy).mean()),
        )
        if abs(sigma - .005) < 1e-12:
            for i, idx in enumerate(test):
                pred_rows.append([int(idx), float(err[i]), float(p_goal[i]),
                                  float(y_te[i, 0]), float(y_te[i, 1]),
                                  float(pred_all[i, 0]), float(pred_all[i, 1])])
        print("mdn", sigma, mdn_reports[f"{sigma*1000:g}mm"]["error"]["median"],
              mdn_reports[f"{sigma*1000:g}mm"]["coverage50"])

    np.savetxt(OUT / "mdn_test_predictions_5mm.csv",
               np.array(pred_rows), delimiter=",",
               header="test_index,error_m,p_goal,y_true,z_true,y_pred,z_pred",
               comments="")

    # baseline error at each sigma (same noise draws as MDN)
    base_reports = {}
    for sigma in LEVELS:
        rng_s = np.random.default_rng(9000 + int(sigma * 1e6))
        noisy = obs_te + rng_s.normal(size=obs_te.shape) * sigma
        bp = baseline_endpoint(noisy)
        ok = np.isfinite(bp).all(axis=1)
        be = np.linalg.norm(bp[ok] - y_te[ok], axis=1)
        base_reports[f"{sigma*1000:g}mm"] = dict(
            sigma_m=sigma, n=int(ok.sum()), invalid=int((~ok).sum()),
            median_error=float(np.median(be)), p90_error=float(np.quantile(be, .9)),
            mean_error=float(be.mean()))

    # ---------------------------------------------------------------- 1.7 coverage estimator note
    coverage_estimator = dict(
        rule="HDR: threshold = quantile of 512 mixture samples at 1-alpha; "
             "coverage = fraction of truths with log_prob >= threshold; "
             "area = mean(1[logp>=thr] * exp(-logp)) over 1024 independent samples",
        n_threshold_samples=512, n_area_samples=1024, n_goal_samples=512,
        note="Identical estimator used for every arm and for the legacy MDN; "
             "no quantile heuristic with 200 samples.",
    )

    # ---------------------------------------------------------------- 1.8 mixture weights
    pis = []
    with torch.no_grad():
        for j in range(0, len(obs_te), 1024):
            dist = mdn_dist(obs_te[j:j + 1024], .005)
            pis.append(dist.mixture_distribution.probs.numpy())
    pis = np.concatenate(pis)
    ent = -(pis * np.log(np.maximum(pis, 1e-12))).sum(1)
    mixture = dict(
        k=int(pis.shape[1]),
        mean_pi=[float(v) for v in pis.mean(0)],
        median_pi=[float(v) for v in np.median(pis, 0)],
        max_pi_mean=float(pis.max(1).mean()),
        frac_max_pi_gt_0_9=float((pis.max(1) > .9).mean()),
        entropy_mean=float(ent.mean()),
        entropy_max=float(np.log(pis.shape[1])),
        collapsed_components=int((pis.mean(0) < .02).sum()),
    )

    # ---------------------------------------------------------------- 1.6 feature diagnostics
    rng_f = np.random.default_rng(7)
    train_idx = np.flatnonzero(valid & (split == 0))
    pick = rng_f.choice(train_idx, size=min(20000, len(train_idx)), replace=False)
    obs_f, theta_f = obs[pick], theta[pick]

    # true C_L at t=0.05 from theta (canonical law)
    w = theta_f[:, 3:6]
    v_clean = (obs_f[:, 1] - R0) / (2 * DT)
    speed = np.maximum(np.linalg.norm(v_clean, axis=1), 1e-9)
    cross = np.cross(w, v_clean)
    S = RADIUS * np.linalg.norm(cross, axis=1) / speed**2
    cl_true = np.minimum(1.4 * S, .30)
    cd_true = theta_f[:, 6]

    feat_reports = {}
    corr_matrices = {}
    for sigma in LEVELS:
        noisy = obs_f + rng_f.normal(size=obs_f.shape) * sigma
        F_all = physics_features(noisy, np.full(len(noisy), sigma))
        finite_f = np.isfinite(F_all).all(axis=1)
        F = F_all[finite_f]
        cd_true_f, cl_true_f = cd_true[finite_f], cl_true[finite_f]
        names = ["vx", "vy", "vz", "ax", "ay", "az", "aa_x", "aa_y", "aa_z",
                 "speed", "a_par", "a_perp", "cd_app", "cl_app", "T_goal", "sigma"]
        mu, sd = F.mean(0), np.maximum(F.std(0), 1e-12)
        Z = (F - mu) / sd
        # sigma is constant within a level, so correlation/conditioning is
        # computed on the 15 physics features only.
        C = np.corrcoef(Z[:, :15], rowvar=False)
        corr_matrices[f"{sigma*1000:g}mm"] = C.tolist()
        eig = np.linalg.eigvalsh(C)
        off = np.abs(C - np.eye(15))
        i, j = np.unravel_index(np.argmax(off), off.shape)
        feat_reports[f"{sigma*1000:g}mm"] = dict(
            sigma_m=sigma,
            finite_frac=float(finite_f.mean()),
            rank_standardized=int(np.linalg.matrix_rank(Z[:, :15])),
            rank_raw=int(np.linalg.matrix_rank(F[:, :15])),
            condition_standardized=float(eig.max() / max(eig.min(), 1e-12)),
            condition_raw_cov=float(np.linalg.cond(np.cov(F[:, :15], rowvar=False))),
            max_abs_corr=float(off[i, j]),
            max_corr_pair=[names[i], names[j]],
            eig_min=float(eig.min()), eig_max=float(eig.max()),
            cd_app_mean=float(F[:, 12].mean()), cd_app_std=float(F[:, 12].std()),
            cd_app_rmse_vs_true=float(np.sqrt(np.mean((F[:, 12] - cd_true_f) ** 2))),
            cd_app_corr_true=float(np.corrcoef(F[:, 12], cd_true_f)[0, 1]),
            cl_app_mean=float(F[:, 13].mean()), cl_app_std=float(F[:, 13].std()),
            cl_app_rmse_vs_true=float(np.sqrt(np.mean((F[:, 13] - cl_true_f) ** 2))),
            cl_app_corr_true=float(np.corrcoef(F[:, 13], cl_true_f)[0, 1]),
            a_perp_mean=float(F[:, 11].mean()), a_perp_std=float(F[:, 11].std()),
            t_goal_finite_frac=float(np.isfinite(F[:, 14]).mean()),
        )
        print("features", sigma, feat_reports[f"{sigma*1000:g}mm"]["condition_standardized"])

    # correlation heatmap at 5 mm (15 physics features; sigma is constant)
    C5 = np.array(corr_matrices["5mm"])
    fig, ax = plt.subplots(figsize=(9, 7))
    im = ax.imshow(C5, cmap="coolwarm", vmin=-1, vmax=1)
    names15 = ["vx", "vy", "vz", "ax", "ay", "az", "aa_x", "aa_y", "aa_z",
               "speed", "a_par", "a_perp", "cd_app", "cl_app", "T_goal"]
    ax.set_xticks(range(len(names15)))
    ax.set_xticklabels(names15, rotation=90, fontsize=7)
    ax.set_yticks(range(len(names15)))
    ax.set_yticklabels(names15, fontsize=7)
    ax.set_title("Physics feature correlation (sigma=5 mm, n=20k)")
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    fig.savefig(FIG / "feature_correlation_5mm.png", dpi=150)
    plt.close(fig)

    # coverage figure (legacy MDN)
    fig, ax = plt.subplots(figsize=(6, 4))
    sig = [2, 5, 10, 15]
    ax.plot(sig, [mdn_reports[f"{s}mm"]["coverage50"] for s in sig], "o-", label="50% region")
    ax.plot(sig, [mdn_reports[f"{s}mm"]["coverage95"] for s in sig], "s-", label="95% region")
    ax.axhline(.5, ls="--", c="gray", lw=.8)
    ax.axhline(.95, ls="--", c="gray", lw=.8)
    ax.set(xlabel="position noise sigma (mm)", ylabel="empirical coverage",
           title="Legacy MDN coverage vs sigma")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG / "coverage_vs_sigma_legacy.png", dpi=150)
    plt.close(fig)

    # ---------------------------------------------------------------- blocked items
    blocked = dict(
        pi_res_mdn=dict(
            status="BLOCKED",
            reason="pi_res_mdn.py was not found in the repository, the working "
                   "directory, Documents, Downloads or Desktop on this machine.",
            needed="The critic's script (or a zip/path) to run 1.1, 1.2 and the "
                   "PI-ResMDN column of 1.4.",
        ),
        simulator_diff=dict(
            status="BLOCKED",
            reason="Requires pi_res_mdn.py's generator; only one simulator is "
                   "available locally (student_b/physics.py).",
            known_differences_from_todo=[
                "rho 1.225 vs 1.20 kg/m^3",
                "C_D prior [0.15,0.26]/[0.26,0.38] vs [0.15,0.30]",
                "C_L=0.38S/(0.18+S) vs min(1.4S,0.30)",
                "spin decay present vs none",
                "different initial-state ranges",
            ],
        ),
    )

    out = dict(
        generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        data=str(DATA.relative_to(SB)),
        checkpoint=str(CKPT.relative_to(SB)),
        dataset=stats,
        baseline_residual=residual,
        baseline_by_sigma=base_reports,
        legacy_mdn=mdn_reports,
        coverage_estimator=coverage_estimator,
        mixture_weights=mixture,
        features=feat_reports,
        blocked=blocked,
    )
    dump(OUT / "diagnostics.json", out)

    md = []
    md.append("# P0 diagnostics (todo.md 1.1-1.8)\n")
    md.append(f"- data: `{DATA.relative_to(SB)}` n={n}, "
              f"valid airborne={stats['valid_airborne']}, "
              f"test={stats['valid_by_split']['2']}")
    md.append(f"- legacy MDN checkpoint: `{CKPT.relative_to(SB)}`")
    md.append("\n## 1.5 baseline residual (truth - constant acceleration)\n")
    md.append(f"- n={residual['n']} invalid={residual['invalid']}; "
              f"median |r|={residual['norm_median']:.3f} m, "
              f"p90={residual['norm_p90']:.3f} m, p99={residual['norm_p99']:.3f} m")
    md.append(f"- dY mean/std={residual['dy_mean']:.3f}/{residual['dy_std']:.3f} m; "
              f"dZ mean/std={residual['dz_mean']:.3f}/{residual['dz_std']:.3f} m; "
              f"corr={residual['corr_dy_dz']:.3f}")
    md.append(f"- |r|>0.5 m: {residual['frac_norm_gt_0_5m']*100:.1f}%, "
              f"|r|>1 m: {residual['frac_norm_gt_1m']*100:.1f}%")
    md.append("\n## 1.4 legacy MDN on the same test set\n")
    md.append("| sigma | median err | p90 | 50% cov | 95% cov | area50 | area95 | NLL |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for sigma in LEVELS:
        r = mdn_reports[f"{sigma*1000:g}mm"]
        md.append(f"| {sigma*1000:g} mm | {r['error']['median']:.3f} | "
                  f"{r['error']['p90']:.3f} | {r['coverage50']*100:.1f}% | "
                  f"{r['coverage95']*100:.1f}% | {r['area50']:.3f} | "
                  f"{r['area95']:.3f} | {r['nll_mean']:.3f} |")
    md.append("\n## 1.8 mixture weights (sigma=5 mm)\n")
    md.append(f"- mean pi = {['%.3f' % v for v in mixture['mean_pi']]}; "
              f"mean max pi={mixture['max_pi_mean']:.3f}; "
              f"frac(max pi>0.9)={mixture['frac_max_pi_gt_0_9']*100:.1f}%; "
              f"collapsed components={mixture['collapsed_components']}")
    md.append("\n## 1.6 feature condition (16-dim reconstruction)\n")
    md.append("| sigma | cond(std corr) | max abs corr | cd_app corr(true) | cl_app corr(true) |")
    md.append("|---|---:|---:|---:|---:|")
    for sigma in LEVELS:
        r = feat_reports[f"{sigma*1000:g}mm"]
        md.append(f"| {sigma*1000:g} mm | {r['condition_standardized']:.1f} | "
                  f"{r['max_abs_corr']:.3f} ({r['max_corr_pair'][0]}/{r['max_corr_pair'][1]}) | "
                  f"{r['cd_app_corr_true']:.3f} | {r['cl_app_corr_true']:.3f} |")
    md.append("\n## Blocked\n")
    md.append(f"- 1.1/1.2/1.4 PI-ResMDN column: **{blocked['pi_res_mdn']['reason']}**")
    md.append("\nFigures: `figures/baseline_residuals.png`, `figures/feature_correlation_5mm.png`, "
              "`figures/coverage_vs_sigma_legacy.png`")
    (OUT / "diagnostics.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("written", OUT / "diagnostics.json")


if __name__ == "__main__":
    main()
