"""P0 1.2: reproduce pi_res_mdn.py's simulator and diff it against canonical physics.py.

The uploaded script samples theta internally, so this module re-implements its
RK4/force law exactly (lines 95-170 of pi_res_mdn.py) with theta as an argument.
Four variants isolate the known differences: density, C_L law, spin decay/gain.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SB = HERE.parent
sys.path.insert(0, str(SB))

import physics as canonical  # noqa: E402

G, R, M, X_GOAL = 9.81, 0.11, 0.43, 11.0
AREA = np.pi * R**2
OUT = HERE / "results"


def pi_res_sim(theta, rho=1.225, cl_law="sat", tau=None, gain=1.0,
               dt=0.0025, max_steps=280, s_definition="full", sin_factor=True):
    """Vectorised replica of pi_res_mdn.generate_physics_dataset's integrator.

    s_definition="full" uses |omega|/|v| (the uploaded script); "transverse"
    uses |omega x v|/|v|^2 (canonical physics.py). sin_factor=True keeps the
    uploaded script's |v|^2*sin(theta) Magnus magnitude.
    """
    theta = np.asarray(theta, float)
    n = len(theta)
    pref = 0.5 * rho * AREA / M
    r = np.zeros((n, 3))
    r[:, 2] = R
    v = theta[:, :3].copy()
    omega0 = theta[:, 3:6].copy()
    cd = theta[:, 6].copy()
    tau_v = np.full(n, np.inf) if tau is None else np.broadcast_to(np.asarray(tau, float), (n,))
    gain_v = np.broadcast_to(np.asarray(gain, float), (n,))
    crossed = np.zeros(n, bool)
    grounded = np.zeros(n, bool)
    yz = np.full((n, 2), np.nan)
    obs = np.full((n, 2, 3), np.nan)
    step05 = int(round(0.05 / dt))
    step10 = int(round(0.10 / dt))
    g_vec = np.array([0.0, 0.0, -G])

    def accel(vel, t):
        speed = np.linalg.norm(vel, axis=1, keepdims=True) + 1e-8
        decay = np.exp(-t / tau_v)[:, None]
        om = omega0 * decay
        om_norm = np.linalg.norm(om, axis=1, keepdims=True) + 1e-8
        cross = np.cross(om, vel)
        cross_norm = np.linalg.norm(cross, axis=1, keepdims=True) + 1e-8
        if s_definition == "full":
            s = R * om_norm / speed
        else:
            s = R * cross_norm / speed**2
        if cl_law == "sat":
            cl = gain_v[:, None] * (0.38 * s / (0.18 + s))
        elif cl_law == "canonical":
            cl = gain_v[:, None] * np.minimum(1.4 * s, 0.30)
        else:
            raise ValueError(cl_law)
        a_drag = -pref * cd[:, None] * speed * vel
        mag_scale = speed * (cross_norm / om_norm) if sin_factor else speed**2 * np.ones_like(speed)
        a_mag = pref * cl * mag_scale * (cross / cross_norm)
        return g_vec + a_drag + a_mag

    for step in range(1, max_steps + 1):
        t = (step - 1) * dt
        r_prev = r.copy()
        k1r, k1v = v, accel(v, t)
        k2r, k2v = v + 0.5 * dt * k1v, accel(v + 0.5 * dt * k1v, t + 0.5 * dt)
        k3r, k3v = v + 0.5 * dt * k2v, accel(v + 0.5 * dt * k2v, t + 0.5 * dt)
        k4r, k4v = v + dt * k3v, accel(v + dt * k3v, t + dt)
        r = r + (dt / 6) * (k1r + 2 * k2r + 2 * k3r + k4r)
        v = v + (dt / 6) * (k1v + 2 * k2v + 2 * k3v + k4v)
        if step == step05:
            obs[:, 0] = r
        elif step == step10:
            obs[:, 1] = r
        newly_ground = (~crossed) & (r[:, 2] <= R)
        grounded |= newly_ground
        newly_cross = ((~crossed) & (~grounded) & (r_prev[:, 0] < X_GOAL)
                       & (r[:, 0] >= X_GOAL))
        if np.any(newly_cross):
            alpha = (X_GOAL - r_prev[newly_cross, 0]) / (
                r[newly_cross, 0] - r_prev[newly_cross, 0] + 1e-12)
            interp = r_prev[newly_cross] + alpha[:, None] * (r[newly_cross] - r_prev[newly_cross])
            ok = interp[:, 2] > R
            idx = np.where(newly_cross)[0]
            crossed[idx[ok]] = True
            yz[idx[ok]] = interp[ok, 1:3]
            grounded[idx[~ok]] = True
    return dict(obs=obs, endpoint=yz, status=np.where(crossed, 1, np.where(grounded, 2, 0)),
                arrival=None)


def metrics(a, b, mask):
    d = a[mask] - b[mask]
    norm = np.linalg.norm(d, axis=-1)
    return dict(n=int(mask.sum()), rms=float(np.sqrt(np.mean(norm**2))),
                mean=float(norm.mean()), max=float(norm.max()),
                p95=float(np.quantile(norm, .95)),
                frac_gt_5cm=float((norm > .05).mean()),
                frac_gt_10cm=float((norm > .10).mean()))


def main():
    rng = np.random.default_rng(20261107)
    n = 1000
    theta = np.column_stack([
        rng.uniform(20.0, 33.5, n), rng.uniform(-10.5, 10.5, n),
        rng.uniform(1.5, 9.5, n), np.clip(rng.normal(0, 12, n), -60, 60),
        rng.uniform(-35, 35, n), rng.uniform(-75, 75, n), rng.uniform(.15, .30, n),
    ])
    tau = rng.uniform(.8, 2.5, n)
    gain = rng.uniform(.85, 1.15, n)

    ref = canonical.simulate(theta, canonical.Config(dt=.002))
    variants = {
        "V0c_exact_law_dt2ms": pi_res_sim(theta, rho=1.20, cl_law="canonical",
                                           dt=.002, s_definition="transverse", sin_factor=False),
        "V0d_exact_law_dt2.5ms": pi_res_sim(theta, rho=1.20, cl_law="canonical",
                                             dt=.0025, s_definition="transverse", sin_factor=False),
        "V0_theirS_canonicalCL": pi_res_sim(theta, rho=1.20, cl_law="canonical", dt=.0025),
        "V1_plus_rho1.225": pi_res_sim(theta, rho=1.225, cl_law="canonical", dt=.0025),
        "V2_plus_saturating_CL": pi_res_sim(theta, rho=1.20, cl_law="sat", dt=.0025),
        "V3_full_typical": pi_res_sim(theta, rho=1.225, cl_law="sat", tau=tau, gain=gain,
                                      dt=.0025),
    }
    out = dict(n_theta=n, theta_sampling="vx U(20,33.5), vy U(-10.5,10.5), "
               "vz U(1.5,9.5), wx N(0,12) clipped, wy U(-35,35), wz U(-75,75), "
               "Cd U(0.15,0.30); tau U(0.8,2.5), gain U(0.85,1.15) only used in V3")
    ref_ok = ref["status"] == 1
    out["canonical_valid"] = int(ref_ok.sum())
    for name, sim in variants.items():
        ok = ref_ok & (sim["status"] == 1) & np.isfinite(sim["obs"]).all(axis=(1, 2))
        out[name] = dict(
            both_valid=int(ok.sum()),
            status_mismatch=int((ref_ok != (sim["status"] == 1)).sum()),
            r005=metrics(ref["observations"], sim["obs"], ok),
            r010=metrics(ref["observations"][:, 1], sim["obs"][:, 1], ok),
            endpoint=metrics(ref["endpoint"], sim["endpoint"], ok),
        )
        print(name, "endpoint rms", round(out[name]["endpoint"]["rms"], 4),
              "max", round(out[name]["endpoint"]["max"], 3),
              ">5cm", round(out[name]["endpoint"]["frac_gt_5cm"] * 100, 1), "%", flush=True)

    OUT.mkdir(exist_ok=True)
    (OUT / "simulator_diff.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    lines = ["# P0 1.2 simulator diff (1,000 common theta)\n",
             f"- canonical valid: {out['canonical_valid']}/1000",
             "",
             "| variant | both valid | r(0.05) RMS | r(0.10) RMS | endpoint RMS | endpoint max | >5 cm |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for name in variants:
        r = out[name]
        lines.append(f"| {name} | {r['both_valid']} | {r['r005']['rms']:.4f} | "
                     f"{r['r010']['rms']:.4f} | {r['endpoint']['rms']:.4f} | "
                     f"{r['endpoint']['max']:.3f} | {r['endpoint']['frac_gt_5cm']*100:.1f}% |")
    lines.append("\n读数：V0 是同一物理律换积分器的数值差；V1 加密度；V2 加 C_L 律；"
                 "V3 再加自旋衰减/升力增益（真实生成器）。")
    (OUT / "simulator_diff.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("written", OUT / "simulator_diff.json")


if __name__ == "__main__":
    main()
