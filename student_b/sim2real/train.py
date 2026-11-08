"""Train a fresh P1-compatible MDN and score it against frozen P1.

Train a fresh P1-compatible MDN on an anchored-prior dataset (2026-11-08).
"""
import argparse
import json
from pathlib import Path
import os
import sys

import numpy as np
import torch

HERE = Path(__file__).resolve()
REPO = Path(os.environ.get("UPC_REPO", HERE.parents[2])).resolve()
SB = REPO / "student_b"
sys.path.insert(0, str(SB / "experiments"))
import ablation
import p1

CONFIG = ("phys_reduced", 3)
ARCHITECTURE = {"depth": 3, "activation": "GELU"}
PUBLISHED = REPO / "student-c" / "P1" / "final"


@torch.no_grad()
def replay_asai(directory, manifest, predictors):
    from build_data import FILES, read_trial
    from replay_asai_3kicks import crossing

    anchors = {row["id"]: row for row in manifest["anchors"] if row["cohort"] == "asai"}
    excluded = set(manifest.get("exclude_cohorts") or ())
    excluded_ids = set(manifest.get("exclude_anchor_ids") or ())
    rows = []
    for name, filename in FILES.items():
        path = directory / filename
        # For leave-one-cohort-out runs the anchor is excluded from training, but the
        # workbook hash must still match the one used for the reference geometry.
        if p1.digest(path) not in anchors[name]["sources"].values():
            raise ValueError(f"{name}: replay workbook differs from the prior-fit source")
        times, points, _ = read_trial(path)
        _, reference = crossing(times, points)
        if reference is None:
            raise ValueError(f"{name}: observed airborne 11 m reference missing")
        obs = points[np.searchsorted(times, (.05, .10))].copy()
        shift = np.array([0., points[0, 2] - .11])
        obs[:, 2] -= shift[1]
        for label, model, stats in predictors:
            dist = p1.predict(model, stats, CONFIG[0], obs[None], .010)
            mean = dist.mean.numpy()[0] * stats["ys"] + stats["ym"] + shift
            rows.append(dict(case=name, model=label, sigma_mm=10,
                             error_cm=float(100 * np.linalg.norm(mean - reference)),
                             assessment=("Held-out trial: this Asai anchor excluded from "
                                         "training" if name in excluded_ids else
                                         ("Held-out cohort: Asai anchors excluded from this "
                                          "training run" if "asai" in excluded else
                                          "Retrospective; trial contributed to fresh simulation prior"))))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--asai-dir", type=Path, help="Optional local retrospective workbook replay")
    parser.add_argument("--skip-frozen", action="store_true",
                        help="Do not score the frozen P1 (for pure fresh-only runs)")
    args = parser.parse_args()
    if args.epochs < 1 or args.threads < 1:
        parser.error("epochs and threads must be positive")
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    ablation.EPOCHS = args.epochs

    with np.load(args.dataset, allow_pickle=False) as data:
        valid = (data["status"] == 1) & np.isfinite(data["observations"]).all(axis=(1, 2))
        valid &= np.isfinite(data["endpoint"]).all(axis=1)
        partitions = [np.flatnonzero(valid & (data["split"] == code)) for code in range(3)]
        validation = np.random.default_rng(p1.VALIDATION_SEED).permutation(partitions[1])
        select, calibrate = np.array_split(validation, 2)
        indices = (partitions[0], np.sort(select), np.sort(calibrate), partitions[2])
        if min(map(len, indices)) < 2:
            raise ValueError("Every partition needs at least two eligible trajectories")
        train, selection, calibration, test = [p1.load_partition(data, group) for group in indices]
        np.savez_compressed(args.output / "indices.npz", **dict(zip(
            ("train", "selection", "calibration", "test"), indices)))

    model, stats, curve, seconds, parameters = ablation.train_one(
        "C", args.seed, {"tr": train, "va": selection},
        input_kind=CONFIG[0], k=CONFIG[1], select_validation=True, **ARCHITECTURE)
    if not np.isfinite([row["val_nll_phys"] for row in curve]).all():
        raise RuntimeError("Non-finite validation NLL")
    checkpoint = args.output / "model.pt"
    torch.save({"state": model.state_dict(), "stats": stats, "architecture": ARCHITECTURE},
               checkpoint)
    p1.save_csv(args.output / "curve.csv", [
        {key: row[key] for key in ("epoch", "train_nll", "val_nll_phys")} for row in curve])
    thresholds = p1.fit_calibration(model, stats, CONFIG[0], calibration)

    old_config = json.loads((PUBLISHED / "best_config.json").read_text(encoding="utf-8"))
    old_path = p1.get_checkpoint(PUBLISHED, CONFIG, 11)
    old_hash = p1.digest(old_path)
    if old_hash != old_config["checkpoint_sha256"][old_path.stem]:
        raise ValueError("Frozen P1 checkpoint hash mismatch")
    p1.save_json(args.output / "config.json", dict(
        dataset_sha256=p1.digest(args.dataset), checkpoint_sha256=p1.digest(checkpoint),
        old_checkpoint_sha256=old_hash, architecture=ARCHITECTURE, features=CONFIG[0],
        k=CONFIG[1], epochs=args.epochs, seed=args.seed, parameters=parameters, seconds=seconds,
        sizes=dict(zip(("train", "selection", "calibration", "test"), map(len, indices))),
        selected_epoch=curve[-1]["selected_epoch"], calibration=thresholds,
        evaluation="Synthetic holdout from the same fitted prior, conditional on airborne crossing"))
    model, stats = p1.load_checkpoint(checkpoint, CONFIG)
    rows = []
    if not args.skip_frozen:
        old, old_stats = p1.load_checkpoint(old_path, CONFIG)
        for name, predictor, normalization, seed, cal in (
                ("fresh", model, stats, args.seed, thresholds),
                ("frozen_p1", old, old_stats, 11, old_config["calibration"][old_path.stem])):
            rows.extend(dict(model=name, **row) for row in p1.score(
                predictor, normalization, CONFIG, seed, test, "fresh_test", cal))
        if not all(np.isfinite(row[key]) for row in rows for key in p1.METRICS):
            raise RuntimeError("Non-finite holdout score")
        p1.save_csv(args.output / "test_scores.csv", rows)
    if args.asai_dir:
        manifest = json.loads(args.dataset.with_name("data_manifest.json").read_text(encoding="utf-8"))
        if manifest["sha256"] != p1.digest(args.dataset):
            raise ValueError("Dataset manifest hash mismatch")
        p1.save_csv(args.output / "asai_replay.csv", replay_asai(
            args.asai_dir, manifest, (("fresh", model, stats),)))


if __name__ == "__main__":
    main()
