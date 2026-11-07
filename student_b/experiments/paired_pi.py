"""Paired 5 mm comparison: PI-ResMDN (canonical retrain) vs arm A and arm C."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
SB = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SB))

from common import LEVELS, baseline_endpoint, build_mdn, make_inputs, make_target
from pi_res_mdn import PhysicsResidualMDN
from pi_res_canonical import build_dist

DATA = SB / "runs" / "canonical50k" / "data.npz"
RES = HERE / "results"
CKPT = RES / "checkpoints"
SIGMA = .005


def dist_for(arm, seed, noisy):
    st = torch.load(CKPT / f"{arm}_{seed}.pt", map_location="cpu", weights_only=False)
    model = build_mdn(st["input_dim"], k=st["k"], hidden=st["hidden"], depth=st["depth"])
    model.load_state_dict(st["state"])
    model.eval()
    z = np.nan_to_num((make_inputs("phys" if arm == "C" else "raw", noisy, SIGMA)
                       - st["stats"]["xm"]) / st["stats"]["xs"],
                      nan=0.0, posinf=0.0, neginf=0.0)
    with torch.no_grad():
        d = model(torch.tensor(z, dtype=torch.float32))
        err = np.linalg.norm((d.mean.numpy() * st["stats"]["ys"] + st["stats"]["ym"])
                             - y_true, axis=1)
    return d, err, st


def pi_dist(seed, noisy):
    ck = torch.load(CKPT / f"pi_canonical_{seed}.pt", map_location="cpu", weights_only=False)
    model = PhysicsResidualMDN(16, 128, 5)
    model.load_state_dict(ck["state"])
    model.eval()
    with torch.no_grad():
        xb = torch.tensor(noisy.reshape(len(noisy), 6), dtype=torch.float32)
        sb = torch.full((len(xb), 1), SIGMA)
        log_pi, mu, sig, rho = model(xb, sb, ck["feat_mean"], ck["feat_std"])
        d = build_dist(log_pi, mu, sig, rho)
        err = np.linalg.norm(d.mean.numpy() - y_true, axis=1)
        lp = d.log_prob(torch.tensor(y_true, dtype=torch.float32)).numpy()
    return err, -lp


if __name__ == "__main__":
    torch.set_num_threads(4)
    d = np.load(DATA)
    valid = (d["status"] == 1) & np.isfinite(d["observations"]).all(axis=(1, 2))
    te = valid & (d["split"] == 2)
    obs_te, y_true = d["observations"][te], d["endpoint"][te]
    rng = np.random.default_rng(9100 + int(SIGMA * 1e6))
    noisy = obs_te + rng.normal(size=obs_te.shape) * SIGMA

    rows = []
    for seed in (11, 22, 33):
        errA, nllA = None, None
        st = torch.load(CKPT / f"A_{seed}.pt", map_location="cpu", weights_only=False)
        mA = build_mdn(st["input_dim"], k=st["k"], hidden=st["hidden"], depth=st["depth"])
        mA.load_state_dict(st["state"]); mA.eval()
        with torch.no_grad():
            zA = np.nan_to_num((make_inputs("raw", noisy, SIGMA) - st["stats"]["xm"])
                               / st["stats"]["xs"], nan=0., posinf=0., neginf=0.)
            dA = mA(torch.tensor(zA, dtype=torch.float32))
            errA = np.linalg.norm((dA.mean.numpy() * st["stats"]["ys"] + st["stats"]["ym"])
                                  - y_true, axis=1)
            nllA = -(dA.log_prob(torch.tensor((y_true - st["stats"]["ym"])
                                              / st["stats"]["ys"], dtype=torch.float32))
                     .numpy()) + np.log(st["stats"]["ys"]).sum()

        stC = torch.load(CKPT / f"C_{seed}.pt", map_location="cpu", weights_only=False)
        mC = build_mdn(stC["input_dim"], k=stC["k"], hidden=stC["hidden"], depth=stC["depth"])
        mC.load_state_dict(stC["state"]); mC.eval()
        with torch.no_grad():
            zC = np.nan_to_num((make_inputs("phys", noisy, SIGMA) - stC["stats"]["xm"])
                               / stC["stats"]["xs"], nan=0., posinf=0., neginf=0.)
            dC = mC(torch.tensor(zC, dtype=torch.float32))
            errC = np.linalg.norm((dC.mean.numpy() * stC["stats"]["ys"] + stC["stats"]["ym"])
                                  - y_true, axis=1)
            nllC = -(dC.log_prob(torch.tensor((y_true - stC["stats"]["ym"])
                                              / stC["stats"]["ys"], dtype=torch.float32))
                     .numpy()) + np.log(stC["stats"]["ys"]).sum()

        errP, nllP = pi_dist(seed, noisy)
        rows.append(dict(
            seed=seed,
            median_A=float(np.median(errA)), median_C=float(np.median(errC)),
            median_PI=float(np.median(errP)),
            nll_A=float(nllA.mean()), nll_C=float(nllC.mean()), nll_PI=float(nllP.mean()),
            median_delta_PI_minus_A=float(np.median(errP - errA)),
            median_delta_PI_minus_C=float(np.median(errP - errC)),
            frac_PI_better_than_A=float((errP < errA).mean()),
            frac_PI_better_than_C=float((errP < errC).mean()),
        ))
        print(rows[-1], flush=True)

    with open(RES / "paired_PI_vs_AC_5mm.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print("written", RES / "paired_PI_vs_AC_5mm.csv")
