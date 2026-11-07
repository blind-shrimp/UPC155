"""P0 section 2: five-arm feature/target ablation (todo.md section 2).

Fixed recipe: 2x128 MLP, LayerNorm, SiLU, K=3 full-covariance mixture,
continuous per-sample noise U(1,20) mm, cosine LR, 100 epochs, 3 seeds.
Arms A-E are defined in common.ARMS.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SB = HERE.parent
sys.path.insert(0, str(SB))

from common import (ARMS, LEVELS, baseline_endpoint, build_mdn,  # noqa: E402
                    evaluate_distribution, make_inputs, make_target,
                    standardize_fit, summarize_errors)

import torch  # noqa: E402
from torch import nn  # noqa: E402

DATA = SB / "runs" / "canonical50k" / "data.npz"
OUT = HERE / "results"
CKPT = OUT / "checkpoints"
GOAL = (3.66, 0.0, 2.44)
SEEDS = (11, 22, 33)
EPOCHS = 100
BATCH = 256
LR = 1e-3
K = 3
HIDDEN = 128
DEPTH = 2


def dump(path, obj):
    def clean(x):
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [clean(v) for v in x]
        if isinstance(x, (np.floating, np.integer)):
            return x.item()
        if isinstance(x, float) and not np.isfinite(x):
            return None
        return x
    Path(path).write_text(json.dumps(clean(obj), indent=2, ensure_ascii=False),
                          encoding="utf-8")


def load():
    d = np.load(DATA)
    valid = (d["status"] == 1) & np.isfinite(d["observations"]).all(axis=(1, 2))
    parts = {}
    for name, sid in (("tr", 0), ("va", 1), ("te", 2)):
        m = valid & (d["split"] == sid)
        parts[name] = dict(obs=d["observations"][m], y=d["endpoint"][m],
                           idx=np.flatnonzero(m))
    return d, parts


def train_one(arm, seed, parts, verbose=True):
    spec = ARMS[arm]
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    obs_tr, y_tr = parts["tr"]["obs"], parts["tr"]["y"]
    obs_va, y_va = parts["va"]["obs"], parts["va"]["y"]
    n_tr, n_va = len(obs_tr), len(obs_va)

    # standardization reference: 5000 training flights at sigma=10 mm
    ref = rng.choice(n_tr, size=min(5000, n_tr), replace=False)
    sig_ref = rng.uniform(.001, .020, len(ref))
    obs_ref = obs_tr[ref] + rng.normal(size=obs_tr[ref].shape) * sig_ref[:, None, None]
    X_ref = np.nan_to_num(make_inputs(spec["input"], obs_ref, sig_ref),
                          nan=0.0, posinf=0.0, neginf=0.0)
    Y_ref = make_target(spec["target"], y_tr[ref], obs_ref)
    ok_ref = np.isfinite(Y_ref).all(1)
    X_ref, Y_ref = X_ref[ok_ref], Y_ref[ok_ref]
    st = standardize_fit(X_ref, Y_ref)
    xm, xs = torch.tensor(st["xm"], dtype=torch.float32), torch.tensor(st["xs"], dtype=torch.float32)
    ym, ys = torch.tensor(st["ym"], dtype=torch.float32), torch.tensor(st["ys"], dtype=torch.float32)

    # fixed validation noise for a comparable curve
    sig_va = rng.uniform(.001, .020, n_va)
    obs_va_n = obs_va + rng.normal(size=obs_va.shape) * sig_va[:, None, None]
    Xva_raw = np.nan_to_num(make_inputs(spec["input"], obs_va_n, sig_va),
                            nan=0.0, posinf=0.0, neginf=0.0)
    Yva_raw = make_target(spec["target"], y_va, obs_va_n)
    ok_va = np.isfinite(Yva_raw).all(1)
    Xva = torch.tensor((Xva_raw[ok_va] - st["xm"]) / st["xs"], dtype=torch.float32)
    Yva = torch.tensor((Yva_raw[ok_va] - st["ym"]) / st["ys"], dtype=torch.float32)

    model = build_mdn(X_ref.shape[1], k=K, hidden=HIDDEN, depth=DEPTH)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCHS)
    n_params = sum(p.numel() for p in model.parameters())
    history = []
    t0 = time.perf_counter()
    for epoch in range(EPOCHS):
        perm = rng.permutation(n_tr)
        model.train()
        total, seen = 0.0, 0
        for start in range(0, n_tr, BATCH):
            b = perm[start:start + BATCH]
            sig = rng.uniform(.001, .020, len(b))
            obs_b = obs_tr[b] + rng.normal(size=obs_tr[b].shape) * sig[:, None, None]
            X = np.nan_to_num((make_inputs(spec["input"], obs_b, sig) - st["xm"]) / st["xs"],
                              nan=0.0, posinf=0.0, neginf=0.0)
            Y = (make_target(spec["target"], y_tr[b], obs_b) - st["ym"]) / st["ys"]
            ok = np.isfinite(Y).all(1)
            if not ok.all():
                X, Y = X[ok], Y[ok]
            if len(X) == 0:
                continue
            xb = torch.tensor(X, dtype=torch.float32)
            yb = torch.tensor(Y, dtype=torch.float32)
            opt.zero_grad()
            loss = -model(xb).log_prob(yb).mean()
            if not torch.isfinite(loss):
                raise RuntimeError(f"nonfinite loss arm={arm} seed={seed} epoch={epoch}")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 10.0)
            opt.step()
            total += float(loss.detach()) * len(b)
            seen += len(b)
        sched.step()
        model.eval()
        with torch.no_grad():
            val = float(-model(Xva).log_prob(Yva).mean()) + float(np.log(st["ys"]).sum())
        history.append(dict(epoch=epoch + 1, train_nll=total / seen, val_nll_phys=val))
        if verbose and (epoch + 1) % 20 == 0:
            print(f"  {arm} seed{seed} epoch {epoch+1}/{EPOCHS} train {total/seen:.3f} val {val:.3f}",
                  flush=True)
    seconds = time.perf_counter() - t0
    return model, st, history, seconds, n_params


def evaluate(model, st, arm, parts, seed):
    spec = ARMS[arm]
    obs_te, y_te = parts["te"]["obs"], parts["te"]["y"]
    ym, ys = st["ym"], st["ys"]
    rows, per_sample = [], []
    with torch.no_grad():
        for sigma in LEVELS:
            rng = np.random.default_rng(9100 + int(sigma * 1e6))  # same noise for all arms/seeds
            noisy = obs_te + rng.normal(size=obs_te.shape) * sigma
            base = baseline_endpoint(noisy)
            bad = ~np.isfinite(base).all(axis=1)
            base = np.where(np.isfinite(base), base, 0.0)
            errs, pgs, cov50, cov95, a50, a95, nll, energy = [], [], [], [], [], [], [], []
            for j in range(0, len(noisy), 512):
                sl = slice(j, j + 512)
                X = np.nan_to_num((make_inputs(spec["input"], noisy[sl], sigma) - st["xm"]) / st["xs"],
                                  nan=0.0, posinf=0.0, neginf=0.0)
                dist = model(torch.tensor(X, dtype=torch.float32))
                pred_std = dist.mean.numpy()
                pred = pred_std * ys + ym
                if spec["target"] == "res":
                    pred = pred + base[sl]
                errs.append(np.linalg.norm(pred - y_te[sl], axis=1))
                y_std = (y_te[sl] - ym) / ys
                if spec["target"] == "res":
                    y_std = y_std - base[sl] / ys
                met = evaluate_distribution(dist, y_std, st, spec["target"], base[sl], GOAL)
                pgs.append(met["p_goal"])
                cov50.append(met["coverage"][0.5])
                cov95.append(met["coverage"][0.95])
                a50.append(met["area"][0.5])
                a95.append(met["area"][0.95])
                nll.append(met["nll"])
                energy.append(met["energy"])
            err = np.concatenate(errs)
            p_goal = np.concatenate(pgs)
            goal_true = ((np.abs(y_te[:, 0]) < GOAL[0]) & (y_te[:, 1] > GOAL[1])
                         & (y_te[:, 1] < GOAL[2])).astype(float)
            summary = summarize_errors(err, p_goal, goal_true)
            row = dict(arm=arm, seed=seed, sigma_m=sigma,
                       baseline_invalid=int(bad.sum()),
                       coverage50=float(np.concatenate(cov50).mean()),
                       coverage95=float(np.concatenate(cov95).mean()),
                       area50=float(np.concatenate(a50).mean()),
                       area95=float(np.concatenate(a95).mean()),
                       nll=float(np.concatenate(nll).mean()),
                       energy=float(np.concatenate(energy).mean()), **summary)
            rows.append(row)
            if abs(sigma - .005) < 1e-12:
                per_sample = err
    return rows, per_sample


def main():
    torch.set_num_threads(4)
    OUT.mkdir(parents=True, exist_ok=True)
    CKPT.mkdir(parents=True, exist_ok=True)
    d, parts = load()
    print("splits", {k: len(v["idx"]) for k, v in parts.items()}, flush=True)

    all_rows, curves, paired = [], [], []
    for arm in "ABCDE":
        for seed in SEEDS:
            model, st, hist, seconds, n_params = train_one(arm, seed, parts)
            torch.save(dict(state=model.state_dict(), stats=st, arm=arm, seed=seed,
                            input_dim=len(st["xm"]), k=K, hidden=HIDDEN, depth=DEPTH),
                       CKPT / f"{arm}_{seed}.pt")
            rows, per_sample = evaluate(model, st, arm, parts, seed)
            for r in rows:
                r.update(train_seconds=seconds, n_params=n_params)
            all_rows.extend(rows)
            curves.extend([dict(arm=arm, seed=seed, **h) for h in hist])
            paired.append(dict(arm=arm, seed=seed, errors=per_sample))
            print(f"done {arm} seed{seed} ({seconds:.1f}s, {n_params} params): "
                  f"5mm median {rows[1]['median']:.3f} cov50 {rows[1]['coverage50']:.3f}",
                  flush=True)
            dump(OUT / "ablation_progress.json", all_rows)

    # ---- summaries (pure python; no pandas dependency)
    import csv

    def write_csv(path, rows):
        rows = list(rows)
        if not rows:
            return
        fields = list(rows[0].keys())
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    write_csv(OUT / "ablation_runs.csv", all_rows)

    agg_rows = []
    for arm in "ABCDE":
        for sigma in LEVELS:
            rs = [r for r in all_rows
                  if r["arm"] == arm and abs(r["sigma_m"] - sigma) < 1e-12]
            row = dict(arm=arm, sigma_m=sigma, n=len(rs))
            for key in ("median", "p90", "coverage50", "coverage95", "area50",
                        "area95", "nll", "energy", "goal_ece", "train_seconds"):
                vals = np.array([r[key] for r in rs], float)
                row[f"{key}_mean"] = float(vals.mean())
                row[f"{key}_std"] = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
            agg_rows.append(row)
    write_csv(OUT / "ablation_summary.csv", agg_rows)

    def series(arm, key):
        xs, ys, es = [], [], []
        for sigma in LEVELS:
            row = next(r for r in agg_rows
                       if r["arm"] == arm and r["sigma_m"] == sigma)
            xs.append(sigma * 1e3)
            ys.append(row[f"{key}_mean"])
            es.append(row[f"{key}_std"])
        return np.array(xs), np.array(ys), np.array(es)

    # paired differences vs arm A at 5 mm
    base = {r["seed"]: r["errors"] for r in paired if r["arm"] == "A"}
    pair_rows = []
    for r in paired:
        if r["arm"] == "A":
            continue
        ea, eb = base[r["seed"]], r["errors"]
        diff = eb - ea
        pair_rows.append(dict(arm=r["arm"], seed=r["seed"],
                              median_delta_vs_A=float(np.median(diff)),
                              mean_delta_vs_A=float(diff.mean()),
                              frac_improved=float((diff < 0).mean()),
                              median_abs=float(np.median(eb)),
                              median_A=float(np.median(ea))))
    write_csv(OUT / "ablation_paired_5mm.csv", pair_rows)
    write_csv(OUT / "ablation_curves.csv", curves)

    # ---- figures
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4))
    for arm in "ABCDE":
        x, y, e = series(arm, "median")
        ax.errorbar(x, y, yerr=e, marker="o", capsize=3,
                    label=f"{arm}: {ARMS[arm]['label']}")
    ax.set(xlabel="position noise sigma (mm)", ylabel="median endpoint error (m)",
           title="P0 five-arm ablation (3 seeds)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "figures" / "ablation_median.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    for arm in "ABCDE":
        x, y, _ = series(arm, "coverage50")
        ax[0].plot(x, y, "o-", label=arm)
        x, y, _ = series(arm, "coverage95")
        ax[1].plot(x, y, "s-", label=arm)
    ax[0].axhline(.5, ls="--", c="gray", lw=.8)
    ax[1].axhline(.95, ls="--", c="gray", lw=.8)
    ax[0].set(xlabel="sigma (mm)", ylabel="empirical coverage", title="50% region")
    ax[1].set(xlabel="sigma (mm)", ylabel="empirical coverage", title="95% region")
    ax[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "figures" / "ablation_coverage.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    for arm in "ABCDE":
        x, y, _ = series(arm, "nll")
        ax.plot(x, y, "o-", label=arm)
    ax.set(xlabel="sigma (mm)", ylabel="mean NLL (physical units)",
           title="P0 five-arm ablation: NLL")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "figures" / "ablation_nll.png", dpi=160)
    plt.close(fig)

    dump(OUT / "ablation.json", dict(
        config=dict(epochs=EPOCHS, batch=BATCH, lr=LR, k=K, hidden=HIDDEN, depth=DEPTH,
                    seeds=SEEDS, noise="U(1,20) mm per sample per epoch",
                    target_note="residual arms subtract constant-acceleration endpoint "
                                "computed from the same noisy observations",
                    test_split="split==2, status==1, 4187 flights"),
        runs=all_rows, summary=agg_rows, paired_5mm=pair_rows))
    print("wrote", OUT / "ablation_summary.csv")


if __name__ == "__main__":
    main()
