# Verificación de la API publicada

El 15 de noviembre de 2026 (America/Lima) se ejecutó `scripts/check_live_api.py`
contra **https://visiontext-backend.onrender.com**. Las 27 comprobaciones pasaron.
Se utilizaron Supabase/PostgreSQL, Drive y CLIP reales, sin simuladores.
No se imprimieron credenciales ni tokens.

| Operación | Resultado |
|---|---|
| Raíz, salud y OpenAPI | HTTP 200 |
| CORS de localhost:5173 y 127.0.0.1:5173 | HTTP 200 y origen permitido |
| Administración, subida y borrado sin token | HTTP 401 |
| Texto vacío / archivo que no es imagen | HTTP 422 / HTTP 400 |
| Imagen y miniatura inexistentes | HTTP 404 |
| Login URL-encoded de Android y multipart de la web | HTTP 200 |
| Catálogo de administrador y estado de Drive | HTTP 200 |
| Subida temporal a Drive | HTTP 200 |
| Búsquedas por texto e imagen | HTTP 200, encontraron la imagen temporal |
| Descarga de original y miniatura | HTTP 200, bytes de imagen válidos |
| Borrado de la imagen creada por esta prueba | HTTP 200 |
| Imagen, miniatura y registro ausentes después de borrarla | Verificado |
| Salud final | HTTP 200, healthy |

Las URLs de imágenes devueltas coinciden con la API pública; `BASE_URL` está bien
configurada en ese despliegue. El catálogo comenzó y terminó con 0 imágenes y
0 vectores. No se eliminaron datos ajenos a esta prueba.

La primera respuesta tardó 43,6 s; la subida, 16,3 s; la búsqueda por texto, 3,3 s;
por imagen, 5,6 s. Son observaciones de esta ejecución, no una prueba de carga ni
una garantía de rendimiento. Datos completos: `live-api-check.json`.

La web compiló y pasó ESLint. El bundle contiene Render y no el antiguo
`http://localhost:8000`. Se abrió la web local y una búsqueda respondió con
0 resultados en 2,55 s, coherente con el catálogo vacío. Android generó su APK y
pasó Lint sin errores; quedaron avisos de versiones y APIs antiguas. No había
teléfono o emulador conectado, por lo que no se probó su interfaz en un dispositivo.

Para repetir la prueba (crea y elimina una sola imagen temporal):

```powershell
.\.venv\windows\Scripts\python.exe scripts\check_live_api.py
```

El script lee el administrador de `.env.render` y guarda un informe sin secretos.
Se siguió la guía de pruebas de API con un cliente HTTP y el contrato OpenAPI;
no depende del CLI de Postman ni publica resultados en un workspace externo.

No se proporcionó el dominio de la web publicada. Cuando esté disponible hay que
comprobar su origen CORS exacto en Render. Estas pruebas cubren la web local.
