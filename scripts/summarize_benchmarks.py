"""Write the comparison from measured JSON reports, without estimating results."""
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def read(name):
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def main():
    baseline = read("baseline-linux.json")
    lightweight = read("onnx-q8f16-linux.json")
    api_before = read("api-baseline-linux.json")
    api_after = read("api-onnx-linux-512.json")
    cpu = read("api-onnx-linux-512-cpu10.json")
    windows_before = read("api-baseline-windows.json")
    windows_after = read("api-onnx-windows.json")
    assert all(item["passed"] for item in (api_before, api_after, cpu, windows_before, windows_after))
    old_vectors = np.load(REPORTS / "baseline-linux.npz")
    new_vectors = np.load(REPORTS / "onnx-q8f16-linux.npz")
    cosines = {kind: float((old_vectors[kind] * new_vectors[kind]).sum(axis=1).mean()) for kind in old_vectors}
    same_top1 = sum(a["top5"][0] == b["top5"][0] for a, b in zip(baseline["retrieval"], lightweight["retrieval"]))
    same_natural = sum(a["top5"][0] == b["top5"][0] for a, b in zip(baseline["natural_queries"], lightweight["natural_queries"]))
    peak_mb = int(api_after["memory.peak"]) / 1e6
    cpu_peak_mb = int(cpu["memory.peak"]) / 1e6
    reduction = (1 - api_after["peak_process_tree_rss_mib"] / api_before["peak_process_tree_rss_mib"]) * 100
    fingerprints = {}
    for filename in ("app/services/clip.py", "app/services/clip_torch.py", "app/services/memory.py", "scripts/build_q8.py", "Dockerfile", "requirements.txt"):
        fingerprints[filename] = hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
    summary = {"date": "2026-11-12", "catalog_images": 45, "rss_reduction_percent": reduction,
               "cgroup_peak_mb": peak_mb, "memory_limit_mb": 512, "margin_mb": 512 - peak_mb,
               "mean_embedding_cosine": cosines, "same_class_query_top1": same_top1,
               "same_natural_query_top1": same_natural, "source_sha256": fingerprints}
    (REPORTS / "comparison.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    text = f"""# VisionText: comparación del backend y viabilidad en Render Free

Medición del 12 de noviembre de 2026. **El perfil Q8 pasó la prueba local de la API
completa con un límite estricto de 512,000,000 bytes y sin swap.** El pico total
del cgroup fue **{peak_mb:.1f} MB**, con **{512 - peak_mb:.1f} MB de margen**, y los
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
| Pico RSS del proceso y lanzador | {api_before['peak_process_tree_rss_mib']:.1f} MiB | {api_after['peak_process_tree_rss_mib']:.1f} MiB |
| Mediana búsqueda por texto | {api_before['text_median_ms']:.0f} ms | {api_after['text_median_ms']:.0f} ms |
| Mediana búsqueda por imagen | {api_before['image_median_ms']:.0f} ms | {api_after['image_median_ms']:.0f} ms |

La reducción del pico RSS en esta prueba fue **{reduction:.1f}%**. La inferencia
cuantizada sacrifica velocidad para mantener la precisión con menos memoria.

| Medición de la API nativa en Windows | Anterior | Nuevo |
|---|---:|---:|
| Pico RSS del proceso y lanzador | {windows_before['peak_process_tree_rss_mib']:.1f} MiB | {windows_after['peak_process_tree_rss_mib']:.1f} MiB |
| Mediana búsqueda por texto | {windows_before['text_median_ms']:.0f} ms | {windows_after['text_median_ms']:.0f} ms |
| Mediana búsqueda por imagen | {windows_before['image_median_ms']:.0f} ms | {windows_after['image_median_ms']:.0f} ms |

Con cuota real de **10% de un núcleo** y el mismo límite de memoria, la API pasó
de nuevo las búsquedas, subida, validaciones, descarga y borrado. Se midieron
**{cpu['text_median_ms']/1000:.2f} s por búsqueda de texto** y
**{cpu['image_median_ms']/1000:.2f} s por imagen**; el pico del cgroup fue
**{cpu_peak_mb:.1f} MB**. El arranque observado en ese perfil tardó
{cpu['startup_seconds']:.1f} s. Son tiempos de esta PC/WSL, no una garantía de
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
| Imagen esperada como primer resultado de texto | {baseline['text_retrieval_top1']}/45 | {lightweight['text_retrieval_top1']}/45 |
| Imagen esperada entre los primeros cinco | {baseline['text_retrieval_top5']}/45 | {lightweight['text_retrieval_top5']}/45 |
| Recuperación de la propia imagen | {baseline['image_self_top1']}/45 | {lightweight['image_self_top1']}/45 |
| Descripciones correspondientes aceptadas, umbral 0.20 | {baseline['matched_uploads_accepted_at_020']}/45 | {lightweight['matched_uploads_accepted_at_020']}/45 |
| Descripciones de otra categoría aún aceptadas, umbral 0.20 | {baseline['mismatched_uploads_accepted_at_020']}/45 | {lightweight['mismatched_uploads_accepted_at_020']}/45 |

El primer resultado coincide entre motores en {same_top1}/45 consultas de
categoría y en {same_natural}/10 consultas adicionales. La similitud coseno media
entre los vectores de ambos motores es {cosines['images']:.6f} para imágenes y
{cosines['texts']:.6f} para texto. Se conservaron los umbrales 0.18/0.65/0.20.
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
"""
    (REPORTS / "COMPARACION-RENDER.md").write_text(text, encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
