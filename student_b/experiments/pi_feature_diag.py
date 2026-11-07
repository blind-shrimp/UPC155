"""Diagnostics for the *actual* 16-dim PI-ResMDN feature set (uploaded file)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
SB = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SB))

from common import LEVELS, RADIUS
from pi_res_mdn import extract_physics_features

DATA = SB / "runs" / "canonical50k" / "data.npz"
RES = HERE / "results"

NAMES = ["r1x", "r1y", "r1z", "r2x", "r2y", "r2z",
         "vx/30", "vy/30", "vz/30", "a_par/20",
         "aperp_x/20", "aperp_y/20", "aperp_z/20",
         "cd_app", "t_const", "sigma*100"]


def main():
    d = np.load(DATA)
    valid = (d["status"] == 1) & np.isfinite(d["observations"]).all(axis=(1, 2))
    train = valid & (d["split"] == 0)
    idx = np.flatnonzero(train)
    rng = np.random.default_rng(7)
    pick = rng.choice(idx, size=20000, replace=False)
    obs = d["observations"][pick]
    theta = d["theta"][pick]
    cd_true = theta[:, 6]
    w = theta[:, 3:6]
    v = (obs[:, 1] - np.array([0, 0, RADIUS])) / 0.1
    speed = np.maximum(np.linalg.norm(v, axis=1), 1e-9)
    s = RADIUS * np.linalg.norm(np.cross(w, v), axis=1) / speed**2
    cl_true = np.minimum(1.4 * s, .30)

    out = {}
    for sigma in LEVELS:
        noisy = obs + rng.normal(size=obs.shape) * sigma
        c = torch.tensor(noisy.reshape(len(noisy), 6), dtype=torch.float32)
        sg = torch.full((len(noisy), 1), sigma)
        with torch.no_grad():
            f, _ = extract_physics_features(c, sg)
        F = f.numpy().astype(np.float64)
        finite = np.isfinite(F).all(1)
        F = F[finite]
        Z = (F - F.mean(0)) / np.maximum(F.std(0), 1e-12)
        C = np.corrcoef(Z[:, :15], rowvar=False)
        eig = np.linalg.eigvalsh(C)
        off = np.abs(C - np.eye(15))
        i, j = np.unravel_index(np.argmax(off), off.shape)
        out[f"{sigma*1000:g}mm"] = dict(
            sigma_m=sigma, n=int(finite.sum()),
            finite_frac=float(finite.mean()),
            rank_standardized=int(np.linalg.matrix_rank(Z[:, :15])),
            condition=float(eig.max() / max(eig.min(), 1e-12)),
            max_abs_corr=float(off[i, j]),
            max_corr_pair=[NAMES[i], NAMES[j]],
            cd_app_corr_true=float(np.corrcoef(F[:, 13], cd_true[finite])[0, 1]),
            cd_app_rmse=float(np.sqrt(np.mean((F[:, 13] - cd_true[finite]) ** 2))),
            a_perp_mean=float(F[:, 10:13].mean()),
            t_const_mean=float(F[:, 14].mean()), t_const_std=float(F[:, 14].std()),
        )
        print(f"{sigma*1000:g}mm rank {out[f'{sigma*1000:g}mm']['rank_standardized']} "
              f"cond {out[f'{sigma*1000:g}mm']['condition']:.3g} "
              f"maxcorr {out[f'{sigma*1000:g}mm']['max_abs_corr']:.3f} "
              f"({out[f'{sigma*1000:g}mm']['max_corr_pair']})", flush=True)

    (RES / "pi_feature_diag.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("written", RES / "pi_feature_diag.json")


if __name__ == "__main__":
    main()
