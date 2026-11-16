# Copiar el catálogo local a Drive y Supabase

Los catálogos local y publicado son independientes. La carpeta `dataset_final`
del repositorio contiene 1.575 archivos, pero la aplicación local tenía 45 imágenes
cargadas. Copiar el catálogo significa trasladar esas 45 imágenes, no cargar
automáticamente todo el dataset del disco.

En la nube, Google Drive guarda originales y miniaturas; Supabase guarda el
catálogo y los vectores. No se ha configurado Firebase en este proyecto.

## Preparación

1. Mantén el backend local activo con `./Start-Local.ps1`.
2. `.env` contiene el administrador de la API local; `.env.render`, el de Render.
3. Ambas APIs deben responder `healthy` en `/api/health`.

Desde el backend, primero inspecciona sin subir datos:

```powershell
.\.venv\windows\Scripts\python.exe scripts\migrate_local_catalog.py --dry-run --output .venv/catalog-export/preflight.json
```

Para copiar los registros pendientes:

```powershell
.\.venv\windows\Scripts\python.exe scripts\migrate_local_catalog.py
```

## Comportamiento

- Exporta y comprueba todos los originales antes de comenzar. La copia de
  recuperación queda en `.venv/catalog-export`, excluida de Git y Docker.
- Conserva nombres y descripciones. Sube mediante `/api/upload`, que procesa las
  imágenes y genera IDs, miniaturas, metadatos, vectores y fechas de alta nuevos.
  Los IDs de la nube son independientes de los IDs locales.
- Trabaja secuencialmente para respetar el límite de memoria del backend.
- Reutiliza los nombres ya presentes si la descripción coincide. Si hay nombres
  duplicados o descripciones diferentes, se detiene sin sobrescribir registros.
- Tras un error de conexión, vuelve a consultar el catálogo antes de considerar
  fallida una subida, evitando repetir una operación que ya se guardó.
- Al terminar, descarga y valida cada original y miniatura, comprueba las
  cantidades de Drive y compara el catálogo con el índice de búsqueda.
- No elimina archivos ni registros locales ni borra imágenes de la nube.

El informe queda en `reports/migracion-local-nube.json`, sin credenciales ni tokens.
Puedes volver a ejecutar `--dry-run` para comprobar que no quedan nombres pendientes.

Los registros y las imágenes nuevos se ven desde la web y Android porque ambos
consultan la misma API de Render. Los datos locales no se sincronizan continuamente:
las futuras subidas desde los clientes se guardan directamente en la nube.
