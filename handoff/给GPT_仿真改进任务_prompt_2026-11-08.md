# 给 GPT / Codex 的仿真改进任务书（2026-11-08）

把下面两个 Prompt 分别粘给有额度的 GPT（Codex）。它们是**两个独立工作流**，可分开跑；
共同约束写在最前面，两个 Prompt 都假设 GPT 已经读过共同约束。

---

## 0. 共同背景与硬约束（先读，两个任务都适用）

你是 UPC155 仓库的 coding agent，在台式机上有 Codex/GPT 额度。仓库：`https://github.com/blind-shrimp/UPC155`。
当前状态（2026-11-08 晚）：

- 论文由 C 负责，**交稿前冻结**：不要修改 `论文模板/` 下任何文件、不要替换 P1 主结果、不要重编译提交版 PDF。
- 新仿真集（anchored prior）已在本机复现并审计完，结论已定：
  - 复现：`data.npz` SHA-256 = `00cb3e8199eb21bb57ce5b90e2400810d269255ef8ac1070701b6e9be07a3295`；训练指标逐位复现（5 mm fresh median 28.18 cm，frozen P1 29.71 cm）。
  - 审计：**同分布/同来源变好，但真实 Asai 留出回放没有提升**。关键数字：no-Asai 模型真实 Asai 回放 59.17 / 57.58 / 69.08 cm，冻结 P1 54.49 / 49.87 / 59.57 cm；all-anchor 模型 24.04 / 29.89 / 30.87 cm 是**回顾性泄漏**（三条试次参与了先验拟合）。
  - LOTO：同一实验内留一试次可外推（28.9 / 38.0 / 33.3 cm），但这是同源最近邻，不代表跨来源泛化。
  - 因此：**不要把 anchored 模型在仿真 hold-out 上的提升写成泛化提升**。
- 必读文档（仓库内）：
  - `student_b/sim2real/README.md`（复现 + 审计协议与结果）
  - `student_b/runs/sim2real/audit/README.md`、`.../LOTO.md`（迁移矩阵、真实回放）
  - `handoff/点球实测数据渠道与行动_2026-11-08.md`（数据渠道与邮件草稿）
  - `handoff/台式机_anchored仿真重训_任务书_2026-11-08.md`（已有台式机任务）
  - `student_b/sim2real/` 下的 `build_data.py`、`train.py`、`make_holdout.py`、`eval_matrix.py`
- 工作方式：
  1. 新开分支：`sim/v2-physics-data`（从 `sim/anchored-prior-audit` 或最新 `main` 拉出），提交脚本/报告/小型指标；
     **不要提交 `data.npz`、`*.pt`、原始大文件**（`.gitignore` 已忽略 `*.npz` 和 `student_b/runs/**/*.pt`）。
  2. 所有改进必须是**可关闭的可选参数**，默认行为与现有 P1/仿真一致；先跑现有测试（`python -m unittest discover -s student_b`）。
  3. 任何“更好”的结论必须给出**留出来源/留出试次**的证据；被评估的真实轨迹不得进入先验拟合。先把数据分为
     “prior set（可用于拟合先验）”与“sealed evaluation set（只用于评估）”，写入 manifest 后再开始实验；sealed set 一旦冻结不得回调。
  4. 记录所有 AI 使用（提问 + 完整输出）到本地；提交前需要并入 AI 使用披露（C 那边的 `ai-report-team.tex`/重跑
     `tools/build_ai_report.ps1`）。**你可以把本次会话导出成文件放在 `handoff/`，但不得含身份信息。**
  5. 任何数据下载/使用都要核对许可证（DFL=CC BY 4.0；SkillCorner/StatsBomb/SoccerNet 各有条款；不要把受限原始数据推到公开仓库）。
  6. 环境：Windows + Python（NumPy/SciPy/PyTorch/openpyxl；`C:/Users/pc/miniconda3/envs/mujoco/python.exe` 或
     仓库根 `.venv`；Asai 工作簿在 `handoff/asai_workbooks_2026-11-08/`，可作为 `--asai-dir`）。
  7. 完成后：提交到分支并推送；在 `handoff/` 写一份 ≤2 页的中文/英文结果报告（直接给结论和数字，不要只列过程）。

---

## Prompt Ⓐ — 获取新的独立真实轨迹（DFL 全部 Penalty + 公开点球数据）

### 目标

为“仿真是否真的更好”提供**未参与任何先验拟合的真实轨迹**。当前 20 条实测轨迹全部用于了 anchored 先验，
所以真实留出只能来自**新数据**。本任务不训练模型，只做数据获取、筛选、文档与 sealed split。

### A1. DFL 全部 Penalty 事件（优先，最快产出）

数据来源：Bassek et al. 2025《An integrated dataset of spatiotemporal and event data in elite soccer》
（Scientific Data，CC BY 4.0），数据集 DOI `10.6084/m9.figshare.28196177.v1`；
论文 DOI `10.1038/s41597-025-04505-y`。三场球的 position 文件下载入口：
`J03WMX` https://ndownloader.figshare.com/files/51643514 ，`J03WOH` .../51643520 ，`J03WR9` .../51643532
（event XML 来自同一数据集；A 的机器上也有本地 `raw/dfl/` 三份 XML 和 `B_standard_ball_trajectories/processed/` 三份半场 CSV）。

步骤：

1. 定位/取得原始数据：优先找 A 要本地 `raw/dfl/*.xml` 与完整半场球轨迹 CSV；如果拿不到，从 figshare 数据集页下载三份 position XML（完整文件，不是尾段字节）。
2. 复用并放宽现有筛选脚本：`student-a/additional_flight_data_2026-11-07/extract.py` 与 `screen_quality.py`（后者当前会剔除 Penalty 邻近片段——本任务**专门要** Penalty）。
   - 从 event XML 解析所有 `Penalty` 事件（以及 `ShotAtGoal` 中的点球，若事件层级能区分）；
   - 对每个 Penalty 事件取事件时刻前后 ±1.0–1.5 s 的 BALL 帧，抽出 `(x,y,z,t)`，保留连续、有限、离地高度合理的帧；
   - 不要求“前三点是离脚时刻”——记录首帧相对事件的时间偏移与高度，供后续对齐；不要用未来帧做任何拟合。
3. 去重与标记：与现有 `student-a/flight_trajectory_validation_2026-11-07` 的 2 场点球按事件/时间/哈希去重。
   **已经被用作 anchored 锚点的 2 场点球不能再算“独立留出”**；新抽到的其他 Penalty 才是 sealed evaluation 候选。
4. 输出目录：`student-a/penalty_all_2026-11-08/`，包含：
   - `positions.csv`（case_id, t_s, x_m, y_m, z_m, frame, event_time_offset, phase=prior/sealed）；
   - `events.csv`（每事件一行：match, event_id, period, timestamp, 是否已用于 prior）；
   - `README.md`（来源、许可、提取窗口、筛选规则、每事件质量、不可用于主表的理由）；
   - `manifest.json`（源文件 SHA-256、事件计数、sealed/prior 划分、去重记录）；
   - `extract_penalties.py`（可复现脚本）。
5. 给出一个明确的“可评估”子集：至少 2 个**新** Penalty（不是既有锚点），每个至少覆盖 0–0.2 s 或能对 11 m 平面插值；若不足，如实写“新增 sealed 数据不足”。

### A2. 公开点球/球轨迹数据（按可得性排序）

1. **SkillCorner Open Data**（10 场法甲，转播跟踪，球 x,y 10 Hz + 事件；免费）
   https://github.com/SkillCorner/opendata
   - 解析事件，找 penalty；抽每个点球的球轨迹（2D）。
   - 产出：`student_b/runs/data_channels/skillcorner/`：点球清单、球 2D 轨迹、README（许可、字段、只能做横向 Y 校验，无 z/无自旋）。
2. **StatsBomb Open Data**（多赛事事件数据，点球射门有 goal-plane `end_location`；免费）
   https://github.com/statsbomb/open-data
   - 抽取所有 `Shot` 且 `shot.type.name == "Penalty"` 的 `end_location`（Y,Z 球门平面坐标），按赛事统计入框率、Y/Z 分布。
   - 产出：`student_b/runs/data_channels/statsbomb/`：罚球终点分布、入框率、样本量、README（无轨迹，只做总体先验/校准对照）。
3. **SoccerNet-v3D**（转播重建 3D 球轨迹；需 SoccerNet 注册/NDA，可能数天）
   论文：CVPRW 2025，https://openaccess.thecvf.com/content/CVPR2025W/CVSPORTS/papers/Gutierrez-Perez_SoccerNet-v3D_Leveraging_Sports_Broadcast_Replays_for_3D_Scene_Understanding_CVPRW_2025_paper.pdf
   - 申请访问；若当天能下载，抽 free-kick/penalty 类 3D 球轨迹；否则只写申请记录与后续步骤。
4. **ball3d / 单目 3D 球轨迹数据**（备用；https://github.com/lukaszgrad/ball3d）
   - 检查 DATA.md 的许可与规模；能快速下载就抽可用样本，否则记录原因。
5. **PFF 2022 World Cup enhanced dataset**（论文已引用，商业/学术授权）
   - 只做一次正式的学术数据请求邮件；记录发送时间与答复；不要反复申请。

### A3. 协议与报告（重要）

- 在 `handoff/真实数据_sealed_protocol_2026-11-08.md` 里先定义：
  - `prior set`：可用于拟合先验的真实轨迹（现有 20 条 + 新增的非评估来源）；
  - `sealed evaluation set`：只用于最终评估的真实轨迹（新增的 DFL Penalty、SkillCorner/StatsBomb 校验集等）；
  - 任何模型训练/超参选择都不得触碰 sealed set。
- 报告：`handoff/真实数据获取报告_2026-11-08.md`，含：每个渠道拿到了什么、字段、许可、样本量、能回答什么问题、
  以及“用这些数据能证明/不能证明什么”。不要夸大（SkillCorner 无高度、StatsBomb 无轨迹、SoccerNet 无自旋）。

### 交付清单 Ⓐ

- [ ] `student-a/penalty_all_2026-11-08/`（数据 + 脚本 + README + manifest）
- [ ] `student_b/runs/data_channels/{skillcorner,statsbomb,...}/`（小体积派生数据 + README）
- [ ] `handoff/真实数据_sealed_protocol_2026-11-08.md`
- [ ] `handoff/真实数据获取报告_2026-11-08.md`
- [ ] 分支 `sim/v2-physics-data` 推送；不提交原始大文件与受限数据。

---

## Prompt Ⓑ — 物理模型升级（Cd(v) 阻力危机、旋转轴、按来源噪声）

### 目标

不依赖“把待评估轨迹放进先验”，而是从**物理真实性**上改进仿真：
① 速度相关阻力系数 Cd(v)（drag crisis）；② 有物理意义的自旋轴先验；③ 按来源的真实观测噪声。
目标是让**没有见过该来源**的模型（no-Asai / prior-only 协议）在真实留出上变好，而不是只在同分布上变好。

### 共用实验协议（必须）

- 保留现有默认行为：所有新模型用可选参数开启（如 `Config(drag_model=...)`），关闭时 14 项单测与 P1 结果不变。
- 验证集：用 `student_b/sim2real/` 的 LOCO 协议——训练集排除 Asai / DFL penalty / ISSIA / 全部实测锚点，
  评估：held-out 来源真实回放（尤其 no-Asai 模型对三条真实 Asai：当前 59.2 / 57.6 / 69.1 cm；冻结 P1 54.5 / 49.9 / 59.6 cm）
  以及独立 held-out 仿真集（canonical / asai / dfl_penalty / issia / barber）。
- 参考目标：no-Asai 协议下真实 Asai 回放**至少**要优于当前 59.2/57.6/69.1，最好接近或优于冻结 P1；
  canonical held-out 不得明显变差（≤5%）。达不到就如实报告负结果，不要用 Asai 锚点模型（回顾性）充数。
- 新增单测：物理恒等式、零旋零升力、事件顺序、噪声模型可复现、Cd(v) 连续/有界、自旋轴采样可逆等。

### B1. Cd(v) 阻力危机（优先）

现状：`student_b/physics.py` 中 Cd 是每条轨迹的常数（先验 U[0.15,0.30]）；真实足球 Cd 随速度/Re 变化（drag crisis）。
文献：Asai & Seo 2013（SpringerPlus 2:171）、Goff et al. 2017（Eur. J. Phys. 38:044003）、Barber & Carré 2010；
先读这三篇的 Cd-v/Re 数据（论文表格或图数字化），给出**实现用的 Cd(v) 曲线**（分段线性/单调样条，附数据点与来源）。

步骤：

1. 在 `physics.py` 增加可选 `drag_model`：`"constant"`（默认，行为不变）与 `"cd_of_speed"`；`Config` 增加必要字段（默认不改）。
2. `theta[:,6]` 在 Cd(v) 模式下解释为“参考 Cd”（例如 v=25 m/s 基准），或增加一个形状参数；**明确写出参数化**，避免与旧特征含义混淆。
3. 验证：
   - 空气动力学恒等式/自由落体/零升力测试保持；
   - 用 `student_b/replay_asai_3kicks.py` 或 `student_b/sim2real` 的 full-track fit 对 20 条实测做全段拟合，
     比较 Cd(v) 与常数 Cd 的 full-track RMSE（现有 Asai 三球 1.49 / 1.77 / 1.63 cm，DFL 点球 1.48 / 4.06 cm）；
   - 训练新的 no-Asai 模型（`student_b/sim2real` 管线，同一 seed/epoch）并做真实 Asai 回放与 held-out 矩阵。
4. 产出：`student_b/runs/physics_v2/cd_speed/`（拟合表、RMSE 对比、LOCO 回放、README）；
   若 Cd(v) 不能改善真实留出，报告“物理升级未改变泛化”的原因分析（例如 23 m 弧线球速度区间对 Cd 不敏感）。

### B2. 自旋轴物理（次优先）

现状：`theta` 用 ω 三向量；先验各向同性 U[−60,60]³；anchored 锚点由位置拟合的“有效横向自旋”反推，Asai 只有转速幅值（rps）没有轴向；
三球旋转衰减极慢（拟合 τ≈20–625 s，基本可忽略），所以“自旋轴先验”比“自旋衰减”更值得做。

步骤：

1. 从 20 条实测的全段拟合结果（`student_b/runs/sim2real/.../data_manifest.json` 的 anchors theta）和 Asai rps 幅值，
   拟合一个**低维自旋轴分布**（例如轴向角 θ_axis ~ 以水平为主的分布 + 幅值 |ω| 与 rps 的对应），给出参数与物理依据；
   注意 n=20，不要过拟合；用文献（Asai 2007/2013、Goff 2010）做交叉检查。
2. 在 `physics.sample_prior` 或 anchored builder 中增加可选 `spin_axis_model`（默认旧行为）；
   验证：全段拟合 RMSE 不恶化；LOCO（no-Asai）真实回放是否改善；on-boundary/零旋案例保持正确。
3. 产出：`student_b/runs/physics_v2/spin_axis/` + README；报告用 self-consistency 与留出结果，不夸大 n=3。

### B3. 按来源的真实观测噪声模型（第三优先）

现状：训练时每条轨迹均匀抽 σ∈[1,10] mm 的各向同性高斯噪声；真实来源噪声不同（DFL 15 mm、ISSIA 30 mm 为假设，
Asai 10 mm 假设，Barber 为数字化误差；真实误差还可能相关/非各向同性）。

步骤：

1. 在数据生成/训练中加入可选 `noise_model`：按来源指定 σ（可先验或从数据估计），保留 σ 作为输入特征；
   训练时混合来源噪声；默认行为不变。
2. 验证：在 held-out 来源上（尤其真实 Asai 回放）检查 50%/95% 覆盖是否更接近名义值、NLL 是否改善；
   对比旧噪声模型；报告“噪声模型是否解释了 50% 覆盖偏低”。
3. 产出：`student_b/runs/physics_v2/noise_model/` + README；若无法证明改善，写清原因。

### 交付清单 Ⓑ

- [ ] `physics.py` 可选 `drag_model` / `spin_axis_model`（及噪声模型在数据/训练侧）默认关闭，行为与旧版一致
- [ ] 新增单测并全部通过（`python -m unittest discover -s student_b`）
- [ ] 每个子任务：拟合/RMSE 对比表、LOCO 矩阵与真实留出回放、README（结论 + 负结果也写）
- [ ] 分支 `sim/v2-physics-data` 推送；小型指标/配置/图提交，大文件忽略
- [ ] `handoff/物理升级报告_2026-11-08.md`：一段话结论 + 关键数字 + 是否值得进下一版仿真

---

## 附：两个 Prompt 共用的“完成后回传”格式

```
分支：sim/v2-physics-data
commit：
新增/修改文件：
运行命令：
关键结果（数字）：
  - 留出来源/试次：
  - 对比基线（冻结 P1 / 当前 anchored）：
结论（能证明什么、不能证明什么）：
失败/负结果：
AI 使用记录保存位置：
```

## 附：给用户的快捷使用说明

1. 在台式机 `git fetch && git checkout sim/anchored-prior-audit`（或最新 main），把本文件放在仓库 `handoff/`。
2. 先粘 **Prompt Ⓐ**（数据，优先，半天内可产出 DFL 全部 Penalty + SkillCorner/StatsBomb 派生数据）；
   再粘 **Prompt Ⓑ**（物理，可能 1–2 天；Cd(v) 先做）。
3. 两个任务都要求“留出协议”；**禁止**把 sealed evaluation 轨迹加入先验后再声称提升。
4. 结果回来后，交给 DSH 复核并决定是否值得进下一版仿真；目前论文冻结，所有结果属于赛后/下一轮资产。
5. 本次 GPT 会话的提问与完整输出务必保存，提交前并入 AI 使用披露（`论文模板/ai-report-team.tex` 或重跑 `tools/build_ai_report.ps1`）。
