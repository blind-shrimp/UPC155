# student-c — C 线工作区（论文 / 图表 / 评价）

> 负责人：朱（C）。本目录只放 **C 线交付**，不混入 `student_b/` 的 B 组代码。
> 当前阶段：**P0（2026-11-07）**。

## 目录

```
student-c/
├── README.md                 # 本文件
└── P0/                       # P0 阶段交付（详见 P0/README.md）
    ├── README.md             # 范围、结论、文件索引、复现
    ├── data/                 # 冻结测试集（4,187 条）+ manifest + 导出脚本
    ├── report/               # P0 报告、诊断、汇总 CSV、图
    ├── tables/               # 论文可直接 \input 的 booktabs 表格
    └── code/                 # 测试集导出、LaTeX 表生成脚本
```

## 与其他目录的关系

- **权威实验代码与完整结果**：`student_b/experiments/`（运行环境、checkpoints、逐 epoch 曲线都在那里）。
  本目录是 P0 结束时 C 线的**只读快照**，用于写论文与交接，不替代原目录。
- **数据来源**：`student_b/runs/canonical50k/`（50k 条，seed 42，事件数 41,733/8,267）。
  冻结测试集由 `P0/data/export_test_set.py` 从该数据导出。
- **论文正文**：仍在 `论文模板/`。`P0/tables/*.tex` 可以直接 `\input{}`，但表里的数字是
  **开发结果**，P1 最终评测出来后需要替换。

## P0 一句话

在冻结的 4,187 条测试集上，**物理特征 + 绝对目标（Arm C）** 在 5/10/15 mm 的 NLL 最好；
残差目标（B/D/E）在高噪声出现重尾，PI-ResMDN 在公平重训后也明显差于 C。
50% 区域的覆盖率在所有模型上都漂移（45–64%），**校准是 P1 的首要任务**。

## 使用约定

- `P0/data/test_canonical_4187.csv` 是**测试集**：禁止训练、调参、校准。
- 评估加噪规则与 seed 写在 manifest 里；换 seed 必须同时报告，不能只报最好 seed。
- `P0/tables/*.tex` 的表注已写明“synthetic / development”，进论文前按 P1 结果更新。
