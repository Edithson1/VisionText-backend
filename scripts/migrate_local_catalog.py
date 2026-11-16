"""Copy the active local catalog to Render through its API; never delete source data."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import uuid

from dotenv import dotenv_values
from PIL import Image
import requests

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "http://127.0.0.1:8000"
TARGET = "https://visiontext-backend.onrender.com"


def request(session, method, base, path, **kwargs):
    response = session.request(method, base + path, timeout=(15, 180), allow_redirects=False, **kwargs)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {method} {path}")
    return response


def login(base, env_file):
    values = dotenv_values(env_file, interpolate=False)
    client = requests.Session()
    client.trust_env = False
    response = request(client, "POST", base, "/api/admin/login", data={
        "username": values["ADMIN_USERNAME"], "password": values["ADMIN_PASSWORD"]})
    client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
    return client


def catalog(client, base):
    result = []
    while True:
        page = request(client, "GET", base, f"/api/admin/images?limit=500&offset={len(result)}").json()
        result.extend(page["images"])
        if len(result) >= page["total"]:
            return result
        if not page["images"]:
            raise RuntimeError("Incomplete catalog pagination")


def matching_record(source, destination):
    matches = [row for row in destination if row["filename"] == source["filename"]]
    if len(matches) > 1:
        raise RuntimeError("Destination has ambiguous duplicate filenames")
    if matches and (matches[0].get("description") or "") != (source.get("description") or ""):
        raise RuntimeError("Existing destination description differs; no record was overwritten")
    return matches[0] if matches else None


def verify_image(data):
    with Image.open(io.BytesIO(data)) as picture:
        picture.verify()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Export and inspect only; do not upload")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/migracion-local-nube.json")
    args = parser.parse_args()
    report = {"source": SOURCE, "destination": TARGET, "dry_run": args.dry_run,
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "copied": 0,
              "already_present": 0, "failed": [], "local_data_deleted": False}
    clients = []
    backup = ROOT / ".venv/catalog-export"
    backup.mkdir(parents=True, exist_ok=True)

    def checkpoint():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    try:
        local = login(SOURCE, ROOT / ".env")
        clients.append(local)
        cloud = login(TARGET, ROOT / ".env.render")
        clients.append(cloud)
        source_rows = catalog(local, SOURCE)
        destination_rows = catalog(cloud, TARGET)
        if len({row["filename"] for row in source_rows}) != len(source_rows):
            raise RuntimeError("Local filenames are not unique; cannot safely reconcile the migration")
        report["source_count"] = len(source_rows)
        report["destination_before"] = len(destination_rows)
        # Validate every source file and keep an ignored local export before uploading anything.
        manifest = []
        for row in source_rows:
            source_id = str(uuid.UUID(row["id"]))
            data = request(local, "GET", SOURCE, "/api/images/" + source_id).content
            verify_image(data)
            (backup / (source_id + ".jpg")).write_bytes(data)
            manifest.append({**row, "export_file": source_id + ".jpg",
                             "sha256": hashlib.sha256(data).hexdigest()})
            matching_record(row, destination_rows)
        (backup / "catalog.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        report["source_files_verified"] = len(manifest)
        report["pending_before"] = sum(matching_record(row, destination_rows) is None for row in source_rows)
        print(json.dumps({"source": len(source_rows), "cloud_before": len(destination_rows),
                          "pending": report["pending_before"], "dry_run": args.dry_run}), flush=True)
        if args.dry_run:
            report["passed"] = True
            checkpoint()
            return 0
        checkpoint()
        for number, row in enumerate(manifest, 1):
            existing = matching_record(row, destination_rows)
            if existing:
                report["already_present"] += 1
                checkpoint()
                continue
            description = row.get("description")
            data = (backup / row["export_file"]).read_bytes()
            try:
                response = request(cloud, "POST", TARGET, "/api/upload",
                                   files={"image": (row["filename"], data, "image/jpeg")},
                                   data={"description": description} if description else {})
                uploaded = response.json()
                if not uploaded.get("success") or not uploaded.get("image_id"):
                    raise RuntimeError("Upload returned no image ID")
                destination_rows.append({"id": uploaded["image_id"], "filename": row["filename"],
                                         "description": description})
                report["copied"] += 1
            except (requests.RequestException, RuntimeError):
                # A timeout can happen after the server committed. Reconcile before any future retry.
                destination_rows = catalog(cloud, TARGET)
                if matching_record(row, destination_rows):
                    report["copied"] += 1
                else:
                    report["failed"].append(row["filename"])
            checkpoint()
            print(f"[{number}/{len(manifest)}] copied={report['copied']}, failed={len(report['failed'])}", flush=True)
        final_rows = catalog(cloud, TARGET)
        report["destination_after"] = len(final_rows)
        report["missing_after"] = [row["filename"] for row in source_rows if matching_record(row, final_rows) is None]
        verified = 0
        for row in source_rows:
            target_row = matching_record(row, final_rows)
            if target_row is None:
                continue
            for prefix in ("/api/images/", "/api/thumbnails/"):
                verify_image(request(cloud, "GET", TARGET, prefix + target_row["id"]).content)
            verified += 1
        report["originals_and_thumbnails_verified"] = verified
        health = request(cloud, "GET", TARGET, "/api/health").json()
        storage = request(cloud, "GET", TARGET, "/api/admin/storage").json()
        local_health = request(local, "GET", SOURCE, "/api/health").json()
        report["cloud_images"] = health["images_in_db"]
        report["cloud_vectors"] = health["vectors_in_index"]
        report["drive_originals"] = storage["images_bucket_count"]
        report["drive_thumbnails"] = storage["thumbnails_bucket_count"]
        report["local_images_after"] = local_health["images_in_db"]
        report["passed"] = (not report["missing_after"] and not report["failed"]
                            and verified == len(source_rows)
                            and report["cloud_images"] == report["cloud_vectors"]
                            and report["local_images_after"] == len(source_rows))
    except Exception as error:
        report["passed"] = False
        report["error"] = str(error) if isinstance(error, RuntimeError) else type(error).__name__
    finally:
        for client in clients:
            client.close()
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        checkpoint()
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
