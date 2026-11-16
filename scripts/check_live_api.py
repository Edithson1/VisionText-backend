"""Check the deployed API, creating and deleting only this run's temporary image."""
import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
import uuid

from dotenv import dotenv_values
from PIL import Image
import requests

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://visiontext-backend.onrender.com")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.render")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/live-api-check.json")
    parser.add_argument("--origin", action="append", default=[])
    args = parser.parse_args()
    base = args.url.rstrip("/")
    address = urlsplit(base)
    if address.scheme != "https" or not address.hostname or address.username or address.query or address.fragment:
        parser.error("Use an HTTPS API origin without credentials, query or fragment")
    report = {"target": base, "checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "real_services": True, "checks": []}
    session = requests.Session()
    image_id = None
    token = None

    def check(name, method, path, expected=200, predicate=None, **kwargs):
        start = time.monotonic()
        response = session.request(method, base + path, timeout=(15, 180), allow_redirects=False, **kwargs)
        passed = response.status_code == expected
        if passed and predicate is not None:
            passed = bool(predicate(response))
        report["checks"].append({"name": name, "method": method, "path": path,
                                 "expected_status": expected, "status": response.status_code,
                                 "passed": passed, "seconds": round(time.monotonic() - start, 3)})
        if not passed:
            raise AssertionError(f"Failed check: {name} (HTTP {response.status_code})")
        return response

    try:
        check("root", "GET", "/", predicate=lambda r: r.json().get("status") == "running")
        health = check("health", "GET", "/api/health", predicate=lambda r:
                       r.json().get("status") == "healthy" and
                       r.json().get("storage_provider") == "google_drive").json()
        report["initial_image_count"] = health["images_in_db"]
        check("openapi", "GET", "/openapi.json", predicate=lambda r: "/api/upload" in r.json()["paths"])
        for origin in args.origin or ["http://localhost:5173", "http://127.0.0.1:5173"]:
            check("cors_" + origin, "OPTIONS", "/api/search/text", headers={"Origin": origin,
                  "Access-Control-Request-Method": "POST",
                  "Access-Control-Request-Headers": "content-type,authorization"},
                  predicate=lambda r, origin=origin: r.headers.get("Access-Control-Allow-Origin") == origin)
        for method, path in [("GET", "/api/admin/images"), ("GET", "/api/admin/storage"),
                             ("POST", "/api/upload"), ("DELETE", "/api/admin/images/not-owned-test")]:
            check("requires_auth_" + path, method, path, 401)
        check("empty_query_rejected", "POST", "/api/search/text", 422, json={"query": ""})
        check("non_image_rejected", "POST", "/api/search/image", 400,
              files={"image": ("notes.txt", b"not an image", "text/plain")})
        missing_id = "missing-" + str(uuid.uuid4())
        check("missing_image", "GET", "/api/images/" + missing_id, 404)
        check("missing_thumbnail", "GET", "/api/thumbnails/" + missing_id, 404)
        values = dotenv_values(args.env_file, interpolate=False)
        if not values.get("ADMIN_USERNAME") or not values.get("ADMIN_PASSWORD"):
            raise RuntimeError("Administrator credentials are missing from the private env file")
        credentials = {"username": values["ADMIN_USERNAME"], "password": values["ADMIN_PASSWORD"]}
        # Android sends URL-encoded login data; the web sends multipart form data.
        login = check("android_form_login", "POST", "/api/admin/login", data=credentials).json()
        token = login["access_token"]
        check("web_multipart_login", "POST", "/api/admin/login",
              files={key: (None, value) for key, value in credentials.items()},
              predicate=lambda r: r.json().get("token_type") == "bearer")
        session.headers["Authorization"] = "Bearer " + token
        check("admin_catalog", "GET", "/api/admin/images", predicate=lambda r:
              isinstance(r.json().get("images"), list) and isinstance(r.json().get("total"), int))
        check("drive_status", "GET", "/api/admin/storage", predicate=lambda r:
              r.json().get("provider") == "google_drive" and r.json().get("status") == "connected")
        sample = (ROOT / "dataset_final/african_elephant_african_elephant-0005.jpg").read_bytes()
        filename = "check-elephant-" + uuid.uuid4().hex + ".jpg"
        uploaded = check("upload_to_real_drive", "POST", "/api/upload",
                         files={"image": (filename, sample, "image/jpeg")},
                         data={"description": "a photo of an African elephant"}).json()
        # Capture the ID before asserting anything else, so cleanup remains possible.
        image_id = uploaded.get("image_id")
        assert uploaded.get("success") and image_id, "Upload did not return a temporary image ID"
        search = check("text_search", "POST", "/api/search/text",
                       json={"query": "African elephant", "limit": 100, "threshold": 0}).json()
        found = next((row for row in search["results"] if row["id"] == image_id), None)
        assert found, "Temporary image not found by text search"
        assert found["url"] == base + "/api/images/" + image_id, "BASE_URL does not match the deployed origin"
        assert found["thumbnail_url"] == base + "/api/thumbnails/" + image_id, "Thumbnail URL has the wrong origin"
        report["returned_urls_match_deployed_api"] = True
        search = check("image_search", "POST", "/api/search/image",
                       files={"image": ("query.jpg", sample, "image/jpeg")},
                       data={"limit": "100", "threshold": "0"}).json()
        assert any(row["id"] == image_id for row in search["results"]), "Temporary image not found by image search"
        for name, path in [("download_image", "/api/images/"), ("download_thumbnail", "/api/thumbnails/")]:
            response = check(name, "GET", path + image_id,
                             predicate=lambda r: r.headers.get("Content-Type", "").startswith("image/"))
            with Image.open(io.BytesIO(response.content)) as picture:
                picture.verify()
        check("delete_own_test_image", "DELETE", "/api/admin/images/" + image_id,
              predicate=lambda r: r.json().get("success") is True)
        removed_id = image_id
        image_id = None
        report["temporary_image_deleted"] = True
        check("image_absent_after_delete", "GET", "/api/images/" + removed_id, 404)
        check("thumbnail_absent_after_delete", "GET", "/api/thumbnails/" + removed_id, 404)
        check("catalog_absent_after_delete", "GET", "/api/admin/images?limit=500",
              predicate=lambda r: all(row["id"] != removed_id for row in r.json()["images"]))
        final = check("health_after", "GET", "/api/health", predicate=lambda r:
                      r.json().get("status") == "healthy").json()
        report["final_image_count"] = final["images_in_db"]
        report["final_vector_count"] = final["vectors_in_index"]
        report["passed"] = True
    except Exception as error:
        report["passed"] = False
        report["error"] = str(error) if isinstance(error, (AssertionError, RuntimeError)) else type(error).__name__
    finally:
        if image_id and token:
            try:
                deleted = session.delete(base + "/api/admin/images/" + image_id, timeout=(15, 180))
                report["temporary_image_deleted"] = deleted.status_code == 200
            except requests.RequestException:
                report["temporary_image_deleted"] = False
            if not report["temporary_image_deleted"]:
                report["temporary_image_pending_cleanup"] = image_id
        session.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
