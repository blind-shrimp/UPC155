"""Independent synthetic hold-out sets for the anchored-prior audit.

For each fitted anchor cohort (asai, dfl_penalty, dfl_extra, issia, barber) draw
fresh trajectories from that cohort's fitted anchor parameters with the same
perturbation protocol as the data builder, plus a pure-canonical-prior set.
These sets are used only for scoring; they are generated with independent random
streams and never enter any training run.
"""
import argparse
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve()
REPO = Path(os.environ.get("UPC_REPO", HERE.parents[2])).resolve()
SB = REPO / "student_b"
sys.path[:0] = [str(Path(__file__).resolve().parent), str(SB / "experiments"), str(SB)]

import build_data as B  # noqa: E402
from physics import Config, sample_prior, simulate  # noqa: E402

COHORTS = ("asai", "dfl_penalty", "dfl_extra", "issia", "barber")


def cohort_theta(records, cohort, n, rng):
    """Draw n latent states from one cohort's fitted anchors (builder protocol)."""
    theta = sample_prior(n, rng)
    eligible = [i for i, row in enumerate(records) if row["used"] and row["cohort"] == cohort]
    if not eligible:
        raise ValueError(f"no usable anchors for cohort {cohort}")
    choices = rng.permutation(np.resize(rng.permutation(eligible), n))
    draws = np.array([records[i]["theta"] for i in choices])
    if cohort not in B.LAUNCH_COHORTS:
        yaw = np.arctan2(theta[:, 1], theta[:, 0]) - np.arctan2(draws[:, 1], draws[:, 0])
        wx, wy = draws[:, 3:5].T.copy()
        draws[:, 3] = np.cos(yaw) * wx - np.sin(yaw) * wy
        draws[:, 4] = np.sin(yaw) * wx + np.cos(yaw) * wy
    draws += rng.normal(size=draws.shape) * B.PERTURB
    columns = slice(None) if cohort in B.LAUNCH_COHORTS else slice(3, None)
    theta[:, columns] = np.clip(draws[:, columns], B.LOW[columns], B.HIGH[columns])
    signs = rng.choice((-1., 1.), size=n)
    theta[:, [1, 3, 5]] *= signs[:, None]
    return theta


def simulate_many(theta):
    totals = {}
    for start in range(0, len(theta), 2000):
        result = simulate(theta[start:start + 2000], Config())
        for key, array in result.items():
            totals.setdefault(key, []).append(array)
    return {key: np.concatenate(arrays) for key, arrays in totals.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--n", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=900001)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    records = manifest["anchors"]
    args.output.mkdir(parents=True, exist_ok=False)
    summary = {}
    for offset, cohort in enumerate(COHORTS):
        rng = np.random.default_rng(args.seed + offset)
        theta = cohort_theta(records, cohort, args.n, rng)
        data = simulate_many(theta)
        path = args.output / f"holdout_{cohort}.npz"
        np.savez_compressed(path, theta=theta, **data)
        summary[cohort] = dict(n=args.n, sha256=B.sha256(path),
                               crossings=int((data["status"] == 1).sum()))
        print(f"holdout {cohort}: {summary[cohort]['crossings']} crossings -> {path.name}", flush=True)
    # Pure canonical prior hold-out.
    rng = np.random.default_rng(args.seed + 99)
    theta = sample_prior(args.n, rng)
    data = simulate_many(theta)
    path = args.output / "holdout_canonical.npz"
    np.savez_compressed(path, theta=theta, **data)
    summary["canonical"] = dict(n=args.n, sha256=B.sha256(path),
                                crossings=int((data["status"] == 1).sum()))
    print(f"holdout canonical: {summary['canonical']['crossings']} crossings", flush=True)
    (args.output / "holdout_manifest.json").write_text(
        json.dumps(dict(seed=args.seed, n=args.n, sets=summary), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


if __name__ == "__main__":
    main()
