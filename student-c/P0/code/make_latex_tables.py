"""Generate the P0 LaTeX tables (booktabs) for the paper draft.

Reads the authoritative results from student_b/experiments/results and writes
.tex snippets into student-c/P0/tables/. All numbers are development results on
the frozen 4,187-flight synthetic test set; captions say so.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RES = ROOT / "student_b" / "experiments" / "results"
OUT = HERE.parent / "tables"
SIGMAS = [("0.002", "2"), ("0.005", "5"), ("0.010", "10"), ("0.015", "15")]
ARMS = {"A": "A: raw$_6$+$\\sigma$ $\\to$ absolute",
        "B": "B: raw$_6$+$\\sigma$ $\\to$ residual",
        "C": "C: physics$_{16}$ $\\to$ absolute",
        "D": "D: physics$_{16}$ $\\to$ residual",
        "E": "E: raw$_6$+$\\sigma$+base $\\to$ residual"}


def read_csv(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def mean(vals):
    vals = [float(v) for v in vals]
    return sum(vals) / len(vals)


def ablation_table(metric, caption, label, fmt="{:.3f}", note=None):
    rows = read_csv(RES / "ablation_summary.csv")
    lines = ["\\begin{table}[htbp]", "\\centering", f"\\caption{{{caption}}}",
             f"\\label{{{label}}}", "\\begin{tabular}{lcccc}", "\\toprule",
             "Arm & " + " & ".join(f"{s} mm" for _, s in SIGMAS) + " \\\\", "\\midrule"]
    for arm in "ABCDE":
        cells = []
        for key, _ in SIGMAS:
            r = next(x for x in rows if x["arm"] == arm
                     and abs(float(x["sigma_m"]) - float(key)) < 1e-9)
            cells.append(fmt.format(float(r[f"{metric}_mean"])))
        lines.append(ARMS[arm] + " & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    if note:
        lines += ["\\par\\smallskip\\footnotesize " + note]
    lines += ["\\end{table}", ""]
    (OUT / f"{label}.tex").write_text("\n".join(lines), encoding="utf-8")


def coverage_table():
    rows = read_csv(RES / "ablation_summary.csv")
    lines = ["\\begin{table}[htbp]", "\\centering",
             "\\caption{Empirical coverage of the nominal 50\\% and 95\\% HDRs "
             "(P0, frozen 4,187-flight synthetic test set, 3 seeds).}",
             "\\label{tab:p0-coverage}", "\\small", "\\begin{tabular}{lcccccccc}",
             "\\toprule", " & \\multicolumn{4}{c}{50\\% HDR} & \\multicolumn{4}{c}{95\\% HDR} \\\\",
             "\\cmidrule(lr){2-5}\\cmidrule(lr){6-9}",
             "Arm & 2 & 5 & 10 & 15 & 2 & 5 & 10 & 15 \\\\", "\\midrule"]
    for arm in "ABCDE":
        c50, c95 = [], []
        for key, _ in SIGMAS:
            r = next(x for x in rows if x["arm"] == arm
                     and abs(float(x["sigma_m"]) - float(key)) < 1e-9)
            c50.append(f"{float(r['coverage50_mean'])*100:.1f}")
            c95.append(f"{float(r['coverage95_mean'])*100:.1f}")
        lines.append(f"{arm} & " + " & ".join(c50) + " & " + " & ".join(c95) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}",
              "\\par\\smallskip\\footnotesize Nominal levels are 50\\%/95\\%; entries are percent.",
              "\\end{table}", ""]
    (OUT / "tab_p0_coverage.tex").write_text("\n".join(lines), encoding="utf-8")


def residual_table():
    j = json.loads((RES / "diagnostics.json").read_text(encoding="utf-8"))
    r = j["baseline_residual"]
    rows = [("Mean", f"{r['dy_mean']:.3f}", f"{r['dz_mean']:.3f}"),
            ("Std", f"{r['dy_std']:.3f}", f"{r['dz_std']:.3f}"),
            ("Median", f"{r['dy_quantiles']['q50']:.3f}", f"{r['dz_quantiles']['q50']:.3f}"),
            ("95th pct", f"{r['dy_quantiles']['q95']:.3f}", f"{r['dz_quantiles']['q95']:.3f}"),
            ("99th pct", f"{r['dy_quantiles']['q99']:.3f}", f"{r['dz_quantiles']['q99']:.3f}")]
    lines = ["\\begin{table}[htbp]", "\\centering",
             "\\caption{Constant-acceleration baseline residual $\\Delta={\\rm truth}-{\\rm baseline}$ "
             "on the clean test set (m, $n=4187$).}",
             "\\label{tab:p0-residual}", "\\begin{tabular}{lccc}", "\\toprule",
             "Statistic & $\\Delta Y$ & $\\Delta Z$ & $\\|\\Delta\\|$ \\\\", "\\midrule"]
    for name, dy, dz in rows:
        norm = {"Mean": "---", "Std": "---", "Median": f"{r['norm_median']:.3f}",
                "95th pct": "---", "99th pct": f"{r['norm_p99']:.3f}"}[name]
        lines.append(f"{name} & {dy} & {dz} & {norm} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}",
              f"\\par\\smallskip\\footnotesize $\\|\\Delta\\|$ median {r['norm_median']:.3f} m, "
              f"90th pct {r['norm_p90']:.3f} m; only {r['frac_norm_gt_0_5m']*100:.2f}\\% exceed 0.5 m.",
              "\\end{table}", ""]
    (OUT / "tab_p0_residual.tex").write_text("\n".join(lines), encoding="utf-8")


def feature_table():
    j = json.loads((RES / "diagnostics.json").read_text(encoding="utf-8"))
    lines = ["\\begin{table}[htbp]", "\\centering",
             "\\caption{Conditioning of the physics feature set we reconstructed "
             "(15 features; $\\sigma$ excluded because it is constant per row).}",
             "\\label{tab:p0-features}", "\\begin{tabular}{lcccc}", "\\toprule",
             "$\\sigma$ & Condition no. & Max $|$corr$|$ & $\\hat C_D$ corr. & $\\hat C_D$ RMSE \\\\",
             "\\midrule"]
    for key, label in SIGMAS:
        f = j["features"][f"{float(key)*1000:g}mm"]
        lines.append(f"{label} mm & {f['condition_standardized']:.1e} & "
                     f"{f['max_abs_corr']:.3f} & {f['cd_app_corr_true']:.3f} & "
                     f"{f['cd_app_rmse_vs_true']:.3f} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}",
              "\\par\\smallskip\\footnotesize The three $a$ and $a-g$ components are exactly "
              "collinear; $\\hat C_D$ is the apparent drag coefficient from finite differences.",
              "\\end{table}", ""]
    (OUT / "tab_p0_features.tex").write_text("\n".join(lines), encoding="utf-8")


def pi_table():
    own = json.loads((RES.parent / "runs_pi_res_mdn" / "pi_res_mdn_summary.json")
                     .read_text(encoding="utf-8"))
    e150 = read_csv(RES / "pi_canonical_runs_e150.csv")
    ab = read_csv(RES / "ablation_summary.csv")
    paired = read_csv(RES / "paired_PI_vs_AC_5mm.csv")

    def pi_e(key, metric):
        return mean([float(r[metric]) for r in e150 if abs(float(r["sigma_m"]) - float(key)) < 1e-9])

    def ab_e(arm, key, metric):
        r = next(x for x in ab if x["arm"] == arm
                 and abs(float(x["sigma_m"]) - float(key)) < 1e-9)
        return float(r[f"{metric}_mean"])

    lines = ["\\begin{table}[htbp]", "\\centering",
             "\\caption{PI-ResMDN review at $\\sigma=5$ mm. Own simulator = uploaded script; "
             "canonical = retrained on the canonical simulator and evaluated on the same "
             "4,187-flight test set.}",
             "\\label{tab:p0-pi}", "\\begin{tabular}{lcccc}", "\\toprule",
             "Model & Median err. (m) & 50\\% cov. & 95\\% cov. & NLL \\\\", "\\midrule"]
    o = own["test_evaluation"]["sigma_5mm"]
    lines.append(f"PI-ResMDN (own simulator) & {o['pi_res_mdn_median_err_m']:.3f} & "
                 f"{o['empirical_coverage_50']*100:.1f}\\% & {o['empirical_coverage_95']*100:.1f}\\% & --- \\\\")
    lines.append(f"PI-ResMDN (canonical, 150 ep) & {pi_e('0.005','median'):.3f} & "
                 f"{pi_e('0.005','coverage50')*100:.1f}\\% & {pi_e('0.005','coverage95')*100:.1f}\\% & "
                 f"{pi_e('0.005','nll'):.2f} \\\\")
    for arm in ("A", "C"):
        lines.append(f"Arm {arm} (canonical) & {ab_e(arm,'0.005','median'):.3f} & "
                     f"{ab_e(arm,'0.005','coverage50')*100:.1f}\\% & "
                     f"{ab_e(arm,'0.005','coverage95')*100:.1f}\\% & "
                     f"{ab_e(arm,'0.005','nll'):.2f} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}",
              f"\\par\\smallskip\\footnotesize Paired comparison (same 4,187 flights, same noise): "
              f"PI is better than A on {mean([r['frac_PI_better_than_A'] for r in paired])*100:.1f}\\% "
              f"and than C on {mean([r['frac_PI_better_than_C'] for r in paired])*100:.1f}\\% of trajectories.",
              "\\end{table}", ""]
    (OUT / "tab_p0_pi_review.tex").write_text("\n".join(lines), encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ablation_table("median", "P0 five-arm ablation: median endpoint error (m) on the frozen "
                   "4,187-flight synthetic test set (3 seeds).", "tab_p0_ablation_median")
    ablation_table("nll", "P0 five-arm ablation: mean negative log-likelihood in physical units "
                   "(lower is better; absolute and residual targets are comparable by translation).",
                   "tab_p0_ablation_nll", fmt="{:.2f}")
    coverage_table()
    residual_table()
    feature_table()
    pi_table()
    print("tables written to", OUT)


if __name__ == "__main__":
    main()
