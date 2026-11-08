# Anchored-prior simulation set: reproduction and generalization audit（2026-11-08）

“用实测轨迹参与仿真”的新仿真集（50,000 条）的复现、审计与台式机训练入口。
**核心问题**：新仿真集是否真的让模型变好，还是只是把被评估的轨迹“喂”进了训练分布？

## 1. 新仿真集是什么

`build_data.py` 与原 `deliverables/retrain_all/build_data.py` 的最初设定一致：

1. 用 20 条实测轨迹做**全段有效自旋/阻力拟合**，得到每条轨迹的发射参数锚点：
   - Asai 2020：Fig3 / Sample05 / Sample12（100 Hz，位置 + 转速列）；
   - DFL：2 条空中点球（J03WOH、J03WR9）+ 11 条筛选片段（J03WMX/J03WOH/J03WR9 …）；
   - ISSIA：3 条（seg_0608_0627、seg_1144_1172、ISSIA_2972_2991）；
   - Barber 2010：Fig5 数字化平面轨迹（用 11 m 截面前的弧段）。
2. 50% 样本来自原 P1 宽先验；另外 50% 按来源平衡地在拟合锚点上加扰动
   （v：1.5/2.0/1.2 m/s；ω：6 rad/s；C_D：0.025），非发射类来源只继承气动参数并绕竖直轴转到采样朝向；
   再按 y 镜像做对称增广。
3. canonical RK4（z0=0.11 m，x=11 m 截面，0/50/100 ms 输入时刻），50,000 条按 40k/5k/5k 划分。
4. `train.py` 用与 P1 相同的结构重新训练（11 维 `phys_reduced`、3×128、GELU、K=3、100 epoch、seed 11）。

### 复现结果（已在本机验证）

- 数据集**逐字节复现**：`data.npz` SHA-256 = `00cb3e8199eb21bb57ce5b90e2400810d269255ef8ac1070701b6e9be07a3295`（与用户提供的最新仿真集一致；构建约 36 s）。
- 训练**逐指标复现**：100 epoch、seed 11；2/5/10/15 mm 的 median / coverage / NLL 与提供的 `test_scores.csv` 完全一致（例如 5 mm fresh median **28.18 cm**、frozen P1 **29.71 cm**）。
- 参考模型/配置/分数保存在 [`reference/`](reference/)。

## 2. 原实验的说法与关键漏洞

原实验（`deliverables/retrain_all/README.md`）报告：

| 指标 | 冻结 P1 | 新模型 |
| --- | ---: | ---: |
| 5 mm 仿真测试中位误差 | 29.71 cm | **28.18 cm** |
| 5 mm 50% HDR 覆盖率 | 42.54% | **48.65%** |
| 5 mm 95% HDR 覆盖率 | 94.52% | **95.09%** |
| Asai Fig3 / 05 / 12 回放误差 | 54.49 / 49.87 / 59.57 cm | **24.04 / 29.89 / 30.87 cm** |

**漏洞**：新模型的测试集与训练集共享同一套“拟合锚点先验”（`holdout = independent synthetic draws from shared fitted priors`）；
三条 Asai 回放更是**回顾性**的（原文自己标注 “trial contributed to fresh simulation prior”）。
所以这些提升只能说明“模型学会了新先验”，**不能**说明新仿真更好或能外推到未参与拟合的真实轨迹。

## 3. 泛化审计（leave-one-cohort-out / leave-one-trial-out）

### 3.1 协议

- 训练集（5 个，除锚点集合外完全一致：50,000 条、100 epoch、seed 11、同一 builder）：
  all anchors / no Asai / no DFL penalties / no ISSIA / prior only（排除全部实测锚点 = 纯 canonical 先验重训）。
- held-out（6 个，独立随机流，不进入任何训练）：每个来源一组 + canonical；评估使用统一种子与同一噪声流。
- 真实 Asai 三球回放：对**含** Asai 锚点的模型是**回顾性**（只能作上界/诊断）；对 no Asai / prior only 才是留出证据。

### 3.2 迁移矩阵（5 mm 中位误差，cm）

| held-out | all anchors | no Asai | no DFL penalties | no ISSIA | prior only | frozen P1 |
|---|---:|---:|---:|---:|---:|---:|
| canonical | 30.73 | 30.68 | 31.05 | 31.14 | **29.11** | **28.99** |
| asai | **27.13** | 47.30 | 25.58 | 25.37 | 40.93 | 41.87 |
| dfl_penalty | **15.14** | 13.90 | 30.60 | 13.37 | 24.01 | 24.29 |
| dfl_extra | 30.34 | 29.91 | 30.35 | 30.74 | 31.01 | 30.68 |
| issia | **27.79** | 26.39 | 26.49 | 29.60 | 27.78 | 27.95 |
| barber | 26.88 | 25.04 | 24.34 | 27.03 | 30.64 | 30.48 |

50% HDR 覆盖率（同协议，fraction）见 `../runs/sim2real/audit/README.md`。真实 Asai 回放（10 mm，cm）：

| case | all anchors | no Asai | no DFL penalties | no ISSIA | prior only | frozen P1 |
|---|---:|---:|---:|---:|---:|---:|
| Fig3 | 24.04（回顾性） | 59.17（留出） | 22.26（回顾性） | 22.58（回顾性） | 52.26（留出） | 54.49 |
| Sample05 | 29.89（回顾性） | 57.58（留出） | 24.46（回顾性） | 29.66（回顾性） | 46.47（留出） | 49.87 |
| Sample12 | 30.87（回顾性） | 69.08（留出） | 25.18（回顾性） | 30.19（回顾性） | 60.57（留出） | 59.57 |

### 3.3 判读

1. **同来源 held-out 必然变好、留出来源必然变差**：排除某来源后，该来源 held-out 明显变差
   （Asai 27.1→47.3；DFL 点球 15.1→30.6；ISSIA 27.8→29.6 cm）。anchored 训练确实“学会”了该来源的拟合先验，
   这解释了 attached 在同分布测试上的提升，也说明它不是泛化。
2. **真实 Asai 回放是唯一干净的留出检验**：不含 Asai 锚点的模型**没有提升**——no Asai 59.2 / 57.6 / 69.1 cm、
   prior only 52.3 / 46.5 / 60.6 cm，对比冻结 P1 54.5 / 49.9 / 59.6 cm；没有任何模型在三条上全面优于冻结 P1。
   含 Asai 锚点模型的 22–31 cm 全部是回顾性（被评估轨迹参与了先验拟合），不能作为提升证据。
3. **代价**：anchored 模型在 canonical held-out 上略差（30.7–31.1 vs 29.0 cm）；先验被 20 条实测轨迹拉窄后，
   原宽先验的覆盖变差。anchored 样本的 Cd 均值从 0.224 升到 0.27、|ω| 从 57.5 降到 34.4、入框比例从 44% 升到 53%——
   这是“向实测曲线球靠近”，不是“更真实的点球分布”。
4. 因此 attached 实验的“新模型更好”主要是 **in-distribution / prior-fitting**；Asai 回放的巨大改进来自泄漏。

### 3.4 留一试次（LOTO）补充

### 3.4 留一试次（LOTO）补充

每次只排除一条 Asai 试次（其余 19 个锚点保留），重训后回放三条；**只有被排除那条算留出**：

| 模型（排除的试次） | 被排除试次回放（留出） | 另两条（回顾性） | 冻结 P1 |
|---|---:|---|---:|
| no Fig3 | **28.9 cm** | Sample05 25.5, Sample12 30.2 | 54.5 cm |
| no Sample05 | **38.0 cm** | Fig3 22.7, Sample12 28.5 | 49.9 cm |
| no Sample12 | **33.3 cm** | Fig3 26.7, Sample05 31.5 | 59.6 cm |

判读：**同源外推成立**——同一 100 Hz 实验内，已知 2 条试次可把第 3 条未见试次压到 29–38 cm（冻结 P1 为 50–60 cm）；
但这是同实验/同球/同踢法的最近邻插值，**不能外推到跨来源真实轨迹**：完全没有 Asai 锚点时（no Asai 模型）
三条真实回放为 59.2 / 57.6 / 69.1 cm，比冻结 P1 更差。详见 `../runs/sim2real/audit/LOTO.md`。


## 4. 结论

- **anchored simulation 应定位为 data-augmented prior，而不是“更真实的物理仿真”**：同分布校准会变好，但没有证据表明能提升对未见真实轨迹的泛化。
- 任何后续使用必须：① 在留一来源/留一试次协议下评估；② 被评估的真实轨迹不参与先验拟合；③ 报告真实留出回放；④ 拿到新的独立真实轨迹后再谈“更好”。
- 对当前论文：C 已明确交稿前不改论文；本目录的结果作为赛后/下一轮研究资产，**不作为 P1 主结果或论文证据**。
- 下一步数据是最关键的：Asai 其余试次、DFL 全部点球事件、或公开点球 3D 数据（见 `handoff/点球实测数据渠道与行动_2026-11-08.md`）。


## 5. 台式机训练指南（“重新交给台式机训练模型”）

环境：Python + NumPy/SciPy/PyTorch（openpyxl 仅用于读取 Asai xlsx；仓库 `handoff/asai_workbooks_2026-11-08/` 已带工作簿，可替代桌面路径）。
不需要 GPU；单次 100 epoch、2 线程约 1.5–3 分钟。GPU 不会自动加速（当前训练代码是 CPU/PyTorch 小网络）。

从仓库根目录运行（`$py` 换成台式机 Python）：

```powershell
$asai = 'handoff\asai_workbooks_2026-11-08'
$sim = 'student_b\sim2real'
$runs = 'student_b\runs\sim2real'

# 1) 生成 anchored 数据集（约 36 s）
& $py $sim\build_data.py $runs\data_all --asai-dir $asai

# 2) 训练：与 P1 协议一致的 3 个种子 × 150 epoch（每个约 2–4 分钟）
& $py $sim\train.py $runs\data_all\data.npz $runs\models\seed11 --seed 11 --epochs 150 --asai-dir $asai
& $py $sim\train.py $runs\data_all\data.npz $runs\models\seed22 --seed 22 --epochs 150 --asai-dir $asai
& $py $sim\train.py $runs\data_all\data.npz $runs\models\seed33 --seed 33 --epochs 150 --asai-dir $asai

# 3) 独立 held-out 集（与训练无关的随机流）
& $py $sim\make_holdout.py $runs\data_all\data_manifest.json $runs\holdout --n 4000

# 4) 评测（含冻结 P1、逐来源 held-out、真实 Asai 回放）
& $py $sim\eval_matrix.py $runs\models $runs\eval --holdout $runs\holdout --asai-dir $asai
```

产物：`data_all/data.npz`（~6 MB，可重建）、`models/<seed>/model.pt`、`config.json`、`test_scores.csv`、`asai_replay.csv`；
最终对照表写到 `eval/eval_matrix.csv`。**数据与权重被 .gitignore 忽略，不要提交二进制**；只提交脚本、配置、指标与报告。
完整审计（5 个数据集 + 5 个模型）见 `run_audit.ps1`，约 15 分钟。

### 5b 留一试次（LOTO）与稳定性（审计后新增）

```powershell
$asai = 'handoff\asai_workbooks_2026-11-08'
$sim = 'student_b\sim2real'; $runs = 'student_b\runs\sim2real'

# 每次只排除一条 Asai 试次（其余 19 个锚点保留）
& $py $sim\build_data.py $runs\data_loto_fig3 --exclude-anchor-ids Fig3 --asai-dir $asai
& $py $sim\build_data.py $runs\data_loto_s05 --exclude-anchor-ids Sample05 --asai-dir $asai
& $py $sim\build_data.py $runs\data_loto_s12 --exclude-anchor-ids Sample12 --asai-dir $asai
& $py $sim\train.py $runs\data_loto_fig3\data.npz $runs\models\loto_fig3 --seed 11 --epochs 100 --asai-dir $asai
& $py $sim\train.py $runs\data_loto_s05\data.npz $runs\models\loto_s05 --seed 11 --epochs 100 --asai-dir $asai
& $py $sim\train.py $runs\data_loto_s12\data.npz $runs\models\loto_s12 --seed 11 --epochs 100 --asai-dir $asai
```

判读：每个模型只看**被排除那条**的回放误差（另两条是回顾性，不作数）；结果见 `runs/sim2real/audit/LOTO.md`。
稳定性：all-anchor 数据 3 seeds × 150 epoch，用 held-out 来源与 canonical 报告均值±sd；
**不得用 Asai 回放选择 all-anchor 模型的超参**（回顾性）。

## 6. 可改进的仿真方向（审计之后）

1. **先验比例/扰动尺度选择**：当前 50%/固定扰动是手工设定；应在留一来源协议下选（避免用被评估轨迹调参）。
2. **更多真实锚点**：DFL 全部点球、Asai 其余试次；锚点越多样，anchored 仿真越接近真实先验。
3. **自旋轴物理**：Asai 只有转速幅值，方向由位置拟合；若能拿到旋转轴，先验可显著收紧。
4. **观测噪声模型**：真实跟踪误差不是各向同性高斯；可在 anchored 数据里加按来源的噪声模型（DFL 15 mm、ISSIA 30 mm 假设）。
5. **留出真实轨迹的验证协议**：拿到新数据前，任何“更好”的结论都只能停留在同分布/留一来源层面。

## 7. 文件

| 文件 | 用途 |
| --- | --- |
| `build_data.py` | anchored 先验仿真生成器（支持 `--exclude-cohorts`、`--prior-fraction`） |
| `train.py` | 训练 P1 结构模型并输出配置/曲线/分数/Asai 回放 |
| `make_holdout.py` | 从拟合锚点生成独立 held-out 集（逐来源 + canonical） |
| `eval_matrix.py` | 多模型 × 多 held-out 的迁移矩阵与真实 Asai 回放 |
| `run_audit.ps1` | 一键复现 §3 的留一来源审计 |
| `reference/` | 原实验的数据清单、模型、配置、曲线、分数（可追溯） |
