# student-c — 论文、图表与评测

## 当前交付

- [P1 实验报告](P1/results.md) 汇总结构选择、盲测、校准、稳健性与实测结果。
- [P1 最终配置](P1/final/best_config.json) 包含架构、种子、校准和权重校验和。根目录 `P1/best_config.json` 记录早期特征与 K 筛选，终稿使用 `P1/final/`。
- [盲测主表](P1/final/summary.csv)、[模型比较](P1/final/all_neural_models.csv)、[论文表格](P1/final/tables/tab_p1_fresh.tex) 和 [图表](P1/final/figures/) 可供正文直接引用。
- [P1 复现脚本](../student_b/experiments/run_p1.ps1) 在 B 线代码目录。P1 结果与权重在本目录。

## P0 历史快照

[P0](P0/README.md) 保存 4,187 条冻结开发测试轨迹、实验报告、图和 LaTeX 表。原始快照见提交 `ebdb13e` 与 [快照清单](SNAPSHOT.json)。快照清单中的根目录 `README.md` 对应当时的版本。开发测试集不用于后续训练、校准或结构选择。

论文在 [论文模板](../论文模板/main.tex)。跨目录入口见 [研究工作总览与论文大纲](../研究工作总览与论文大纲.md)。
