# P0 diagnostics (todo.md 1.1-1.8)

- data: `runs\canonical50k\data.npz` n=50000, valid airborne=41733, test=4187
- legacy MDN checkpoint: `runs\literature50k\mdn.pt`

## 1.5 baseline residual (truth - constant acceleration)

- n=4187 invalid=0; median |r|=0.090 m, p90=0.203 m, p99=0.356 m
- dY mean/std=-0.000/0.099 m; dZ mean/std=0.025/0.080 m; corr=0.033
- |r|>0.5 m: 0.2%, |r|>1 m: 0.0%

## 1.4 legacy MDN on the same test set

| sigma | median err | p90 | 50% cov | 95% cov | area50 | area95 | NLL |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2 mm | 0.165 | 0.441 | 57.2% | 98.1% | 0.159 | 0.742 | -1.055 |
| 5 mm | 0.322 | 0.698 | 51.6% | 96.4% | 0.428 | 1.890 | 0.205 |
| 10 mm | 0.479 | 0.923 | 53.3% | 97.9% | 0.851 | 3.480 | 0.893 |
| 15 mm | 0.553 | 1.003 | 46.5% | 97.1% | 0.945 | 3.459 | 1.077 |

## 1.8 mixture weights (sigma=5 mm)

- mean pi = ['0.120', '0.121', '0.759']; mean max pi=0.768; frac(max pi>0.9)=33.7%; collapsed components=0

## 1.6 feature condition (16-dim reconstruction)

| sigma | cond(std corr) | max abs corr | cd_app corr(true) | cl_app corr(true) |
|---|---:|---:|---:|---:|
| 2 mm | 5095266649234.2 | 1.000 (ax/aa_x) | 0.654 | 0.834 |
| 5 mm | 4440610198235.5 | 1.000 (ay/aa_y) | 0.326 | 0.498 |
| 10 mm | 4094854121945.5 | 1.000 (ax/aa_x) | 0.176 | 0.284 |
| 15 mm | 4088634966707.8 | 1.000 (ax/aa_x) | 0.114 | 0.204 |

## Blocked

- 1.1/1.2/1.4 PI-ResMDN column: **pi_res_mdn.py was not found in the repository, the working directory, Documents, Downloads or Desktop on this machine.**

Figures: `figures/baseline_residuals.png`, `figures/feature_correlation_5mm.png`, `figures/coverage_vs_sigma_legacy.png`
