# P0 code — 本目录只放 C 线自有脚本

权威实验脚本不复制到这里，避免两份代码漂移。它们在 `student_b/experiments/`：

| 脚本 | 作用 |
|---|---|
| `diagnostics.py` | 1.1–1.8 诊断（数据、基线残差、旧 MDN、特征条件、混合权重） |
| `ablation.py` | 5-arm × 3 seeds 消融 |
| `common.py` | 特征、HDR、NLL、ECE 等共享实现 |
| `simulator_diff.py` | canonical vs `pi_res_mdn.py` 的 1,000 组 θ 对比 |
| `pi_res_canonical.py` | PI-ResMDN 在 canonical 数据上的公平重训 |
| `pi_feature_diag.py` | 上传脚本实际 16 维特征的条件数/共线诊断 |
| `paired_pi.py` | PI vs A/C 的 5 mm 配对比较 |
| `run_p0.ps1` | 一条命令复现诊断 + 消融 |

本目录的脚本：

| 脚本 | 作用 |
|---|---|
| `../data/export_test_set.py` | 从 `student_b/runs/canonical50k/data.npz` 导出冻结测试集 CSV + manifest |
| `make_latex_tables.py` | 从 `student_b/experiments/results` 生成 `../tables/*.tex` |

运行环境：Python 3.12 + torch 2.15 CPU（`E:\SJTU2026\threebody\upc155-venv`），
或按 `student_b/experiments/CONFIG.md` 自建。
