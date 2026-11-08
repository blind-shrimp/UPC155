"""Extra diagnostics for Appendix B: spin-cap share, marginal spin shares,
and the depth of the valley between the two profile maxima."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
OUTER = REPO.parent
sys.path.insert(0, str(OUTER / "_web_export"))
import ref  # noqa: E402

CASE = np.array([[0.0, 0.0, 0.11], [1.50, 0.45, 0.44], [2.96, 0.86, 0.74]])
CFG = json.loads((ref.P1 / "best_config.json").read_text(encoding="utf-8"))

d = np.load(OUTER / "_web_export" / "posterior_case.npz")
y, z, w, th = d["y"], d["z"], d["w"], d["theta"]
w = w / w.sum()
U = np.array([29.6, 8.6, 6.3])
speed = float(np.linalg.norm(U))
K = 1.20 * math.pi * 0.110**2 / (2 * 0.430)
cross = np.cross(th[:, 3:6], U)
cn = np.linalg.norm(cross, axis=1)
S = 0.110 * cn / speed**2
CL = np.minimum(1.4 * S, 0.30)
print("share at lift cap (CL=0.30):", round(float(w[CL >= 0.30 - 1e-12].sum()), 3))
print("share |wz|>55:", round(float(w[np.abs(th[:, 5]) > 55].sum()), 3))
print("share |w|>55:", round(float(w[np.linalg.norm(th[:, 3:6], axis=1) > 55].sum()), 3))
print("share |wz|>50:", round(float(w[np.abs(th[:, 5]) > 50].sum()), 3))

comps, _ = ref.predict(11, CASE, 5, True, CFG)
zz = np.linspace(1.5, 2.6, 4000)
prof = ref.density(comps, np.full((1, len(zz)), 2.62), zz[None, :])[0]
i1 = int(np.argmin(np.abs(zz - 1.86)))
i2 = int(np.argmin(np.abs(zz - 2.16)))
between = prof[i1:i2 + 1]
imin = int(np.argmin(between))
print("profile values at peaks:", round(float(prof[i1]), 4), round(float(prof[i2]), 4))
print("valley at z=", round(float(zz[i1 + imin]), 3), "value",
      round(float(between[imin]), 4),
      "depth rel. to larger peak:", round(1 - float(between[imin]) / max(prof[i1], prof[i2]), 3))
