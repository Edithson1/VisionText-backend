# Dataset completo en la nube

La importación del dataset de 1.575 imágenes se completó el 16 de noviembre de
2026 (America/Lima). Se conservaron las 45 imágenes anteriores y se incorporaron
las 1.530 restantes, sin duplicar nombres ni modificar el catálogo local.

## Datos duraderos verificados

| Comprobación | Resultado |
|---|---|
| Archivos del dataset | 1.575 |
| Nombres únicos en Supabase | 1.575 |
| Registros con vector de 2.048 bytes | 1.575 |
| Registros con original y miniatura identificados por ID de Drive | 1.575 |
| Originales existentes en Drive | 1.575 |
| Miniaturas existentes en Drive | 1.575 |
| Registros o referencias de Drive ausentes | 0 |
| Errores de la carga completada | 0 |

Se calculó CLIP localmente con el mismo perfil Q8 y revisión de pesos que usa
Render. La transferencia guardó archivos privados en Drive y vectores y
metadatos en Supabase mediante parámetros SQL y TLS. RLS no se desactivó y los
secretos quedaron en los archivos privados existentes.

La importación es reanudable. El informe del último tramo indica 151 registros
ya presentes y 1.424 incorporados en ese tramo: incluye el trabajo ya guardado
por la prueba inicial y una primera tanda antes de ajustar las transferencias.
El total final es 1.575, no 1.575 adicionales a las 45 anteriores.

## Clientes y comprobaciones

- Las 56 pruebas de backend pasaron en la
  [ejecución de CI](https://github.com/Edithson1/VisionText-backend/actions/runs/43810640818).
- La web compiló, pasó ESLint y Vercel publicó la paginación del commit
  [52c7dfa](https://github.com/Edithson1/visiontext-frontend/commit/52c7dfa).
- Admin devuelve páginas de 30 registros. Se comprobaron 53 páginas, 1.575 IDs
  únicos y 15 registros en la última página.
- Android 1.2 compiló y pasó Lint. Consulta una sola página de 30 registros en
  cada navegación; no descarga primero todo el catálogo. No se probó en un dispositivo físico.

## Índice de búsqueda

Después del despliegue del commit `81975ee`, Render reconstruyó FAISS con los
1.575 vectores. La verificación contra la API pública terminó el 16 de noviembre
de 2026 a las 00:58 (America/Lima), con `passed: true` y 85 comprobaciones
correctas en [el informe completo](verificacion-dataset-completo.json).

- El estado de la API indicó 1.575 imágenes y 1.575 vectores activos.
- Se recorrieron las 53 páginas de Admin y se recuperaron los 1.575 IDs únicos.
- Las búsquedas por texto de `African elephant`, `alpaca` y `zebra` devolvieron
  imágenes de la categoría correspondiente. Las solicitudes completas tardaron
  entre 9,2 y 9,5 segundos desde este equipo.
- La búsqueda mediante una imagen del dataset recuperó esa misma imagen entre
  sus resultados y tardó 11,9 segundos.
- Se descargaron y decodificaron 13 originales y sus 13 miniaturas mediante la
  API pública, además de comprobar las referencias de todos los archivos de Drive.
- La comprobación CORS permitió el origen `https://visiontext-sigma.vercel.app`.

Estos tiempos son observaciones de esta ejecución; no representan una prueba de
carga ni una medición de memoria máxima de Render con el catálogo completo.

Herramientas y pasos reproducibles: [IMPORTAR-DATASET.md](../IMPORTAR-DATASET.md).
