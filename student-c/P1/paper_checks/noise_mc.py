"""Monte-Carlo propagation of the two observation errors into the
constant-acceleration crossing, for the stated UPC 2026 Problem B kick.

Inputs (task statement):
    r(0)    = (0.00, 0.00, 0.11) m   exact
    r(0.05) = (1.50, 0.45, 0.44) m   independent Gaussian, sd = sigma
    r(0.10) = (2.96, 0.86, 0.74) m   independent Gaussian, sd = sigma

Method: finite-difference velocity at 0.05 s and acceleration from the three
points, then solve x(T) = 11 m exactly (smallest root with tau > 0) and
evaluate (Y, Z) at T = 0.05 + tau.  A draw is discarded when the quadratic has
no positive root, when T exceeds the 1.5 s horizon, or when the ball centre
would be below R before the goal plane (ground hit).

Also reports the origin-mismatch variant that evaluates the displacement over
T instead of tau = T - 0.05; that variant reproduces the 0.41 m figure in the
A-to-B handoff table.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

DT = 0.05
R0 = np.array([0.0, 0.0, 0.11])
R1 = np.array([1.50, 0.45, 0.44])
R2 = np.array([2.96, 0.86, 0.74])
RADIUS = 0.11
HORIZON = 1.5
N = 150_000
SEED = 20261108

OUT = Path(__file__).resolve().parent


def crossing(r1, r2):
    """Return (tau, Y, Z, ok_with_tau, Y_mismatch, Z_mismatch)."""
    v = (r2 - R0) / (2 * DT)
    a = (r2 - 2 * r1 + R0) / DT**2
    vx, ax = v[:, 0], a[:, 0]
    x1 = r1[:, 0]
    tau = np.full(len(vx), np.nan)
    small = np.abs(ax) < 1e-9
    tau[small] = (11.0 - x1[small]) / np.maximum(vx[small], 1e-9)
    disc = vx**2 - 2 * ax * (x1 - 11.0)
    ok = (~small) & (disc >= 0)
    sq = np.sqrt(np.maximum(disc, 0.0))
    # roots of 0.5 ax tau^2 + vx tau + (x1-11) = 0
    with np.errstate(divide="ignore", invalid="ignore"):
        t1 = (-vx + sq) / ax
        t2 = (-vx - sq) / ax
    cand = np.where((t1 > 0) & ok, t1, np.inf)
    cand = np.minimum(cand, np.where((t2 > 0) & ok, t2, np.inf))
    tau[ok] = cand[ok]
    T = DT + tau
    Y = r1[:, 1] + v[:, 1] * tau + 0.5 * a[:, 1] * tau**2
    Z = r1[:, 2] + v[:, 2] * tau + 0.5 * a[:, 2] * tau**2
    # ground hit before the plane (ball centre at R)
    valid = np.isfinite(tau) & np.isfinite(T) & (T > DT) & (T <= HORIZON) & (Z > RADIUS)
    reason = np.zeros(len(tau), np.int8)          # 0 valid
    no_root = ~np.isfinite(tau)
    reason[no_root] = 1                           # discriminant < 0 or no root > 0
    reason[~no_root & (T > HORIZON)] = 2          # beyond horizon
    reason[~no_root & (T <= HORIZON) & (Z <= RADIUS)] = 3   # ground hit first
    # variant with the wrong time origin: displacement measured over T
    Ym = r1[:, 1] + v[:, 1] * T + 0.5 * a[:, 1] * T**2
    Zm2 = r1[:, 2] + v[:, 2] * T + 0.5 * a[:, 2] * T**2
    return dict(tau=tau, T=T, Y=Y, Z=Z, valid=valid, reason=reason, Ym=Ym, Zm=Zm2, v=v, a=a)


def stats(x):
    q = np.percentile(x, [5, 50, 95])
    return dict(sd=float(np.std(x, ddof=1)), q05=float(q[0]), q50=float(q[1]), q95=float(q[2]))


def main():
    rng = np.random.default_rng(SEED)
    out = {"seed": SEED, "n_draws": N, "levels": {}}
    for mm in (2, 5, 15):
        sig = mm / 1000.0
        eps1 = rng.normal(0.0, sig, (N, 3))
        eps2 = rng.normal(0.0, sig, (N, 3))
        r1 = R1 + eps1
        r2 = R2 + eps2
        c = crossing(r1, r2)
        m = c["valid"]
        n_invalid = int((~m).sum())
        d = {k: stats(c[k][m]) for k in ("T", "Y", "Z")}
        d["n_valid"] = int(m.sum())
        d["n_invalid"] = n_invalid
        d["invalid_reasons"] = {int(k): int(v) for k, v in
                                zip(*np.unique(c["reason"][~m], return_counts=True))}
        tau_mean = float(np.mean(c["tau"][m]))
        d["closed_form_half_sa_T2"] = float(0.5 * np.sqrt(5) * sig / DT**2 * 0.4048**2)
        d["closed_form_half_sa_tau2"] = float(0.5 * np.sqrt(5) * sig / DT**2 * tau_mean**2)
        d["mismatch"] = {k: stats(c[k][m]) for k in ("Ym", "Zm")}
        out["levels"][str(mm)] = d
        print(f"\n--- sigma = {mm} mm ---")
        print(f"valid {d['n_valid']} / {N}, discarded {n_invalid}")
        print(f"sd(T) = {d['T']['sd']*1e3:.1f} ms, sd(Y) = {d['Y']['sd']:.3f} m, "
              f"sd(Z) = {d['Z']['sd']:.3f} m")
        print(f"Y 5-95% = [{d['Y']['q05']:.2f}, {d['Y']['q95']:.2f}], "
              f"Z 5-95% = [{d['Z']['q05']:.2f}, {d['Z']['q95']:.2f}]")
        print(f"closed form 0.5 sa T^2 = {d['closed_form_half_sa_T2']:.3f} m, "
              f"with tau = {d['closed_form_half_sa_tau2']:.3f} m")
        print(f"origin-mismatch variant: sd(Y) = {d['mismatch']['Ym']['sd']:.3f}, "
              f"sd(Z) = {d['mismatch']['Zm']['sd']:.3f}")
    (OUT / "noise_mc.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()


