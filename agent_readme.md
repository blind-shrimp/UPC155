# UPC155 协作进度

更新于 2026-11-08 13:10。论文数字、图表和方法以当前 P1 发布结果为准。历史方案与原始交接件可从 [研究工作总览与论文大纲](研究工作总览与论文大纲.md) 查找。

## 2026-11-08 13:10：提交版已就绪（待补队员 AI 记录）

- **提交文件**：[论文模板/155B.pdf](论文模板/155B.pdf)，73 页 = 英文正文 15 页 + AI 使用披露 58 页；每页页眉 Team 155；Summary 212 词（≤300）。
- **AI 使用披露（官方硬性要求）已完成主体**：[ai-report.tex](论文模板/ai-report.tex) 逐字收录 OpenAI ChatGPT/Codex（2 个会话）与 DeepSeek Harness（7 个会话）的 94 条原始提问和 202 段完整输出；日志处理见 [tools/ai_usage](tools/ai_usage/README.md)。
- **仍待补**：`论文模板/ai-report-team.tex` 目前是占位段落，需要 A/C 同学按"系统 + 原始提问 + 完整输出"补充其他 AI 工具记录（若没有则改成一句话声明）。
- **丢失风险已处理**：Codex 额度中断前未提交的本地工作（通用化 `physics.py` 接口、P1–P5/AsAI 实验脚本与运行结果）已备份并合并进 `main`（提交 `dbb2ded`），`main` 与远端同步。
- **最后检查**：提交前用 155B.pdf 核对首页四项、匿名信息、页眉、图表、引用与文件名，然后按官方规则邮件提交（截止北京时间 2026-11-09 09:00）。

## 2026-11-08 14:20：新数据（Asai 三球）分析完成，可交接

- **数据**：数据提供方转来的三份工作簿（Fig3 / Sample05 / Sample12）已收进 [handoff/asai_workbooks_2026-11-08](handoff/asai_workbooks_2026-11-08/README.md)（来源 Asai et al. 2020, CC BY 4.0；sha256 与桌面原件一致）。
- **冻结 P1 三球复演** ✅：[asai_replay](student_b/runs/asai_replay/README.md)。P1 高度平移后 11 m 虚拟截面误差 54.49 / 49.87 / 59.57 cm（Fig3 / Sample05 / Sample12）；canonical 物理后验 55.17 / 52.36 / 61.92 cm；全段回拟合 RMSE 0.20 / 1.12 / 0.65 cm。
- **2×3×2 因子对照** ✅：[asai_factorial](student_b/runs/asai_factorial/README.md)。12 组因子、672 次拟合：无先验 26.00 cm、仅幅值先验 22.30、**手册方向先验 10.63**、手册升力律 11.80、留一先验 22.45。**方向约束（带符号竖直分量）是主因，但先验中心是人工常数，不能当泛化提升**；Sample12 从 50.15 降到 23.37，另两球反而变差。
- **方向先验外推 + MAP/后验匹配** ✅（Codex 中断时未完成的部分，DSH 修复 3 个自检问题后跑完）：[asai_transfer](student_b/runs/asai_transfer/README.md)。
  - 外部 4 例（2 场 DFL 点球 + 2 段 ISSIA）留出帧 RMSE：无先验 **30.09** / 手册方向先验 46.53 / pooled 43.50 cm → **方向先验不能外推**，Asai 上的 10.63 属于样本内正则化，不能写成通用物理先验。
  - Asai 上同模型/同先验/同基：MAP 8.55–13.32 cm，但后验均值 51–54 cm、KDE 众数 5.9–19.8 cm → **旧表"手册 11.39 vs canonical 50–60"的差距很大一部分是估计量定义（MAP vs 后验均值）**；两条后验均值种子不稳定处已标出。
  - 归档复现检查通过（none 26.00、manual 10.63 与 factorial 一致，差 < 0.5 cm）；6 项自检 + 12 项契约测试全过。
- **论文正文未改**：以上属 exploratory/appendix-level 证据，是否写入 Appendix 由 C 决定；正式 P1、训练集、主表均未动。
- **换机继续跑**：见 [handoff/继续跑_交接包_2026-11-08.md](handoff/继续跑_交接包_2026-11-08.md)（环境、数据、命令、剩余待办、给下一个 AI 的启动 prompt、口径与坑）。
- **AI 披露提醒**：换机器继续与 AI 交互后，提交前重跑 `tools/build_ai_report.ps1`，并补 `论文模板/ai-report-team.tex`。

| 工作 | 当前结果与入口 |
|---|---|
| 物理仿真 | 使用重力、二次阻力和横向马格努斯力，RK4 主步长 2 ms。50,000 条中 41,733 空中过门，8,267 提前触地。[实际参数](student_b/params.json) |
| 台式机复现 | 14 项单测、256 条抽样重算通过。全量重建与交付数据 SHA-256 相同。[回传报告](handoff/台式机检验_2026-11-07/回传结果.md) |
| P0 消融 | 比较五种特征和目标组合。统一模拟器后重训 PI-ResMDN。2 mm 下物理残差有优势，高噪声下出现极低密度预测。[P0 报告](student-c/P0/report/P0_report.md) |
| P1 选型 | 11 个特征、3×128、GELU、LayerNorm、K=3 全协方差，直接预测过门坐标。特征、K、层数和激活均按验证集筛选。[冻结配置](student-c/P1/final/best_config.json) |
| P1 独立盲测 | 冻结后另生成 6,000 条，评分 5,036 条空中过门。5 mm 中位误差 0.290 m。四档校准后 50% / 95% 覆盖分别为 47.6–49.1% / 94.5–95.2%。[完整结果](student-c/P1/results.md) |
| 稳健性 | 3 m/s 横风和 0.5 s 自旋衰减均降低 5 mm 情景的 50% 区域覆盖。配对条件和事件变化另报。[压力测试](student-c/P1/final/robustness.csv) |
| 实测外推 | 已完成两次 DFL 点球的基线与旋转比较，并检查 ISSIA、Barber 和 11 段 DFL 比赛轨迹。属于逐案例物理外推。[两次点球](student_b/runs/real_penalties/实测点球外推结果.md) · [四例](student_b/runs/real_spin_final/旋转外推.md) · [11 段](student_b/runs/dfl_screened_spin/DFL旋转对照.md) |
| 论文 | 英文稿已同步 P1 主表、案例、偏移与实测结果，并已追加 AI 使用披露；提交版 155B.pdf 已生成，待补 Section C 队员记录后即可提交。[LaTeX](论文模板/main.tex) · [PDF](论文模板/155B.pdf) · [写作状态](论文模板/写作状态.md) |

## Asai 100 Hz 实测复演

[三球复演报告](student_b/runs/asai_replay/README.md)已补充到论文源码。冻结 P1 经首帧高度平移后，三条弧线球的 11 m 虚拟截面误差约为 50–60 cm。整段拟合和转速辅助作为回顾性诊断单列。仓库中的 main.pdf / 155B.pdf 已是最新编译版。

## 补充整合

[双线成果整合](handoff/2026-11-08-evidence/README.md)对照另一套题例实现，补充同参数仿真器核对、Arm C 开发复核、DFL 观测窗口和跨比赛迁移结果。论文主表继续使用正式 P1 独立盲测。

## 对齐口径

- P0 的 4,187 条是开发阶段测试集。正文主表使用 P1 的 5,036 条新样本。
- 案例的 97.3% 是已知球在空中过门时球心进入门框矩形的概率。贝叶斯参照为 96.3%。
- 仿真覆盖与实测案例误差分开引用。严格零旋和低于 18 m/s 的样本在原仿真先验中缺失。[覆盖审计](student_b/runs/coverage_audit/覆盖审计.md)

## 复现

从仓库根目录运行 [P1 脚本](student_b/experiments/run_p1.ps1)。完整模型对照所需的 P0 权重按 [P0 说明](student-c/P0/README.md) 复现。最终 P1 权重、数据种子和校准参数在 `student-c/P1/final/`。
