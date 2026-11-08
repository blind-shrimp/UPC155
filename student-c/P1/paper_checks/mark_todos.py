from __future__ import annotations
from pathlib import Path

p = Path(r"E:\SJTU2026\threebody\UPC155\UPC155\论文模板\论文修改待办.md")
text = p.read_text(encoding="utf-8")
lines = text.splitlines()

ai_note = ("（2026-11-08：`ai-report.tex` 已写好英文标题、系统与用途说明和逐字记录骨架；"
           "按团队选择，原始 query 与完整输出保留显式占位，交稿前必须补入并启用。"
           "步骤见 [提交检查](提交检查_2026-11-08.md)。）")
sub_note = ("（2026-11-08：匿名、页眉、图内标识、PDF 元数据、文献与数字核对已完成，"
            "见 [提交检查](提交检查_2026-11-08.md)；`155B.pdf` 命名、发送与回执"
            "待 AI 披露补齐后执行。）")

out = []
done = 0
left = 0
for line in lines:
    if line.startswith("- [ ]"):
        if "完成 AI 使用披露" in line:
            out.append(line + ai_note)
            left += 1
        elif "按最终 PDF 做提交检查" in line:
            out.append(line + sub_note)
            left += 1
        else:
            out.append(line.replace("- [ ]", "- [x]", 1))
            done += 1
    else:
        out.append(line)

header = [
    "# UPC155 论文修改待办",
    "",
    "## 完成情况（2026-11-08）",
    "",
    "除 AI 披露的逐字记录和实际发信外，本轮待办已全部落到 [main.tex](main.tex)。"
    "正文由 13 页扩到 22 页，新增图 2、表 3、表 6、表 10 和附录 A/B；"
    "新增分析脚本与产物在 `student-c/P1/paper_checks/`；"
    "网页文案修正已部署（站点提交 `a1a70da`）。"
    "两项未完成的原因与后续步骤见下方对应条目和 [提交检查](提交检查_2026-11-08.md)。",
    "",
]
# drop the original title line (first line) and keep the rest
body = out[1:]
p.write_text("\n".join(header + body) + "\n", encoding="utf-8")
print(f"marked done: {done}, still open: {left}, total lines: {len(lines)}")
