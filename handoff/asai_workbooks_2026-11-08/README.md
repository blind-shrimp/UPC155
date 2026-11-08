# Asai 实测三球原始工作簿（2026-11-08 新增数据）

本目录保存 2026-11-08 由数据提供方转来的三条实测球轨迹工作簿，是 C 同学转交、A 同学在此前工作中使用过的同一批文件（sha256 与桌面原件一致）。它们用于：

- `student_b/runs/asai_replay/`：冻结正式 P1 的三球 100 Hz 复演；
- `student_b/runs/asai_factorial/`：2×3×2 因子对照（MAP vs MAP）；
- `student_b/runs/asai_transfer/`：方向先验外推 + MAP/后验估计量匹配（本次补跑）。

| 文件 | 试次 | 大小 | SHA-256 |
|---|---|---|---|
| `Fig3_Sample data 20261108.xlsx` | Fig. 3 | 28,897 B | `A10D7B7F…31ED2BA0` |
| `Sample 05 data 20261108.xlsx` | Sample 05 | 27,303 B | `7321410A…72F2088` |
| `Sample 12 data 20261108.xlsx` | Sample 12 | 28,564 B | `B6C7F4EE…52964BEBD9` |

## 来源与使用范围

- 测量来源：T. Asai, K. Kimachi, R. Liu, M. Koido, M. Nakayama, J. E. Goff, S. Hong,
  *Measurements of the Flight Trajectory of a Spinning Soccer Ball and the Magnus Force Acting on It*,
  **Proceedings 49**, 88 (2020), DOI 10.3390/proceedings2020049088（MDPI，CC BY 4.0）。
  工作簿由数据提供方（作者方）分享用于本项目，xlsx 为其导出格式。
- 只用于物理模型/估计量的**探索性对照**，不进入正式 P1 的训练、校准或主表；
  三条轨迹数量不足以估计点球总体准确率，也不能用于估计真实覆盖率。
- 读取方式：`student_b/experiments/asai_factorial.py` 的 `read_trial` / `student_b/replay_asai_3kicks.py`；
  需要 `openpyxl`（团队 `.venv` 已装）。原始数值不在仓库中二次导出。
