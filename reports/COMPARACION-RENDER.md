# VisionText: comparación del backend y viabilidad en Render Free

Medición del 12 de noviembre de 2026. **El perfil Q8 pasó la prueba local de la API
completa con un límite estricto de 512,000,000 bytes y sin swap.** El pico total
del cgroup fue **469.1 MB**, con **42.9 MB de margen**, y los
contadores `oom` y `oom_kill` permanecieron en cero. La conclusión se limita al
catálogo actual de 45 imágenes, un proceso y una inferencia simultánea.

## Qué se cambió

- CLIP ViT-B-32/OpenAI se ejecuta con ONNX Runtime; PyTorch y OpenCLIP se conservan
  como motor opcional para comparación, fuera de las dependencias de producción.
- Se cuantizan solo los pesos de las matrices a 8 bits, por bloques de 32,
  conservando activaciones en punto flotante y `accuracy_level=1`. La revisión
  fuente y los SHA-256 de los modelos quedan en `manifest.json`.
- Las dos sesiones usan un hilo, ejecución secuencial y arenas desactivadas.
  En Linux se devuelven páginas de heap libres después de la inferencia.
- El servidor admite una operación de búsqueda o subida a la vez. Otras
  solicitudes esperan; no se crean copias del modelo para atenderlas.
- Se aceptan imágenes de hasta 4 millones de píxeles y 10 MiB. Las nuevas
  imágenes almacenadas se reducen a un lado máximo de 1600 píxeles.
- El índice se reconstruye por lotes. PostgreSQL identifica el motor de cada
  vector para recalcular los antiguos aunque tengan la misma dimensión.
- Docker prepara los pesos durante la compilación y copia solo el resultado al
  contenedor final. `render.yaml` configura el servicio Free y sus variables.

## Memoria y rendimiento de la API completa

Los servicios PostgreSQL y S3 son procesos externos al límite de la API en ambas
versiones. RSS es la suma del proceso servidor y su lanzador; el cgroup también
contabiliza las páginas y cachés que carga el servicio.

| Medición Linux, sin limitar CPU | Anterior PyTorch | Nuevo ONNX Q8 |
|---|---:|---:|
| Pico RSS del proceso y lanzador | 2324.6 MiB | 451.4 MiB |
| Mediana búsqueda por texto | 159 ms | 664 ms |
| Mediana búsqueda por imagen | 284 ms | 1060 ms |

La reducción del pico RSS en esta prueba fue **80.6%**. La inferencia
cuantizada sacrifica velocidad para mantener la precisión con menos memoria.

| Medición de la API nativa en Windows | Anterior | Nuevo |
|---|---:|---:|
| Pico RSS del proceso y lanzador | 2321.2 MiB | 456.2 MiB |
| Mediana búsqueda por texto | 296 ms | 1065 ms |
| Mediana búsqueda por imagen | 532 ms | 2241 ms |

Con cuota real de **10% de un núcleo** y el mismo límite de memoria, la API pasó
de nuevo las búsquedas, subida, validaciones, descarga y borrado. Se midieron
**7.50 s por búsqueda de texto** y
**11.70 s por imagen**; el pico del cgroup fue
**468.3 MB**. El arranque observado en ese perfil tardó
61.9 s. Son tiempos de esta PC/WSL, no una garantía de
latencia de Render. El almacenamiento en NTFS y el estado de las cachés afectan
al arranque. La prueba de CPU usa dos repeticiones por modalidad; la segunda
es la observación caliente. La prueba sin cuota usa cinco, descartando la primera.

## Cambios en los resultados

Se usaron las mismas 45 imágenes locales, una por categoría, con la consulta
`a photo of a <categoría>`. También se compararon diez consultas cortas o libres
en inglés y español. Este conjunto pequeño no mide precisión general ni mejora
el soporte de idiomas del modelo original.

| Comprobación | Anterior | Nuevo Q8 |
|---|---:|---:|
| Imagen esperada como primer resultado de texto | 38/45 | 38/45 |
| Imagen esperada entre los primeros cinco | 45/45 | 45/45 |
| Recuperación de la propia imagen | 45/45 | 45/45 |
| Descripciones correspondientes aceptadas, umbral 0.20 | 45/45 | 45/45 |
| Descripciones de otra categoría aún aceptadas, umbral 0.20 | 15/45 | 15/45 |

El primer resultado coincide entre motores en 45/45 consultas de
categoría y en 10/10 consultas adicionales. La similitud coseno media
entre los vectores de ambos motores es 0.999895 para imágenes y
0.999938 para texto. Se conservaron los umbrales 0.18/0.65/0.20.
La validación de descripciones conserva sus limitaciones: los pares ajenos
aceptados en la tabla son falsos positivos del umbral, no aciertos.

Se descartó INT8 con activaciones cuantizadas por degradar los resultados, Q4 por
cambiar consultas como `elephant`, y FP16 completo por superar los 512 MB incluso
con el modelo aislado. Los resultados de esos experimentos se conservaron aparte.

## Verificación y alcance

- 33 pruebas automatizadas pasan en Windows y Linux, incluyendo autenticación,
  límites de imagen, integridad de FAISS y migración entre motores. Las llamadas
  HTTP verifican CORS para ambos orígenes locales.
- La API limitada pasó una imagen de 4 MP, rechazo de 4.2 MP, una imagen muy
  estrecha, archivos inválidos, validación de descripciones y cuatro búsquedas
  simultáneas. Las cuatro terminaron con HTTP 200 y el catálogo volvió a 45
  imágenes y 45 vectores después del borrado de prueba.
- Los modelos ONNX no importan PyTorch ni OpenCLIP durante estas mediciones.
- El margen no demuestra capacidad para el dataset completo ni muchos usuarios.
  Cada vector de 512 valores float32 añade 2 KiB más índices e identificadores.
- La prueba usa Linux WSL y cgroups; no se publicó en Render. Docker Desktop no
  estaba iniciado, por lo que no se compiló ni ejecutó la imagen Docker completa.
  La generación de pesos se verificó por separado en un entorno Linux limpio;
  ambos SHA-256 coinciden con Windows (`model-build-linux.json`).
  Posteriormente se compiló y probó la imagen Docker completa con Drive simulado;
  esa validación está en [INTEGRACION-DRIVE.md](INTEGRACION-DRIVE.md).
- Render Free requiere base de datos y almacenamiento persistente externos;
  la gratuidad de esos servicios se evalúa aparte. Su pausa por inactividad puede
  provocar una espera y un reintento desde la web o Android.

## Reproducir y volver al motor anterior

```powershell
python -m pip install -r requirements-dev.txt
python scripts/prepare_onnx.py
./Start-Local.ps1
# En otra terminal, con los servicios locales disponibles:
python scripts/benchmark_api.py --backend onnx --output reports/api-onnx-windows.json
```

La prueba Linux requiere PostgreSQL en 55432, S3 preparado en 59010 y una sesión
systemd de usuario. Con esos servicios disponibles:

```bash
.venv/linux/bin/python scripts/benchmark_api.py --backend onnx --storage-port 59010 --memory-limit --output reports/api-onnx-linux-512.json
.venv/linux/bin/python scripts/benchmark_api.py --backend onnx --storage-port 59010 --memory-limit --cpu-quota 10% --iterations 2 --skip-stress --output reports/api-onnx-linux-512-cpu10.json
```

El supervisor mide desde antes de importar la app, ejecuta llamadas HTTP reales
y detiene su proceso al terminar. `MemoryMax=512000000`, `MemorySwapMax=0` y
`CPUQuota=10%` son límites del kernel, no estimaciones del tamaño de los pesos.
La copia del código anterior para esta comparación está en
`.venv/benchmarks/baseline_backend`. Para volver al motor preservado instala
`requirements-torch.txt` y ejecuta `./Start-Local.ps1 -Backend torch`; al cambiar de
motor se regeneran los vectores y el índice.

Datos sin resumir: `comparison.json`, `api-*-linux*.json`,
`api-*-windows.json`, `baseline-linux.json` y `onnx-q8f16-linux.json`.

Fuentes de límites y modelos: [Render Compute Plans](https://render.com/docs/compute-plans),
[Render Free](https://render.com/docs/free),
[pesos fuente fijados por revisión](https://huggingface.co/Xenova/clip-vit-base-patch32/tree/6b7c523703ae26e39be4b03774966f8571c7f523/onnx),
[cuantizador de ONNX Runtime](https://github.com/microsoft/onnxruntime/blob/v1.23.2/onnxruntime/quantization/matmul_nbits_quantizer.py).
