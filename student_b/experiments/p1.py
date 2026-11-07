"""P1 feature/K screen, held-out calibration, and frozen evaluation."""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import platform
import sys
import time
from pathlib import Path

import numpy as np
import torch
from scipy.optimize import minimize_scalar

from ablation import BATCH, DATA, DEPTH, EPOCHS, GOAL, HIDDEN, LR, SEEDS, train_one
from common import LEVELS, build_mdn, evaluate_distribution, make_inputs, summarize_errors

SB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SB))
from experiment import generate
from physics import Config, simulate

DEFAULT_OUT = SB.parent / "student-c" / "P1"
BASE = ("phys", 3)
REDUCED = ("phys_reduced", 3)
LEVEL_TO_MM = dict(zip(LEVELS, (2, 5, 10, 15)))
LEVELS_HDR = (0.5, 0.95)
N_THR = 512
VALIDATION_SEED = 155104
FRESH_SEED = 155107
FRESH_N = 6000
NOISE_BASE = {"selection": 18100, "calibration": 28100, "p0_test": 9100,
              "fresh_test": 38100, "robustness": 48100}
METRICS = ("nll", "median", "p90", "coverage50", "coverage95", "area50", "area95",
           "energy", "goal_ece", "goal_brier")


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def save_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_partition(data, indices):
    return {"obs": data["observations"][indices], "y": data["endpoint"][indices]}


def noisy_obs(part, sigma, split):
    seed = NOISE_BASE[split] + LEVEL_TO_MM[sigma] * 1000
    rng = np.random.default_rng(seed)
    return part["obs"] + rng.normal(size=part["obs"].shape) * sigma


def get_checkpoint(out, config, seed):
    kind, k = config
    return out / "checkpoints" / f"{kind}_k{k}_{seed}.pt"


def load_checkpoint(path, config):
    # P0 checkpoints are locally produced and store NumPy normalization arrays.
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    kind, k = config
    stats = {key: np.asarray(value) for key, value in checkpoint["stats"].items()}
    model = build_mdn(len(stats["xm"]), k=k, hidden=HIDDEN, **checkpoint.get("architecture", {"depth": DEPTH}))
    model.load_state_dict(checkpoint["state"])
    return model.eval(), stats


def train_or_load(out, config, seed, parts):
    kind, k = config
    path = get_checkpoint(out, config, seed)
    if path.exists():
        return load_checkpoint(path, config)
    if config == BASE:
        legacy = SB / "experiments" / "results" / "checkpoints" / f"C_{seed}.pt"
        if legacy.is_file():
            model, stats = load_checkpoint(legacy, config)
            torch.save({"state": model.state_dict(), "stats": stats, "source_sha256": digest(legacy)}, path)
            return model, stats
    print(f"training {kind} K={k} seed={seed}", flush=True)
    model, stats, curves, seconds, _ = train_one("C", seed, parts, input_kind=kind, k=k)
    torch.save({"state": model.state_dict(), "stats": stats, "seconds": seconds}, path)
    save_csv(out / "checkpoints" / f"{kind}_k{k}_{seed}_curve.csv", curves)
    return model.eval(), stats


def predict(model, stats, kind, noisy, sigma):
    features = make_inputs(kind, noisy, sigma)
    x = np.nan_to_num((features - stats["xm"]) / stats["xs"], nan=0., posinf=0., neginf=0.)
    return model(torch.as_tensor(x, dtype=torch.float32))


def rescale(dist, scale):
    component = dist.component_distribution
    normal = torch.distributions.MultivariateNormal(component.loc, scale_tril=component.scale_tril * scale)
    return torch.distributions.MixtureSameFamily(dist.mixture_distribution, normal)


@torch.no_grad()
def fit_calibration(model, stats, kind, part):
    targets = torch.as_tensor((part["y"] - stats["ym"]) / stats["ys"], dtype=torch.float32)
    result = {}
    for sigma, mm in LEVEL_TO_MM.items():
        dist = predict(model, stats, kind, noisy_obs(part, sigma, "calibration"), sigma)
        # One scalar multiplier on standard deviations, preserving centers and weights.
        optimum = minimize_scalar(lambda scale: float(-rescale(dist, scale).log_prob(targets).mean()),
                                  bounds=(0.5, 2.0), method="bounded", options={"xatol": 1e-4})
        if not optimum.success:
            raise RuntimeError(optimum.message)
        scaled = rescale(dist, optimum.x)
        torch.manual_seed(55000 + mm)
        ranks = (scaled.log_prob(scaled.sample((N_THR,))) > scaled.log_prob(targets)).float().mean(0)
        ordered = torch.sort(ranks).values
        masses = {str(level): float(ordered[min(len(ordered), math.ceil((len(ordered) + 1) * level)) - 1])
                  for level in LEVELS_HDR}
        result[str(mm)] = {"scale_sd": float(optimum.x), "hdr_mass": masses}
    return result


@torch.no_grad()
def score(model, stats, config, seed, part, split, calibration=None, levels=LEVELS):
    kind, k = config
    truth = part["y"]
    target = (truth - stats["ym"]) / stats["ys"]
    goal_truth = (np.abs(truth[:, 0]) < GOAL[0]) & (truth[:, 1] > GOAL[1]) & (truth[:, 1] < GOAL[2])
    rows = []
    for sigma in levels:
        mm = LEVEL_TO_MM[sigma]
        noisy = noisy_obs(part, sigma, split)
        methods = ("raw",) if calibration is None else ("raw", "scaled", "scaled_hdr")
        predictions = []
        for offset in range(0, len(truth), 512):
            batch = slice(offset, offset + 512)
            dist = predict(model, stats, kind, noisy[batch], sigma)
            predictions.append((batch, dist))
        for method in methods:
            torch.manual_seed(65000 + mm)
            scale, masses = 1., None
            if method != "raw":
                spec = calibration[str(mm)]
                scale = spec["scale_sd"]
                if method == "scaled_hdr":
                    masses = {float(level): mass for level, mass in spec["hdr_mass"].items()}
            metrics = {key: [] for key in ("nll", "energy", "p_goal", "err",
                                           "coverage50", "coverage95", "area50", "area95")}
            for batch, raw in predictions:
                dist = raw if method == "raw" else rescale(raw, scale)
                stats_batch = evaluate_distribution(dist, target[batch], stats, "abs", None, GOAL,
                                                    n_thr=N_THR, hdr_masses=masses)
                point = dist.mean.numpy() * stats["ys"] + stats["ym"]
                metrics["err"].append(np.linalg.norm(point - truth[batch], axis=1))
                for name in ("nll", "energy", "p_goal"):
                    metrics[name].append(stats_batch[name])
                for name in ("coverage", "area"):
                    for level in LEVELS_HDR:
                        metrics[f"{name}{int(level * 100)}"].append(stats_batch[name][level])
            metrics = {key: np.concatenate(value) for key, value in metrics.items()}
            row = {key: float(metrics[key].mean()) for key in
                   ("nll", "energy", "coverage50", "coverage95", "area50", "area95")}
            row.update(summarize_errors(metrics["err"], metrics["p_goal"], goal_truth))
            rows.append(dict(split=split, features=kind, k=k, seed=seed, sigma_mm=mm,
                             method=method, n=len(truth), **row))
    return rows


def select(configs, scores):
    """Prefer simpler option within paired seed variation and a coverage guard."""
    simpler, reference = configs
    summaries = {}
    for config in configs:
        rows = scores[config]
        nll_by_seed = [float(np.mean([r["nll"] for r in rows if r["seed"] == seed])) for seed in SEEDS]
        coverage_gap = np.mean([abs(r[key] - level) for r in rows
                                for key, level in zip(("coverage50", "coverage95"), LEVELS_HDR)])
        summaries[config] = {"nll_by_seed": nll_by_seed, "mean_absolute_coverage_gap": float(coverage_gap)}
    first, second = (summaries[config] for config in configs)
    paired = np.subtract(first["nll_by_seed"], second["nll_by_seed"])
    mean, sd = float(paired.mean()), float(paired.std(ddof=1))
    winner = simpler if mean <= sd and first["mean_absolute_coverage_gap"] <= (
        second["mean_absolute_coverage_gap"] + .015) else reference
    return winner, dict(simpler=list(simpler), reference=list(reference), chosen=list(winner),
                        simpler_metrics=first, reference_metrics=second, delta_nll_mean=mean,
                        delta_nll_seed_sd=sd)


def prepare(out, data, valid):
    rng = np.random.default_rng(VALIDATION_SEED)
    validation = rng.permutation(np.flatnonzero(valid & (data["split"] == 1)))
    selection, calibration = np.array_split(validation, 2)
    part_select = load_partition(data, np.sort(selection))
    part_cal = load_partition(data, np.sort(calibration))
    parts = {"tr": load_partition(data, np.flatnonzero(valid & (data["split"] == 0))), "va": part_select}
    save_json(out / "protocol.json", dict(
        python=platform.python_version(), torch=str(torch.__version__), numpy=np.__version__,
        canonical_data_sha256=digest(DATA), split_seed=VALIDATION_SEED, training_seed=list(SEEDS),
        selection_flight_indices_sha256=hashlib.sha256(np.sort(selection).astype("<i8").tobytes()).hexdigest(),
        calibration_flight_indices_sha256=hashlib.sha256(np.sort(calibration).astype("<i8").tobytes()).hexdigest(),
        n_train=len(parts["tr"]["y"]), n_selection=len(selection), n_calibration=len(calibration),
        fresh_seed=FRESH_SEED, fresh_generated=FRESH_N, noise_seed_base=NOISE_BASE,
        levels_mm=list(LEVEL_TO_MM.values()), hdr_samples=N_THR,
        selection_rule="Simpler candidate if paired mean NLL delta <= paired seed SD and "
                       "mean absolute coverage gap worsens by <= 0.015.",
        robustness={"sigma_mm": 5, "wind_y_m_per_s": 3, "spin_decay_time_s": 0.5,
                    "paired": "same launch parameters, common airborne crossing and same observation noise"}))
    scores = {}
    for config in (BASE, REDUCED):
        scores[config] = []
        for seed in SEEDS:
            model, stats = train_or_load(out, config, seed, parts)
            scores[config].extend(score(model, stats, config, seed, part_select, "selection"))
    feature_winner, feature_decision = select((REDUCED, BASE), scores)
    k1 = (feature_winner[0], 1)
    scores[k1] = []
    for seed in SEEDS:
        model, stats = train_or_load(out, k1, seed, parts)
        scores[k1].extend(score(model, stats, k1, seed, part_select, "selection"))
    winner, k_decision = select((k1, feature_winner), scores)
    save_csv(out / "selection.csv", list(itertools.chain.from_iterable(scores.values())))
    configs = list(dict.fromkeys((BASE, winner)))
    calibration_rows, validation_rows = {}, []
    for kind, k in configs:
        for seed in SEEDS:
            model, stats = load_checkpoint(get_checkpoint(out, (kind, k), seed), (kind, k))
            calibration_fit = fit_calibration(model, stats, kind, part_cal)
            calibration_rows[f"{kind}_k{k}_{seed}"] = calibration_fit
            validation_rows.extend(score(model, stats, (kind, k), seed, part_select, "selection", calibration_fit))
    save_csv(out / "calibration_validation.csv", validation_rows)
    frozen = dict(winner=list(winner), reference=list(BASE), depth=DEPTH, width=HIDDEN,
                  layer_norm=True, activation="SiLU", target="absolute (Y,Z), conditional on airborne crossing",
                  training={"epochs": EPOCHS, "batch": BATCH, "lr": LR, "schedule": "cosine",
                            "noise_mm": "U(1,20) per trajectory per epoch", "seeds": list(SEEDS)},
                  calibration_method="scaled_hdr", calibration=calibration_rows, case_seed=SEEDS[0],
                  feature_decision=feature_decision, k_decision=k_decision,
                  checkpoint_sha256={f"{kind}_k{k}_{seed}": digest(get_checkpoint(out, (kind, k), seed))
                                     for kind, k in configs for seed in SEEDS},
                  protocol_sha256=digest(out / "protocol.json"))
    save_json(out / "best_config.json", frozen)
    print(f"FROZEN winner={winner}; saved config before opening either test set", flush=True)


def frozen_score(out, data, valid):
    frozen = json.loads((out / "best_config.json").read_text(encoding="utf-8"))
    protocol_path = out / "protocol.json"
    if digest(protocol_path) != frozen["protocol_sha256"]:
        raise RuntimeError("Frozen protocol changed")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if digest(DATA) != protocol["canonical_data_sha256"]:
        raise RuntimeError("Canonical dataset changed since model selection")
    for name, expected in frozen["checkpoint_sha256"].items():
        if digest(out / "checkpoints" / f"{name}.pt") != expected:
            raise RuntimeError(f"Frozen checkpoint changed: {name}")
    p0 = load_partition(data, np.flatnonzero(valid & (data["split"] == 2)))
    fresh_path = out / "fresh_data" / "data.npz"
    if not fresh_path.exists():
        fresh_path.parent.mkdir(parents=True, exist_ok=True)
        generate(fresh_path.parent, FRESH_N, FRESH_SEED)
    manifest_path = fresh_path.parent / "data_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["seed"] != FRESH_SEED or manifest["n"] != FRESH_N:
        raise RuntimeError("Unexpected fresh dataset manifest")
    evaluation_manifest = fresh_path.parent / "evaluation_manifest.json"
    fresh_digest = digest(fresh_path)
    if evaluation_manifest.exists():
        previous = json.loads(evaluation_manifest.read_text(encoding="utf-8"))
        if previous["sha256"] != fresh_digest:
            raise RuntimeError("Fresh dataset changed since previous scoring")
    with np.load(fresh_path, allow_pickle=False) as fresh:
        theta = fresh["theta"]
        if len(theta) != FRESH_N:
            raise RuntimeError("Unexpected fresh dataset size")
        eligible = (fresh["status"] == 1) & np.isfinite(fresh["observations"]).all(axis=(1, 2))
        fresh_part = load_partition(fresh, np.flatnonzero(eligible))
        pairs = {}
        robustness_info = {}
        for label, cfg in (("wind_3mps", Config(wind_y=3)), ("spin_tau_0.5s", Config(spin_decay=.5))):
            shifted = simulate(theta, cfg)
            both = eligible & (shifted["status"] == 1) & np.isfinite(shifted["observations"]).all(axis=(1, 2))
            indices = np.flatnonzero(both)
            pairs[label] = (load_partition(fresh, indices), load_partition(shifted, indices))
            robustness_info[label] = dict(n_paired=len(indices), nominal_airborne=int(eligible.sum()),
                                          shifted_airborne=int((shifted["status"] == 1).sum()),
                                          status_changes=int((fresh["status"] != shifted["status"]).sum()))
    save_json(evaluation_manifest, dict(
        sha256=fresh_digest, seed=FRESH_SEED, generated=len(theta), scored=len(fresh_part["y"]),
        robustness=robustness_info))

    rows, robust_rows = [], []
    configs = list(dict.fromkeys((tuple(frozen["reference"]), tuple(frozen["winner"]))))
    for kind, k in configs:
        for seed in SEEDS:
            model, stats = load_checkpoint(get_checkpoint(out, (kind, k), seed), (kind, k))
            calibration = frozen["calibration"][f"{kind}_k{k}_{seed}"]
            for name, part in (("p0_test", p0), ("fresh_test", fresh_part)):
                rows.extend(score(model, stats, (kind, k), seed, part, name, calibration))
            if [kind, k] != frozen["winner"]:
                continue
            for scenario, (nominal, shifted) in pairs.items():
                for condition, part in (("nominal", nominal), ("shifted", shifted)):
                    result = score(model, stats, (kind, k), seed, part, "robustness", calibration, levels=(.005,))
                    robust_rows.extend(dict(scenario=scenario, condition=condition, **row) for row in result)
            print(f"scored {kind} K={k} seed={seed}", flush=True)
    save_csv(out / "final_scores.csv", rows)
    save_csv(out / "robustness.csv", robust_rows)
    grouped = []
    for key, group in itertools.groupby(sorted(rows, key=group_key), key=group_key):
        subset = list(group)
        summary = dict(zip(("split", "features", "k", "method", "sigma_mm"), key), n=subset[0]["n"])
        for metric in METRICS:
            values = [row[metric] for row in subset]
            summary[f"{metric}_mean"] = float(np.mean(values))
            summary[f"{metric}_std"] = float(np.std(values, ddof=1))
        grouped.append(summary)
    save_csv(out / "summary.csv", grouped)


def group_key(row):
    return tuple(row[key] for key in ("split", "features", "k", "method", "sigma_mm"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--stage", choices=("all", "prepare", "score"), default="all")
    args = parser.parse_args()
    torch.set_num_threads(4)
    out = args.out.resolve()
    (out / "checkpoints").mkdir(parents=True, exist_ok=True)
    if not DATA.exists():
        DATA.parent.mkdir(parents=True, exist_ok=True)
        generate(DATA.parent, 50000, 42)
    start = time.perf_counter()
    with np.load(DATA, allow_pickle=False) as data:
        valid = (data["status"] == 1) & np.isfinite(data["observations"]).all(axis=(1, 2))
        if args.stage in ("all", "prepare"):
            if (out / "best_config.json").exists():
                raise FileExistsError("Configuration already frozen. Use --stage score or a new --out directory.")
            prepare(out, data, valid)
        if args.stage in ("all", "score"):
            frozen_score(out, data, valid)
    print(f"P1 {args.stage}: {time.perf_counter() - start:.1f}s; {out}", flush=True)


if __name__ == "__main__":
    main()
