"""Reproducible local CLIP comparison. Run each engine in a fresh process."""
import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["baseline", "onnx", "torch"], required=True)
    parser.add_argument("--precision", choices=["uint8", "fp16", "mixed", "q4f16", "q8f16"], default="q8f16")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-directory", type=Path)
    parser.add_argument("--samples", type=Path, default=ROOT / ".venv/sample-images")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.model_directory:
        args.model_directory = args.model_directory.resolve()
    os.environ.update({
        "POSTGRES_URL": "postgresql+asyncpg://unused:unused@localhost/unused",
        "MINIO_ACCESS_KEY": "unused", "MINIO_SECRET_KEY": "unused",
        "CORS_ORIGINS": "http://localhost:5173", "ADMIN_USERNAME": "unused",
        "ADMIN_PASSWORD": "unused", "JWT_SECRET_KEY": "unused",
        "CLIP_BACKEND": "torch" if args.backend == "baseline" else args.backend,
        "CLIP_MODEL": "ViT-B-32", "CLIP_PRETRAINED": "openai",
        "CLIP_CHECKPOINT": str(ROOT / "model_cache/ViT-B-32.pt"),
        "CACHE_DIR": str(ROOT / "model_cache"),
        "ONNX_MODEL_DIR": str(args.model_directory or ROOT / ("model_cache/onnx" if args.precision in {"q4f16", "q8f16"} else "model_cache/onnx-int8")),
        "INFERENCE_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "ONNX_PRECISION": args.precision,
    })
    os.chdir(ROOT / ".venv")  # Do not read Compose's .env as application settings.
    source = ROOT / ".venv/benchmarks/baseline_backend" if args.backend == "baseline" else ROOT
    sys.path.insert(0, str(source))
    import psutil
    process = psutil.Process()
    samples = []
    running = threading.Event()
    running.set()

    def sample_memory():
        while running.is_set():
            info = process.memory_info()
            samples.append({"t": time.perf_counter(), "rss": info.rss, "private": getattr(info, "private", 0)})
            time.sleep(0.01)

    monitor = threading.Thread(target=sample_memory, daemon=True)
    monitor.start()
    started = time.perf_counter()
    from app.services.clip import clip_service
    clip_service.load_model()
    loaded = time.perf_counter()
    import numpy as np
    files = sorted(args.samples.glob("*.jpg"))
    labels = []
    for path in files:
        parts = path.stem.rsplit("-", 1)[0].split("_")
        half = len(parts) // 2
        if len(parts) % 2 == 0 and parts[:half] == parts[half:]:
            parts = parts[:half]
        labels.append(" ".join(parts))
    image_times, text_times = [], []
    images, texts = [], []
    for index, (path, label) in enumerate(zip(files, labels)):
        before = time.perf_counter()
        images.append(clip_service.encode_image(str(path)))
        image_times.append(time.perf_counter() - before)
        before = time.perf_counter()
        texts.append(clip_service.encode_text(f"a photo of a {label}"))
        text_times.append(time.perf_counter() - before)
        if index % 10 == 0:
            print(f"{args.backend}: {index + 1}/{len(files)}", flush=True)
    images, texts = np.stack(images), np.stack(texts)
    scores = texts @ images.T
    order = np.argsort(-scores, axis=1)
    image_order = np.argsort(-(images @ images.T), axis=1)
    natural_queries = ["elephant", "a large animal with a trunk", "a fox in snow", "a striped animal", "a bird with colorful feathers", "a bear", "elefante", "un animal con trompa", "zorro", "un pajaro de colores"]
    extra = []
    for query in natural_queries:
        vector = clip_service.encode_text(query)
        values = images @ vector
        ranked = np.argsort(-values)[:5]
        extra.append({"query": query, "top5": [files[i].name for i in ranked], "scores": [float(values[i]) for i in ranked]})
    running.clear()
    monitor.join()
    report = {
        "backend": args.backend, "platform": platform.platform(), "python": platform.python_version(),
        "precision": args.precision if args.backend == "onnx" else "float32",
        "torch_imported": "torch" in sys.modules,
        "open_clip_imported": "open_clip" in sys.modules,
        "threads": 1, "samples": len(files), "startup_seconds": loaded - started,
        "peak_rss_mib": max(s["rss"] for s in samples) / 2**20,
        "peak_private_mib": max(s["private"] for s in samples) / 2**20,
        "startup_peak_rss_mib": max(s["rss"] for s in samples if s["t"] <= loaded) / 2**20,
        "final_rss_mib": process.memory_info().rss / 2**20,
        "image_median_ms": statistics.median(image_times[1:]) * 1000,
        "text_median_ms": statistics.median(text_times[1:]) * 1000,
        "text_retrieval_top1": int(sum(order[i, 0] == i for i in range(len(files)))),
        "text_retrieval_top5": int(sum(i in order[i, :5] for i in range(len(files)))),
        "image_self_top1": int(sum(image_order[i, 0] == i for i in range(len(files)))),
        "matched_uploads_accepted_at_020": int(sum(scores[i, i] >= .20 for i in range(len(files)))),
        "mismatched_uploads_accepted_at_020": int(sum(scores[(i + 1) % len(files), i] >= .20 for i in range(len(files)))),
        "retrieval": [{"query": label, "expected": path.name, "top5": [files[j].name for j in order[i, :5]], "matched_score": float(scores[i, i]), "mismatched_score": float(scores[(i + 1) % len(files), i])} for i, (path, label) in enumerate(zip(files, labels))],
        "natural_queries": extra,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    np.savez_compressed(args.output.with_suffix(".npz"), images=images, texts=texts)
    print(json.dumps({k: v for k, v in report.items() if k not in ("retrieval", "natural_queries")}, indent=2), flush=True)


if __name__ == "__main__":
    main()
