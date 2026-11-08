param(
    [string]$Python = 'python',
    [string]$Out = (Join-Path $PSScriptRoot '..\..\student_b\runs\asai_transfer'),
    [ValidateSet('transfer', 'estimators', 'all')]
    [string]$Stage = 'all'
)

# Run the Asai external-transfer + matched-estimator experiment from the
# repository root. Requires NumPy, SciPy, openpyxl (the team .venv has them).
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$script = Join-Path $root 'student_b\experiments\asai_transfer.py'

& $Python -X utf8 $script --stage $Stage --out $Out
exit $LASTEXITCODE
