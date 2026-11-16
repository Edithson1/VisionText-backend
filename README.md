# VisionText
Sistema que integra un modelo multimodal CLIP, permitiendo la interpretación y relación de imágenes y texto de manera interactiva.

- Despliegue en Railway, CI/CD y referencia de endpoints: [DEPLOY.md](DEPLOY.md)
- Variables de entorno y contraseña de Supabase: [ENVIRONMENT.md](ENVIRONMENT.md).
- Plantillas públicas: [.env.example](.env.example) (local) y [.env.render.example](.env.render.example) (nube).
- Medición del perfil ligero y límites de Render: [reports/COMPARACION-RENDER.md](reports/COMPARACION-RENDER.md)
- Despliegue preparado para **Edithson1/VisionText-backend**: [Render + Google Drive + Supabase](DEPLOY-RENDER-DRIVE.md).
- Carga y verificación del dataset de 1.575 imágenes: [IMPORTAR-DATASET.md](IMPORTAR-DATASET.md).

## Perfil ligero de inferencia

El perfil predeterminado usa CLIP `ViT-B-32` en ONNX Runtime con pesos Q8 y
activaciones en punto flotante (`ONNX_PRECISION=q8f16`). La imagen de producción instala
`requirements.txt`, sin PyTorch, y descarga los dos modelos fijados por revisión
durante la compilación. Conserva la búsqueda por texto e imagen, la validación de
descripciones, la autenticación y la administración.

Para preparar un entorno nuevo:

```powershell
python -m pip install -r requirements-dev.txt
python scripts/prepare_onnx.py
```

La configuración limita la inferencia a una solicitud a la vez, acepta imágenes
de hasta 4 millones de píxeles y 10 MiB, y guarda las nuevas imágenes con un lado
máximo de 1600 píxeles. Una imagen que supera el límite de píxeles recibe HTTP 413.
Los vectores guardan el identificador del motor: el primer arranque migra los
vectores antiguos por lotes, y los siguientes arranques reconstruyen FAISS desde
PostgreSQL sin volver a procesar las imágenes.

`requirements-torch.txt` conserva las dependencias del motor anterior para
comparaciones. En este equipo puede iniciarse con `./Start-Local.ps1 -Backend torch`;
el valor predeterminado de `./Start-Local.ps1` es `onnx`. Cambiar el motor obliga a
regenerar los vectores del catálogo.

## Render

El [Blueprint](render.yaml) prepara un servicio Docker Free con un único proceso,
el catálogo en el proyecto existente de Supabase y los archivos en Google Drive.
El [autorizador](scripts/authorize_google_drive.py) crea una carpeta `VisionText`
con `imagenes` y `miniaturas`, y obtiene el acceso sin conexión para Render.
Completa los secretos con la [guía de despliegue](DEPLOY-RENDER-DRIVE.md).
`BASE_URL` debe ser la URL pública de la API, y `CORS_ORIGINS` los orígenes de la web.

El disco de Render Free es temporal. Las imágenes y los vectores quedan en los
servicios externos; el índice local se puede reconstruir. El consumo y la cuota
de esos servicios se evalúan por separado. Consulta el informe antes de usar este
perfil con un catálogo más grande.

## Arranque en este equipo Windows

Desde esta carpeta, ejecuta `./Start-Local.ps1` en PowerShell. La instalación
local usa el entorno Python preparado en `.venv`, RustFS para los objetos S3 y
PostgreSQL portable en Ubuntu WSL. La API escucha en `http://localhost:8000`.
El motor ONNX usa FAISS directamente. El motor opcional de PyTorch utiliza el
mismo producto interno con NumPy en Windows para evitar un conflicto entre sus
bibliotecas OpenMP. Docker Compose ofrece una instalación alternativa para otro equipo.

Para cargar el resto del dataset con la API en ejecución, abre una segunda
terminal y ejecuta `./Start-Local.ps1 -LoadDataset`. El cargador salta los nombres
que ya existen. Las credenciales de administrador están en `.env`.

## Backend local con Docker Desktop

Desde esta carpeta, con Docker Desktop abierto, ejecuta:

```powershell
docker compose up -d --build
docker compose logs -f backend
```

El servicio está listo cuando [el estado del backend](http://localhost:8000/api/health)
responde con `status: healthy`. La compilación descarga las dependencias y los
pesos Q8 de CLIP; los pesos se incluyen en la imagen. PostgreSQL, el almacenamiento
S3 de MinIO y el índice usan volúmenes de Docker.

El archivo `.env` local contiene las credenciales de desarrollo. Si falta, créalo
con estas variables y sustituye cada marcador por un valor aleatorio hexadecimal
distinto. Usa `ADMIN_USERNAME` y `ADMIN_PASSWORD` para iniciar sesión en la web o
en la app.

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD=REEMPLAZAR
JWT_SECRET_KEY=REEMPLAZAR
POSTGRES_PASSWORD=REEMPLAZAR
MINIO_ACCESS_KEY=visiontext-local
MINIO_SECRET_KEY=REEMPLAZAR
```

Para indexar las imágenes del repositorio después del arranque:

```powershell
docker compose exec backend python load_dataset.py
```

La carga usa la API real y mantiene actualizado el índice de búsqueda. Se puede
reanudar con el mismo comando. Para detener los servicios conservando los datos,
ejecuta `docker compose down`.
