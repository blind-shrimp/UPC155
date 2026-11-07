# P0 — 测试集与实验证据（2026-11-07）

> 阶段：**P0**（todo.md 的 1.1–1.8 诊断 + 第 2 节 5-arm 特征/目标消融；`pi_res_mdn.py`
> 到位后补做 1.1/1.2/1.4 复核）。
> 快照提交：`81f9ce3`（权威代码与完整结果在 `student_b/experiments/`）。
> 状态：**开发结果，不是最终论文数字**；P1 校准/结构筛选后替换。

## 1. 冻结测试集（本目录最重要交付）

`data/test_canonical_4187.csv`：

| 项 | 值 |
|---|---|
| 条数 | **4,187**（canonical 50k 的 split==2、status==1、观测有限） |
| 生成 | `experiment.generate(n=50000, seed=42)`；事件数 41,733 空中 / 8,267 触地 |
| 列 | flight_id, source_index, split, status；θ=(vx,vy,vz,ωx,ωy,ωz,C_D)；r(0.05)、r(0.10) 各 3 维；落点 (Y,Z) |
| 观测 | **无噪声**；评估时加独立 N(0,σ²) |
| 噪声 seed | 模型/消融：σ=2/5/10/15 mm → 11100/14100/19100/24100；诊断旧 MDN：11000/14000/19000/24000 |
| 禁止 | 训练、调参、校准（这是封存测试集） |
| 校验 | 见 `test_canonical_4187_manifest.json` 的 SHA256 |

`data/export_test_set.py` 可复现导出；`manifest` 同时记录事件数，防止拿错数据。

## 2. 关键结论（P0）

1. **Arm C（physics16 → 绝对目标）最好**：5 mm median 0.294 m、NLL −0.15；
   A 为 0.309 / 0.07，B 为 0.307 / 0.14。C 在 5/10/15 mm 的 NLL 全部最低。
2. **残差目标不是主因**：B≈A；D 只在 2 mm 最好，15 mm 有 3% 轨迹 NLL>100（基线病态/无解）。
3. **PI-ResMDN 复核**：原脚本 5 mm median 0.377（它自己的基线 0.412）、50% 覆盖 64.1%、
   案例 95% 面积 13.1 m²；canonical 公平重训后 0.424 / NLL 1.08，配对仅 31% 优于 A、27% 优于 C。
   **“<0.05 m”不成立**。
4. **双 simulator 差 0.240 m RMS、80% 轨迹 >5 cm**（主因 C_L 律）；两套数字不能同表。
5. **50% 覆盖在所有模型上漂移 45–64%** → P1 先做 per-σ 校准，再谈结构。

## 3. 文件索引

| 路径 | 内容 |
|---|---|
| `data/test_canonical_4187.csv` | 冻结测试集（4,187 行） |
| `data/test_canonical_4187_manifest.json` | 口径、事件数、噪声 seed、SHA256 |
| `data/export_test_set.py` | 从 `student_b/runs/canonical50k/data.npz` 重新导出 |
| `report/P0_report.md` | 完整 P0 报告（§6 为 PI-ResMDN 复核） |
| `report/P0_summary.md` | 一页纸摘要（给队内/论文用） |
| `report/diagnostics.json` / `.md` | 基线残差、特征条件数、混合权重、旧 MDN 指标 |
| `report/ablation_summary.csv` | 5 arm × 4 σ × 3 seeds 均值/标准差 |
| `report/ablation_runs.csv` | 15 runs 的逐条明细 |
| `report/ablation_paired_5mm.csv` | 5 mm 配对差 vs Arm A |
| `report/nll_tails.json` | 15 mm 逐样本 NLL 尾部 |
| `report/simulator_diff.md` / `.json` | 1,000 组 θ 的双 simulator 对比 |
| `report/pi_canonical_runs_e150.csv` | PI-ResMDN 在 canonical 上的重训结果 |
| `report/paired_PI_vs_AC_5mm.csv` | PI vs A/C 的配对比较 |
| `report/pi_feature_diag.json` | 上传脚本实际 16 维特征的条件数/共线/cd_app 相关 |
| `report/figures/*.png` | 消融 NLL/median/coverage、残差、特征相关、PI 案例热图 |
| `tables/tab_p0_*.tex` | booktabs 表：消融 median/NLL/coverage、残差、特征、PI 复核 |
| `code/make_latex_tables.py` | 从 `student_b/experiments/results` 重新生成上述 .tex |

## 4. 复现

```powershell
# 1) 50k canonical 数据（若本机没有 runs/canonical50k/data.npz）
cd student_b
python -c "from pathlib import Path; import experiment; experiment.generate(Path('runs/canonical50k'),50000,42)"

# 2) P0 诊断 + 五臂消融（需 torch；见 student_b/experiments/CONFIG.md）
$py = 'E:\SJTU2026\threebody\upc155-venv\Scripts\python.exe'
& $py experiments/diagnostics.py
& $py experiments/ablation.py

# 3) PI-ResMDN 复核
& $py experiments/simulator_diff.py
$env:PI_EPOCHS='150'; & $py experiments/pi_res_canonical.py
& $py experiments/paired_pi.py

# 4) 导出测试集 / 生成 LaTeX 表
python student-c/P0/data/export_test_set.py
python student-c/P0/code/make_latex_tables.py
```

## 5. 使用限制

- 全部数字来自**同一 canonical simulator 的仿真数据**（不是真实点球）；真实点球只有
  B 目前的两个 DFL 案例。
- `physics16` 是本仓库按 `pi_res_mdn.py` 描述重建的特征（v, a, a−g, speed, a_par,
  |a_perp|, cd_app, cl_app, T, σ），与上传脚本的 16 维（r1,r2,v/30,a_par/20,a_perp/20,
  cd_app,t_const,σ）**不是同一组**；两组都病态（条件数 ~4×10¹²）。
- 49%/95% 区域是 HDR，不是 ±1.96σ 椭圆；覆盖率是仿真留出集上的经验值。
- 门框概率是“球心到达矩形”的条件概率，不是进球/碰撞概率。
