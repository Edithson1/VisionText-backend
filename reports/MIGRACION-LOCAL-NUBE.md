# Catálogo local copiado a la nube

Completado el 15 de noviembre de 2026 (America/Lima), mediante
`scripts/migrate_local_catalog.py`, usando las APIs local y publicada.

| Comprobación | Resultado |
|---|---|
| Catálogo local inicial | 45 imágenes |
| Catálogo de nube inicial | 0 imágenes |
| Imágenes copiadas / fallidas | 45 / 0 |
| Originales en Google Drive | 45 |
| Miniaturas en Google Drive | 45 |
| Registros en Supabase `public.images` | 45 |
| Registros con vector de búsqueda | 45 |
| Registros con IDs persistidos de Drive | 45 |
| Vectores activos en Render | 45 |
| Pares original/miniatura descargados y validados | 45 |
| Imágenes locales conservadas | 45 |

El conector de Supabase confirmó 45 vectores de 2.048 bytes y 45 pares de IDs
de Drive. La migración conservó los nombres y las descripciones del catálogo;
en esta muestra las 45 descripciones estaban vacías. Se usó la API de subida,
que generó IDs, fechas de alta, archivos procesados y vectores nuevos en la nube.

En [la web publicada](https://visiontext-sigma.vercel.app/), la búsqueda
`African elephant` devolvió 20 resultados, con la imagen del elefante en primer
lugar y las miniaturas visibles. CORS ya permite ese dominio de Vercel.
La consulta de esta comprobación tardó 10,02 s durante la verificación de archivos.

Los datos estructurados están en `migracion-local-nube.json`. La exportación
local de recuperación está en `.venv/catalog-export`, excluida de Git y Docker.
Las pruebas de reconciliación de nombres y conflictos pasaron (3 pruebas).
No se eliminaron datos locales ni registros previos de la nube.

## Alcance

Se trasladaron las **45 imágenes que estaban cargadas en el catálogo local**.
La carpeta `dataset_final` tiene 1.575 archivos, pero los restantes no estaban
cargados en ese catálogo y no forman parte de esta copia.

El proyecto usa **Supabase**, no Firebase. Drive conserva los archivos y Supabase
el catálogo y los vectores; Render mantiene el modelo y un índice reconstruible.
Web y Android consultan el mismo backend y acceden a ese catálogo de nube.

Para repetir la comprobación sin crear registros, consulta
[MIGRAR-CATALOGO.md](../MIGRAR-CATALOGO.md) y utiliza `--dry-run`.
