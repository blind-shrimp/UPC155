param(
    [string]$Python = 'python',
    [string]$AsaiDir = (Join-Path $env:USERPROFILE 'Desktop')
)

# Reproduce the anchored-prior simulation set and the leave-one-cohort-out audit.
# Run from the repository root. Datasets/models are written under
# student_b/runs/sim2real/ (ignored by git; regenerate with this script).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$sim = Join-Path $root 'student_b\sim2real'
$runs = Join-Path $root 'student_b\runs\sim2real'
New-Item -ItemType Directory -Force -Path $runs | Out-Null
Set-Location $root

Write-Host '== [1/5] build all-anchor candidate dataset =='
& $Python (Join-Path $sim 'build_data.py') (Join-Path $runs 'data_all') --asai-dir $AsaiDir

Write-Host '== [2/5] build leave-one-cohort-out datasets =='
& $Python (Join-Path $sim 'build_data.py') (Join-Path $runs 'data_no_asai') --exclude-cohorts asai --asai-dir $AsaiDir
& $Python (Join-Path $sim 'build_data.py') (Join-Path $runs 'data_no_dflp') --exclude-cohorts dfl_penalty --asai-dir $AsaiDir
& $Python (Join-Path $sim 'build_data.py') (Join-Path $runs 'data_no_issia') --exclude-cohorts issia --asai-dir $AsaiDir
& $Python (Join-Path $sim 'build_data.py') (Join-Path $runs 'data_prior_only') --exclude-cohorts asai dfl_penalty dfl_extra issia barber --prior-fraction 0 --asai-dir $AsaiDir

Write-Host '== [3/5] independent synthetic hold-out sets =='
& $Python (Join-Path $sim 'make_holdout.py') (Join-Path $runs 'data_all\data_manifest.json') (Join-Path $runs 'holdout') --n 4000

Write-Host '== [4/5] train one model per dataset (seed 11, 100 epochs) =='
foreach ($name in @('data_all', 'data_no_asai', 'data_no_dflp', 'data_no_issia', 'data_prior_only')) {
    & $Python (Join-Path $sim 'train.py') `
        (Join-Path $runs "$name\data.npz") (Join-Path $runs "models\$name") `
        --seed 11 --epochs 100 --asai-dir $AsaiDir
}

Write-Host '== [5/5] transfer matrix =='
& $Python (Join-Path $sim 'eval_matrix.py') (Join-Path $runs 'models') (Join-Path $runs 'eval') `
    --holdout (Join-Path $runs 'holdout') --asai-dir $AsaiDir

Write-Host 'Audit complete: results in student_b/runs/sim2real/eval/'
