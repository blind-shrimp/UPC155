"""Audit all existing model families on the final frozen simulation data."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import time
from pathlib import Path

import numpy as np
import torch

from p1 import (DEFAULT_OUT, LEVELS, NOISE_BASE, SB, SEEDS, digest, get_checkpoint,
                load_checkpoint, load_partition, noisy_obs, predict, rescale, save_csv,
                save_json, score)
from ablation import evaluate as evaluate_arm
from common import baseline_endpoint, load_legacy_mdn
from inference import posterior
from pi_res_canonical import CKPT, PhysicsResidualMDN, evaluate as evaluate_pi

BAYES_SUBSET_SEED = 155108
BAYES_SUBSET_N = 32
BAYES_ESS = 100
SIGMA = .005


def metrics(draws, truth):
    half = len(draws) // 2
    return dict(error=float(np.linalg.norm(draws.mean(0) - truth)),
                energy=float(np.linalg.norm(draws - truth, axis=1).mean()
                             - .5 * np.linalg.norm(draws[:half] - draws[half:], axis=1).mean()))


def bayesian_forecast(task):
    obs, truth, seed = task
    start = time.perf_counter()
    try:
        result = posterior(n=6000, sigma=SIGMA, seed=seed, observations=obs)
        if result["conditional_ess"] < BAYES_ESS:
            result = posterior(n=18000, sigma=SIGMA, seed=seed + 1, observations=obs)
    except RuntimeError as error:
        return {"failure": str(error), "seconds": time.perf_counter() - start}
    rng = np.random.default_rng(seed)
    draws = result["endpoints"][rng.choice(len(result["weights"]), 4096, p=result["weights"])]
    scored = metrics(draws, truth)
    scored.update(error=float(np.linalg.norm(np.asarray(result["conditional_mean"]) - truth)),
                  ess=result["conditional_ess"], p_cross=result["airborne_probability"],
                  seconds=time.perf_counter() - start)
    return scored


@torch.no_grad()
def mdn_forecast(model, stats, kind, obs, truth, scale):
    start = time.perf_counter()
    dist = predict(model, stats, kind, obs[None], SIGMA)
    if scale != 1.:
        dist = rescale(dist, scale)
    draws = dist.sample((4096,))[:, 0].numpy() * stats["ys"] + stats["ym"]
    scored = metrics(draws, truth)
    scored.update(error=float(np.linalg.norm(dist.mean[0].numpy() * stats["ys"] + stats["ym"] - truth)),
                  seconds=time.perf_counter() - start)
    return scored


def compare_bayesian(out, fresh, indices, model, stats, kind, old, old_stats, scale, workers):
    rng = np.random.default_rng(BAYES_SUBSET_SEED)
    indices_subset = np.sort(rng.choice(len(indices), BAYES_SUBSET_N, replace=False))
    obs = noisy_obs(fresh, SIGMA, "fresh_test")[indices_subset]
    truth = fresh["y"][indices_subset]
    tasks = [(a, b, int(seed)) for a, b, seed in zip(obs, truth, rng.integers(2**30, size=len(truth)))]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        physics = list(pool.map(bayesian_forecast, tasks))
    baselines = baseline_endpoint(obs)
    torch.manual_seed(85155)
    rows = []
    for index, noisy, label, base, bayes in zip(indices[indices_subset], obs, truth, baselines, physics):
        valid = bool(np.isfinite(base).all())
        rows.append(dict(flight_index=int(index), truth_yz_m=label.tolist(), noisy_observations_m=noisy.tolist(),
                         quadratic_error=float(np.linalg.norm(base - label)) if valid else None,
                         bayesian=bayes, p1_mdn=mdn_forecast(model, stats, kind, noisy, label, scale),
                         legacy_mdn=mdn_forecast(old, old_stats, "raw", noisy, label, 1.)))
    paired = [row for row in rows if row["bayesian"].get("ess", 0) >= BAYES_ESS
              and row["quadratic_error"] is not None]
    summary = {}
    if paired:
        for method in ("bayesian", "p1_mdn", "legacy_mdn"):
            summary[method] = {key: float(np.median([row[method][key] for row in paired]))
                               for key in ("error", "energy", "seconds")}
        summary["quadratic"] = {"error": float(np.median([row["quadratic_error"] for row in paired]))}
    save_json(out / "paired_bayesian.json", dict(
        seed=BAYES_SUBSET_SEED, sigma_mm=5, n_sampled=len(rows), n_paired=len(paired), ess_min=BAYES_ESS,
        low_ess=sum("ess" in row["bayesian"] and row["bayesian"]["ess"] < BAYES_ESS for row in rows),
        failed=sum("failure" in row["bayesian"] for row in rows),
        quadratic_invalid=sum(row["quadratic_error"] is None for row in rows), summary=summary, rows=rows))
    print("Bayesian paired subset complete", len(paired), "/", len(rows), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT / "final")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    torch.set_num_threads(2)
    out = args.out
    frozen = json.loads((out / "best_config.json").read_text(encoding="utf-8"))
    config = tuple(frozen["winner"])
    fresh_path = out / "fresh_data" / "data.npz"
    manifest = json.loads((fresh_path.parent / "evaluation_manifest.json").read_text(encoding="utf-8"))
    if digest(fresh_path) != manifest["sha256"]:
        raise RuntimeError("Fresh dataset differs from final scoring")
    with np.load(fresh_path, allow_pickle=False) as data:
        indices = np.flatnonzero((data["status"] == 1) & np.isfinite(data["observations"]).all(axis=(1, 2)))
        fresh = load_partition(data, indices)
    parts, noise = {"te": fresh}, NOISE_BASE["fresh_test"]
    rows = []
    fields = ("median", "p90", "nll", "energy", "coverage50", "coverage95", "area50", "area95", "goal_ece")

    def append(label, seed, observations):
        for row in observations:
            mm = row["sigma_mm"] if "sigma_mm" in row else round(row["sigma_m"] * 1000)
            rows.append(dict(model=label, seed=seed, sigma_mm=mm, **{key: row[key] for key in fields}))

    for arm in "ABCDE":
        for seed in SEEDS:
            path = CKPT / f"{arm}_{seed}.pt"
            if not path.is_file():
                raise FileNotFoundError(f"Run the documented P0 ablation to regenerate {path.name}.")
            model, stats = load_checkpoint(path, (arm, 3))
            evaluated, _ = evaluate_arm(model, stats, arm, parts, seed, noise_seed_base=noise)
            append(f"P0_{arm}", seed, evaluated)
        print(f"P0 arm {arm} scored on fresh data", flush=True)
    for seed in SEEDS:
        checkpoint = torch.load(CKPT / f"pi_canonical_{seed}.pt", weights_only=False, map_location="cpu")
        pi = PhysicsResidualMDN(16, 128, 5)
        pi.load_state_dict(checkpoint["state"])
        evaluated, _ = evaluate_pi(pi.eval(), checkpoint["feat_mean"], checkpoint["feat_std"], parts,
                                   seed, noise_seed_base=noise)
        append("PI_ResMDN_canonical", seed, evaluated)
    old, old_stats = load_legacy_mdn(SB / "runs" / "literature50k" / "mdn.pt")
    append("Legacy_MDN", 42, score(old, old_stats, ("raw", 3), 42, fresh, "fresh_test"))
    for seed in SEEDS:
        path = get_checkpoint(out, config, seed)
        if digest(path) != frozen["checkpoint_sha256"][path.stem]:
            raise RuntimeError("Final checkpoint changed")
        model, stats = load_checkpoint(path, config)
        cal = frozen["calibration"][path.stem]
        scored = score(model, stats, config, seed, fresh, "fresh_test", cal)
        for method in ("raw", "scaled_hdr"):
            append(f"P1_{method}", seed, [row for row in scored if row["method"] == method])
    save_csv(out / "all_neural_models.csv", rows)
    quadratic = []
    for sigma in LEVELS:
        guess = baseline_endpoint(noisy_obs(fresh, sigma, "fresh_test"))
        good = np.isfinite(guess).all(1)
        error = np.linalg.norm(guess[good] - fresh["y"][good], axis=1)
        quadratic.append(dict(sigma_mm=round(sigma * 1000), n_scored=int(good.sum()),
                              n_invalid=int((~good).sum()), median=float(np.median(error)),
                              p90=float(np.quantile(error, .9))))
    save_csv(out / "quadratic_baseline.csv", quadratic)
    seed = frozen["case_seed"]
    path = get_checkpoint(out, config, seed)
    model, stats = load_checkpoint(path, config)
    scale = frozen["calibration"][path.stem]["5"]["scale_sd"]
    compare_bayesian(out, fresh, indices, model, stats, config[0], old, old_stats, scale, args.workers)


if __name__ == "__main__":
    main()
