# Google Drive, Supabase y Render

Preparado el 13 de noviembre de 2026 para `Edithson1/VisionText-backend`.

## Implementación

- El backend selecciona `s3` para la instalación local o `google_drive` para
  Render. Los endpoints de búsqueda, archivos y administración se conservan.
- Drive utiliza OAuth de usuario con permiso `drive.file`. Sus archivos no se
  publican mediante permisos de Drive. La API existente sirve el catálogo a sus clientes.
- Se crea/reutiliza `VisionText/imagenes` y `VisionText/miniaturas`, con etiquetas
  del proyecto y un ID de carpeta persistido en la configuración.
- PostgreSQL guarda los IDs devueltos por Drive. Las subidas que fallan después
  de crear un archivo intentan limpiar los archivos creados. Un borrado remoto
  fallido conserva el registro del catálogo para poder reintentarlo.
- El catálogo identifica su proveedor de archivos. Cambiar de proveedor con una
  base que contiene archivos del otro proveedor se rechaza para evitar enlaces rotos.
- La conexión de Supabase admite campos separados y TLS, así como URLs
  PostgreSQL normalizadas para asyncpg. Los secretos no se incluyen en el código.

## Verificado en el proyecto Supabase

El conector identificó el proyecto `VisionText` como `ACTIVE_HEALTHY`, región
`us-east-2`. Se aplicó `initialize_private_visiontext_catalog`, con el SQL
revisable en `supabase/schema.sql`. La consulta posterior confirmó:

| Comprobación | Resultado |
|---|---|
| Tabla `public.images` | Creada |
| RLS | Activado |
| Lectura directa de `anon` | Denegada |
| Lectura directa de `authenticated` | Denegada |
| Registros iniciales | 0 |

El asesor informó únicamente `rls_enabled_no_policy` a nivel informativo. Es
intencional: el catálogo se consulta mediante FastAPI usando su conexión de
backend, sin políticas para clientes Data API.
[Referencia del aviso](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy).

## Pruebas de la integración

La suite local completó **46 pruebas correctas** el 13 de noviembre de 2026.

Los tests ejecutan llamadas HTTP reales contra un servidor local de prueba que
modela las rutas de Drive y OAuth. Comprueban carpetas sin duplicación, acceso
por IDs después de recrear el cliente, paginación, multipart/related, renovación
de token y reintento por 401, errores 403/429/503, timeout, limpieza de subidas
fallidas y borrado reintentable. También se conserva la suite anterior del backend.

Esto establece compatibilidad con los contratos simulados. No verifica permisos,
consentimiento, cuota ni la cuenta real de Google. El descubridor público Orbit
devolvió HTTP 403; se consultó la documentación oficial de Google como fuente.
El CLI de Postman no estaba instalado; las pruebas usan el servidor HTTP local y pytest.

La [CI](../.github/workflows/ci.yml) compila la imagen Docker de producción,
ejecuta la suite y prueba la API con CLIP real, PostgreSQL 17 y Drive/OAuth
simulados bajo `--memory=512000000 --memory-swap=512000000`. Las pruebas incluyen
subida, búsqueda por texto e imagen, descarga, validación, una imagen de 4 MP,
cuatro búsquedas simultáneas y borrado. Los logs del workflow muestran los
contadores reales de memoria del cgroup.

## Lo que requiere los valores privados del propietario

1. Autorizar una vez la cuenta Google con `scripts/authorize_google_drive.py`.
   Este paso crea la carpeta **real** y guarda sus variables en `.env.drive`,
   excluido de Git y Docker. Aún no se ha ejecutado contra la cuenta real.
2. Completar el secreto de Google, refresh token y contraseña PostgreSQL en Render.
3. Desplegar el Blueprint y comprobar `/api/health`. La consulta del conector
   Supabase confirma el esquema, pero no prueba la contraseña que usarás en Render.

La guía completa está en [DEPLOY-RENDER-DRIVE.md](../DEPLOY-RENDER-DRIVE.md).
