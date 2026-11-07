"""P0 1.4: train the uploaded PI-ResMDN architecture on the canonical simulator
data and evaluate it on the canonical 4,187-flight test set with the unified HDR
estimator, so it is directly comparable with arms A-E.

The uploaded pi_res_mdn.py trains on its own simulator (rho=1.225, saturating
C_L, spin decay), which differs from canonical by ~0.24 m RMS (see
simulator_diff.json). For a same-test comparison we must retrain on canonical
data; this script reuses the uploaded feature extractor and model class verbatim.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SB = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SB))

import torch
from torch import nn

from common import LEVELS, evaluate_distribution, summarize_errors
from pi_res_mdn import (PhysicsResidualMDN, bivariate_gaussian_nll,
                        extract_physics_features, predict_distribution_and_hpd)

DATA = SB / "runs" / "canonical50k" / "data.npz"
OUT = HERE / "results"
CKPT = OUT / "checkpoints"
GOAL = (3.66, 0.0, 2.44)
SEEDS = (11, 22, 33)
EPOCHS = int(os.environ.get("PI_EPOCHS", "60"))
BATCH = 512
LR = 2e-3


def build_dist(log_pi, mu, sig, rho):
    from torch.distributions import Categorical, MixtureSameFamily, MultivariateNormal
    b, k, _ = mu.shape
    L = torch.zeros((b, k, 2, 2), device=mu.device)
    L[..., 0, 0] = sig[..., 0]
    L[..., 1, 0] = rho * sig[..., 1]
    L[..., 1, 1] = sig[..., 1] * torch.sqrt(1 - rho**2 + 1e-6)
    return MixtureSameFamily(Categorical(logits=log_pi), MultivariateNormal(mu, scale_tril=L))


def train(seed, parts):
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    x_tr, y_tr = parts["tr"]["obs"], parts["tr"]["y"]
    x_va, y_va = parts["va"]["obs"], parts["va"]["y"]
    n_tr = len(x_tr)
    xt = torch.tensor(x_tr.reshape(n_tr, 6), dtype=torch.float32)
    yt = torch.tensor(y_tr, dtype=torch.float32)

    ref = rng.choice(n_tr, size=min(5000, n_tr), replace=False)
    sig_ref = torch.full((len(ref), 1), .005)
    noisy_ref = xt[ref] + torch.randn((len(ref), 6)) * sig_ref
    feats, _ = extract_physics_features(noisy_ref, sig_ref)
    feat_mean = feats.mean(0, keepdim=True)
    feat_std = feats.std(0, keepdim=True).clamp(min=1e-5)

    model = PhysicsResidualMDN(16, 128, 5)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCHS, eta_min=2e-5)

    xv = torch.tensor(x_va.reshape(len(x_va), 6), dtype=torch.float32)
    yv = torch.tensor(y_va, dtype=torch.float32)
    sig_v = torch.full((len(xv), 1), .005)
    torch.manual_seed(seed + 500)
    xv_noisy = xv + torch.randn_like(xv) * sig_v

    best = float("inf")
    best_state = None
    t0 = time.perf_counter()
    for epoch in range(EPOCHS):
        model.train()
        perm = torch.randperm(n_tr)
        total, seen = 0.0, 0
        for start in range(0, n_tr, BATCH):
            idx = perm[start:start + BATCH]
            sigma = torch.empty((len(idx), 1)).uniform_(.001, .020)
            xb = xt[idx] + torch.randn((len(idx), 6)) * sigma
            opt.zero_grad()
            log_pi, mu, sig, rho = model(xb, sigma, feat_mean, feat_std)
            loss = bivariate_gaussian_nll(yt[idx], log_pi, mu, sig, rho)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            opt.step()
            total += float(loss) * len(idx)
            seen += len(idx)
        sched.step()
        model.eval()
        with torch.no_grad():
            log_pi, mu, sig, rho = model(xv_noisy, sig_v, feat_mean, feat_std)
            val = float(bivariate_gaussian_nll(yv, log_pi, mu, sig, rho))
        if val < best:
            best = val
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        if (epoch + 1) % 20 == 0:
            print(f"  seed{seed} epoch {epoch+1}/{EPOCHS} train {total/seen:.3f} val {val:.3f}",
                  flush=True)
    model.load_state_dict(best_state)
    model.eval()
    return model, feat_mean, feat_std, time.perf_counter() - t0, best


def evaluate(model, feat_mean, feat_std, parts, seed):
    x_te, y_te = parts["te"]["obs"], parts["te"]["y"]
    rows = []
    per_sample = None
    identity = dict(ym=np.zeros(2), ys=np.ones(2))
    with torch.no_grad():
        for sigma in LEVELS:
            rng = np.random.default_rng(9100 + int(sigma * 1e6))
            noisy = x_te + rng.normal(size=x_te.shape) * sigma
            errs, nll, c50, c95, a50, a95, pg, en = [], [], [], [], [], [], [], []
            pis = []
            for j in range(0, len(noisy), 256):
                sl = slice(j, j + 256)
                xb = torch.tensor(noisy[sl].reshape(len(noisy[sl]), 6), dtype=torch.float32)
                sb = torch.full((len(xb), 1), sigma)
                log_pi, mu, sig, rho = model(xb, sb, feat_mean, feat_std)
                dist = build_dist(log_pi, mu, sig, rho)
                errs.append(np.linalg.norm(dist.mean.numpy() - y_te[sl], axis=1))
                met = evaluate_distribution(dist, y_te[sl], identity, "abs", y_te[sl], GOAL)
                nll.append(met["nll"])
                c50.append(met["coverage"][0.5])
                c95.append(met["coverage"][0.95])
                a50.append(met["area"][0.5])
                a95.append(met["area"][0.95])
                pg.append(met["p_goal"])
                en.append(met["energy"])
                pis.append(torch.exp(log_pi).numpy())
            err = np.concatenate(errs)
            goal_true = ((np.abs(y_te[:, 0]) < GOAL[0]) & (y_te[:, 1] > GOAL[1])
                         & (y_te[:, 1] < GOAL[2])).astype(float)
            pis = np.concatenate(pis)
            summary = summarize_errors(err, np.concatenate(pg), goal_true)
            rows.append(dict(arm="PI-ResMDN-canonical", seed=seed, sigma_m=sigma,
                             nll=float(np.concatenate(nll).mean()),
                             coverage50=float(np.concatenate(c50).mean()),
                             coverage95=float(np.concatenate(c95).mean()),
                             area50=float(np.concatenate(a50).mean()),
                             area95=float(np.concatenate(a95).mean()),
                             energy=float(np.concatenate(en).mean()),
                             mean_pi=[float(v) for v in pis.mean(0)],
                             frac_max_pi_gt_0_9=float((pis.max(1) > .9).mean()),
                             collapsed=int((pis.mean(0) < .02).sum()),
                             **summary))
            if abs(sigma - .005) < 1e-12:
                per_sample = err
    return rows, per_sample


def main():
    torch.set_num_threads(6)
    OUT.mkdir(parents=True, exist_ok=True)
    CKPT.mkdir(parents=True, exist_ok=True)
    d = np.load(DATA)
    valid = (d["status"] == 1) & np.isfinite(d["observations"]).all(axis=(1, 2))
    parts = {}
    for name, sid in (("tr", 0), ("va", 1), ("te", 2)):
        m = valid & (d["split"] == sid)
        parts[name] = dict(obs=d["observations"][m], y=d["endpoint"][m], idx=np.flatnonzero(m))
    print({k: len(v["idx"]) for k, v in parts.items()}, flush=True)

    rows, paired = [], []
    cases = []
    for seed in SEEDS:
        model, fm, fs, seconds, best = train(seed, parts)
        torch.save(dict(state=model.state_dict(), feat_mean=fm, feat_std=fs, seed=seed),
                   CKPT / f"pi_canonical_{seed}.pt")
        rr, per_sample = evaluate(model, fm, fs, parts, seed)
        for r in rr:
            r["train_seconds"] = seconds
            r["best_val_nll_5mm"] = best
        rows.extend(rr)
        paired.append(dict(seed=seed, errors=per_sample))
        case = predict_distribution_and_hpd(
            model, np.array([1.50, .45, .44, 2.96, .86, .74], dtype=np.float32), .005,
            fm, fs, torch.device("cpu"), grid_res=160)
        case.pop("grid")
        cases.append(dict(seed=seed, **case))
        print(f"done seed{seed} ({seconds:.1f}s): 5mm median "
              f"{rr[1]['median']:.3f} cov50 {rr[1]['coverage50']:.3f}", flush=True)

    tag = f"e{EPOCHS}"
    with open(OUT / f"pi_canonical_runs_{tag}.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # paired comparison vs arm A is reported separately (see paired_arms.py)
    (OUT / f"pi_canonical_{tag}.json").write_text(
        json.dumps(dict(epochs=EPOCHS, runs=rows, case_5mm=cases), indent=2,
                   ensure_ascii=False), encoding="utf-8")
    print("written", OUT / f"pi_canonical_runs_{tag}.csv")


if __name__ == "__main__":
    main()
