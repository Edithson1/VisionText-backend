# Configuración del backend

| Archivo | Uso | Se sube a GitHub |
|---|---|---|
| `.env` | PostgreSQL y S3 locales, administrador local | No |
| `.env.drive` | Credenciales generadas al autorizar Google; copia privada de recuperación | No |
| `.env.render` | Configuración unificada de Supabase, Drive y administrador para importar en Render | No |
| `.env.example` | Plantilla pública para ejecutar en local | Sí |
| `.env.render.example` | Plantilla pública para preparar la nube | Sí |

## Dónde escribir la contraseña de Supabase

Abre **`.env.render`**, en la carpeta del backend. En la sección **1. SUPABASE**,
completa esta línea con la contraseña de PostgreSQL del proyecto:

```dotenv
POSTGRES_PASSWORD='TU_CONTRASEÑA_DE_POSTGRESQL_EN_SUPABASE'
```

Las comillas simples delimitan el valor en el archivo. Si tu contraseña contiene
una comilla simple, escápala como `\'` o introduce el valor directamente en Render.
No pegues aquí el secreto de Google, una API key ni la URL completa de conexión.
No necesitas añadir `POSTGRES_URL`: el backend construye la conexión con los campos
`POSTGRES_*` ya preparados. Un `POSTGRES_URL` antiguo tendría prioridad.

La contraseña de `.env` pertenece a la base **local**. Cambiarla no configura Supabase
y podría impedir acceder a los datos locales existentes.

## Preparar el archivo privado

```powershell
.\.venv\windows\Scripts\python.exe scripts\prepare_render_env.py
```

Este comando crea `.env.render` a partir de la plantilla si falta, copia las
credenciales de Google desde `.env.drive`, completa el administrador desde `.env`
si está vacío y genera una clave JWT independiente. Conserva la contraseña de
Supabase y demás ajustes que ya hayas escrito; nunca copia la contraseña local
como contraseña de Supabase. No imprime secretos.

Al volver a autorizar Google, el autorizador actualiza también `.env.render`.
Después de una nueva autorización, actualiza esas variables también en Render.

## Configurar Render

El backend local sigue usando `.env` con `Start-Local.ps1` o Compose.
**`.env.render` no se carga automáticamente ni se incluye en Docker o GitHub**.
Sus valores deben cargarse en las variables de entorno del servicio en Render.

Revisa en `.env.render`:

1. `POSTGRES_PASSWORD`: contraseña de PostgreSQL en Supabase.
2. `ADMIN_USERNAME` y `ADMIN_PASSWORD`: acceso administrativo deseado.
3. `BASE_URL`: URL HTTPS del backend de Render, sin barra final.
4. `CORS_ORIGINS`: origen HTTPS del frontend; separa varios con comas.

En Render, la variable se llama exactamente **`POSTGRES_PASSWORD`**. Al introducirla
individualmente escribe solo la contraseña, sin comillas adicionales. Usa los
demás valores de `.env.render` para completar la configuración del servicio.
El Blueprint puede generar su propia `JWT_SECRET_KEY`; conserva la elegida entre
despliegues. No cambies una clave de un servicio ya activo sin querer cerrar sus sesiones.

La guía de despliegue está en [DEPLOY-RENDER-DRIVE.md](DEPLOY-RENDER-DRIVE.md).
