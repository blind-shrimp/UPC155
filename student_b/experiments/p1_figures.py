"""Export P1 calibration and case figures and a LaTeX table."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import numpy as np
import torch

from p1 import DEFAULT_OUT, GOAL, get_checkpoint, load_checkpoint, predict, rescale, save_json
from physics import CASE


def plot_calibration(out, rows):
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4), layout="constrained")
    for nominal, axis in zip((50, 95), axes):
        for method, label in (("raw", "Before calibration"), ("scaled", "Scale only"),
                              ("scaled_hdr", "Scale + HDR correction")):
            series = sorted((row for row in rows if row["method"] == method),
                            key=lambda row: int(row["sigma_mm"]))
            axis.plot([int(row["sigma_mm"]) for row in series],
                      [100 * float(row[f"coverage{nominal}_mean"]) for row in series],
                      marker="o", label=label)
        axis.axhline(nominal, color="0.4", linestyle=":", label="Target")
        axis.set(xlabel="Position noise SD (mm)", ylabel="Observed coverage (%)",
                 title=f"{nominal}% nominal region", xticks=(2, 5, 10, 15))
    axes[0].legend(fontsize=8)
    fig.savefig(out / "figures" / "coverage_fresh.png", dpi=300)
    plt.close(fig)


def plot_architecture(out):
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4), layout="constrained")
    for axis, filename, key, title in zip(
        axes, ("depth.csv", "activation.csv"), ("depth", "activation"),
        ("Depth with SiLU", "Activation at selected depth"),
    ):
        with (out / filename).open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        choices = list(dict.fromkeys(row[key] for row in rows))
        means, spreads = [], []
        for choice in choices:
            group = [row for row in rows if row[key] == choice]
            by_seed = [np.mean([float(row["nll"]) for row in group if row["seed"] == seed])
                       for seed in dict.fromkeys(row["seed"] for row in group)]
            means.append(np.mean(by_seed))
            spreads.append(np.std(by_seed, ddof=1))
        x = np.arange(len(choices))
        axis.errorbar(x, means, yerr=spreads, fmt="o", capsize=4, color="tab:blue")
        axis.set(xticks=x, xticklabels=choices, ylabel="Mean validation NLL (lower is better)", title=title)
    fig.savefig(out / "figures" / "architecture_screen.png", dpi=300)
    plt.close(fig)


@torch.no_grad()
def plot_case(out, config, frozen):
    kind, k = config
    seed = frozen["case_seed"]
    model, stats = load_checkpoint(get_checkpoint(out, config, seed), config)
    calibration = frozen["calibration"][f"{kind}_k{k}_{seed}"]
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.2), layout="constrained", sharex=True, sharey=True)
    records = []
    for mm, axis in zip((2, 5, 15), axes):
        spec = calibration[str(mm)]
        dist = rescale(predict(model, stats, kind, CASE[None], mm / 1000), spec["scale_sd"])
        torch.manual_seed(75000 + mm)
        samples = dist.sample((65536,))
        points = samples[:, 0].numpy() * stats["ys"] + stats["ym"]
        log_threshold = {level: float(torch.quantile(dist.log_prob(samples), 1 - mass))
                         for level, mass in spec["hdr_mass"].items()}
        lower, upper = np.quantile(points, [0.0005, 0.9995], axis=0)
        lower -= .15 * (upper - lower)
        upper += .15 * (upper - lower)
        y, z = np.meshgrid(np.linspace(lower[0], upper[0], 300), np.linspace(lower[1], upper[1], 300))
        grid = np.stack((y, z), axis=-1)
        standardized = torch.as_tensor((grid - stats["ym"]) / stats["ys"], dtype=torch.float32)
        log_density = dist.log_prob(standardized).numpy()
        density = np.exp(log_density) / np.prod(stats["ys"])
        mode = grid[np.unravel_index(np.argmax(density), density.shape)]
        cell_area = float((y[0, 1] - y[0, 0]) * (z[1, 0] - z[0, 0]))
        goal = (np.abs(points[:, 0]) < GOAL[0]) & (points[:, 1] > GOAL[1]) & (points[:, 1] < GOAL[2])
        records.append(dict(sigma_mm=mm, mode_m=mode.tolist(),
                            mean_m=(dist.mean[0].numpy() * stats["ys"] + stats["ym"]).tolist(),
                            goal_probability_given_airborne=float(goal.mean()),
                            grid_integrated_mass=float(density.sum() * cell_area),
                            hdr_area_m2={level: float((log_density >= threshold).sum() * cell_area)
                                         for level, threshold in log_threshold.items()}))
        axis.set_facecolor("#000004")
        axis.pcolormesh(y, z, density, cmap="magma", shading="auto")
        axis.contour(y, z, log_density, [log_threshold["0.95"], log_threshold["0.5"]],
                     colors=["cyan", "white"])
        axis.add_patch(Rectangle((-GOAL[0], GOAL[1]), 2 * GOAL[0], GOAL[2] - GOAL[1],
                                 fill=False, edgecolor="limegreen", linestyle="--"))
        axis.plot(*mode, marker="+", color="white")
        axis.set(xlabel="Y (m)", title=f"{mm} mm noise SD", aspect="equal")
    axes[0].set(ylabel="Z (m)")
    fig.legend(handles=[
        Line2D([], [], color="0.35", label="50% HDR (white on plot)"),
        Line2D([], [], color="darkturquoise", label="95% HDR"),
        Line2D([], [], color="limegreen", linestyle="--", label="Goal frame"),
        Line2D([], [], color="0.35", linestyle="none", marker="+", label="Mode"),
    ], loc="outside lower center", ncols=4, frameon=False)
    fig.savefig(out / "figures" / "case_regions.png", dpi=300)
    plt.close(fig)
    save_json(out / "case.json", dict(features=kind, k=k, seed=seed, rows=records))


def latex_table(out, rows):
    slash = chr(92)
    lines = [
        slash + "begin{tabular}{rrrrrr}", slash + "toprule",
        f"Noise (mm) & Median (m) & NLL & 50{slash}% pre/post & 95{slash}% pre/post & 95{slash}% area (m$^2$)"
        + " " + slash * 2, slash + "midrule",
    ]
    for mm in (2, 5, 10, 15):
        matching = {row["method"]: row for row in rows if int(row["sigma_mm"]) == mm}
        pre, post = matching["raw"], matching["scaled_hdr"]
        coverage = []
        for level in (50, 95):
            key = f"coverage{level}_mean"
            coverage.append(f"{100 * float(pre[key]):.1f} / {100 * float(post[key]):.1f}")
        lines.append(f"{mm} & {float(post['median_mean']):.3f} & {float(post['nll_mean']):.3f} & "
                     f"{coverage[0]} & {coverage[1]} & {float(post['area95_mean']):.3f} " + slash * 2)
    lines.extend((slash + "bottomrule", slash + "end{tabular}"))
    (out / "tables" / "tab_p1_fresh.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    out = parser.parse_args().out
    for subdirectory in ("figures", "tables"):
        (out / subdirectory).mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    frozen = json.loads((out / "best_config.json").read_text(encoding="utf-8"))
    config = tuple(frozen["winner"])
    with (out / "summary.csv").open(encoding="utf-8", newline="") as file:
        rows = [row for row in csv.DictReader(file)
                if row["split"] == "fresh_test" and (row["features"], int(row["k"])) == config]
    plot_calibration(out, rows)
    if (out / "depth.csv").is_file() and (out / "activation.csv").is_file():
        plot_architecture(out)
    plot_case(out, config, frozen)
    latex_table(out, rows)


if __name__ == "__main__":
    main()
