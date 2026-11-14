param([switch]$LoadDataset, [ValidateSet('onnx', 'torch')][string]$Backend = 'onnx')

$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$runtime = Join-Path $project '.venv'
$python = Join-Path $runtime 'windows\Scripts\python.exe'
$storage = Join-Path $runtime 'rustfs\rustfs.exe'
$envFile = Join-Path $project '.env'

foreach ($path in @($python, $storage, $envFile)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Falta $path. Consulta README.md para configurar el backend local."
    }
}

$settings = ConvertFrom-StringData ((Get-Content -LiteralPath $envFile -Raw).Replace("`r", ''))
$env:ADMIN_USERNAME = $settings.ADMIN_USERNAME
$env:ADMIN_PASSWORD = $settings.ADMIN_PASSWORD
$env:PYTHONUTF8 = '1'

if ($LoadDataset) {
    if (-not $env:LOAD_API_URL) { $env:LOAD_API_URL = 'http://127.0.0.1:8000' }
    & $python (Join-Path $project 'load_dataset.py')
    exit $LASTEXITCODE
}

$env:JWT_SECRET_KEY = $settings.JWT_SECRET_KEY
$env:POSTGRES_URL = 'postgresql+asyncpg://visiontext:{0}@127.0.0.1:55432/visiontext' -f [uri]::EscapeDataString($settings.POSTGRES_PASSWORD)
$env:MINIO_ENDPOINT = '127.0.0.1:59000'
$env:MINIO_ACCESS_KEY = $settings.MINIO_ACCESS_KEY
$env:MINIO_SECRET_KEY = $settings.MINIO_SECRET_KEY
$env:RUSTFS_ACCESS_KEY = $settings.MINIO_ACCESS_KEY
$env:RUSTFS_SECRET_KEY = $settings.MINIO_SECRET_KEY
$env:RUSTFS_CONSOLE_ENABLE = 'false'
$env:CLIP_MODEL = 'ViT-B-32'
$env:CLIP_BACKEND = $Backend
$env:CLIP_PRETRAINED = 'openai'
$env:CACHE_DIR = Join-Path $project 'model_cache'
$env:ONNX_MODEL_DIR = Join-Path $env:CACHE_DIR 'onnx'
$env:ONNX_PRECISION = 'q8f16'
if ($Backend -eq 'onnx') {
    & $python (Join-Path $project 'scripts/prepare_onnx.py') --directory $env:ONNX_MODEL_DIR
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron preparar los modelos ONNX.' }
}
$checkpoint = Join-Path $env:CACHE_DIR 'ViT-B-32.pt'
if (Test-Path -LiteralPath $checkpoint -PathType Leaf) { $env:CLIP_CHECKPOINT = $checkpoint }
$env:FAISS_INDEX_PATH = Join-Path $project 'faiss_indices\faiss_index.bin'
$env:CORS_ORIGINS = 'http://localhost:5173,http://127.0.0.1:5173'
$env:BASE_URL = 'http://localhost:8000'
$env:INFERENCE_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:PYTHONUNBUFFERED = '1'

$storageProcess = $null
Push-Location -LiteralPath $project
try {
    wsl.exe -d Ubuntu --exec bash './scripts/postgres-local.sh'
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo iniciar PostgreSQL en Ubuntu.' }

    try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:59000/health' -TimeoutSec 2 | Out-Null
    } catch {
        New-Item -ItemType Directory -Path (Join-Path $runtime 'rustfs-data') -Force | Out-Null
        $storageProcess = Start-Process -FilePath $storage -WorkingDirectory $runtime -WindowStyle Hidden -PassThru `
            -ArgumentList @('server', '--address', $env:MINIO_ENDPOINT, 'rustfs-data') `
            -RedirectStandardOutput (Join-Path $runtime 'rustfs.log') `
            -RedirectStandardError (Join-Path $runtime 'rustfs-error.log')
        $ready = $false
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            try {
                Invoke-RestMethod -Uri 'http://127.0.0.1:59000/health' -TimeoutSec 1 | Out-Null
                $ready = $true
                break
            } catch {
                if ($storageProcess.HasExited) { break }
                Start-Sleep -Milliseconds 300
            }
        }
        if (-not $ready) { throw 'No se pudo iniciar el almacenamiento local. Revisa .venv\rustfs-error.log.' }
    }

    # Compose utiliza .env para interpolar su propia configuración. El proceso nativo
    # recibe las variables de la API y arranca desde .venv para no leerlo de nuevo.
    Set-Location -LiteralPath $runtime
    & $python -m uvicorn main:app --app-dir $project --host 127.0.0.1 --port 8000 --workers 1
    if ($LASTEXITCODE -ne 0) { throw "Uvicorn terminó con código $LASTEXITCODE." }
} finally {
    if ($storageProcess -and -not $storageProcess.HasExited) { $storageProcess.Kill() }
    Pop-Location
}
