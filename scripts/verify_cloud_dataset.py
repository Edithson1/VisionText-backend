"""Verify all dataset records and Drive IDs, then test the rebuilt live API."""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import time

import asyncpg
from dotenv import dotenv_values
from PIL import Image
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.google_drive import DriveConfig, GoogleDriveStorage

BASE = "https://visiontext-backend.onrender.com"
ORIGIN = "https://visiontext-sigma.vercel.app"


async def read_catalog(values):
    connection = await asyncpg.connect(host=values["POSTGRES_HOST"], port=int(values["POSTGRES_PORT"]),
                                       user=values["POSTGRES_USER"], password=values["POSTGRES_PASSWORD"],
                                       database=values["POSTGRES_DB"], ssl="require", timeout=30)
    try:
        rows = await connection.fetch("""SELECT id, filename, image_path, thumbnail_path, embedding_model,
            storage_provider, octet_length(embedding) AS vector_bytes FROM public.images""")
        return [dict(row) for row in rows]
    finally:
        await connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-index-seconds", type=int, default=600)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/verificacion-dataset-completo.json")
    args = parser.parse_args()
    values = dotenv_values(ROOT / ".env.render", interpolate=False)
    names = {path.name for path in (ROOT / "dataset_final").iterdir() if path.is_file()}
    report = {"target": BASE, "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "dataset_files": len(names), "checks": []}
    session = requests.Session()
    session.trust_env = False
    drive = GoogleDriveStorage(DriveConfig(
        client_id=values["GOOGLE_DRIVE_CLIENT_ID"], client_secret=values["GOOGLE_DRIVE_CLIENT_SECRET"],
        refresh_token=values["GOOGLE_DRIVE_REFRESH_TOKEN"], folder_id=values["GOOGLE_DRIVE_FOLDER_ID"],
        namespace=values["GOOGLE_DRIVE_NAMESPACE"], timeout=30))

    def api(name, method, path, **kwargs):
        start = time.monotonic()
        result = session.request(method, BASE + path, timeout=(15, 180), allow_redirects=False, **kwargs)
        report["checks"].append({"name": name, "status": result.status_code,
                                 "seconds": round(time.monotonic() - start, 3)})
        assert result.status_code == 200, f"{name}: HTTP {result.status_code}"
        return result

    try:
        rows = asyncio.run(read_catalog(values))
        dataset_rows = [row for row in rows if row["filename"] in names]
        counts = Counter(row["filename"] for row in dataset_rows)
        report["database_total"] = len(rows)
        report["dataset_records"] = len(dataset_rows)
        report["missing_records"] = sorted(names - set(counts))
        report["duplicate_filenames"] = [name for name, count in counts.items() if count != 1]
        assert not report["missing_records"] and not report["duplicate_filenames"], "Dataset catalog mismatch"
        assert all(row["vector_bytes"] == 2048 and row["embedding_model"]
                   and row["storage_provider"] == "google_drive" for row in dataset_rows), "Invalid vectors or provider"
        drive.init_buckets()
        file_sets = {}
        for kind, folder in drive.folders.items():
            file_sets[kind] = {item["id"] for item in drive._list(drive._tag_query() + " and '" + drive._q(folder) + "' in parents")}
        report["drive_originals"] = len(file_sets["images"])
        report["drive_thumbnails"] = len(file_sets["thumbnails"])
        missing = []
        for row in dataset_rows:
            for key, kind in [("image_path", "images"), ("thumbnail_path", "thumbnails")]:
                if not row[key].startswith("gdrive:") or row[key][7:] not in file_sets[kind]:
                    missing.append(row["filename"] + ":" + kind)
        report["missing_drive_files"] = missing
        assert not missing, "A referenced Drive file is missing"
        print(json.dumps({key: report[key] for key in ["dataset_records", "drive_originals", "drive_thumbnails"]}), flush=True)

        deadline = time.monotonic() + args.wait_index_seconds
        while True:
            try:
                health_response = session.get(BASE + "/api/health", timeout=(10, 30))
                health = health_response.json() if health_response.status_code == 200 else {}
                if (health.get("status") == "healthy" and health.get("images_in_db") == len(rows)
                        and health.get("vectors_in_index") == len(rows)):
                    break
            except (requests.RequestException, ValueError):
                health = {}
            if time.monotonic() >= deadline:
                raise RuntimeError("Render has not rebuilt its index with the complete catalog")
            print(json.dumps({"waiting_for_index": True, "database": health.get("images_in_db"),
                              "vectors": health.get("vectors_in_index")}), flush=True)
            time.sleep(15)
        report["live_images"] = health["images_in_db"]
        report["live_vectors"] = health["vectors_in_index"]
        login = api("login", "POST", "/api/admin/login", data={
            "username": values["ADMIN_USERNAME"], "password": values["ADMIN_PASSWORD"]}).json()
        session.headers["Authorization"] = "Bearer " + login["access_token"]
        seen = set()
        offset = 0
        while offset < len(rows):
            page = api("admin_page_" + str(offset // 30 + 1), "GET", f"/api/admin/images?limit=30&offset={offset}").json()
            assert page["total"] == len(rows) and len(page["images"]) == min(30, len(rows) - offset), "Incorrect page size/total"
            ids = {row["id"] for row in page["images"]}
            assert not (seen & ids), "Duplicate records between pages"
            seen.update(ids)
            offset += len(page["images"])
        assert len(seen) == len(rows), "Some catalog rows were not reachable by pagination"
        report["admin_pages_verified"] = (len(rows) + 29) // 30
        report["admin_unique_records"] = len(seen)
        cors = api("vercel_preflight", "OPTIONS", "/api/search/text", headers={"Origin": ORIGIN,
                   "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,authorization"})
        assert cors.headers.get("Access-Control-Allow-Origin") == ORIGIN
        searches = []
        for query, expected in [("African elephant", "african_elephant"), ("alpaca", "alpaca"), ("zebra", "zebra")]:
            response = api("text_" + expected, "POST", "/api/search/text", json={"query": query, "limit": 20},
                           headers={"Origin": ORIGIN})
            results = response.json()
            assert response.headers.get("Access-Control-Allow-Origin") == ORIGIN
            assert 0 < results["total_count"] <= 20
            assert any(expected in row["filename"] for row in results["results"]), "Expected subject absent from search"
            searches.append({"query": query, "seconds": results["query_time"],
                             "first_filename": results["results"][0]["filename"]})
        report["text_searches"] = searches
        sample_name = "african_elephant_african_elephant-0026.jpg"
        sample = (ROOT / "dataset_final" / sample_name).read_bytes()
        results = api("image_search", "POST", "/api/search/image",
                      files={"image": (sample_name, sample, "image/jpeg")}).json()
        assert any(row["filename"] == sample_name for row in results["results"]), "Dataset image absent from image search"
        report["image_search_seconds"] = results["query_time"]
        ordered = sorted(dataset_rows, key=lambda row: row["filename"])
        samples = ordered[::max(1, len(ordered) // 12)]
        for row in samples:
            for kind, prefix in [("original", "/api/images/"), ("thumbnail", "/api/thumbnails/")]:
                response = api("sample_" + kind, "GET", prefix + row["id"])
                with Image.open(io.BytesIO(response.content)) as picture:
                    picture.load()
        report["sample_image_pairs_downloaded"] = len(samples)
        report["passed"] = True
    except Exception as error:
        report["passed"] = False
        report["error"] = str(error) if isinstance(error, (AssertionError, RuntimeError)) else type(error).__name__
    finally:
        session.close()
        drive._session.close()
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
