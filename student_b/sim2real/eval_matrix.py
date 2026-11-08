"""Evaluate trained anchored-prior models on independent synthetic cohorts.

Usage:
  python eval_matrix.py <runs_dir> <out_dir> [--holdout runs/holdout] [--asai-dir Desktop]

runs_dir is expected to contain sub-directories with model.pt + config.json from
train2.py, plus the frozen P1 is added automatically. Prints a transfer matrix
(median error at 5 mm) and writes eval_matrix.csv / eval_matrix.json.
"""
import argparse
import json
import os
from pathlib import Path
import sys

import numpy as np
import torch

HERE = Path(__file__).resolve()
REPO = Path(os.environ.get("UPC_REPO", HERE.parents[2])).resolve()
SB = REPO / "student_b"
sys.path.insert(0, str(SB / "experiments"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import p1  # noqa: E402
from build_data import FILES, read_trial  # noqa: E402
from replay_asai_3kicks import crossing  # noqa: E402

CONFIG = ("phys_reduced", 3)
PUBLISHED = REPO / "student-c" / "P1" / "final"
LEVEL = 0.005
LEVEL_MM = "5"


def load_models(runs_dir):
    models = {}
    for sub in sorted(Path(runs_dir).iterdir()):
        if not (sub / "model.pt").is_file():
            continue
        cfg = json.loads((sub / "config.json").read_text(encoding="utf-8"))
        model, stats = p1.load_checkpoint(sub / "model.pt", CONFIG)
        models[sub.name] = dict(model=model, stats=stats, calibration=cfg["calibration"],
                                seed=cfg.get("seed", 11))
    old_config = json.loads((PUBLISHED / "best_config.json").read_text(encoding="utf-8"))
    old_path = p1.get_checkpoint(PUBLISHED, CONFIG, 11)
    model, stats = p1.load_checkpoint(old_path, CONFIG)
    models["frozen_p1"] = dict(model=model, stats=stats,
                               calibration=old_config["calibration"][old_path.stem], seed=11)
    return models


def score_partition(model_info, obs, y):
    part = {"obs": obs, "y": y}
    rows = p1.score(model_info["model"], model_info["stats"], CONFIG, model_info["seed"],
                    part, "fresh_test", model_info["calibration"], levels=(LEVEL,))
    return {row["method"]: row for row in rows}


@torch.no_grad()
def replay_real_asai(models, asai_dir):
    rows = []
    for name, filename in FILES.items():
        path = Path(asai_dir) / filename
        times, points, _ = read_trial(path)
        _, reference = crossing(times, points)
        if reference is None:
            raise ValueError(f"{name}: reference missing")
        obs = points[np.searchsorted(times, (.05, .10))].copy()
        shift = np.array([0., points[0, 2] - .11])
        obs[:, 2] -= shift[1]
        for label, info in models.items():
            dist = p1.predict(info["model"], info["stats"], CONFIG[0], obs[None], .010)
            mean = dist.mean.detach().numpy()[0] * info["stats"]["ys"] + info["stats"]["ym"] + shift
            rows.append(dict(case=name, model=label, sigma_mm=10,
                             error_cm=float(100 * np.linalg.norm(mean - reference))))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--holdout", type=Path, default=Path("runs/holdout"))
    parser.add_argument("--asai-dir", type=Path, default=Path.home() / "Desktop")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    models = load_models(args.runs)
    matrix = {}
    for npz in sorted(args.holdout.glob("holdout_*.npz")):
        cohort = npz.stem.replace("holdout_", "")
        data = np.load(npz, allow_pickle=False)
        valid = (data["status"] == 1) & np.isfinite(data["observations"]).all(axis=(1, 2))
        valid &= np.isfinite(data["endpoint"]).all(axis=1)
        obs, y = data["observations"][valid], data["endpoint"][valid]
        matrix[cohort] = {}
        for label, info in models.items():
            rows = score_partition(info, obs, y)
            raw = rows["raw"]
            scaled = rows.get("scaled", {})
            matrix[cohort][label] = dict(
                n=int(valid.sum()),
                median_cm=100. * float(raw["median"]),
                coverage50=float(scaled.get("coverage50", raw["coverage50"])),
                coverage95=float(scaled.get("coverage95", raw["coverage95"])),
                nll=float(scaled.get("nll", raw["nll"])),
            )
    replay = replay_real_asai(models, args.asai_dir)
    out = dict(level_mm=5., holdout_seed=None, matrix=matrix, real_asai_replay=replay)
    (args.out / "eval_matrix.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    import csv
    with (args.out / "eval_matrix.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["holdout", "model", "n", "median_cm", "coverage50", "coverage95", "nll"])
        for cohort, per_model in matrix.items():
            for label, value in per_model.items():
                writer.writerow([cohort, label, value["n"], round(value["median_cm"], 3),
                                 round(value["coverage50"], 4), round(value["coverage95"], 4),
                                 round(value["nll"], 4)])
    labels = list(models)
    header = "holdout".ljust(14) + "".join(label.rjust(14) for label in labels)
    print(header)
    for cohort, per_model in matrix.items():
        print(cohort.ljust(14) + "".join(
            f"{per_model[label]['median_cm']:14.2f}" for label in labels))
    print()
    for row in replay:
        print("replay", row["case"], row["model"], round(row["error_cm"], 2))


if __name__ == "__main__":
    main()
