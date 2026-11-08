"""Case-study statistics used in Sections 3.1 and the decomposition appendix.

Outputs
  1. calibrated MDN marginal quantiles, in-frame / above-bar probabilities
     for seeds 11, 22, 33 at 5 mm;
  2. Z profile at fixed Y = 2.62 m: number of local maxima per seed;
  3. physics posterior (saved weighted samples) quantiles, correlations,
     upper-tail diagnostics;
  4. three representative trajectories from the saved posterior samples,
     re-integrated with student_b/physics.py.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]          # inner UPC155 repository
OUTER = REPO.parent                                 # holds _web_export
sys.path.insert(0, str(OUTER / "_web_export"))
sys.path.insert(0, str(REPO / "student_b"))

import ref  # noqa: E402
import physics  # noqa: E402
from scipy.special import ndtr  # noqa: E402

CASE = np.array([[0.0, 0.0, 0.11], [1.50, 0.45, 0.44], [2.96, 0.86, 0.74]])
GOAL = ref.GOAL
CFG = json.loads((ref.P1 / "best_config.json").read_text(encoding="utf-8"))


def mixture_quantiles(comps, axis, qs):
    """Quantiles of the marginal of a bivariate Gaussian mixture."""
    p, means, Lm = comps
    sd = np.abs(Lm[:, axis, 0]) if axis == 0 else np.hypot(Lm[:, 1, 0], Lm[:, 1, 1])
    mu = means[:, axis]

    def cdf(x):
        return float(np.sum(p * ndtr((x - mu) / sd)))

    out = []
    for q in qs:
        lo, hi = mu.min() - 12 * sd.max(), mu.max() + 12 * sd.max()
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if cdf(mid) < q:
                lo = mid
            else:
                hi = mid
        out.append(0.5 * (lo + hi))
    return out


def tail_prob(comps, axis, x, above=True):
    p, means, Lm = comps
    sd = np.abs(Lm[:, axis, 0]) if axis == 0 else np.hypot(Lm[:, 1, 0], Lm[:, 1, 1])
    mu = means[:, axis]
    z = (x - mu) / sd
    return float(np.sum(p * (ndtr(-z) if above else ndtr(z))))


def profile_peaks(comps, y0, zlo=1.30, zhi=2.75, n=3000):
    z = np.linspace(zlo, zhi, n)
    d = ref.density(comps, np.full((1, n), y0), z[None, :])[0]
    peaks = [z[i] for i in range(1, n - 1)
             if d[i] > d[i - 1] and d[i] > d[i + 1]]
    # merge peaks closer than 0.05 m (numerical wiggles)
    merged = []
    for zz in peaks:
        if not merged or zz - merged[-1] > 0.05:
            merged.append(zz)
    return [round(float(v), 2) for v in merged]


def marginal_z_peaks(comps, n=4000):
    z = np.linspace(0.9, 3.1, n)
    # marginal density: mixture of normals
    p, means, Lm = comps
    sd = np.hypot(Lm[:, 1, 0], Lm[:, 1, 1])
    d = np.zeros_like(z)
    for k in range(len(p)):
        d += p[k] * np.exp(-0.5 * ((z - means[k, 1]) / sd[k]) ** 2) / (math.sqrt(2 * math.pi) * sd[k])
    peaks = [z[i] for i in range(1, n - 1) if d[i] > d[i - 1] and d[i] > d[i + 1]]
    merged = []
    for zz in peaks:
        if not merged or zz - merged[-1] > 0.05:
            merged.append(zz)
    return [round(float(v), 2) for v in merged]


def responsibility(comps, y, z):
    p, means, Lm = comps
    dens = np.zeros(len(p))
    for k in range(len(p)):
        l00, l10, l11 = Lm[k, 0, 0], Lm[k, 1, 0], Lm[k, 1, 1]
        det = l00 * l11
        i00, i01, i11 = (l10**2 + l11**2) / det**2, -l00 * l10 / det**2, l00**2 / det**2
        dy, dz = y - means[k, 0], z - means[k, 1]
        q = i00 * dy**2 + 2 * i01 * dy * dz + i11 * dz**2
        dens[k] = p[k] * np.exp(-0.5 * q) / (2 * math.pi * det)
    return dens / dens.sum()


def main():
    report = {}
    print("== MDN, 5 mm, calibrated ==")
    report["mdn"] = {}
    for seed in (11, 22, 33):
        comps, _ = ref.predict(seed, CASE, 5, True, CFG)
        qy = mixture_quantiles(comps, 0, [0.05, 0.5, 0.95])
        qz = mixture_quantiles(comps, 1, [0.05, 0.5, 0.95])
        p_in = ref.p_inside(comps, (-GOAL[0], GOAL[0], GOAL[1], GOAL[2]))
        p_above = tail_prob(comps, 1, GOAL[2], True)
        p_wide = tail_prob(comps, 0, GOAL[0], True) + tail_prob(comps, 0, -GOAL[0], False)
        prof = profile_peaks(comps, 2.62)
        marg = marginal_z_peaks(comps)
        report["mdn"][seed] = dict(
            y_q=[round(v, 3) for v in qy], z_q=[round(v, 3) for v in qz],
            y_width=round(qy[2] - qy[0], 3), z_width=round(qz[2] - qz[0], 3),
            p_in=round(p_in, 4), p_above=round(p_above, 4), p_wide=round(p_wide, 4),
            profile_peaks=prof, marginal_z_peaks=marg,
            weights=[round(v, 3) for v in comps[0]])
        print(f"seed {seed}: Y 5/50/95 {np.round(qy,3)} width {qy[2]-qy[0]:.3f} | "
              f"Z 5/50/95 {np.round(qz,3)} width {qz[2]-qz[0]:.3f}")
        print(f"        P(in) {p_in:.4f}  P(above) {p_above:.4f}  P(wide) {p_wide:.5f}")
        print(f"        peaks at Y=2.62: {prof} ; marginal-Z peaks: {marg}")

    print("\n== physics posterior ==")
    d = np.load(OUTER / "_web_export" / "posterior_case.npz")
    y, z, w, th = d["y"], d["z"], d["w"], d["theta"]
    w = w / w.sum()

    def wq(x, qs):
        idx = np.argsort(x)
        xs, ws = x[idx], w[idx]
        c = np.cumsum(ws) / ws.sum()
        return np.round([np.interp(q, c, xs) for q in qs], 3)

    def wm(x, m=None):
        m = np.ones(len(x), bool) if m is None else m
        return float((w[m] * x[m]).sum() / w[m].sum())

    def wcorr(a, b):
        aa = a - wm(a)
        bb = b - wm(b)
        return float((w * aa * bb).sum() / math.sqrt((w * aa * aa).sum() * (w * bb * bb).sum()))

    omy, omz = th[:, 4], th[:, 5]
    report["physics"] = dict(
        n=int(len(w)),
        y_q=[float(v) for v in wq(y, [0.05, 0.5, 0.95])],
        z_q=[float(v) for v in wq(z, [0.05, 0.5, 0.95])],
        p_above=float(w[z > GOAL[2]].sum()), p_wide=float(w[np.abs(y) > GOAL[0]].sum()),
        corr_wy_wz=round(wcorr(omy, omz), 3), corr_wy_z=round(wcorr(omy, z), 3),
        corr_wz_y=round(wcorr(omz, y), 3), corr_cd_y=round(wcorr(th[:, 6], y), 3),
        left_tail_wz55=float(w[(y < 2.45) & (np.abs(omz) > 55)].sum() / w[y < 2.45].sum()),
        left_tail_abs_w55=float(w[(y < 2.45) & (np.linalg.norm(th[:, 3:6], axis=1) > 55)].sum() / w[y < 2.45].sum()),
    )
    print("Y 5/50/95", report["physics"]["y_q"], "width",
          round(report["physics"]["y_q"][2] - report["physics"]["y_q"][0], 3))
    print("Z 5/50/95", report["physics"]["z_q"], "width",
          round(report["physics"]["z_q"][2] - report["physics"]["z_q"][0], 3))
    print("P(above)", round(report["physics"]["p_above"], 4),
          "P(wide)", round(report["physics"]["p_wide"], 5))
    print("corr(wy,wz)", report["physics"]["corr_wy_wz"],
          "corr(wy,Z)", report["physics"]["corr_wy_z"],
          "corr(wz,Y)", report["physics"]["corr_wz_y"])
    print("left tail (y<2.45): share with |wz|>55 =", round(report["physics"]["left_tail_wz55"], 3),
          "| share with |omega|>55 =", round(report["physics"]["left_tail_abs_w55"], 3))

    print("\n== representative trajectories ==")
    report["traj"] = {}
    for idx in (6953, 2827, 18017):
        theta = th[idx][None, :]
        res = physics.simulate(theta, physics.Config())
        obs = res["observations"][0]
        rmse = float(np.sqrt(np.mean((obs - CASE[1:]) ** 2)))
        endpoint = res["endpoint"][0]
        arrival = float(res["arrival"][0])
        # integrate to 0.05 s and read the acceleration decomposition there
        cfg = physics.Config()
        state = np.zeros((1, 6)); state[0, 2] = cfg.radius; state[0, 3:] = theta[:, :3]
        t = 0.0
        while t < 0.05 - 1e-12:
            h = min(cfg.dt, 0.05 - t)
            state = physics.rk4(state, theta, t, h, cfg)
            t += h
        v = state[0, 3:]
        u = v.copy()
        speed = float(np.linalg.norm(u))
        omega = theta[0, 3:6]
        cross = np.cross(omega, u)
        norm = float(np.linalg.norm(cross))
        S = cfg.radius * norm / speed**2
        cl = min(1.4 * S, 0.30)
        k = cfg.density * math.pi * cfg.radius**2 / (2 * cfg.mass)
        direction = cross / norm
        lift = k * cl * speed**2 * direction
        drag = -k * theta[0, 6] * speed * u
        resp = responsibility(ref.predict(11, CASE, 5, True, CFG)[0], endpoint[0], endpoint[1])
        report["traj"][int(idx)] = dict(
            rmse_mm=round(rmse * 1e3, 2), endpoint=[round(float(v), 3) for v in endpoint],
            arrival=round(arrival, 4), status=int(res["status"][0]),
            cd=round(float(theta[0, 6]), 3),
            omega=[round(float(v), 1) for v in omega],
            lift=[round(float(v), 2) for v in lift],
            lift_z=round(float(lift[2]), 2), drag_z=round(float(drag[2]), 2),
            cl=round(float(cl), 3), S=round(float(S), 3),
            resp=[round(float(v), 3) for v in resp])
        print(f"idx {idx}: early RMSE {rmse*1e3:.2f} mm -> crossing "
              f"({endpoint[0]:.3f}, {endpoint[1]:.3f}) at t={arrival:.3f}, "
              f"Cd={theta[0,6]:.3f}, omega={np.round(omega,1)}")
        print(f"        a_Magnus = {np.round(lift,2)} (z {lift[2]:+.2f}), "
              f"S={S:.3f}, CL={cl:.3f}, responsibility {np.round(resp,2)}")

    (Path(__file__).resolve().parent / "case_stats.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

