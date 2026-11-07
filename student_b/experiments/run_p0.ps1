# P0 reproducible runner: diagnostics + five-arm ablation.
# Usage:  powershell -ExecutionPolicy Bypass -File student_b\experiments\run_p0.ps1
$ErrorActionPreference = "Stop"
$py = "E:\SJTU2026\threebody\upc155-venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "venv python not found: $py (see CONFIG.md section 5)" }

Push-Location (Join-Path $PSScriptRoot "..")
try {
    Write-Host "== diagnostics (todo 1.1-1.8) =="
    & $py experiments\diagnostics.py
    Write-Host "== five-arm ablation (todo 2) =="
    & $py experiments\ablation.py
} finally {
    Pop-Location
}
