# ISSIA 筛选与仿真验证

## ISSIA 数据筛选

本地 CSV 共 2,465 行，其中 1,689 行有可用的三维坐标。原始数据为 25 fps。官方标定中六台架高相机的世界坐标 z 都为负，因此筛选时将高度转换为 `height=-z`。初筛时误把正 z 当高度，已纠正。[原始采集说明](https://pspagnolo.jimdofree.com/download/) · [作者发布的相机标定](https://github.com/mguti97/SoccerNet-v3D/releases/download/v1.0.0/issia_calibration.json)

筛选条件为高度至少 0.30 m、至少两台相机、至少连续 8 帧、首尾水平位移至少 2 m。逐帧中位重投影误差上限为 5、10、20 像素时，分别筛出 21、25、27 个候选片段。像素误差用于筛选，无法直接转换为三维坐标精度。

10 像素阈值下，5 段首尾水平位移超过 11 m。可先核查帧 608–627、1056–1084、1144–1172 和 2972–2998。余下一段 2892–2937 的整段二次拟合 RMSE 约 0.89 m，应优先排查接触或重建异常。拟合残差仅用于排序，无法确认中途有无接触。

候选片段可用于后续核对一般空中飞行。25 fps 的帧间隔为 0.04 s，且 CSV 缺少离脚时刻和点球事件标签。该批片段尚未进入点球训练、校准或验证。

[候选帧 CSV](C:/Users/pc/Documents/ChatGPT/upc/student_b/runs/issia_screen/candidate_frames.csv) · [筛选统计](C:/Users/pc/Documents/ChatGPT/upc/student_b/runs/issia_screen/screening.json)

## 全新仿真样本上的比较

使用独立种子生成无风及 3 m/s 横风各 12 条空中穿越轨迹。两种预测器都按无风模型运行，各坐标观测噪声标准差为 5 mm。物理推断从每轮 6,000 个样本开始，若最终有效样本量低于 100，则增加至每轮 18,000 重试。下表只使用达到该门槛的共同样本。门槛是筛查标准，无法保证收敛。

| 场景 | 可配对/总样本 | 恒加速度误差 | MDN 误差 | 物理误差 | MDN / 物理能量评分 |
|---|---:|---:|---:|---:|---:|
| 无风 | 9/12 | 0.425 m | 0.341 m | 0.353 m | 0.258 / 0.211 m |
| 3 m/s 横风 | 10/12 | 0.804 m | 0.352 m | 0.266 m | 0.233 / 0.169 m |

表中均为中位数。误差以预测分布均值计算。能量评分评价整个预测分布，越小越好。两组的物理推断能量评分更低。无风组点误差相近，横风组物理法点误差更低。5 个低 ESS 样本仍保留在逐条输出，不能将表格解读为全样本排名或实测性能。

[逐条结果](C:/Users/pc/Documents/ChatGPT/upc/student_b/runs/fresh_validation/benchmark_rows.json) · [汇总](C:/Users/pc/Documents/ChatGPT/upc/student_b/runs/fresh_validation/benchmark.json)

## 题面案例的联合预测区域

采用文献参数模型、Cd 在 0.15–0.30 内均匀取值。贝叶斯后验端点用加权 KDE 平滑后，在球门平面网格上计算联合最高密度区域。以下结果以球保持空中并穿越球门平面为条件。

| 各坐标误差标准差 | 最可能穿越点 (Y,Z) | 50% 区域面积 | 95% 区域面积 | ESS |
|---|---|---:|---:|---:|
| 2 mm | (2.617, 1.984) m | 0.051 m² | 0.207 m² | 124 |
| 5 mm | (2.650, 2.052) m | 0.219 m² | 0.809 m² | 2,893 |
| 15 mm | (2.657, 2.400) m | 0.841 m² | 2.645 m² | 5,744 |

题目没有指定误差标准差，三个数值是独立情景。2 mm 情景的 ESS 明显低于另外两组，区域和众数应谨慎解读。网格众数依赖 KDE 平滑，不能与分布均值混用。

[案例联合区域图](C:/Users/pc/Documents/ChatGPT/upc/student_b/runs/fresh_validation/case_regions.png) · [原始数值](C:/Users/pc/Documents/ChatGPT/upc/student_b/runs/fresh_validation/case_regions.json)

## 复现

从项目根目录运行。原有 7 项自动测试全部通过。

```powershell
$py = 'C:/Users/pc/miniconda3/envs/mujoco/python.exe'
& $py student_b/screen_issia.py data_sources/ISSIA-3D.csv student_b/runs/issia_screen
& $py student_b/validate.py benchmark --output student_b/runs/fresh_validation --n 6000
& $py student_b/validate.py case --output student_b/runs/fresh_validation --n 40000
```
