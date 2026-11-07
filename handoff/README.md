# handoff/ — 队友交接包（只读留档）

本目录存放队友之间实际传递的交接材料，**原样留档、不改内容**。当前只有一轮：

## A到B_v2_2026-11-07/（A → B，2026-11-07）

A 交付给 B 的 ISSIA 数据与口径确认包（v2，已含 B 的回签结果）。**唯一有效的口径记录是
`05_口径定稿_v2.md`**；`params_run_literature50k.json` 是 B 实际跑 5 万条用的参数
（与 `student_b/params.json` 一致）；`params_candidate_A_v1.json` 已作废，不要引用。

| 文件 | 用途 |
|---|---|
| `README_先看这个.md` | 包内导航与 v2 变更说明 |
| `05_口径定稿_v2.md` | ★ 唯一有效口径：参数、数值、C 要改的三处、两条撤回判断 |
| `04_回复B_第二轮.md` | A 对 B 回签的逐条确认（含 √5 修正与 150k MC 噪声表） |
| `02_ISSIA数据说明.md` | ISSIA 数据来源/帧率/坐标系/质量/两段帧结论 + B 的外推表 |
| `03_仿真器自检用例.md` | 案例解析解 + 数值 + 积分断言（**注：§3 升力方向约定有误，见 `student_b/对A自检用例的核对.md`**） |
| `selftest_case.json` | 自检用例机器可读版（B 已落成 6 项单元测试） |
| `00_发给B的回复文案.md` / `01_待确认事项_回签单.md` | 第一轮材料（留档；回签单已由 B 回签） |
| `params_run_literature50k.json` / `params_candidate_A_v1.json` | 实际运行参数 / 已作废的候选参数（留档） |
| `data/` | 两段轨迹 CSV（608–622、1144–1172 帧）、相机标定、审计、连续性片段、校验和、`prepare_issia.py` |

**未入库的大文件**（体积原因，均可从 A 的原始表复现）：
`data/ISSIA-3D_raw.csv`（与 `data_sources/ISSIA-3D.csv` 同源同 sha256）、
`data/ISSIA_native_normalized.csv`、`data/ISSIA_valid_3d_only.csv`。
原始来源：<https://github.com/mguti97/SoccerNet-v3D/releases/download/v1.0.0/ISSIA-3D.csv>
（sha256 `7f4b3306…70ddc4`）。用 `data/prepare_issia.py` 可重新生成规范化表。

**使用红线（A 的原话）**：不要当 σ=2/5 mm 的独立测试集算覆盖率；不要用来校核初始条件
（没有离脚时刻）；不要混入 `z_up<0` 的 40 帧；不要假设坐标系朝向。
