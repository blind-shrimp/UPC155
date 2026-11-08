# AI-use report generation (tools/ai_usage)

This directory holds the scripts that produced the mandatory **Report on the Use of AI**
appended at the end of the paper (`论文模板/ai-report.pdf`).

## What is included

- `decompress_dsh_sessions.js` — reads the local DeepSeek Harness session logs
  (`%USERPROFILE%\.dsh\sessions\**\session.v4.jsonl.zstd`, concatenated-zstd JSONL)
  and writes plain JSONL copies.
- `extract_ai_usage.py` — reads the local OpenAI ChatGPT/Codex thread database
  (`%USERPROFILE%\.codex\thread_history_1.sqlite`) and the decompressed DSH sessions,
  and extracts only the **visible** conversation: the exact user queries and the
  assistant text messages. Internal reasoning traces and tool/shell output are excluded.
- `make_ai_report.py` — generates
  - `论文模板/ai-report.tex` (XeLaTeX/ctex; verbatim queries and complete outputs), and
  - `ai_logs/UPC155_AI_usage_log.md` (same content as plain text, easier for the team to search/edit).
- `../build_ai_report.ps1` — full rebuild: database copy → session decompression →
  extraction → report generation → XeLaTeX report → pdfLaTeX paper → `论文模板/155B.pdf`.

## How the report is included in the paper

`论文模板/main.tex` ends with `\includepdf[pages=-,pagecommand={\thispagestyle{cover}}]{ai-report.pdf}`.
The main paper is compiled with pdfLaTeX (English); the AI report is compiled separately
with XeLaTeX so that the original Chinese queries are reproduced verbatim.

## Before submission

1. Fill `论文模板/ai-report-team.tex` with the AI records of the other team members
   (system, exact query, complete output), or state that no other AI tool was used.
2. Re-run `tools/build_ai_report.ps1` (or just recompile `ai-report.tex` and `main.tex`)
   so that any AI interaction made after the last build is included.
3. Check `论文模板/155B.pdf`: first page has only team number/problem/title/summary,
   summary ≤ 300 words, every page shows "Team 155", and no identifying information.

## Notes

- The scripts contain no API keys or credentials; they read local logs only.
- Session logs may quote repository URLs, messaging IDs or the team's university;
  `make_ai_report.py` replaces such identifying strings with bracketed placeholders
  for anonymous review and states this in the report.
- The log files themselves are **not** committed; only the generated report is
  (`ai-report.tex`, `ai-report.pdf`, `ai_logs/UPC155_AI_usage_log.md`).
