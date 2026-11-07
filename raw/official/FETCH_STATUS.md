---
time: "2026-10-23"
---

# UPC official crawl — STATUS / INCIDENT LOG
date: 2026-10-23 (Asia/Shanghai)
target: https://www.uphysicsc.com
tool: `mcp__web-search-safe__web_fetch` (the built-in `web_fetch` tool cannot reach this host at all — "TypeError: fetch failed")

## What was captured (real fetches, HTTP 200)

| page | file | status | notes |
|---|---|---|---|
| home.html | home.md | OK | full body text captured |
| 2026contest.html | 2026-contest.md | OK | announcement only; problems not yet published |
| 2025contest.html | 2025-contest.md | OK (2nd attempt; 1st timed out) | complete Problem A + B verbatim + all 16 gold teams + medal counts |
| contestrules.html | contestrules.md | OK — but fetched by a PARALLEL agent at 11:28:25, not by this session | rule text including early-registration rule; contains NO dollar amount |

## What failed — site-wide outage / rate-limit ban

Every other contest page returned **HTTP 502 Bad Gateway** (OpenResty/nginx error page:
"An error occurred. Sorry, the page you are looking for is currently unavailable."),
and the final attempt degraded to a plain request timeout.

Chronology (local time):
- 11:28–11:32 — home.html, 2026contest.html, 2025contest.html all succeed.
- 11:33 — registerateam.html → 502 (retry at 11:35 → 502 again).
- 11:36 — 2024contest.html → 502.
- 11:37 — 2023contest.html → 502.
- 11:38 — 2019contest.html → 502.
- 11:39 (after a 95 s cooldown) — 2024contest.html → request timeout.

Interpretation: 4 successful page loads were followed by total failure of the origin
for every path. Most likely a WAF/rate-limit ban triggered by this crawl (and by
parallel sibling agents hitting the same host), or the origin host went down.
It is NOT a per-page or per-year condition — 2023/2024/2019 are ordinary pages.

## Consequences for the research report

1. **Problem statements for 2010–2024 are MISSING.** The `YYYY-contest.md` files for
   those years exist but are explicit `FETCH FAILED` placeholders. They must NOT be
   filled from memory — the whole point was first-hand verbatim text.
2. **Registration fee amounts are MISSING.** `registerateam.html` never loaded (502 twice).
   Known from contestrules.md (verbatim): *"All teams must be officially registered on this
   website and pay the registration fee at least six hours before the contest begins.
   Early registration, at a reduced registration fee, must be completed at least 7 days
   before the contest begins."* — the actual dollar figures, the early-vs-regular
   differential, and the payment method are NOT yet known.
3. `web.archive.org` (Wayback) and `r.jina.ai` are both unreachable from this sandbox
   (DNS `EAI_AGAIN` / `ECONNRESET`), so the pages could not be recovered from a mirror.

## Recommended recovery procedure (when the site is back)

- Use ONE request at a time, 45–60 s apart; a fresh IP/session may be required if the
  current one is banned.
- Order of value: registerateam.html (fee) → 2019–2024 (recent problems) → 2010–2018.
- If a fetch reports `"truncated": true`, the complete response is written to a spill file
  under `%LOCALAPPDATA%\Temp\dsh-spill-*\...-mcp__web-search-safe__web_fetch.txt`;
  clean that file to recover the tail (this is how 2025's gold list was completed).
