# 学生B：仿真、概率推断与MDN工作区

状态：已接入队员 A 提供的气动参数。训练数据仍为文献约束下的仿真，真实轨迹校准和独立实测验证待完成。

## 文件与审查顺序

1. `physics.py`：批量RK4、空气相对速度、横向旋转升力、穿越/触地事件。theta依次为vx,vy,vz,wx,wy,wz,Cd。单位SI。
2. `test_physics.py`：解析退化、耗散、正交性、触地与步长收敛测试。
3. `inference.py`：四轮自适应重要性采样，显式计算p/q，含20%先验混合分量；只用最后一轮估计，不错误混合不同提议分布样本。
4. `experiment.py`：生成数据、训练全协方差MDN、覆盖率和面积评测、案例输出。
5. `run_overnight.py`：分阶段保存日志，可从成功阶段继续；失败即停止，不掩盖异常。

## 本机运行

已有环境：`C:/Users/pc/miniconda3/envs/mujoco/python.exe`，已补充SciPy。PyTorch目前是CPU版本；代码在可用时自动选择CUDA，无需先升级GPU环境。

在项目根目录PowerShell运行：

```powershell
$py = 'C:/Users/pc/miniconda3/envs/mujoco/python.exe'
& $py -m unittest discover -s student_b -v
& $py student_b/experiment.py smoke --out student_b/runs/literature_dev --n 10000 --epochs 60
& $py student_b/experiment.py case --out student_b/runs/literature_cd022 --n 30000 --cd 0.22
```

夜间执行（新输出目录；关闭休眠需由操作者自行安排）：

```powershell
& $py student_b/run_overnight.py --out student_b/runs/overnight --n 50000 --epochs 150
```

`requirements.txt`用于新环境安装；当前环境具体版本另存`environment-freeze.txt`。

## 物理与统计约定

- 球质量 0.430 kg、半径 0.110 m、空气密度 1.20 kg/m³。阻力基准固定为 0.22，训练及阻力敏感性推断使用 0.15–0.30 均匀分布。均匀分布是建模选择，初速度和旋转的范围沿用开发先验。
- 升力采用 `CL=min(1.4*S, 0.30)`，其中 `S=R|omega×u|/|u|²`。斜率和上限是队员 A 依据文献提出的建模取值。轴向旋转和零旋转下升力为零。
- 当前求解器采用常数阻力。无旋 Teamgeist 的速度依赖阻力曲线留作模型形式对照。
- 无风为主模型，可配置横风、升力倍率与旋转衰减；尚未完成这些条件下的系统测试。
- 初始位置精确。两次观测加入独立各向同性误差；2、5、15毫米只是实验情景。
- 网络只输入六个位置与sigma，共7维。不输入真实初速度或旋转。物理特征增强属于后续消融。
- 数据按轨迹划分后加噪，避免同轨迹泄漏。MDN仅学习有效空中穿越条件下的端点分布；完整数据保留触地样本与事件标签。
- 模型输出全协方差混合高斯。评价点误差使用均值；案例另估网格众数，两者明确区分。
- HDR阈值通过密度抽样估计；面积用独立样本的逆密度积分估计，有蒙特卡洛误差。案例HDR在包含门外区域的网格上计算，不截断到门框。
- 重要性采样必须同时看ESS、最大权重和独立种子稳定性。局部自适应可能漏模态；不能称黄金标准。
- 事件采用线性插值而非精确根；通过步长加密控制误差。
- `Config.spin_decay=inf`表示不衰减；JSON清单将无穷值写为null。

## 已产出的开发结果

`runs/dev/` 和 `runs/pilot50k/` 保存旧参数的开发结果。`runs/literature50k/` 保存新参数重训的结果，`runs/literature_cd022/` 保存固定阻力案例。

## 后续工作

接入真实轨迹后，进一步校准初速度、旋转和观测误差，并在封存样本上独立测试。更换先验后重新生成训练集。

公开数据中的球心重建值不是无误差真值；导入时需确认单位、帧率、坐标与是否含物理拟合。未经筛选的ISSIA数据尚未进入训练。
