# 成果清单（inventory）

**来源：** ① ChatGPT（Codex 模式）UPC 工作会话，2026-11-07 13:34–16:29（对话线程 `01a1b47f-ae53-7281-8123-c3e6234b5664`）；② 同一工作区 16:50–16:52 的 Codex 第二轮产出（A 第一轮回复处理、ISSIA 外推、回签）；③ **A→B 交接包 v2**（2026-11-07，A 交付）；④ 2026-11-07 17:00–17:25 的继续分析（A 自检用例落地、C_D 先验面积敏感性、ISSIA 净升力可辨识性检验）。
**原始工作区：** `F:\ChatGPT\upc`（= `C:\Users\pc\Documents\ChatGPT\upc` 的映射）
**导出方式：** 2026-11-07 由 B 同学使用 DSH 整理，原有文件逐字复制；新增根 `README.md`、本 `inventory.md`、根 `.gitignore`，以及第二轮分析脚本/报告（见 §B、§C、§J）。
**仓库规模：** 193 个文件（含队友上传的调研材料与论文模板），约 2.0 MB；其中 B 组产出 98 个（含 `handoff/` 19 个）。自动测试 **13/13 通过**。

> 注：本清单只覆盖 **B 组产出**（`UPC-B题-*.md`、`student_b/`、`data_sources/`）。仓库根目录下的 `UPC赛事调研报告.md`、`AB-资料总览.md`、`未命名.md`、`raw/`、`准备文档.xlsx`、`论文模板/` 由队友 `x1shang` 于 2026-11-07 16:39 上传，不计入本清单。

---

## A. 研究文档（仓库根目录，4 份）

| 文件 | 大小 | 内容 |
|---|---:|---|
| `UPC-B题-中文研究路线.md` | 20.2 KB | 主线研究路线修订版：题目再定义、由简到繁的模型体系、可辨识性/灵敏度分析、贝叶斯可靠性、对照与验证、写作建议 |
| `UPC-B题-高分作品因素与路线修订.md` | 9.6 KB | 2022 获奖论文与往届资料的复盘：高分作品共性、对原路线的 6 点修订、资料失实之处提示 |
| `UPC-B题-团队实验方案.md` | 7.8 KB | 可直接发队的实验方案：数据准备、仿真校准、数据生成、MDN、对照/消融、独立评价、分工与交付清单 |
| `UPC-B题-数据获取渠道与联系邮件.md` | 6.9 KB | 真实数据渠道（ISSIA-3D / ball3d / IDSSE）核查结果 + 两封英文申请邮件草稿（尚未发送） |

## B. 代码（`student_b/`，GPT 撰写、B 同学审查）

| 文件 | 大小 | 用途 |
|---|---:|---|
| `physics.py` | 4.7 KB | 批量 RK4 三维物理引擎：重力 + 二次阻力 + 横向旋转马格努斯力；穿越/触地事件；参数先验采样；恒加速度解析基线；`fixed_cl` 仅用于 A 自检用例 |
| `test_physics.py` | 1.8 KB | 解析退化（无气动时应回到抛体解）、阻力耗散、升力正交性、触地截断、步长收敛等 6 项检查 |
| `inference.py` | 3.8 KB | 物理约束贝叶斯重要性采样：四轮自适应提议、显式 p/q 校正、20% 先验混合、ESS 诊断；新增 `cd_upper`（先验上限敏感性） |
| `test_inference.py` | 1.1 KB | 已知截断高斯解析后验的采样正确性检查 |
| `experiment.py` | 11.8 KB | 数据生成、全协方差 MDN 训练/早停、覆盖率与 HDR 面积评测、案例输出；CLI：`generate/train/evaluate/case/smoke` |
| `validate.py` | 6.8 KB | 全新仿真样本上的恒加速度/MDN/物理推断对照（`benchmark`）与案例联合区域（`case`） |
| `screen_issia.py` | 3.6 KB | ISSIA-3D 连续空中片段筛选（有效坐标、相机数、帧连续性、水平位移、重投影误差） |
| `run_overnight.py` | 1.4 KB | 分阶段顺序批处理（generate→train→evaluate→case），阶段级落盘、可续跑、失败即停 |
| `test_selftest_case.py` | 6.5 KB | **A 自检用例的 6 项单元测试**（运动学、反演系数、基线 T/Y/Z、√5 噪声、常系数积分、升力方向约定） |
| `check_issia_arcs.py` | 2.4 KB | ISSIA 两段的零旋转 6 帧前缀外推对照（Codex 16:51） |
| `case_cd_prior.py` | 6.2 KB | 案例 C_D 先验上限敏感性：[0.15,0.30] vs [0.15,0.45] 的 50%/95% HDR 面积（3 seeds） |
| `fit_issia_cd_lift.py` | 6.4 KB | ISSIA 两段：加竖直净升力后的 (C_D, L) 可辨识性检验（含水平升力负对照） |
| `params.json` | 1.6 KB | **唯一有效参数表**（A→B 口径定稿 v2：参数、先验、划分、噪声、状态计数） |
| `selftest_case.json` | 3.0 KB | A 的自检用例机器可读版（测试直接 assert） |
| `requirements.txt` | 29 B | numpy / scipy / torch / matplotlib |
| `environment-freeze.txt` | 781 B | B 同学本机实际环境（Python 3.13 / numpy 2.5.4 / scipy 1.18.1 / torch 2.14.1+cpu） |

## C. B 组报告（`student_b/`，可直接发队）

| 文件 | 大小 | 内容 |
|---|---:|---|
| `README.md` | 3.9 KB | 代码归档说明、审查顺序、物理与统计约定、运行命令（**先读**） |
| `开发结果与待办.md` | 3.2 KB | 第一轮结果（旧参数，`pilot50k`）+ 待办顺序 |
| `气动参数更新结果.md` | 2.3 KB | 接入 A 提供气动参数后的重训结果（`literature50k`）与新旧模型对照 |
| `ISSIA筛选与仿真验证.md` | 4.1 KB | ISSIA 筛选结论、全新仿真样本三模型对照、题面案例联合区域 |
| `给A的回签与ISSIA外推结果.md` | 3.7 KB | **B→A 回签**（参数/坐标/触地/划分/噪声）+ 两段 ISSIA 外推表（Codex 16:52） |
| `给A的回复_第三轮.md` | 5.6 KB | **对本轮 A→B v2 的回复**：面积对比表、自检用例 §3 勘误、ISSIA (C_D,L) 结果、给 C 的四处同步 |
| `对A自检用例的核对.md` | 4.4 KB | A 自检用例 §3 升力方向约定的勘误与两种积分对照证据（常系数可拟合到 1.4/2.6 mm） |
| `ISSIA_CD_L拟合检验.md` | 4.6 KB | ISSIA 两段：竖直净升力 vs 水平升力、(C_D, L) 可辨识性、留出误差对比 |
| `审查清单.md` | 2.0 KB | 请 A/B 优先审查的公式、先验与指标问题；已解决的方案问题；下一轮必须补齐项 |

## D. 数据（`data_sources/` 与 `handoff/`）

| 文件 | 大小 | 说明 |
|---|---:|---|
| `data_sources/ISSIA-3D.csv` | 451.9 KB | SoccerNet-v3D 官方发布的 ISSIA-3D 标注（2,465 行，1,689 行有可用三维坐标）。来源 <https://github.com/mguti97/SoccerNet-v3D>（release v1.0.0）；仅转载标注文件，引用其论文并遵守发布条款。**尚未进入训练/校准/验证** |
| `handoff/A到B_v2_2026-11-07/` | 约 60 KB | **A 交付的交接包 v2**：口径定稿 v2、ISSIA 数据说明、仿真器自检用例（md + json）、5 问回签单、第一/二轮回复、`params_run_literature50k.json`、两段轨迹 CSV、相机标定、审计、校验和、`prepare_issia.py`（SHA256 已核对一致） |

> A 交接包中未入库的原始大表（`ISSIA-3D_raw.csv`，与 `data_sources/ISSIA-3D.csv` 同源同 sha256）及派生全表（`ISSIA_native_normalized.csv`、`ISSIA_valid_3d_only.csv`）可由 `handoff/A到B_v2_2026-11-07/data/prepare_issia.py` 从官方 release 复现。

## E. 实验结果（`student_b/runs/`，JSON/PNG/日志/模型权重共 50+ 个文件）

| 运行目录 | 内容 |
|---|---|
| `runs/dev/` | 最早 1 万条开发运行（旧参数）：训练记录、评测、案例 MDN 图、案例后验、跨种子审计 (`posterior_seed_audit.json`)、模型 `mdn.pt` |
| `runs/pilot50k/` | 第一轮 5 万条运行（旧参数）：3 种噪声水平覆盖率/面积、案例 MDN 图与后验、步级耗时 `pipeline.json`、日志、`mdn.pt` |
| `runs/literature50k/` | **接入 A 气动参数后的 5 万条重训（当前主结果）**：`evaluation.json`、新旧模型 `paired_comparison.json`、训练/生成/案例日志、案例图、`mdn.pt` |
| `runs/literature_cd022/` | 题面案例固定 `Cd = 0.22` 的贝叶斯后验数值 `case_posterior.json` |
| `runs/issia_screen/` | ISSIA 筛选统计 `screening.json` + 25 个候选片段逐帧表 `candidate_frames.csv` |
| `runs/fresh_validation/` | 全新仿真样本对照 `benchmark.json` / 逐条 `benchmark_rows.json`、案例联合区域数值 `case_regions.json` 与图 `case_regions.png` |
| `runs/issia_A/` | **A 两段轨迹（seg csv、审计）+ 零旋转外推 `arc_forecasts.json`** + 回签自检 `selftest_audit.json` + `drag_sensitivity.json` + **净升力拟合 `cd_lift_fit.json`** |
| `runs/case_cd_prior/` | **C_D 先验上限敏感性** `cd_prior_sensitivity.json` + 双先验等高线图 `cd_prior_contours.png` |

关键数值统一见仓库根 `README.md` §3；原始数值以各目录 JSON 为准。

## F. 未上传文件（11 个，约 18.5 MB）

以下为本机中间数据/数组，体积大且可由代码完整重新生成，故未放入仓库：

| 文件 | 大小 | 再生成方式 |
|---|---:|---|
| `runs/pilot50k/data.npz` | 5.71 MB | `python student_b/experiment.py generate --out student_b/runs/pilot50k` |
| `runs/pilot50k/case_posterior.npz` | 1.34 MB | `python student_b/experiment.py case --out student_b/runs/pilot50k` |
| `runs/pilot50k/case_mdn_samples.npy` | 313 KB | 同上（训练/案例流程） |
| `runs/literature50k/data.npz` | 5.70 MB | `python student_b/run_overnight.py --out student_b/runs/literature50k --n 50000 --epochs 150` |
| `runs/literature50k/case_posterior.npz` | 1.53 MB | 同上 |
| `runs/literature50k/case_mdn_samples.npy` | 313 KB | 同上 |
| `runs/literature_cd022/case_posterior.npz` | 1.54 MB | `python student_b/experiment.py case --out student_b/runs/literature_cd022 --n 30000 --cd 0.22` |
| `runs/dev/data.npz` | 1.14 MB | `python student_b/experiment.py smoke --out student_b/runs/dev --n 10000 --epochs 60` |
| `runs/dev/case_posterior.npz` | 610 KB | 同上 |
| `runs/dev/case_mdn_samples.npy` | 313 KB | 同上 |
| `student_b/.gitignore` | 19 B | 原始工作区本地忽略规则（忽略整个 `runs/`）。仓库改用根 `.gitignore`，以便共享结果文件 |
| `handoff/A到B_v2_2026-11-07/data/ISSIA-3D_raw.csv` | 451.9 KB | 与 `data_sources/ISSIA-3D.csv` 同源、同 sha256（`7f4b3306…`），不重复入库 |
| `handoff/A到B_v2_2026-11-07/data/ISSIA_native_normalized.csv` | 229.7 KB | 规范化全表，可由 `prepare_issia.py` 从原始表复现 |
| `handoff/A到B_v2_2026-11-07/data/ISSIA_valid_3d_only.csv` | 209.1 KB | 仅 1,689 个有效 3D 帧，可由 `prepare_issia.py` 复现 |

> 说明：`student_b/runs/*/mdn.pt`（26 KB/个）已上传，`validate.py` 默认从 `student_b/runs/literature50k/mdn.pt` 读取检查点，克隆后可直接复现案例与对照图。

## G. 对话中产出、但未落盘为文件的内容（摘要）

完整对话记录保存在 B 同学本机 ChatGPT 会话中（比赛要求保留原始提问与完整输出，用于论文 AI 使用披露；未放入公开仓库）。以下为对团队有意义的对话内产出：

1. **2022 年三篇获奖论文的差异分析**：它们做的是"如何踢/射到有利位置"的正问题，本题是"从早期观测反演"的反问题，只能借鉴气动力与数值积分框架，不能照搬系数与假设。
2. **对 `upc_b_48.md`（48 小时极限方案）的含金量评估**：框架强但证据未成熟；指出 6 处足以削弱可信度的问题——二维/三维轨迹数字化不成立、"马格努斯公式前后不一致"、"贝叶斯 MC 不能称精确基准/理论天花板"、噪声放大证明系数应为 √5/Δt² 且不能直接当病态性证明、毫米级舍入误差被低估等。**结论：按 GPT 修订后的保守路线执行更稳，48h 方案中的高调表述必须删除。**
3. **真实数据渠道核查**：ISSIA-3D 已下载并初检；ball3d 的三角测量参考轨迹需确认是否经物理拟合；IDSSE 25 fps 与 0.05/0.10 s 不对齐，需插值评估；两封申请邮件草稿已备好但未发送。
4. **每轮开发说明**（物理引擎 6 项检查、第一轮 MDN 结果、气动参数接入后的新旧对照、ISSIA 坐标方向纠正、案例联合区域补齐等）已分别沉淀到 C 节报告与 `runs/` 结果文件。
5. **给队友的同步消息模板**：已整理进根 `README.md` §4，可直接粘贴到群里。

## H. 校验

- 单元测试：在仓库根运行 `python -m unittest discover -s student_b -v` → **Ran 13 tests, OK**（原有 7 项 + A 自检用例 6 项，约 0.7 s）。
- 复现检查：`check_issia_arcs.py` 重跑结果与 Codex `runs/issia_A/arc_forecasts.json` 完全一致；`case_cd_prior.py` 的 [0.15,0.30] seed=8047 结果（0.219/0.808 m²）与已发布 `runs/fresh_validation/case_regions.json` 一致。
- 数据校验：A 交接包 `SHA256SUMS.txt` 中两段轨迹、审计、标定等文件逐一核对通过。
- 环境：`C:/Users/pc/miniconda3/envs/mujoco/python.exe`（Python 3.13.17，numpy 2.5.4，scipy 1.18.1，torch 2.14.1+cpu，matplotlib）。
- 文件清单与本清单一致；所有 `runs/` 中 JSON/PNG/日志/权重均可直接打开，无需重跑。

## I. 尚未完成（不是成果，仅备忘）

- 点球专项的真实轨迹接入与封存实测验证（A 已交付两段 ISSIA 空中轨迹，非点球；文献高速摄影轨迹待 A 交付）。
- 等 A 确认：自检用例 §3 升力方向勘误、面积对比写法；确认后 C 需更新论文四处。
- MDN 50% 区域校准改进（当前实际覆盖 46–59%）。
- 变阻力 C_D(v)、旋转衰减、物理特征增强等消融实验；大样本多种子稳定性。
- 为 C 输出 LaTeX 三线表与 300 dpi 定稿图；论文 AI 使用披露附录。

## J. 第二轮新增（2026-11-07 16:50–17:25，A→B v2 之后）

1. **同步 Codex 16:50–16:52 产出**：`check_issia_arcs.py`、`inference.py` 的 `cd_upper`、`params.json`、`runs/issia_A/*`、`给A的回签与ISSIA外推结果.md`。
2. **A→B 交接包 v2 入库**（`handoff/A到B_v2_2026-11-07/`，SHA256 已核对）。
3. **A 自检用例落地为单元测试**：`test_selftest_case.py` + `selftest_case.json`（6 项，13/13 通过）；核对中发现并记录 §3 升力方向约定勘误（`对A自检用例的核对.md`）。
4. **A 的 §8 请求：C_D 先验面积对比**（`case_cd_prior.py` + `runs/case_cd_prior/`）：[0.15,0.30] vs [0.15,0.45] 的 50% 面积 +1.1%、95% 面积 −0.5%，均值移动 1.7–2.0 cm（3 seeds）。
5. **ISSIA (C_D, L) 可辨识性检验**（`fit_issia_cd_lift.py` + `ISSIA_CD_L拟合检验.md`）：竖直净升力模型留出 RMSE 0.452→0.188 m、1.488→1.084 m；L≈6–7 m/s²、C_D–L 相关系数 ≈ 0；水平升力负对照被数据拒绝。
6. **给 A 的第三轮回复**（`给A的回复_第三轮.md`）：确认 v2 全部口径、给出面积表与两项新结果、提出 §3 勘误与三项待确认。

## K. 微信留档（2026-11-07 18:02，溪上 → B；不计入 B 产出）

连续 14 条消息（3 文字 + 1 链接 + 1 图片 + 9 文件）已按类型存于 `wechat_archive/2026-11-07_溪上/`，逐条清单、归属与 SHA256 见该目录 `00_对话记录.md`。

- 与仓库已有文件逐字一致（仅 CRLF/LF）：`气动参数更新结果.md`、`给A的回签与ISSIA外推结果.md`、`ISSIA筛选与仿真验证.md`、`UPC-B题-团队实验方案.md`；`params.json` 字节一致。
- 新增：`physics_simulation.py`（单轨迹 `solve_ivp` 参考实现，与 `student_b/physics.py` 不同，未接入主流程）、`upc_b_48.md`（48h 方案稿；评估见 §G.2）。
- 压缩包：`UPC_B_给B的ISSIA数据与待确认_2026-11-07.zip`（v1，已被取代）、`UPC_B_给B的交接包_v2_2026-11-07.zip`（v2，解包 21 个文件中 18 个与 `handoff/A到B_v2_2026-11-07/` 内容一致，另含 3 个大 CSV）。