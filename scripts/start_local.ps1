param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$webRoot = Join-Path $repoRoot "web"
$runRoot = Join-Path $repoRoot ".local-run"
$nextCli = Join-Path $webRoot "node_modules\next\dist\bin\next"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python não foi encontrado no PATH."
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js não foi encontrado no PATH."
}
if (-not (Test-Path -LiteralPath $nextCli -PathType Leaf)) {
    throw "Dependências do frontend ausentes. Execute 'cd web; npm install' uma vez."
}

Push-Location $repoRoot
try {
    & python -c "import fastapi, uvicorn, norgatedata" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Dependências Python ausentes. Instale o projeto com 'python -m pip install -e .[api,norgate]'."
    }
    & python -c "import norgatedata as nd; raise SystemExit(0 if nd.status() else 1)" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "O Norgate Data Updater não está disponível. Abra o NDU e tente novamente."
    }
} finally {
    Pop-Location
}

New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$apiOut = Join-Path $runRoot "api-$stamp.out.log"
$apiErr = Join-Path $runRoot "api-$stamp.err.log"
$webOut = Join-Path $runRoot "web-$stamp.out.log"
$webErr = Join-Path $runRoot "web-$stamp.err.log"

$apiProcess = $null
$webProcess = $null

try {
    $apiProcess = Start-Process -FilePath "python" -ArgumentList @("-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr -PassThru
    $webProcess = Start-Process -FilePath "node" -ArgumentList @($nextCli, "dev", "--hostname", "127.0.0.1", "--port", "3000", "--webpack") -WorkingDirectory $webRoot -WindowStyle Hidden -RedirectStandardOutput $webOut -RedirectStandardError $webErr -PassThru

    $apiReady = $false
    $webReady = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        if ($apiProcess.HasExited) { throw "A API encerrou durante a inicialização. Consulte $apiErr" }
        if ($webProcess.HasExited) { throw "O frontend encerrou durante a inicialização. Consulte $webErr" }
        if (-not $apiReady) {
            try { $apiReady = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2).StatusCode -eq 200 } catch { $apiReady = $false }
        }
        if (-not $webReady) {
            try { $webReady = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:3000" -TimeoutSec 2).StatusCode -eq 200 } catch { $webReady = $false }
        }
        if ($apiReady -and $webReady) { break }
        Start-Sleep -Seconds 1
    }
    if (-not ($apiReady -and $webReady)) {
        throw "Os serviços não ficaram prontos em 90 segundos. Logs: $runRoot"
    }

    Write-Host ""
    Write-Host "RSI2 Research Lab está pronto." -ForegroundColor Green
    Write-Host "Frontend: http://127.0.0.1:3000"
    Write-Host "API/docs: http://127.0.0.1:8000/docs"
    Write-Host "Logs: $runRoot"
    Write-Host "Pressione Ctrl+C para encerrar os dois serviços."
    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:3000"
    }

    while (-not $apiProcess.HasExited -and -not $webProcess.HasExited) {
        Start-Sleep -Seconds 1
    }
    if ($apiProcess.HasExited) { throw "A API foi encerrada inesperadamente. Consulte $apiErr" }
    if ($webProcess.HasExited) { throw "O frontend foi encerrado inesperadamente. Consulte $webErr" }
} finally {
    if ($webProcess -and -not $webProcess.HasExited) { Stop-Process -Id $webProcess.Id }
    if ($apiProcess -and -not $apiProcess.HasExited) { Stop-Process -Id $apiProcess.Id }
}
