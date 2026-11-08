# Rebuild the AI-use report and the final paper PDF.
#
# Usage (PowerShell, from anywhere):
#   powershell -ExecutionPolicy Bypass -File tools\build_ai_report.ps1
#
# Steps:
#   1. copy the local Codex/ChatGPT thread database to %TEMP%\th_latest2.sqlite
#   2. decompress the local DSH session logs into ai_logs\_work\dsh_sessions
#   3. extract visible queries/outputs into ai_logs\_work\ai_usage_extract.json
#   4. regenerate the ai-report LaTeX source and the plain-text log copy
#   5. compile ai-report.pdf with XeLaTeX (two passes)
#   6. compile main.pdf with pdfLaTeX (two passes) and copy it to 155B.pdf
#
# Local log sources (not in the repository):
#   %USERPROFILE%\.codex\thread_history_1.sqlite
#   %USERPROFILE%\.dsh\sessions\**
# Requirements: Python 3 (standard library only), Node.js >= 22.15, MiKTeX/TeX Live.

$ErrorActionPreference = 'Stop'

$toolsDir = $PSScriptRoot                      # ...\UPC155\tools
$root = Split-Path -Parent $toolsDir           # ...\UPC155
$work = Join-Path $root 'ai_logs\_work'

# Locate the paper directory without relying on non-ASCII path literals.
$mainTex = Get-ChildItem -Path $root -Recurse -Filter 'main.tex' -File -ErrorAction SilentlyContinue |
           Where-Object { $_.DirectoryName -ne $root } | Select-Object -First 1
if (-not $mainTex) { throw 'main.tex not found under the repository root' }
$texDir = $mainTex.DirectoryName

$py = 'C:/Users/pc/miniconda3/envs/mujoco/python.exe'
if (-not (Test-Path $py)) { $py = 'python' }

New-Item -ItemType Directory -Force -Path $work | Out-Null

Write-Host '[1/6] copying Codex thread database'
$db = Join-Path $env:USERPROFILE '.codex\thread_history_1.sqlite'
if (Test-Path $db) {
  Copy-Item $db (Join-Path $env:TEMP 'th_latest2.sqlite') -Force
  foreach ($suf in @('-wal', '-shm')) {
    $f = "$db$suf"
    if (Test-Path $f) { Copy-Item $f (Join-Path $env:TEMP "th_latest2.sqlite$suf") -Force }
  }
} else {
  Write-Warning "Codex thread database not found: $db (the report will omit ChatGPT/Codex logs)"
}

Write-Host '[2/6] decompressing DSH session logs'
$sessionsRoot = Join-Path $env:USERPROFILE '.dsh\sessions'
if (Test-Path $sessionsRoot) {
  node (Join-Path $toolsDir 'ai_usage\decompress_dsh_sessions.js') $sessionsRoot (Join-Path $work 'dsh_sessions')
} else {
  Write-Warning "DSH session directory not found: $sessionsRoot"
}

Write-Host '[3/6] extracting visible queries and outputs'
& $py -X utf8 (Join-Path $toolsDir 'ai_usage\extract_ai_usage.py')

Write-Host '[4/6] regenerating the ai-report LaTeX source'
& $py -X utf8 (Join-Path $toolsDir 'ai_usage\make_ai_report.py')

$xe = 'xelatex'
if (-not (Get-Command xelatex -ErrorAction SilentlyContinue)) {
  if (Test-Path 'C:\texlive\2026\bin\windows\xelatex.exe') { $xe = 'C:\texlive\2026\bin\windows\xelatex.exe' }
  else { throw 'xelatex not found' }
}
$pdflatex = 'pdflatex'
if (-not (Get-Command pdflatex -ErrorAction SilentlyContinue)) {
  if (Test-Path 'C:\texlive\2026\bin\windows\pdflatex.exe') { $pdflatex = 'C:\texlive\2026\bin\windows\pdflatex.exe' }
  else { throw 'pdflatex not found' }
}

Write-Host '[5/6] compiling ai-report.pdf (XeLaTeX, two passes)'
Push-Location $texDir
try {
  & $xe -interaction=nonstopmode -halt-on-error ai-report.tex | Out-Null
  & $xe -interaction=nonstopmode -halt-on-error ai-report.tex | Out-Null
} finally { Pop-Location }

Write-Host '[6/6] compiling main.pdf (pdfLaTeX, two passes) and creating 155B.pdf'
Push-Location $texDir
try {
  & $pdflatex -interaction=nonstopmode -halt-on-error main.tex | Out-Null
  & $pdflatex -interaction=nonstopmode -halt-on-error main.tex | Out-Null
  Copy-Item 'main.pdf' '155B.pdf' -Force
} finally { Pop-Location }

Write-Host 'Done. Final file: 155B.pdf in the paper directory.'
Write-Host 'Before submission: fill ai-report-team.tex with other team members AI records.'
