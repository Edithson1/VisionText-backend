"""Exercise the real local API and monitor its process, optionally in a cgroup."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
from urllib.parse import quote

import httpx
import psutil
from dotenv import dotenv_values
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["baseline", "onnx"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--storage-host", default="127.0.0.1")
    parser.add_argument("--storage-port", type=int, default=59000)
    parser.add_argument("--memory-limit", action="store_true")
    parser.add_argument("--cpu-quota", default="")
    parser.add_argument("--skip-stress", action="store_true")
    parser.add_argument("--iterations", type=int, default=5)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    local = dotenv_values(ROOT / ".env")
    env = os.environ.copy()
    env.update({
        "POSTGRES_URL": f"postgresql+asyncpg://visiontext:{quote(local['POSTGRES_PASSWORD'], safe='')}@127.0.0.1:55432/visiontext",
        "MINIO_ENDPOINT": f"{args.storage_host}:{args.storage_port}", "MINIO_ACCESS_KEY": local["MINIO_ACCESS_KEY"],
        "MINIO_SECRET_KEY": local["MINIO_SECRET_KEY"], "MINIO_SECURE": "false",
        "ADMIN_USERNAME": local["ADMIN_USERNAME"], "ADMIN_PASSWORD": local["ADMIN_PASSWORD"],
        "JWT_SECRET_KEY": local["JWT_SECRET_KEY"], "BASE_URL": f"http://127.0.0.1:{args.port}",
        "CORS_ORIGINS": "http://localhost:5173,http://127.0.0.1:5173",
        "CLIP_BACKEND": "torch" if args.backend == "baseline" else "onnx", "CLIP_MODEL": "ViT-B-32",
        "CLIP_PRETRAINED": "openai", "CLIP_CHECKPOINT": str(ROOT / "model_cache/ViT-B-32.pt"),
        "ONNX_PRECISION": "q8f16",
        "CACHE_DIR": str(ROOT / "model_cache"), "ONNX_MODEL_DIR": str(ROOT / "model_cache/onnx"),
        "FAISS_INDEX_PATH": str(ROOT / f".venv/benchmarks/index-{args.backend}/faiss.bin"),
        "INFERENCE_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "MALLOC_ARENA_MAX": "2",
        "MALLOC_TRIM_THRESHOLD_": "65536",
        "PYTHONUNBUFFERED": "1",
    })
    source = ROOT / ".venv/benchmarks/baseline_backend" if args.backend == "baseline" else ROOT
    command = [sys.executable, "-m", "uvicorn", "main:app", "--app-dir", str(source), "--host", "127.0.0.1", "--port", str(args.port), "--workers", "1"]
    unit = f"visiontext-bench-{args.port}-{os.getpid()}"
    if args.memory_limit or args.cpu_quota:
        prefix = ["systemd-run", "--user", "--scope", "--unit", unit]
        if args.memory_limit:
            prefix += ["-p", "MemoryMax=512000000", "-p", "MemorySwapMax=0"]
        if args.cpu_quota:
            prefix += ["-p", f"CPUQuota={args.cpu_quota}"]
        command = prefix + command
    started = time.perf_counter()
    log = args.output.with_suffix(".log").open("w", encoding="utf-8")
    child = subprocess.Popen(command, cwd=ROOT / ".venv", env=env, stdout=log, stderr=subprocess.STDOUT)
    monitor = psutil.Process(child.pid)
    memory, active = [], threading.Event()
    active.set()
    cgroup = None

    def sample():
        nonlocal cgroup
        while active.is_set():
            try:
                processes = [monitor] + monitor.children(recursive=True)
                memory.append(sum(p.memory_info().rss for p in processes if p.is_running()))
                if args.memory_limit and cgroup is None:
                    for candidate in Path("/sys/fs/cgroup/user.slice").rglob(unit + ".scope"):
                        cgroup = candidate
                        break
            except (psutil.Error, FileNotFoundError):
                pass
            time.sleep(.02)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    report = {"backend": args.backend, "memory_limit_bytes": 512000000 if args.memory_limit else None, "cpu_quota": args.cpu_quota, "checks": {}}
    client = httpx.Client(base_url=env["BASE_URL"], timeout=120)
    def checked(name, response, expected=200):
        report["checks"][name] = {"status": response.status_code, "passed": response.status_code == expected}
        if cgroup and cgroup.exists():
            report["checks"][name]["memory_peak_bytes"] = int((cgroup / "memory.peak").read_text())
            report["checks"][name]["memory_current_bytes"] = int((cgroup / "memory.current").read_text())
        response.raise_for_status() if expected < 400 else None
        assert response.status_code == expected, (name, response.status_code)
        return response.json() if response.headers.get("content-type", "").startswith("application/json") else response.content

    uploaded_ids = []
    headers = {}
    try:
        for _ in range(1200):
            if child.poll() is not None:
                raise RuntimeError("API exited before readiness. See the benchmark log.")
            try:
                response = client.get("/api/health", timeout=2)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.25)
        else:
            raise TimeoutError("API did not become ready")
        report["startup_seconds"] = time.perf_counter() - started
        report["health_before"] = checked("health", response)
        before_count = report["health_before"]["images_in_db"]
        checked("unauthorized_upload", client.post("/api/upload"), 401)
        token = checked("login", client.post("/api/admin/login", data={"username": local["ADMIN_USERNAME"], "password": local["ADMIN_PASSWORD"]}))
        headers = {"Authorization": "Bearer " + token["access_token"]}
        text_times, image_times = [], []
        sample_file = ROOT / "dataset_final/african_elephant_african_elephant-0005.jpg"
        sample_bytes = sample_file.read_bytes()
        for number in range(max(2, args.iterations)):
            before = time.perf_counter()
            result = checked(f"text_{number}", client.post("/api/search/text", json={"query": "elephant", "limit": 5}))
            text_times.append(time.perf_counter() - before)
            assert result["total_count"] and "elephant" in result["results"][0]["filename"]
            before = time.perf_counter()
            result = checked(f"image_{number}", client.post("/api/search/image", files={"image": (sample_file.name, sample_bytes, "image/jpeg")}))
            image_times.append(time.perf_counter() - before)
            assert result["results"][0]["filename"] == sample_file.name
        report["text_median_ms"] = statistics.median(text_times[1:]) * 1000
        report["image_median_ms"] = statistics.median(image_times[1:]) * 1000
        image_id = result["results"][0]["id"]
        checked("original", client.get(f"/api/images/{image_id}"))
        checked("thumbnail", client.get(f"/api/thumbnails/{image_id}"))
        upload = checked("upload", client.post("/api/upload", headers=headers, files={"image": ("benchmark-elephant.jpg", sample_bytes, "image/jpeg")}, data={"description": "a photo of an African elephant"}))
        assert upload["success"]
        uploaded_ids.append(upload["image_id"])
        # A semantically wrong description must retain the project's rejection behavior.
        checked("mismatched_description", client.post("/api/upload", headers=headers, files={"image": ("benchmark-elephant.jpg", sample_bytes, "image/jpeg")}, data={"description": "a red sports car on a city street"}), 422)
        checked("banned_filename", client.post("/api/upload", headers=headers, files={"image": ("gun.jpg", sample_bytes, "image/jpeg")}), 422)
        checked("invalid_image", client.post("/api/search/image", files={"image": ("bad.jpg", b"not an image", "image/jpeg")}), 400)
        if not args.skip_stress:
            large = io.BytesIO()
            Image.new("RGB", (2000, 2000), "white").save(large, format="JPEG")
            checked("four_megapixel_image", client.post("/api/search/image", files={"image": ("large.jpg", large.getvalue(), "image/jpeg")}))
            large = io.BytesIO()
            Image.new("RGB", (2100, 2000), "white").save(large, format="JPEG")
            checked("oversized_pixels", client.post("/api/search/image", files={"image": ("large.jpg", large.getvalue(), "image/jpeg")}), 413)
            thin = io.BytesIO()
            Image.new("RGB", (16000, 1), "white").save(thin, format="PNG")
            checked("extreme_aspect_ratio", client.post("/api/search/image", files={"image": ("thin.png", thin.getvalue(), "image/png")}))
            def concurrent_query(index):
                return client.post("/api/search/image", files={"image": (sample_file.name, sample_bytes, "image/jpeg")}).status_code
            before = time.perf_counter()
            with ThreadPoolExecutor(max_workers=4) as pool:
                statuses = list(pool.map(concurrent_query, range(4)))
            report["concurrent_four_images"] = {"statuses": statuses, "seconds": time.perf_counter() - before}
            assert statuses == [200] * 4
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
            response = client.options("/api/search/text", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
            assert response.headers["access-control-allow-origin"] == origin
        report["checks"]["cors"] = {"passed": True}
        for image_id in uploaded_ids[:]:
            checked("delete", client.delete(f"/api/admin/images/{image_id}", headers=headers))
            uploaded_ids.remove(image_id)
        health = checked("health_after", client.get("/api/health"))
        assert health["images_in_db"] == health["vectors_in_index"] == before_count
        report["health_after"] = health
        report["passed"] = True
    except Exception as error:
        report["passed"] = False
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        for image_id in uploaded_ids:
            try:
                client.delete(f"/api/admin/images/{image_id}", headers=headers)
            except httpx.HTTPError:
                pass
        active.clear()
        sampler.join()
        report["peak_process_tree_rss_mib"] = max(memory, default=0) / 2**20
        if cgroup and cgroup.exists():
            for name in ("memory.peak", "memory.events", "cpu.stat"):
                report[name] = (cgroup / name).read_text().strip()
        if args.memory_limit or args.cpu_quota:
            subprocess.run(["systemctl", "--user", "kill", unit + ".scope"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
        log.close()
        client.close()
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
