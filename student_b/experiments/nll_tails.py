"""NLL tail diagnostics for the five arms: mean vs median vs worst cases."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SB = HERE.parent
sys.path.insert(0, str(SB))

from common import LEVELS, baseline_endpoint, build_mdn, make_inputs, make_target

import torch

DATA = SB / "runs" / "canonical50k" / "data.npz"
RES = HERE / "results"
CKPT = RES / "checkpoints"


def main():
    torch.set_num_threads(4)
    d = np.load(DATA)
    valid = (d["status"] == 1) & np.isfinite(d["observations"]).all(axis=(1, 2))
    test = valid & (d["split"] == 2)
    obs_te, y_te = d["observations"][test], d["endpoint"][test]
    rows = []
    for arm in "ABCDE":
        for seed in (11, 22, 33):
            ck = torch.load(CKPT / f"{arm}_{seed}.pt", map_location="cpu", weights_only=False)
            model = build_mdn(ck["input_dim"], k=ck["k"], hidden=ck["hidden"], depth=ck["depth"])
            model.load_state_dict(ck["state"])
            model.eval()
            st = ck["stats"]
            for sigma in (0.010, 0.015):
                rng = np.random.default_rng(9100 + int(sigma * 1e6))
                noisy = obs_te + rng.normal(size=obs_te.shape) * sigma
                spec_target = "res" if arm in "BDE" else "abs"
                base = baseline_endpoint(noisy)
                base = np.where(np.isfinite(base), base, 0.0)
                nll = []
                with torch.no_grad():
                    for j in range(0, len(noisy), 512):
                        sl = slice(j, j + 512)
                        X = np.nan_to_num((make_inputs(
                            "phys" if arm in "CD" else ("rawbase" if arm == "E" else "raw"),
                            noisy[sl], sigma) - st["xm"]) / st["xs"],
                            nan=0.0, posinf=0.0, neginf=0.0)
                        dist = model(torch.tensor(X, dtype=torch.float32))
                        y_std = (y_te[sl] - st["ym"]) / st["ys"]
                        if spec_target == "res":
                            y_std = y_std - base[sl] / st["ys"]
                        lp = dist.log_prob(torch.tensor(y_std, dtype=torch.float32))
                        nll.append((-lp.numpy() + np.log(st["ys"]).sum()))
                nll = np.concatenate(nll)
                rows.append(dict(arm=arm, seed=seed, sigma_m=sigma,
                                 nll_mean=float(nll.mean()),
                                 nll_median=float(np.median(nll)),
                                 nll_p90=float(np.quantile(nll, .9)),
                                 nll_p99=float(np.quantile(nll, .99)),
                                 nll_max=float(nll.max()),
                                 frac_gt_10=float((nll > 10).mean()),
                                 frac_gt_100=float((nll > 100).mean())))
                print(arm, seed, sigma, round(nll.mean(), 2), round(np.median(nll), 2),
                      round(np.quantile(nll, .99), 2), flush=True)
    out = RES / "nll_tails.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print("written", out)


if __name__ == "__main__":
    main()
