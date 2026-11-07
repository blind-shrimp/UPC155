# P0 1.2 simulator diff (1,000 common theta)

- canonical valid: 887/1000

| variant | both valid | r(0.05) RMS | r(0.10) RMS | endpoint RMS | endpoint max | >5 cm |
|---|---:|---:|---:|---:|---:|---:|
| V0c_exact_law_dt2ms | 818 | 0.0000 | 0.0000 | 0.0000 | 0.000 | 0.0% |
| V0d_exact_law_dt2.5ms | 887 | 0.0000 | 0.0000 | 0.0000 | 0.000 | 0.0% |
| V0_theirS_canonicalCL | 887 | 0.0014 | 0.0019 | 0.0356 | 0.277 | 9.9% |
| V1_plus_rho1.225 | 887 | 0.0014 | 0.0020 | 0.0314 | 0.259 | 6.3% |
| V2_plus_saturating_CL | 886 | 0.0090 | 0.0123 | 0.2178 | 0.464 | 75.2% |
| V3_full_typical | 885 | 0.0092 | 0.0126 | 0.2400 | 0.567 | 80.1% |

读数：V0 是同一物理律换积分器的数值差；V1 加密度；V2 加 C_L 律；V3 再加自旋衰减/升力增益（真实生成器）。
