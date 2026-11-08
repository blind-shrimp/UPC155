"""Generate the AI-use report (LaTeX, XeLaTeX/ctex) from extracted AI conversation logs.

Input : ai_logs/_work/ai_usage_extract.json (from extract_ai_usage.py)
Output: 论文模板/ai-report.tex   (appendix appended to main.pdf)
        ai_logs/UPC155_AI_usage_log.md (plain-text copy for the team)

Run from any directory; paths are derived from this file's location.
"""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
WORK = os.path.join(ROOT, 'ai_logs', '_work')
SRC = os.path.join(WORK, 'ai_usage_extract.json')
TEX = os.path.join(ROOT, '论文模板', 'ai-report.tex')
MD = os.path.join(ROOT, 'ai_logs', 'UPC155_AI_usage_log.md')

data = json.load(open(SRC, encoding='utf-8'))
sessions = data['sessions']

EXCLUDE = {'01a1b61e-5b41-7961-9af8-a510387fd518'}  # unrelated V2G writing session
LABELS = {
    '01a1b47f-ae53-7281-8123-c3e6234b5664': ('Main UPC Problem B working session', '2026-11-07 13:34 to 2026-11-08 11:46 (Beijing time)'),
    '01a1b702-20c0-7771-83d3-ca8ff843fe15': ('Second UPC session: independent reference implementation from an attached plan', '2026-11-08 01:14 to 01:34 (Beijing time)'),
    'session-647c9a78-6938-4266-83d2-7fc5cb9446cd': ('UPC repository maintenance and AI-report preparation', '2026-11-07 16:33 to 2026-11-08 12:20 (Beijing time)'),
    'session-60ae33b3-ab82-4c61-9ff6-52a3b9d864ae': ('Asai measured-kick discrepancy experiment (delegated design and code)', '2026-11-08 11:37 (Beijing time)'),
    'session-3967613a-eb27-4236-9be7-598d77c378ec': ('Measured-kick data verification task (delegated)', '2026-11-08 12:00 (Beijing time)'),
    'session-328b41e9-abe0-41d7-82fa-0e1a951ce926': ('Paper raw-data link verification (delegated)', '2026-11-07 21:18 (Beijing time)'),
    'session-1f960b38-9786-4d27-8a9f-7077ddc30007': ('Measured trajectory dataset search (delegated)', '2026-11-07 21:17 (Beijing time)'),
    'c1fbcbd3-0c92-4cb7-8156-da2bef6ece6e': ('Read-only static review task (delegated)', '2026-11-08 11:37 (Beijing time)'),
    '152fb4dd-fe1f-46bd-b91b-458fd0df947e': ('Command-behaviour test task (delegated)', '2026-11-08 11:25 (Beijing time)'),
}

SENSITIVE = re.compile(r'(sk-[A-Za-z0-9]{10,}|ghp_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,}|'
                       r'(api[_-]?key|password|secret|token)\s*[:=]\s*[^\s,;]{6,})', re.IGNORECASE)
redactions = []


def esc(t):
    return (t.replace('\\', '\\textbackslash{}').replace('&', '\\&').replace('%', '\\%')
            .replace('#', '\\#').replace('_', '\\_').replace('{', '\\{').replace('}', '\\}')
            .replace('~', '\\textasciitilde{}').replace('^', '\\textasciicircum{}'))


def clean(text):
    if not text:
        return ''
    for m in SENSITIVE.finditer(text):
        redactions.append(m.group(0)[:40])
    text = SENSITIVE.sub('[REDACTED CREDENTIAL]', text)
    # Anonymous-review redactions: remove team-identifying handles, repository URLs,
    # messaging IDs and institution names. Wording is otherwise unchanged.
    text = re.sub(r'https?://github\.com/blind-shrimp/UPC155[^\s)\]>]*', '[team repository]', text)
    text = re.sub(r'github\.com/blind-shrimp/UPC155[^\s)\]>]*', '[team repository]', text)
    text = text.replace('blind-shrimp', '[team]')
    text = re.sub(r'wxid_[A-Za-z0-9_\-]+', '[redacted messaging id]', text)
    text = re.sub(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', '[email redacted]', text)
    text = text.replace('SJTU', '[university]').replace('交大', '[university]')
    text = text.replace('x1shang', '[team member]')
    text = re.sub(r'(?i)chen\s+zixuan', '[team member]', text)
    text = text.replace('Jasonchenczx', '[team member]').replace('jasonchenczx', '[team member]')
    text = re.sub(r'(?i)jason', '[team member]', text)
    text = text.replace('zhu_jiahe', '[team member]').replace('Zixuan', '[team member]')
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\x00', '')
    text = text.replace('\ufe0f', '')  # invisible emoji variation selector
    text = text.replace('\\end{Verbatim}', '\\textbackslash end\\{Verbatim\\}')
    return text.strip('\n')


def verbatim(text):
    if not text:
        return ''
    return ('\\begin{Verbatim}[breaklines=true,breakanywhere=true,fontsize=\\scriptsize,'
            'frame=single,framesep=2pt]\n' + text + '\n\\end{Verbatim}\n')


count_q = count_o = count_chars = 0
codex_blocks, dsh_blocks = [], []
for s in sessions:
    if s['id'] in EXCLUDE:
        continue
    label, when = LABELS.get(s['id'], (s.get('title') or s['id'], ''))
    target = dsh_blocks if s['system'].startswith('DeepSeek') else codex_blocks
    target.append('\\subsection*{%s}' % esc(label))
    target.append('\\noindent System: %s. Model: %s. Period: %s. Session identifier: %s.\n' % (
        esc(s['system']), esc(s.get('model', '')), esc(when), s['id']))
    for i, turn in enumerate(s['turns'], 1):
        q = clean(turn['query'])
        if q:
            target.append('\\paragraph{Query %d (exact wording).}' % i)
            target.append(verbatim(q))
            count_q += 1
            count_chars += len(q)
        for j, out in enumerate(turn['outputs'], 1):
            o = clean(out)
            if not o:
                continue
            target.append('\\paragraph{Complete output %d.%d.}' % (i, j))
            target.append(verbatim(o))
            count_o += 1
            count_chars += len(o)

preamble = r'''\documentclass[UTF8,10pt]{ctexart}
\usepackage[a4paper,margin=1.6cm,headheight=15pt]{geometry}
\usepackage{fvextra}
\usepackage{hyperref}
\hypersetup{hidelinks,pdfauthor={},pdftitle={},pdfsubject={},pdfkeywords={}}
% Monospace for verbatim: DejaVu Sans Mono covers Greek, subscripts, arrows,
% circled numbers and most technical symbols used in the logs.
\setmonofont{DejaVu Sans Mono}[Scale=0.86]
% Characters missing from DejaVu Sans Mono are routed to the CJK font, which
% contains them in its GB symbol set: circled digits and the parallel sign.
\xeCJKDeclareCharClass{CJK}{"2460->"2473,"2225}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.35em}
\begin{document}
\begin{center}
{\Large\bfseries Report on the Use of AI}
\end{center}

\noindent\textbf{Systems used and how they were used.}
(i)~The OpenAI ChatGPT desktop application with the Codex coding agent was used throughout the 48-hour contest. It was used for research planning, physics and statistics method design, writing and running the Python simulation and neural-network code, executing and checking experiments, checking physical parameters against the literature, validating measured data, and drafting and revising the paper and the repository documents. (ii)~A DeepSeek Harness (DSH) coding agent (system label: DeepSeek Harness; model \texttt{deepseek-v4-flash-vision-exp}) acted as a second AI agent. It maintained and synchronized the shared repository, independently re-computed and reviewed the physics results, added further data analyses, designed delegated experiments, and prepared this report. (iii)~Records of any additional generative-AI tools used by other team members are given in the final subsection.

\noindent\textbf{What is reproduced below.}
The exact wording of every query sent by the team to each AI system is reproduced verbatim, followed by the complete text of each AI response that the team received. Internal reasoning traces, tool-invocation traces and shell/program output produced by the AI tools are not reproduced, because they are not output delivered to the team; the responses below are the complete visible output. The material is reproduced in the language in which it was written. \textbf{The AI tools were also used to generate, modify and verify computer code and result files that are part of the submitted repository and paper; all reported results were checked by the team and by a second AI agent, and they are reproducible from the repository.}

\noindent\textbf{Note on language.} The team's working language was Chinese, so many queries and outputs are in Chinese. They are reproduced without translation, as required for an exact record.

\noindent\textbf{Note on anonymisation.} For anonymous review, strings in the preserved logs that could identify the team or individuals (account handles, repository URLs of the team, messaging identifiers, e-mail addresses, and the name of the team's university) are replaced by bracketed placeholders such as [team repository]. The wording of the queries and outputs is otherwise unchanged.

'''

systems_section = r'''\subsection*{A. OpenAI ChatGPT desktop application (Codex agent)}
The following sessions were run in the OpenAI ChatGPT desktop application with its Codex coding agent (model shown by the application: GPT-5-based Codex profile, internal name \texttt{gpt-6-astra}). Sessions are listed in chronological order.

'''
dsh_section = r'''\subsection*{B. DeepSeek Harness (DSH) coding agent}
The following sessions were run with the DeepSeek Harness coding agent (model \texttt{deepseek-v4-flash-vision-exp}). The agent was used as the second agent in the team repository and as a delegated sub-agent called by the Codex agent through a local bridge for specific verification and experiment-design tasks. In the delegated mode the "query" is the exact task message delivered by the calling agent. Sessions are listed in chronological order.

'''
team_section = r'''\subsection*{C. Additional generative-AI tools used by other team members}
\input{ai-report-team}

'''

tex = (preamble + systems_section + '\n'.join(codex_blocks) + '\n' + dsh_section
       + '\n'.join(dsh_blocks) + '\n' + team_section + '\n\\end{document}\n')
if redactions:
    print('WARNING: redactions found:', sorted(set(redactions)))
open(TEX, 'w', encoding='utf-8').write(tex)

# Markdown copy
lines = ['# UPC155 AI 使用记录（原始文本汇总）', '',
         '> 由 DSH 自动导出，供 AI 使用披露使用；文本与 `论文模板/ai-report.tex` 相同。',
         '> 系统：(A) OpenAI ChatGPT/Codex；(B) DeepSeek Harness。团队成员的其他 AI 记录请在文件末尾追加。', '']
for s in sessions:
    if s['id'] in EXCLUDE:
        continue
    label, when = LABELS.get(s['id'], (s.get('title') or s['id'], ''))
    lines += ['---', '', f'## {label}', '',
              f"- 系统：{s['system']}；模型：{s.get('model')}；时间：{when}；会话：{s['id']}", '']
    for i, turn in enumerate(s['turns'], 1):
        q = turn['query'].strip()
        if q:
            lines += [f'### Query {i}（原文）', '', '```', q, '```', '']
        for j, out in enumerate(turn['outputs'], 1):
            if out.strip():
                lines += [f'### Output {i}.{j}（完整输出）', '', '```', out, '```', '']
os.makedirs(os.path.dirname(MD), exist_ok=True)
open(MD, 'w', encoding='utf-8').write('\n'.join(lines))

print('wrote', TEX, len(tex), 'chars')
print('wrote', MD, os.path.getsize(MD), 'bytes')
print(f'queries={count_q} outputs={count_o} chars_included={count_chars}')
