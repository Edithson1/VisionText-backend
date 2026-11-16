# Publicar VisionText en Render con Google Drive y Supabase

Repositorio: https://github.com/Edithson1/VisionText-backend

Render ejecuta FastAPI y el modelo ONNX Q8. Google Drive conserva las imágenes
y miniaturas. Supabase conserva el catálogo, las descripciones, los IDs de Drive
y los vectores para reconstruir la búsqueda. Los archivos de Drive no se hacen
públicos: la web y Android siguen usando las URLs de la API del catálogo.

La organización de archivos privados está en [ENVIRONMENT.md](ENVIRONMENT.md).
Tu contraseña de Supabase se escribe en **`.env.render`, variable `POSTGRES_PASSWORD`**.
Las plantillas `.example` se conservan sin secretos.

La web publicada es `https://visiontext-sigma.vercel.app`. El Blueprint incluye ese
origen exacto en `CORS_ORIGINS`, junto con localhost para desarrollo. Si el Blueprint
no se sincroniza automáticamente, aplica su actualización desde Render o configura
esa misma lista en las variables de entorno del servicio y despliega el cambio.

## 1. Autorizar Google Drive y crear la carpeta

El ID de cliente está preparado en los ejemplos. El secreto del cliente y el
refresh token van en variables privadas. El refresh token permite que Render
acceda a la cuenta autorizada cuando tú no estás conectado.

1. En el proyecto de Google Cloud de ese cliente, habilita **Google Drive API**.
2. El cliente OAuth debe ser de tipo **Aplicación web**. En sus **URIs de
   redireccionamiento autorizadas**, agrega exactamente `http://localhost:8765/`.
3. Configura el consentimiento para el permiso `https://www.googleapis.com/auth/drive.file`.
   Si la aplicación está en pruebas, incluye tu cuenta como usuario de prueba.
4. Desde la carpeta del backend ejecuta en una terminal propia:

   ```powershell
   .\.venv\windows\Scripts\python.exe scripts\authorize_google_drive.py
   ```

   En otro equipo, crea un entorno con Python 3.12 e instala
   `python -m pip install -r requirements-dev.txt`; usa `python` para ese comando.

5. El script utiliza `GOOGLE_DRIVE_CLIENT_SECRET` si ya está en tu entorno. Si
   falta, te lo pide de forma oculta en la terminal. Abre el enlace que imprime
   y autoriza la cuenta que guardará los archivos.
6. Al terminar, el script crea esta estructura y guarda las variables privadas
   en `.env.drive`, excluido de Git y Docker:

   ```text
   VisionText/
   ├── imagenes/
   └── miniaturas/
   ```

   La carpeta se identifica también con etiquetas internas del proyecto. El
   backend reutiliza la misma estructura al reiniciarse, aunque cambies su nombre.

Copia a Render los valores de `GOOGLE_DRIVE_CLIENT_SECRET`,
`GOOGLE_DRIVE_REFRESH_TOKEN` y `GOOGLE_DRIVE_FOLDER_ID` que contiene `.env.drive`.
No incluyas las comillas que usa el archivo para delimitar los valores.

El autorizador prepara también `.env.render` con esos valores. Si ya autorizaste
Google con una versión anterior del asistente, ejecuta:

```powershell
.\.venv\windows\Scripts\python.exe scripts\prepare_render_env.py
```

Así completas la configuración de nube en un solo archivo privado: `.env.render`.

Si Google mantiene una app externa en estado **Testing**, los refresh tokens de
Drive pueden caducar a los siete días. Para uso continuo configura el estado de
publicación apropiado o vuelve a autorizar la cuenta cuando sea necesario.
[Caducidad de tokens](https://developers.google.com/identity/protocols/oauth2#expiration)

## 2. Configurar Supabase

El proyecto existente es **VisionText**, referencia `rallvjbmmlezptdhtfzx`.
Se preparó `public.images`, con RLS activado y sin permisos de lectura o escritura
para `anon` ni `authenticated`. La aplicación usa su propia autorización FastAPI
y se conecta directamente por PostgreSQL; no necesita la clave `service_role`.
El esquema revisable está en [supabase/schema.sql](supabase/schema.sql).

En Render usa los campos separados de tu `.env.render`, generado desde
[.env.render.example](.env.render.example):

| Variable | Valor |
|---|---|
| `POSTGRES_HOST` | `aws-0-us-east-2.pooler.supabase.com` |
| `POSTGRES_PORT` | `5432` |
| `POSTGRES_DB` | `postgres` |
| `POSTGRES_USER` | `postgres.rallvjbmmlezptdhtfzx` |
| `POSTGRES_SSL` | `require` |
| `POSTGRES_PASSWORD` | La contraseña **de PostgreSQL** de este proyecto |

La contraseña de PostgreSQL es distinta del secreto OAuth de Google. Estos
campos aceptan la contraseña directamente, incluidos caracteres como `@` o `#`.
El backend construye la URL con el escape correcto. El puerto 5432 del pooler
usa modo **Session**, apropiado para este servidor con conexiones persistentes.
[Conexiones de Supabase](https://supabase.com/docs/guides/database/connecting-to-postgres)

Si prefieres `POSTGRES_URL`, admite `postgresql://` y
`postgresql+asyncpg://`; convierte `sslmode=require` en el parámetro de asyncpg.
**No dejes un POSTGRES_URL antiguo junto con los campos separados**: tiene prioridad.

## 3. Crear el servicio en Render

Importa este repositorio como un **Blueprint** y usa [render.yaml](render.yaml).
También puedes crear un Web Service manual con runtime Docker, rama `main`,
plan Free y health check `/api/health`. Los modelos se preparan durante el build;
el arranque no requiere descargar sus pesos.

El Blueprint ya indica el cliente Google, el pooler de Supabase y ONNX Q8. Completa:

| Variable privada o específica del despliegue | Cómo completarla |
|---|---|
| `POSTGRES_PASSWORD` | Contraseña de PostgreSQL |
| `GOOGLE_DRIVE_CLIENT_SECRET` | Secreto del cliente Google |
| `GOOGLE_DRIVE_REFRESH_TOKEN` | Valor de `.env.drive` tras autorizar |
| `GOOGLE_DRIVE_FOLDER_ID` | ID de la carpeta creada por el autorizador |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | Credenciales para Subir y Admin |
| `JWT_SECRET_KEY` | El Blueprint genera una; consérvala entre despliegues |
| `BASE_URL` | URL pública HTTPS de tu servicio, sin barra final |
| `CORS_ORIGINS` | Origen de Vercel; para pruebas también admite localhost |

No necesitas `MINIO_ENDPOINT`, claves MinIO ni Supabase Storage en este perfil.
El modo S3 sigue disponible para la instalación local con `STORAGE_BACKEND=s3`.

## 4. Comprobar y cargar imágenes

Cuando el servicio esté listo, `/api/health` debe indicar `status: healthy`,
`storage_provider: google_drive` y conexiones disponibles. Inicia sesión en la
web o Android, sube una imagen y busca por texto y por imagen. En
`/api/admin/storage`, con token de administrador, puedes comprobar la carpeta y
el número de archivos.

El catálogo de Supabase comienza vacío. Las 45 imágenes de la instalación local
no se transfieren automáticamente: se conservan en su base local y en RustFS.
Para copiar ese catálogo conservando los nombres y descripciones, utiliza
[MIGRAR-CATALOGO.md](MIGRAR-CATALOGO.md). La copia se realiza explícitamente por la
API, y se comprueba que los originales, miniaturas y vectores queden disponibles.
En este proyecto esa copia se completó el 15 de noviembre de 2026: 45 imágenes,
45 miniaturas y 45 vectores. [Resultado verificado](reports/MIGRACION-LOCAL-NUBE.md).
Después se cargó el dataset completo de 1.575 imágenes. Consulta
[IMPORTAR-DATASET.md](IMPORTAR-DATASET.md) y el
[informe de la carga completa](reports/DATASET-COMPLETO.md).
Puedes subirlas a la nube desde la app o ejecutar el cargador existente contra
la URL del backend, con las credenciales del administrador de ese despliegue:

```powershell
$env:LOAD_API_URL = 'https://TU-SERVICIO.onrender.com'
$env:LOAD_ADMIN_USERNAME = 'admin'
$env:LOAD_ADMIN_PASSWORD = Read-Host 'Contraseña del administrador en Render' -MaskInput
.\.venv\windows\Scripts\python.exe load_dataset.py
```

Los archivos se identifican por UUID, y el catálogo conserva el nombre original.
Las nuevas imágenes se limitan a 4 millones de píxeles y se almacenan en JPEG
con un lado máximo de 1600 píxeles. Render conserva una copia reconstruible del
índice; PostgreSQL y Drive conservan los datos duraderos.

## Evidencia y pendientes

- Proyecto Supabase consultado mediante su conector y esquema preparado allí.
- Imagen Docker compilada y 46 pruebas correctas en Windows y Linux. La
  [prueba de integración](https://github.com/Edithson1/VisionText-backend/actions/runs/43551289437)
  con CLIP real y Drive simulado pasó bajo 512 MB sin swap: pico de 422,9 MB y cero OOM.
- Operaciones Drive probadas contra un servidor HTTP local que reproduce las
  rutas oficiales, incluyendo OAuth refresh, carpetas, paginación, carga,
  lectura, borrado, 401, 403, 429, 503 y timeout.
- La cuenta Google real debe autorizarse con el comando del paso 1. Sin ese
  consentimiento no se puede crear la carpeta real ni probar archivos en tu Drive.
- La conexión PostgreSQL desde Render requiere la contraseña que tú configurarás;
  la consulta mediante el conector no sustituye esa prueba de credenciales.
- Las mediciones previas de memoria están en [reports/COMPARACION-RENDER.md](reports/COMPARACION-RENDER.md).
  Los resultados de integración de esta versión se documentan en [reports/INTEGRACION-DRIVE.md](reports/INTEGRACION-DRIVE.md).
