param(
    [switch]$Cuda,
    [switch]$Parakeet
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install uv first (https://docs.astral.sh/uv/getting-started/installation/), then run setup.ps1 again.'
}
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & uv venv --python 3.11 .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
$extras = @()
if ($Cuda) { $extras += 'cuda' }
if ($Parakeet) { $extras += 'parakeet' }
$target = '.'
if ($extras.Count) { $target = '.[' + ($extras -join ',') + ']' }
& uv pip install --python .venv\Scripts\python.exe -e $target
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host 'Installed. Run .\run.bat --check, then .\run.bat.'
