param(
    [string]$Python = 'python',
    [string]$Out = (Join-Path $PSScriptRoot '..\..\student-c\P1_reproduction'),
    [switch]$ModelComparison
)

$ErrorActionPreference = 'Stop'
& $Python (Join-Path $PSScriptRoot 'p1.py') --stage prepare --out $Out
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python (Join-Path $PSScriptRoot 'p1_architecture.py') --source $Out
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python (Join-Path $PSScriptRoot 'p1_figures.py') --out (Join-Path $Out 'final')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($ModelComparison) {
    & $Python (Join-Path $PSScriptRoot 'p1_model_comparison.py') --out (Join-Path $Out 'final')
}
exit $LASTEXITCODE
