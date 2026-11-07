"""Screen observed ISSIA-3D frames for possible airborne segments."""
import argparse
import ast
import csv
from pathlib import Path

import numpy as np

from experiment import dump


def screen(source, output):
    fps = 25
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    frames = []
    for row in rows:
        if not row["ball_3D"]:
            continue
        point = np.asarray(ast.literal_eval(row["ball_3D"]), float)
        if point.shape != (3,) or not np.isfinite(point).all():
            continue
        errors = [float(row[f"err_cam{i}"]) for i in range(1, 7) if row[f"err_cam{i}"]]
        # Released calibration places above-pitch cameras at negative world z.
        x, y, z = point
        frames.append((int(row["frame"]), x, y, -z, int(row["num_cameras"]),
                       float(np.median(errors)) if errors else float("inf")))
    frames.sort()
    points = np.asarray(frames)
    # Pixel reprojection error is a screening flag, not 3D position accuracy.
    summaries = {}
    for threshold in (5, 10, 20):
        accepted = points[(points[:, 3] >= .30) & (points[:, 4] >= 2) &
                          (points[:, 5] <= threshold)]
        runs = np.split(accepted, np.flatnonzero(np.diff(accepted[:, 0]) != 1) + 1)
        candidates = []
        for run in runs:
            if len(run) < 8:
                continue
            displacement = np.linalg.norm(run[-1, 1:3] - run[0, 1:3])
            if displacement < 2:
                continue
            t = (run[:, 0]-run[0, 0])/fps
            # Fit only for triage, never to decide that an arc is genuine.
            predicted = np.polynomial.polynomial.polyval(t, np.polynomial.polynomial.polyfit(t, run[:, 1:4], 2)).T
            candidates.append(dict(first_frame=int(run[0, 0]), last_frame=int(run[-1, 0]),
                duration_s=float(t[-1]), horizontal_displacement_m=float(displacement),
                max_height_m=float(run[:, 3].max()), median_reprojection_px=float(np.median(run[:, 5])),
                quadratic_fit_rmse_m=float(np.sqrt(np.mean(np.sum((predicted-run[:, 1:4])**2, axis=1))))))
        summaries[str(threshold)] = dict(accepted_frames=len(accepted), candidates=candidates)
        if threshold == 10:
            with (output/"candidate_frames.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["candidate_start_frame", "frame", "segment_time_s", "x_m", "y_m",
                                 "height_m", "num_cameras", "median_reprojection_px"])
                for c in candidates:
                    start, end = c["first_frame"], c["last_frame"]
                    for frame, x, y, z, cameras, error in accepted[(accepted[:, 0]>=start) & (accepted[:, 0]<=end)]:
                        writer.writerow([start, int(frame), (frame-start)/fps, x, y, z, int(cameras), error])
    dump(output/"screening.json", dict(rows=len(rows), valid_3d=len(points), fps=fps,
        minimum_height_m=.30, minimum_frames=8, minimum_horizontal_displacement_m=2,
        thresholds_px=summaries, height_convention="height_m = -world_z_m",
        limitation="Candidate arcs only. No kick-off instant, contact labels or penalty truth in this CSV."))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    screen(args.source, args.output)
