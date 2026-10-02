param(
    [ValidateSet('standard', 'hub', 'assistant')]
    [string]$Profile = 'hub',
    [switch]$Cuda,
    [switch]$Bot,
    [switch]$Overlay
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
$requirements = switch ($Profile) {
    'standard' { 'requirements.txt' }
    'hub' { 'requirements-hub.txt' }
    'assistant' { 'requirements-assistant.txt' }
}
& uv pip install --python .venv\Scripts\python.exe -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$extras = @()
if ($Cuda) { $extras += 'cuda' }
if ($Bot) { $extras += 'bot' }
if ($Overlay) { $extras += 'overlay' }
if ($extras.Count) {
    $target = '.[' + ($extras -join ',') + ']'
    & uv pip install --python .venv\Scripts\python.exe -e $target
    if ($LASTEXITCODE -ne 0) { throw 'Optional dependency installation failed.' }
}
Write-Host 'Installed. Run .\run.bat --check, then .\run.bat.'
Write-Host 'See docs\SETUP.md for optional integrations and account setup.'
