"""Conditional in-frame probability scores from the frozen P1 blind test.

Reads student-c/P1/final/final_scores.csv and reports, per noise level, the
mean and seed range of the calibration/ECE/Brier values for the final
(calibrated, density-rank adjusted) model on the 5,036 fresh airborne
crossings.  Only samples that crossed the goal plane in flight are scored, so
the probability is P(centre in frame | airborne crossing).
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
import statistics

SRC = Path(__file__).resolve().parents[1] / "final" / "final_scores.csv"

rows = list(csv.DictReader(SRC.open(encoding="utf-8")))
sel = [r for r in rows
       if r["split"] == "fresh_test" and r["method"] == "scaled_hdr"
       and r["features"] == "phys_reduced"]
by = defaultdict(list)
for r in sel:
    by[int(r["sigma_mm"])].append(r)

print(f"{'sigma':>5} {'n':>5} {'seeds':>5} {'ECE':>8} {'ECE sd':>8} "
      f"{'Brier':>8} {'Brier sd':>9} {'goal rate':>10}")
for sig in sorted(by):
    group = sorted(by[sig], key=lambda r: int(r["seed"]))
    ece = [float(r["goal_ece"]) for r in group]
    brier = [float(r["goal_brier"]) for r in group]
    rate = [float(r["goal_rate"]) for r in group]
    print(f"{sig:>5} {group[0]['n']:>5} {len(group):>5} {statistics.mean(ece):>8.4f} "
          f"{statistics.pstdev(ece):>8.4f} {statistics.mean(brier):>8.4f} "
          f"{statistics.pstdev(brier):>9.4f} {statistics.mean(rate):>10.4f}")
    print("      ECE per seed:", [round(v, 4) for v in ece],
          " Brier per seed:", [round(v, 4) for v in brier])
