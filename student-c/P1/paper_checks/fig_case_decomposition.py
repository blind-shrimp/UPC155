"""Figure for Section 3.1: MDN density, physics posterior coloured by the
vertical Magnus acceleration, and three representative trajectories.

Output: student-c/P1/final/figures/case_decomposition.png
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

REPO = Path(__file__).resolve().parents[3]
OUTER = REPO.parent
sys.path.insert(0, str(OUTER / "_web_export"))
sys.path.insert(0, str(REPO / "student_b"))

import ref  # noqa: E402
import physics  # noqa: E402

CASE = np.array([[0.0, 0.0, 0.11], [1.50, 0.45, 0.44], [2.96, 0.86, 0.74]])
CFG = json.loads((ref.P1 / "best_config.json").read_text(encoding="utf-8"))
GOAL = ref.GOAL

plt.rcParams.update({
    "font.size": 8.5, "axes.labelsize": 8.5, "axes.titlesize": 9,
    "legend.fontsize": 7.5, "xtick.labelsize": 8, "ytick.labelsize": 8,
    "axes.linewidth": 0.8, "savefig.dpi": 300,
})

comps, _ = ref.predict(11, CASE, 5, True, CFG)
p, means, Lm = comps

# ------------------------------------------------------------------ panel a
yg = np.linspace(2.15, 3.75, 340)
zg = np.linspace(1.30, 2.72, 300)
Y, Z = np.meshgrid(yg, zg)
dens = ref.density(comps, Y, Z)
flat = dens.ravel()
order = np.argsort(flat)[::-1]
cum = np.cumsum(flat[order]) / flat[order].sum()
levels = {q: flat[order][np.searchsorted(cum, m)] for q, m in
          ((0.50, 0.49609375), (0.95, 0.943359375))}

fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.9), layout="constrained",
                         gridspec_kw=dict(height_ratios=[1, 1]))

ax = axes[0, 0]
cf = ax.contourf(Y, Z, dens, levels=np.linspace(0, dens.max(), 33), cmap="magma",
                 norm=matplotlib.colors.PowerNorm(gamma=0.45, vmin=0, vmax=dens.max()))
ax.contour(Y, Z, dens, [levels[0.95]], colors=["#2ca9a0"], linewidths=[1.1])
ax.contour(Y, Z, dens, [levels[0.50]], colors=["w"], linewidths=[1.8])
ax.contour(Y, Z, dens, [levels[0.50]], colors=["0.2"], linewidths=[0.6])
mode = means[np.argmax(p)]
ax.plot(*mode, "+", color="w", ms=7, mew=1.2, zorder=5)
ax.axhline(GOAL[2], color="w", ls="--", lw=0.7, alpha=0.65)
ax.axvline(GOAL[0], color="w", ls="--", lw=0.7, alpha=0.65)
ax.set(xlim=yg[[0, -1]], ylim=zg[[0, -1]], xlabel="$Y$ (m)", ylabel="$Z$ (m)",
       title="(a) calibrated MDN density, $\\sigma=5$ mm")
ax.text(3.62, 2.50, "crossbar", color="w", fontsize=6.5, ha="right", rotation=90)
ax.text(3.62, 1.36, "post", color="w", fontsize=6.5, ha="right")
cb = fig.colorbar(cf, ax=ax, shrink=0.92)
cb.set_label("density (m$^{-2}$)")

# ------------------------------------------------------------------ panel b
d = np.load(OUTER / "_web_export" / "posterior_case.npz")
y, z, w, th = d["y"], d["z"], d["w"], d["theta"]
w = w / w.sum()
rng = np.random.default_rng(7)
idx = rng.choice(len(w), size=9000, replace=True, p=w)
ys, zs, oms, cds = y[idx], z[idx], th[idx, 3:6], th[idx, 6]

U = np.array([(2.96 - 0.0) / 0.1, (0.86 - 0.0) / 0.1, (0.74 - 0.11) / 0.1])
RHO, RAD, MASS = 1.20, 0.110, 0.430
K = RHO * math.pi * RAD**2 / (2 * MASS)
speed = float(np.linalg.norm(U))
cross = np.cross(oms, U)
cn = np.linalg.norm(cross, axis=1)
S = RAD * cn / speed**2
CL = np.minimum(1.4 * S, 0.30)
lift = K * (CL * speed**2)[:, None] * cross / np.maximum(cn[:, None], 1e-24)
lift_z = lift[:, 2]

ax = axes[0, 1]
sc = ax.scatter(ys, zs, c=lift_z, s=1.4, cmap="coolwarm", alpha=0.35,
                linewidths=0, vmin=-8, vmax=8)
ax.contour(Y, Z, dens, [levels[0.95]], colors=["#2ca9a0"], linewidths=[0.9])
ax.contour(Y, Z, dens, [levels[0.50]], colors=["#2ca9a0"], linewidths=[0.9], linestyles="--")
ax.axhline(GOAL[2], color="0.35", ls="--", lw=0.7)
ax.set(xlim=yg[[0, -1]], ylim=zg[[0, -1]], xlabel="$Y$ (m)", ylabel="$Z$ (m)",
       title="(b) physics posterior, coloured by vertical Magnus")
cb = fig.colorbar(sc, ax=ax, shrink=0.92)
cb.set_label("$a_{\\mathrm{M},z}$ at 0.05 s (m s$^{-2}$)")

# three representative trajectories
cfg = physics.Config()
labels = {6953: "A", 2827: "B", 18017: "C"}
offsets = {6953: (-13, -4), 2827: (7, 3), 18017: (8, -8)}
path_out = {}
for k, idx_t in enumerate((6953, 2827, 18017)):
    theta = th[idx_t][None, :]
    state = np.zeros((1, 6)); state[0, 2] = cfg.radius; state[0, 3:] = theta[:, :3]
    traj = [state[0, :3].copy()]
    t = 0.0
    active = True
    while active and t < 1.0:
        new = physics.rk4(state, theta, t, cfg.dt, cfg)
        if state[0, 0] < cfg.goal <= new[0, 0]:
            frac = (cfg.goal - state[0, 0]) / (new[0, 0] - state[0, 0])
            hit = state[0, :3] + frac * (new[0, :3] - state[0, :3])
            traj.append(hit)
            active = False
        else:
            traj.append(new[0, :3].copy())
        state = new
        t += cfg.dt
    path_out[idx_t] = np.array(traj)
    res = physics.simulate(theta, cfg)
    ep = res["endpoint"][0]
    ax.plot(ep[0], ep[1], "o", ms=5.5, mfc="w", mec="k", mew=0.9, zorder=6)
    ax.annotate(labels[idx_t], (ep[0], ep[1]), textcoords="offset points",
                xytext=offsets[idx_t], fontsize=8.5, fontweight="bold", zorder=7)
    axes[1, 0].plot(path_out[idx_t][:, 0], path_out[idx_t][:, 2], lw=1.4,
                    label=labels[idx_t])
    axes[1, 1].plot(path_out[idx_t][:, 0], path_out[idx_t][:, 1], lw=1.4,
                    label=labels[idx_t])

# ------------------------------------------------------------- panels c / d
for ax, k, lab in ((axes[1, 0], 2, "$Z$ (m)"), (axes[1, 1], 1, "$Y$ (m)")):
    ax.axvline(GOAL[0], color="0.4", ls="--", lw=0.8)
    for xmark in (1.50, 2.96):
        ax.axvline(xmark, color="0.6", ls=":", lw=0.7)
    ax.set_xlim(0, 11.4)
    ax.set_xlabel("$x$ (m)")
    ax.set_ylabel(lab)
    ax.legend(loc="lower right", frameon=False, title=None)

axes[1, 0].set_title("(c) vertical motion of A, B, C")
axes[1, 1].set_title("(d) lateral motion of A, B, C")

out = REPO / "student-c" / "P1" / "final" / "figures" / "case_decomposition.png"
fig.savefig(out)
print("saved", out)


