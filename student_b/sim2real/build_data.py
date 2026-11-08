"""Calibrate a launch prior on local flight data and simulate fresh trajectories.

Anchored-prior simulation builder (2026-11-08). Adapted from the retrain_all
builder so that the DSH repository layout and leave-one-cohort-out audits work. Added options:
  --exclude-cohorts   leave-one-cohort-out audit (e.g. asai dfl_penalty)
  --prior-fraction    share of anchored (measured-fit) samples, default .5
  --tag               recorded in the manifest

The default run (50 000, seed 155211, prior-fraction .5, no excluded cohort) is
byte-identical to the original builder.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve()
REPO = Path(os.environ.get("UPC_REPO", HERE.parents[2])).resolve()
SB = REPO / "student_b"
sys.path[:0] = [str(SB / "experiments"), str(SB)]

from asai_transfer import align_track, load_dfl_penalty, load_extra_dfl, load_issia, read_csv
from p4_window_residual import fit_and_forecast
from physics import HIGH, LOW, Config, sample_prior, simulate
from replay_asai_3kicks import FILES, read_trial

HANDOFF = REPO / "student-a"
FLIGHTS = HANDOFF / "flight_trajectory_validation_2026-11-07"
EXTRA = HANDOFF / "additional_flight_data_2026-11-07" / "positions.csv"
ISSIA_ARCS = SB / "runs" / "issia_A"
PENALTIES = SB / "runs" / "data_integration" / "penalty_trajectories.csv"
LAUNCH_COHORTS = {"asai", "dfl_penalty"}
RMSE_LIMIT = {"asai": .05, "dfl_penalty": .10, "dfl_extra": .12,
              "issia": .20, "barber": .12}
PERTURB = np.array([1.5, 2.0, 1.2, 6.0, 6.0, 6.0, .025])
FIT_INPUTS = (FLIGHTS / "inputs_only.csv", FLIGHTS / "held_out.csv",
              FLIGHTS / "case_config.json")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_id(path):
    return str(path.relative_to(REPO)) if path.is_relative_to(REPO) else path.name


def full_case(case):
    return (np.r_[case["fit_times"], case["future_times"]],
            np.concatenate((case["fit_points"], case["future_points"])))


def handoff_track(rows, name, planar=False):
    selected = sorted((row for row in rows if row["case_id"] == name),
                      key=lambda row: float(row["t_s"]))
    points = [[float(row["x_m"]), 0.0 if planar else float(row["y_m"]),
               float(row["z_m"])] for row in selected]
    return np.array([float(row["t_s"]) for row in selected]), np.array(points)


def load_tracks(asai_dir):
    tracks = []
    for name, filename in FILES.items():
        path = asai_dir / filename
        times, positions, spin = read_trial(path)
        tracks.append((name, "asai", times, positions, (path,), len(spin)))
    for case in load_dfl_penalty(FLIGHTS):
        tracks.append((case["case"], "dfl_penalty", *full_case(case), FIT_INPUTS, None))
    for case in load_extra_dfl(EXTRA):
        tracks.append((case["case"], "dfl_extra", *full_case(case), (EXTRA,), None))
    for case in load_issia(ISSIA_ARCS):
        path = ISSIA_ARCS / (case["case"] + ".csv")
        tracks.append((case["case"], "issia", *full_case(case), (path,), None))
    rows = read_csv(FIT_INPUTS[0]) + read_csv(FIT_INPUTS[1])
    times, points = handoff_track(rows, "ISSIA_2972_2991")
    tracks.append(("ISSIA_2972_2991", "issia", times, align_track(points), FIT_INPUTS[:2], None))
    name = "Barber2010_Fig5"
    tracks.append((name, "barber", *handoff_track(rows, name, planar=True), FIT_INPUTS[:2], None))
    names = [track[0] for track in tracks]
    if len(set(names)) != len(names) or Counter(track[1] for track in tracks) != Counter(
            asai=3, dfl_penalty=2, dfl_extra=11, issia=3, barber=1):
        raise ValueError("Unexpected source inventory")
    return tracks


def fit_anchors(tracks, excluded=(), excluded_ids=()):
    records = []
    for name, cohort, times, points, paths, spin_count in tracks:
        if times[0] != 0 or not np.all(np.diff(times) > 0) or not np.isfinite(points).all():
            raise ValueError(f"{name}: invalid observed flight")
        row = dict(id=name, cohort=cohort, frames=len(times),
                   sources={source_id(path): sha256(path) for path in paths},
                   spin_magnitude_frames=spin_count, use_launch=cohort in LAUNCH_COHORTS)
        if cohort == "barber":
            crossing = np.flatnonzero(points[:, 0] >= 11.)
            if len(crossing) == 0:
                raise ValueError("Barber arc does not reach 11 m")
            end = int(crossing[0]) + 1
            times, points = times[:end], points[:end]
            row["fit_window"] = "through first frame at or past 11 m"
        row["fitted_frames"] = len(times)
        try:
            fit, _, aero = fit_and_forecast(times, points, 11., "effective_spin")
            rmse = float(np.sqrt(np.mean(np.sum(fit.fun.reshape(-1, 3)**2, axis=1))))
            theta = np.r_[fit.x[3:6], aero[3:]]
            if cohort == "barber":
                theta[[1, 3, 5]] = 0.
            row.update(rmse_m=rmse, theta=theta.tolist(), active_bounds=fit.active_mask.tolist())
            row["used"] = bool(np.isfinite(theta).all() and rmse <= RMSE_LIMIT[cohort])
            if not row["used"]:
                row["exclusion"] = "Full-flight fit failed the prespecified residual/finite gate"
        except RuntimeError as exc:
            row.update(used=False, exclusion=str(exc))
        if cohort in excluded or row["id"] in excluded_ids:
            row["used"] = False
            row["exclusion"] = ("excluded for leave-one-cohort-out audit"
                                if cohort in excluded else
                                "excluded for leave-one-trial-out audit")
        if (not row["used"] and cohort in LAUNCH_COHORTS
                and cohort not in excluded and row["id"] not in excluded_ids):
            raise RuntimeError(f"Required launch fit failed: {row}")
        records.append(row)
        print(f"fit {cohort}/{name}: {row.get('rmse_m', float('nan')):.4f} m, used={row['used']}",
              flush=True)
    used_cohorts = {row["cohort"] for row in records if row["used"]}
    if not used_cohorts:
        print("WARNING: no usable fitted anchors (prior-only build)", flush=True)
    return records


def sample(n, rng, records, excluded=(), prior_fraction=.5):
    theta = sample_prior(n, rng)
    anchor = np.full(n, -1, dtype=np.int16)
    cohorts = [c for c in sorted(RMSE_LIMIT) if c not in excluded]
    n_empirical = int(round(n * prior_fraction))
    if n_empirical > 0 and cohorts:
        empirical = rng.permutation(n)[:n_empirical]
        groups = np.array_split(empirical, len(cohorts))
    else:
        groups = []
    for cohort, indices in zip(cohorts, groups):
        eligible = [i for i, row in enumerate(records) if row["used"] and row["cohort"] == cohort]
        if len(eligible) == 0 or len(indices) == 0:
            continue
        choices = rng.permutation(np.resize(rng.permutation(eligible), len(indices)))
        draws = np.array([records[i]["theta"] for i in choices])
        if cohort not in LAUNCH_COHORTS:
            yaw = (np.arctan2(theta[indices, 1], theta[indices, 0])
                   - np.arctan2(draws[:, 1], draws[:, 0]))
            wx, wy = draws[:, 3:5].T.copy()
            draws[:, 3] = np.cos(yaw) * wx - np.sin(yaw) * wy
            draws[:, 4] = np.sin(yaw) * wx + np.cos(yaw) * wy
        draws += rng.normal(size=draws.shape) * PERTURB
        columns = slice(None) if cohort in LAUNCH_COHORTS else slice(3, None)
        theta[indices, columns] = np.clip(draws[:, columns], LOW[columns], HIGH[columns])
        anchor[indices] = choices
    signs = rng.choice((-1., 1.), size=n)
    theta[:, [1, 3, 5]] *= signs[:, None]
    return theta, anchor


def build(n, seed, records, excluded=(), prior_fraction=.5):
    sizes = [n * 8 // 10, n // 10]
    sizes.append(n - sum(sizes))
    parts, counts = [], {}
    for code, (size, sequence) in enumerate(zip(sizes, np.random.SeedSequence(seed).spawn(3))):
        theta, anchor = sample(size, np.random.default_rng(sequence), records,
                               excluded=excluded, prior_fraction=prior_fraction)
        totals = {}
        for start in range(0, size, 2000):
            result = simulate(theta[start:start + 2000], Config())
            for key, array in result.items():
                totals.setdefault(key, []).append(array)
        data = {key: np.concatenate(arrays) for key, arrays in totals.items()}
        parts.append(dict(theta=theta, anchor=anchor, split=np.full(size, code, dtype=np.int8), **data))
        counts[str(code)] = {
            "seed_spawn_key": list(sequence.spawn_key),
            "status": {str(k): int(np.count_nonzero(data["status"] == k)) for k in range(3)},
            "anchors": {"canonical" if i == -1 else records[i]["id"]: int(np.count_nonzero(anchor == i))
                        for i in np.unique(anchor)},
        }
        print(f"split {code}: {size} simulated, {counts[str(code)]['status']['1']} crossings", flush=True)
    dataset = {key: np.concatenate([part[key] for part in parts]) for key in parts[0]}
    if len(np.unique(dataset["theta"], axis=0)) != n:
        raise RuntimeError("Repeated latent state across simulations")
    crossings = dataset["status"] == 1
    if not np.isfinite(dataset["endpoint"][crossings]).all() or np.isfinite(
            dataset["endpoint"][~crossings]).any():
        raise RuntimeError("Invalid crossing labels")
    return dataset, counts


def exclusions():
    low_rows = read_csv(PENALTIES)
    low_cases = {}
    for name in ("J03WMX", "PFF_3816"):
        times, points = handoff_track(low_rows, name)
        low_cases[name] = dict(frames=len(times), minimum_z_m=float(points[:, 2].min()),
                               role="Low-ball diagnostic only. Rolling/bounce/height uncertainty.",
                               source_sha256=sha256(PENALTIES))
    return dict(
        low_ball=low_cases,
        dfl_screened_out=dict(count=49, role="Rejected by the existing event/continuity screen",
                              audit_sha256=sha256(EXTRA.with_name("screening_audit.csv"))),
        issia_raw=dict(role="Three vetted arcs used. Other candidates lack contact verification.",
                       sha256=sha256(REPO / "data_sources" / "ISSIA-3D.csv")),
        duplicate_inputs="Archived copies, DFL duplicate penalties and same-content ISSIA CSV counted once",
        previous_simulation="Older synthetic datasets and weights are frozen; legacy prior retained at 50%",
        question_case="Competition query does not enter the fitted prior or training")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--asai-dir", type=Path, default=Path.home() / "Desktop")
    parser.add_argument("--n", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=155211)
    parser.add_argument("--exclude-cohorts", nargs="*", default=[],
                        choices=sorted(RMSE_LIMIT))
    parser.add_argument("--exclude-anchor-ids", nargs="*", default=[],
                        help="Exclude individual fitted anchors (leave-one-trial-out).")
    parser.add_argument("--prior-fraction", type=float, default=.5)
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    if args.n < 1200:
        parser.error("--n must be at least 1200 so every split includes each anchor")
    if not 0. <= args.prior_fraction <= 1.:
        parser.error("--prior-fraction must be in [0, 1]")
    args.output.mkdir(parents=True, exist_ok=False)
    tracks = load_tracks(args.asai_dir)
    records = fit_anchors(tracks, excluded=args.exclude_cohorts,
                           excluded_ids=args.exclude_anchor_ids)
    excluded = exclusions()
    dataset, counts = build(args.n, args.seed, records,
                            excluded=args.exclude_cohorts,
                            prior_fraction=args.prior_fraction)
    path = args.output / "data.npz"
    np.savez_compressed(path, **dataset)
    manifest = dict(
        n=args.n, seed=args.seed, sha256=sha256(path),
        prior_fraction_canonical=1. - args.prior_fraction,
        prior_fraction_anchored=args.prior_fraction,
        exclude_cohorts=list(args.exclude_cohorts),
        exclude_anchor_ids=list(args.exclude_anchor_ids), tag=args.tag,
        perturbation_sd=PERTURB.tolist(), lower=LOW.tolist(), upper=HIGH.tolist(),
        rmse_limit_m=RMSE_LIMIT, splits=counts, anchors=records, exclusions=excluded,
        simulator_sha256=sha256(SB / "physics.py"),
        builder_sha256=sha256(Path(__file__)),
        setting="Canonical RK4, z0=.11 m, observations .05/.10 s, plane x=11 m",
        holdout="Independent synthetic draws from shared fitted priors",
        asai_spin="Magnitude samples counted; direction unknown, effective spin fitted to positions")
    (args.output / "data_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")


if __name__ == "__main__":
    main()
