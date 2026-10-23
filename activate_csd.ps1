$env:CSD_API_HOME = if ($env:CSD_API_HOME) { $env:CSD_API_HOME } else { "D:\CCDC\ccdc-software\csd-python-api" }
$envPath = Join-Path $env:CSD_API_HOME "miniconda\Scripts\Activate.ps1"
if (Test-Path $envPath) {
    & $envPath
} else {
    Write-Warning "CSD Python activation script not found: $envPath"
}
Set-Location $PSScriptRoot
Write-Host "CSD Python API 环境已启用"
python -c "import ccdc, sys; print(sys.executable); print('ccdc ok')"
