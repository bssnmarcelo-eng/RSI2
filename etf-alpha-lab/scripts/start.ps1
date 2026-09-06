$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:NORGATEDATA_ROOT = Join-Path $projectRoot '.norgate'
New-Item -ItemType Directory -Force -Path $env:NORGATEDATA_ROOT | Out-Null
Set-Location $projectRoot
python -m streamlit run app.py
