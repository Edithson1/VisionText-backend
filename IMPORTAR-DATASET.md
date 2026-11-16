# Importar el dataset completo

El dataset tiene 1.575 imágenes. La utilidad conserva los registros existentes
y agrega solo los nombres pendientes; no borra ni sobrescribe imágenes.

Para esta operación administrativa se usan las credenciales privadas de `.env.render`:
PostgreSQL de Supabase y OAuth de Drive. No se incluyen en GitHub ni se necesitan
en la web o Android. Se mantiene RLS y el acceso del catálogo a través de FastAPI.

## Preparación

Instala las dependencias de desarrollo y prepara los pesos con
`python scripts/prepare_onnx.py`. El modelo local debe coincidir con el modelo de
los vectores ya guardados; la utilidad lo comprueba antes de hacer cambios.

```powershell
python scripts/import_cloud_dataset.py --preflight --output .venv/dataset-import/preflight.json
```

## Carga

```powershell
python scripts/import_cloud_dataset.py --workers 8 --threads 2
```

Ejecuta un solo proceso de importación a la vez. En este equipo se utilizó el
entorno Linux de WSL, con `.venv/linux/bin/python`, para calcular CLIP localmente.

- Valida formato, tamaño, dimensiones y nombre con las reglas del backend.
- Calcula vectores Q8 normalizados de 512 valores con los pesos fijados del proyecto.
- Guarda originales y miniaturas en las carpetas privadas existentes de Drive.
- Inserta metadatos, IDs persistentes de Drive y vectores mediante parámetros SQL,
  usando el pooler de Supabase con TLS y un pool de dos conexiones.
- Las transferencias usan clientes independientes y reintentos con espera creciente.
- El progreso y los archivos preparados quedan en `.venv/dataset-import`, excluido
  de Git y Docker. Los IDs deterministas y los registros existentes permiten reanudar.

El informe del proceso queda en `reports/importacion-dataset-completo.json`.
Los datos y las 45 imágenes locales anteriores permanecen intactos.

## Actualizar el índice de Render

Esta utilidad inserta directamente en Supabase para calcular CLIP en el equipo
local. **Al terminar hay que reiniciar o volver a desplegar el backend**, que
reconstruye FAISS con los vectores guardados. Durante la importación el índice
activo puede seguir mostrando únicamente las imágenes que ya tenía cargadas.

Publicar los cambios del backend en `main` ejecuta CI y permite el despliegue
automático configurado. También se puede volver a desplegar desde Render.
No se debe considerar terminada la operación hasta que `/api/health` indique
que las imágenes y los vectores coinciden con el catálogo completo.

## Verificación

```powershell
python scripts/verify_cloud_dataset.py
```

La comprobación contrasta todos los nombres, vectores e IDs de Drive; espera a
que Render tenga el índice completo; recorre todas las páginas de Admin; prueba
CORS, búsquedas por texto e imagen y descargas de una muestra de originales y
miniaturas. Guarda `reports/verificacion-dataset-completo.json` sin credenciales.

La web y Android usan páginas de 30 registros en Admin. Para 1.575 imágenes son
53 páginas: 52 completas y una última con 15 registros. La búsqueda pública
continúa mostrando hasta 20 resultados por consulta.
