$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $project '.venv'
$local = ConvertFrom-StringData ((Get-Content -LiteralPath (Join-Path $project '.env') -Raw).Replace("`r", ''))
$env:RUSTFS_ACCESS_KEY = $local.MINIO_ACCESS_KEY
$env:RUSTFS_SECRET_KEY = $local.MINIO_SECRET_KEY
$env:RUSTFS_CONSOLE_ENABLE = 'false'
try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:59000/health' -TimeoutSec 2 | Out-Null
    Write-Output 'Storage already running.'
} catch {
    $process = Start-Process -FilePath (Join-Path $runtime 'rustfs/rustfs.exe') -WorkingDirectory $runtime -WindowStyle Hidden -PassThru `
        -ArgumentList @('server', '--address', '0.0.0.0:59000', 'rustfs-data') `
        -RedirectStandardOutput (Join-Path $runtime 'rustfs.log') `
        -RedirectStandardError (Join-Path $runtime 'rustfs-error.log')
    Set-Content -LiteralPath (Join-Path $runtime 'benchmarks/storage.pid') -Value $process.Id
    Write-Output "Started storage PID $($process.Id)."
}
