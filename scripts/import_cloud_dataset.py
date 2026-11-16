"""Import the dataset using local CLIP, private Drive files and parameterized PostgreSQL writes.

Render must rebuild its FAISS index after this utility finishes.
No existing catalog row is overwritten or deleted.
"""
import argparse
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

import asyncpg
from dotenv import dotenv_values
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CACHE = ROOT / ".venv/dataset-import"
IMPORT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://visiontext-backend.onrender.com/dataset-v1")

INSERT = """INSERT INTO public.images
(id, filename, description, image_path, thumbnail_path, width, height, size,
 format, status, similarity_score, created_at, updated_at, embedding, embedding_model, storage_provider)
SELECT $1::varchar,$2::varchar,$3::text,$4::varchar,$5::varchar,$6::integer,$7::integer,$8::integer,
       $9::varchar,$10::varchar,$11::double precision,$12::timestamp,$13::timestamp,$14::bytea,$15::varchar,$16::varchar
WHERE NOT EXISTS (SELECT 1 FROM public.images WHERE filename=$2::varchar)
ON CONFLICT (id) DO NOTHING RETURNING id"""


def configure_local_model(threads):
    # These are only local import-time settings. Cloud credentials are kept out of this environment.
    os.environ.update({"CLIP_BACKEND": "onnx", "CLIP_MODEL": "ViT-B-32", "CLIP_PRETRAINED": "openai",
                       "ONNX_PRECISION": "q8f16", "ONNX_MODEL_DIR": str(ROOT / "model_cache/onnx"),
                       "INFERENCE_THREADS": str(threads), "OMP_NUM_THREADS": str(threads),
                       "MALLOC_ARENA_MAX": "2", "POSTGRES_URL": "postgresql+asyncpg://unused:unused@localhost/unused",
                       "STORAGE_BACKEND": "s3", "MINIO_ACCESS_KEY": "unused", "MINIO_SECRET_KEY": "unused",
                       "CORS_ORIGINS": "http://localhost", "ADMIN_USERNAME": "local-import",
                       "ADMIN_PASSWORD": "local-import-only", "JWT_SECRET_KEY": "local-import-only"})


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)


def record_arguments(record):
    if not all(isinstance(record.get(key), str) and record[key].startswith("gdrive:")
               and len(record[key]) > 7 for key in ("image_path", "thumbnail_path")):
        raise ValueError("Missing persistent Drive file IDs")
    embedding = base64.b64decode(record["embedding_base64"])
    vector = np.frombuffer(embedding, dtype="float32")
    if len(vector) != 512 or not np.isfinite(vector).all() or abs(float(np.linalg.norm(vector)) - 1) > 1e-4:
        raise ValueError("Invalid CLIP vector")
    return (record["id"], record["filename"], record.get("description"), record["image_path"],
            record["thumbnail_path"], record["width"], record["height"], record["size"], record["format"],
            "completed", None, datetime.fromisoformat(record["created_at"]), None, embedding,
            record["embedding_model"], "google_drive")


async def run(args):
    from app.services.clip import clip_service
    from app.services.google_drive import DriveConfig, GoogleDriveStorage
    from app.services.image import image_processing_service
    from app.services.validation import content_validator

    credentials = dotenv_values(ROOT / ".env.render", interpolate=False)
    report = {"dataset_count": 0, "already_present": 0, "imported": 0, "failed": [],
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "phase": "preflight",
              "dry_run": args.preflight, "requires_index_reload": True}
    report.update({"pid": os.getpid(), "workers": args.workers, "inference_threads": args.threads})
    pool = None
    model_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-clip")
    drive_executor = ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="drive-upload")
    state = threading.local()
    drive_clients = []
    drive_config = DriveConfig(client_id=credentials["GOOGLE_DRIVE_CLIENT_ID"],
                               client_secret=credentials["GOOGLE_DRIVE_CLIENT_SECRET"],
                               refresh_token=credentials["GOOGLE_DRIVE_REFRESH_TOKEN"],
                               folder_id=credentials["GOOGLE_DRIVE_FOLDER_ID"],
                               namespace=credentials["GOOGLE_DRIVE_NAMESPACE"], timeout=30)
    if not drive_config.folder_id:
        raise RuntimeError("Authorize the existing project Drive folder first")

    def prepare(path):
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        image_id = str(uuid.uuid5(IMPORT_NAMESPACE, path.name))
        checkpoint = CACHE / "records" / (image_id + ".json")
        if checkpoint.is_file():
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            if saved["source_sha256"] != source_hash or saved["embedding_model"] != clip_service.embedding_model:
                raise ValueError("Existing import checkpoint belongs to different data or model")
            return saved
        metadata, image, original, thumbnail = image_processing_service.process_image(path.read_bytes(), path.name)
        vector = clip_service.encode_image(image)
        image.close()
        metadata.id = image_id
        record = metadata.model_dump(mode="json")
        record.update({"source_sha256": source_hash, "embedding_model": clip_service.embedding_model,
                       "embedding_base64": base64.b64encode(vector.astype("float32").tobytes()).decode(),
                       "image_path": "", "thumbnail_path": ""})
        files = CACHE / "files"
        files.mkdir(parents=True, exist_ok=True)
        (files / (image_id + ".jpg")).write_bytes(original)
        (files / (image_id + "_thumb.jpg")).write_bytes(thumbnail)
        save_json(checkpoint, record)
        return record

    def upload(record):
        if not hasattr(state, "drive"):
            state.drive = GoogleDriveStorage(drive_config)
            state.drive.init_buckets()
            drive_clients.append(state.drive)
        checkpoint = CACHE / "records" / (record["id"] + ".json")
        for attempt in range(4):
            try:
                if not record["image_path"]:
                    record["image_path"] = state.drive.upload_image(record["id"], (CACHE / "files" / (record["id"] + ".jpg")).read_bytes())
                    save_json(checkpoint, record)
                if not record["thumbnail_path"]:
                    record["thumbnail_path"] = state.drive.upload_thumbnail(record["id"], (CACHE / "files" / (record["id"] + "_thumb.jpg")).read_bytes())
                    save_json(checkpoint, record)
                return record
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 ** (attempt + 1))

    try:
        pool = await asyncpg.create_pool(host=credentials["POSTGRES_HOST"], port=int(credentials["POSTGRES_PORT"]),
                                        user=credentials["POSTGRES_USER"], password=credentials["POSTGRES_PASSWORD"],
                                        database=credentials["POSTGRES_DB"], ssl="require", min_size=1, max_size=2,
                                        timeout=30, command_timeout=60)
        rows = await pool.fetch("SELECT filename, embedding_model FROM public.images")
        existing = {row["filename"] for row in rows}
        if any(row["embedding_model"] != clip_service.embedding_model for row in rows):
            raise RuntimeError("The cloud uses a different embedding model")
        if not await pool.fetchval("SELECT relrowsecurity FROM pg_class WHERE oid='public.images'::regclass"):
            raise RuntimeError("Catalog RLS must stay enabled")
        paths = sorted(path for path in args.dataset.iterdir() if path.is_file())
        if not paths:
            raise RuntimeError("Dataset is empty")
        report["dataset_count"] = len(paths)
        report["already_present"] = sum(path.name in existing for path in paths)
        pending = [path for path in paths if path.name not in existing]
        report["pending_at_start"] = len(pending)
        for path in paths:
            data = path.read_bytes()
            if not (image_processing_service.validate_image_size(data)
                    and image_processing_service.validate_image_format(data)
                    and image_processing_service.validate_image_dimensions(data)
                    and content_validator.validate_image_metadata(path.name)[0]):
                raise RuntimeError("Dataset validation failed: " + path.name)
        initial_drive = GoogleDriveStorage(drive_config)
        drive_clients.append(initial_drive)
        await asyncio.to_thread(initial_drive.init_buckets)
        save_json(args.output, report)
        print(json.dumps(report), flush=True)
        if args.preflight:
            report["passed"] = True
            return True
        if args.max_new:
            pending = pending[:args.max_new]
        if pending:
            await asyncio.get_running_loop().run_in_executor(model_executor, clip_service.load_model)
        report["phase"] = "importing"
        queue = asyncio.Queue()
        for path in pending:
            queue.put_nowait(path)
        completed = 0
        failures_in_a_row = 0
        stop = asyncio.Event()

        async def worker():
            nonlocal completed, failures_in_a_row
            loop = asyncio.get_running_loop()
            while not queue.empty() and not stop.is_set():
                try:
                    path = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    record = await loop.run_in_executor(model_executor, prepare, path)
                    record = await loop.run_in_executor(drive_executor, upload, record)
                    result = None
                    for attempt in range(3):
                        try:
                            result = await pool.fetchval(INSERT, *record_arguments(record))
                            if result is None:
                                result = await pool.fetchval("SELECT id FROM public.images WHERE filename=$1", path.name)
                            if result is None:
                                raise RuntimeError("Catalog insert was not confirmed")
                            break
                        except (asyncpg.PostgresError, OSError):
                            if attempt == 2:
                                raise
                            await asyncio.sleep(2 ** attempt)
                    report["imported"] += 1
                    failures_in_a_row = 0
                except Exception as error:
                    report["failed"].append({"filename": path.name, "error_type": type(error).__name__})
                    failures_in_a_row += 1
                    if failures_in_a_row >= 3:
                        stop.set()
                finally:
                    completed += 1
                    queue.task_done()
                    if completed % 10 == 0 or report["failed"] or completed == len(pending):
                        save_json(args.output, report)
                        print(json.dumps({"completed": completed, "imported": report["imported"],
                                          "remaining_this_run": queue.qsize(), "failed": len(report["failed"])}), flush=True)

        await asyncio.gather(*(worker() for _ in range(args.workers)))
        final = await pool.fetch("SELECT filename, embedding, image_path, thumbnail_path, embedding_model FROM public.images")
        final_by_name = {row["filename"]: row for row in final}
        report["cloud_total"] = len(final)
        report["dataset_present"] = sum(path.name in final_by_name for path in paths)
        report["missing"] = [path.name for path in paths if path.name not in final_by_name]
        report["valid_dataset_records"] = sum(
            path.name in final_by_name and len(final_by_name[path.name]["embedding"] or b"") == 2048
            and final_by_name[path.name]["image_path"].startswith("gdrive:")
            and final_by_name[path.name]["thumbnail_path"].startswith("gdrive:")
            and final_by_name[path.name]["embedding_model"] == clip_service.embedding_model for path in paths)
        report["phase"] = "import_finished_requires_index_reload"
        report["passed"] = (not report["failed"] and report["valid_dataset_records"] == report["dataset_present"]
                            and (args.max_new is not None or not report["missing"]))
    except Exception as error:
        report["passed"] = False
        report["error_type"] = type(error).__name__
        if isinstance(error, RuntimeError):
            report["error"] = str(error)
    finally:
        model_executor.shutdown(wait=True)
        drive_executor.shutdown(wait=True)
        for client in drive_clients:
            client._session.close()
        if pool is not None:
            await pool.close()
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        save_json(args.output, report)
        summary = {key: value for key, value in report.items() if key != "missing"}
        summary["missing_count"] = len(report.get("missing", []))
        print(json.dumps(summary, indent=2), flush=True)
    return report.get("passed", False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "dataset_final")
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=8)
    parser.add_argument("--threads", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--max-new", type=int)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/importacion-dataset-completo.json")
    args = parser.parse_args()
    configure_local_model(args.threads)
    return 0 if asyncio.run(run(args)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
