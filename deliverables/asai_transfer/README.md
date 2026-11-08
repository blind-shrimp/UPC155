# Asai 方向先验外推 + MAP/后验估计量匹配（实现、运行、结果入口）

**状态**：✅ 已运行完成（2026-11-08，458 s；6 项自检 + 归档复现 + 12 项契约测试全部通过）。
Codex 额度中断时只完成到脚本与自检（3 项自检失败后停机）；DSH 修复后跑完，完整结果与自动生成的中文报告在
[`../../student_b/runs/asai_transfer/README.md`](../../student_b/runs/asai_transfer/README.md)。

**一句话结论**：

- **方向先验不能外推**：外部 4 例（2 场 DFL 点球 + 2 段 ISSIA）留出帧 RMSE 为无先验 30.09 cm、手册方向先验 46.53 cm、pooled 43.50 cm；11 例补充 DFL 片段上平均略好但逐例混杂。Asai 上的 10.63 cm 是样本内正则化，不是通用物理先验。
- **估计量定义解释旧差距**：Asai 同模型/同先验/同边界/固定早期速度基下，MAP 8.55–13.32 cm，而后验均值 51–54 cm、KDE 众数 5.9–19.8 cm。旧表"手册 MAP ≈11.39 vs canonical 后验均值 ≈50–60"的差距很大一部分来自"MAP vs 后验均值"的定义差异。
- 归档复现检查通过：none 26.00 cm、manual 10.63 cm 与 factorial 归档一致（差 < 0.5 cm）。

## 这个实验回答什么

1. **方向先验能否外推**：在 Asai 三球上，手册式"幅值 + 带符号竖直分量"先验把平均 11 m 截面误差从 26.00 cm 降到 10.63 cm。
   现在把同一先验（以及从三球全段拟合得到的 pooled 先验）用到 **外部** DFL 点球与 ISSIA 片段上，看是否仍然有利。
   外部目标只用前 0/0.04/0.08 s（DFL，目标面用 case_config；ISSIA 25 fps 片段 + 假设 30 mm 噪声），
   参考值只用于打分；不做按留出结果反选先验。
2. **MAP vs 后验均值/众数**：在 Asai 三球上统一同一物理模型、同一 prior 密度（对 dc_vert dc_lat 测度）、
   同一状态边界、同一 σ 与同一**固定早期速度/基**，分别算潜变量 MAP、后验预测均值、KDE 众数；
   看旧的"手册 11.39 cm vs canonical 50–60 cm"差异有多少来自估计量定义。

## 运行

```powershell
# 需要 NumPy / SciPy / openpyxl（团队 .venv 已装）
F:\ChatGPT\upc\.venv\Scripts\python.exe student_b/experiments/asai_transfer.py --selftest
F:\ChatGPT\upc\.venv\Scripts\python.exe -m unittest deliverables.asai_transfer.test_asai_transfer -v
powershell -ExecutionPolicy Bypass -File deliverables/asai_transfer/run.ps1
```
默认输出：`student_b/runs/asai_transfer/`（`results_transfer.json`、`rows_transfer.csv`、
`results_estimators.json`、`checks.json`、`settings.json`、README.md）。

## 自检/契约测试（已通过）

- 6 项脚本内自检：代数一致性、未来帧不变性、对齐不变性、评分算术、端到端聚合、估计量管线。
- 12 项契约测试：上述 + 真实输入 schema（pooled 先验数值、2 场 DFL 点球、2 段 ISSIA、11 段补充 DFL）+ 未来帧不可见约束。
- 修复记录（DSH，2026-11-08）：
  1. `endpoint_draws` 在"本步未触地"时仍计算了负的 ground fraction，导致上升段过截面被误判为触地而丢弃（**真实数值 bug**，影响后验截面质量）；
  2. 对齐不变性自检的期望轨道应取 `align_track(世界轨道)`，不是原始世界轨道；
  3. 评分自检的 RMSE 期望值括号位置错误（先平方和再求和 vs 先按行求和再平方，后者在对称残差下恒为 0）。

## 口径与局限

- 外部样本 n=4（+11 段无目标面只评 RMSE）；Asai n=3，且三条轨迹此前都已看过 → 探索性，无独立测试。
- ISSIA 的 30 mm 是明确假设，不是标定；不能与 DFL 15 mm 横向比较。
- pooled 先验在 Asai 上是"样本内"参考，对 DFL/ISSIA 才是外部先验。
- 不评价概率校准/覆盖率；不调整正式 P1；不导出原始观测。
- 已知风险：free3 用 9 个残差拟合 8 个参数，c 的辨识较弱；MAP 可能落在平坦方向上（全部多起点分支写入 JSON）。
