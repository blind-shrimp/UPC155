"""P1 depth/activation screen and three targeted checks of the critique."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import torch

from p1 import (BASE, DATA, DEFAULT_OUT, SB, SEEDS, VALIDATION_SEED, digest, fit_calibration,
                frozen_score, get_checkpoint, load_checkpoint, load_partition, save_csv,
                save_json, score, select, train_one)

ACTIVATIONS = ("SiLU", "GELU", "ReLU", "Tanh")
OPTIONS = {"rho_zero": {"correlation": False}, "fixed_lr": {"cosine": False},
           "fixed_noise": {"dynamic_noise": False}}


def validation_partitions(data, valid):
    indices = np.random.default_rng(VALIDATION_SEED).permutation(
        np.flatnonzero(valid & (data["split"] == 1)))
    return [load_partition(data, np.sort(fold)) for fold in np.array_split(indices, 2)]


def worker_init():
    global WORKER_PARTS
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    with np.load(DATA, allow_pickle=False) as data:
        valid = (data["status"] == 1) & np.isfinite(data["observations"]).all(axis=(1, 2))
        train = load_partition(data, np.flatnonzero(valid & (data["split"] == 0)))
        selection, _ = validation_partitions(data, valid)
    WORKER_PARTS = {"tr": train, "va": selection}


def train_variant(task):
    kind, k, depth, activation, intervention, seed, source, out = task
    architecture = {"depth": depth, "activation": activation}
    path = out / "candidates" / f"d{depth}_{activation}_{intervention}_{seed}.pt"
    is_existing = (depth, activation, intervention) == (2, "SiLU", "reference")
    checkpoint = get_checkpoint(source, (kind, k), seed) if is_existing else path
    if checkpoint.exists():
        model, stats = load_checkpoint(checkpoint, (kind, k))
        metadata = torch.load(checkpoint, map_location="cpu", weights_only=False)
        seconds = metadata.get("seconds")
        n_params = sum(p.numel() for p in model.parameters())
    else:
        model, stats, curves, seconds, n_params = train_one(
            "C", seed, WORKER_PARTS, False, input_kind=kind, k=k, **architecture,
            **OPTIONS.get(intervention, {}))
        options = OPTIONS.get(intervention, {})
        model.eval()
        torch.save({"state": model.state_dict(), "stats": stats, "seconds": seconds,
                    "architecture": dict(architecture, correlation=options.get("correlation", True))}, path)
        save_csv(path.with_suffix(".csv"), curves)
    rows = score(model, stats, (kind, k), seed, WORKER_PARTS["va"], "selection")
    for row in rows:
        row.update(depth=depth, activation=activation, intervention=intervention,
                   n_params=n_params, train_seconds=seconds)
    print(f"validated {depth}x{activation} {intervention} seed={seed} "
          f"NLL={np.mean([r['nll'] for r in rows]):.4f}", flush=True)
    return (depth, activation, intervention), rows, seed, checkpoint


def run_configs(pool, variants, config, source, out, scores, paths):
    tasks = [(*config, *variant, seed, source, out)
             for variant in variants if variant not in scores for seed in SEEDS]
    for variant, rows, seed, checkpoint in pool.map(train_variant, tasks):
        scores.setdefault(variant, []).extend(rows)
        paths[variant, seed] = checkpoint


def mean_nll(rows):
    return float(np.mean([row["nll"] for row in rows]))


def architecture_screen(source, out, workers):
    core = json.loads((source / "best_config.json").read_text(encoding="utf-8"))
    config = tuple(core["winner"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "candidates").mkdir(exist_ok=True)
    (out / "checkpoints").mkdir(exist_ok=True)
    protocol = json.loads((source / "protocol.json").read_text(encoding="utf-8"))
    if digest(DATA) != protocol["canonical_data_sha256"]:
        raise RuntimeError("Canonical dataset differs from the feature/K screen")
    protocol.update(architecture={
        "depths": [1, 2, 3, 4], "depth_screen_activation": "SiLU",
        "activations": list(ACTIVATIONS), "interventions": OPTIONS,
        "selection": "Lowest mean validation NLL, prefer shallower depth or original SiLU "
                     "when inside paired seed SD and passing the same coverage guard.",
    }, git_base=subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=SB, text=True).strip())
    save_json(out / "protocol.json", protocol)
    scores, paths = {}, {}
    with ProcessPoolExecutor(max_workers=workers, initializer=worker_init) as pool:
        depths = [(depth, "SiLU", "reference") for depth in range(1, 5)]
        run_configs(pool, depths, config, source, out, scores, paths)
        best_depth = min(depths, key=lambda variant: mean_nll(scores[variant]))
        chosen_depth = best_depth
        depth_decisions = []
        for candidate in depths:
            if candidate[0] >= best_depth[0]:
                break
            choice, detail = select((candidate, best_depth), scores)
            depth_decisions.append(detail)
            if choice == candidate:
                chosen_depth = candidate
                break
        activations = [(chosen_depth[0], name, "reference") for name in ACTIVATIONS]
        run_configs(pool, activations, config, source, out, scores, paths)
        best_activation = min(activations, key=lambda variant: mean_nll(scores[variant]))
        winner, act_decision = select((chosen_depth, best_activation), scores)
        print(f"architecture selected on validation: {winner}", flush=True)
        interventions = [(winner[0], winner[1], name) for name in OPTIONS]
        run_configs(pool, interventions, config, source, out, scores, paths)
    save_csv(out / "depth.csv", [row for variant in depths for row in scores[variant]])
    save_csv(out / "activation.csv", [row for variant in activations for row in scores[variant]])
    save_csv(out / "critics_ablation.csv", [row for variant in (winner, *interventions) for row in scores[variant]])
    save_json(out / "architecture_decisions.json", dict(
        best_depth=list(best_depth), chosen_depth=list(chosen_depth),
        best_activation=list(best_activation), winner=list(winner),
        depth_decisions=depth_decisions, activation_decision=act_decision,
        depth_nll=[{"depth": variant[0], "mean_nll": mean_nll(scores[variant])} for variant in depths],
        activation_nll=[{"activation": variant[1], "mean_nll": mean_nll(scores[variant])} for variant in activations],
        critique_nll=[{"intervention": variant[2], "mean_nll": mean_nll(scores[variant])}
                      for variant in (winner, *interventions)]))
    return core, config, winner, paths


def finalize(source, out, core, config, winner, paths):
    calibration, validation_scores, checksums = {}, [], {}
    with np.load(DATA, allow_pickle=False) as data:
        valid = (data["status"] == 1) & np.isfinite(data["observations"]).all(axis=(1, 2))
        selection, cal = validation_partitions(data, valid)
        for candidate in dict.fromkeys((BASE, config)):
            for seed in SEEDS:
                path = get_checkpoint(out, candidate, seed)
                previous = paths[winner, seed] if candidate == config else get_checkpoint(source, candidate, seed)
                shutil.copyfile(previous, path)
                model, stats = load_checkpoint(path, candidate)
                identifier = path.stem
                checksums[identifier] = digest(path)
                calibration[identifier] = fit_calibration(model, stats, candidate[0], cal)
                validation_scores.extend(score(model, stats, candidate, seed, selection, "selection",
                                               calibration[identifier]))
        save_csv(out / "calibration_validation.csv", validation_scores)
        core.update(depth=winner[0], activation=winner[1], calibration=calibration,
                    checkpoint_sha256=checksums, protocol_sha256=digest(out / "protocol.json"))
        save_json(out / "best_config.json", core)
        print("Final architecture and calibration frozen before fresh test generation", flush=True)
        frozen_score(out, data, valid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    torch.set_num_threads(4)
    source = args.source.resolve()
    out = args.out.resolve() if args.out else source / "final"
    if (out / "best_config.json").exists():
        raise FileExistsError("Final configuration already frozen. Use p1.py --stage score to resume scoring.")
    core, config, winner, paths = architecture_screen(source, out, args.workers)
    finalize(source, out, core, config, winner, paths)


if __name__ == "__main__":
    main()
