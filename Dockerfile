FROM python:3.12-slim AS model-builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-model.txt .
RUN pip install --no-cache-dir -r requirements-model.txt
COPY app/clip_assets.py app/clip_assets.py
COPY scripts/prepare_onnx.py scripts/build_q8.py scripts/
RUN python scripts/prepare_onnx.py --directory /opt/clip-onnx --source-directory /tmp/clip-source

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CLIP_BACKEND=onnx \
    CLIP_MODEL=ViT-B-32 \
    ONNX_PRECISION=q8f16 \
    ONNX_MODEL_DIR=/opt/clip-onnx \
    INFERENCE_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    MALLOC_ARENA_MAX=2 \
    MALLOC_TRIM_THRESHOLD_=65536

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# Fijar la herramienta de instalación para repetir la compilación.
RUN pip install --upgrade pip==25.0.1

# Copiar requirements
COPY requirements.txt .

# Instalar dependencias Python
RUN pip install -r requirements.txt

# El contenedor final recibe solo los modelos preparados, sin sus fuentes FP16.
COPY --from=model-builder /opt/clip-onnx /opt/clip-onnx

# Copiar código
COPY . .

# Crear directorios necesarios
RUN mkdir -p /app/faiss_indices 

# Exponer puerto
EXPOSE 8000

# Render/Railway inyectan PORT; en local se usa 8000.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
