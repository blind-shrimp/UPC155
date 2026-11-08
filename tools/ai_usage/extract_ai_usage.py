"""Extract visible AI conversation text for the UPC155 AI-use report.

Sources (read locally, not committed):
  1. Plain-text DSH session JSONL files produced by decompress_dsh_sessions.js
     (from ~/.dsh/sessions/**/session.v4.jsonl.zstd).
  2. A copy of the Codex/ChatGPT app thread database (~/.codex/thread_history_1.sqlite)
     placed at %TEMP%/th_latest2.sqlite by build_ai_report.ps1.

Output: ai_logs/_work/ai_usage_extract.json (consumed by make_ai_report.py).
Only user queries and the assistants' visible text messages are extracted; internal
reasoning, tool calls and shell output are excluded.
"""
import datetime
import glob
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
WORK = os.path.join(ROOT, 'ai_logs', '_work')
OUT = os.path.join(WORK, 'ai_usage_extract.json')

CODEX_THREADS = [
    '01a1b47f-ae53-7281-8123-c3e6234b5664',  # main UPC session
    '01a1b702-20c0-7771-83d3-ca8ff843fe15',  # second UPC session (reference implementation)
    '01a1b61e-5b41-7961-9af8-a510387fd518',  # unrelated session, filtered later
]


def text_of_content(content):
    out = []
    if not isinstance(content, list):
        return ''
    for c in content:
        if isinstance(c, dict) and c.get('type') == 'text' and c.get('text'):
            out.append(c['text'])
    return '\n'.join(out)


def dsh_sessions():
    sessions = []
    for p in sorted(glob.glob(os.path.join(WORK, 'dsh_sessions', '*.jsonl'))):
        title, cwd, turns = '', '', []
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            t, d = o.get('type'), (o.get('data') or {})
            if t == 'session':
                cwd = o.get('cwd', '')
            elif t == 'session/title':
                title = d.get('title') or d.get('val') or ''
                if isinstance(title, dict):
                    title = title.get('text', '')
            elif t == 'user/message':
                q = text_of_content(d.get('content'))
                if q.strip():
                    turns.append({'query': q, 'outputs': []})
            elif t == 'assistant/message':
                txt = text_of_content((d.get('message') or {}).get('content'))
                if txt.strip():
                    if not turns:
                        turns.append({'query': '', 'outputs': []})
                    turns[-1]['outputs'].append(txt)
        sessions.append({'id': os.path.basename(p).replace('.jsonl', ''),
                         'system': 'DeepSeek Harness', 'model': 'deepseek-v4-flash-vision-exp',
                         'cwd': cwd, 'title': title, 'turns': turns})
    return sessions


def codex_threads():
    db = os.path.join(os.environ.get('TEMP', '.'), 'th_latest2.sqlite')
    if not os.path.exists(db):
        print('WARNING: Codex thread database copy not found at', db)
        return []
    c = sqlite3.connect(db)
    out = []
    for tid in CODEX_THREADS:
        rows = c.execute(
            'select item_type, item_json from thread_items where thread_id=? order by rollout_ordinal',
            (tid,)).fetchall()
        turns = []
        for itype, ij in rows:
            try:
                o = json.loads(ij)
            except Exception:
                continue
            if itype == 'userMessage':
                q = text_of_content(o.get('content', []))
                if q.strip():
                    turns.append({'query': q, 'outputs': []})
            elif itype == 'agentMessage':
                txt = o.get('text') or text_of_content(o.get('content', []))
                if txt and txt.strip():
                    if not turns:
                        turns.append({'query': '', 'outputs': []})
                    turns[-1]['outputs'].append(txt)
        out.append({'id': tid, 'system': 'OpenAI ChatGPT (Codex agent)',
                    'model': 'GPT-5-based Codex profile (app label gpt-6-astra)',
                    'cwd': '', 'title': 'UPC session', 'turns': turns})
    return out


def main():
    os.makedirs(WORK, exist_ok=True)
    data = {'generated': datetime.datetime.now().isoformat(timespec='seconds'),
            'sessions': codex_threads() + dsh_sessions()}
    json.dump(data, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    tq = to = 0
    for s in data['sessions']:
        q = sum(len(t['query']) for t in s['turns'])
        o = sum(len(x) for t in s['turns'] for x in t['outputs'])
        tq += q; to += o
        print(f"{s['system'][:18]:18s} {s['id'][:44]:44s} turns={len(s['turns']):3d} "
              f"query_chars={q:7d} output_chars={o:7d}")
    print(f'TOTAL query chars={tq} output chars={to} -> {OUT}')


if __name__ == '__main__':
    main()
