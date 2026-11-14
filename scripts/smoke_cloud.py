"""Verify a CI-only Drive app over HTTP with real CLIP and PostgreSQL."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import time

import httpx
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8008")
    parser.add_argument("--output", type=Path, default=Path("reports/cloud-smoke.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = {"provider": "google_drive", "drive_is_emulated": True, "checks": {}}
    client = httpx.Client(base_url=args.url, timeout=180)
    image_id = None
    headers = {}

    def checked(name, response, expected=200):
        report["checks"][name] = response.status_code
        assert response.status_code == expected, f"{name}: HTTP {response.status_code}"
        return response

    try:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            try:
                health = client.get("/api/health", timeout=2)
                if health.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.5)
        else:
            raise TimeoutError("API did not become healthy")
        assert client.get("/_test/provider").json()["emulated_drive"]
        assert health.json()["storage_provider"] == "google_drive"
        assert health.json()["images_in_db"] == 0, "Use an empty, isolated test database"
        report["checks"]["health"] = 200
        credentials = {"username": os.getenv("SMOKE_ADMIN_USERNAME", "ci-admin"),
                       "password": os.getenv("SMOKE_ADMIN_PASSWORD", "ci-test-password")}
        token = checked("login", client.post("/api/admin/login", data=credentials)).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        sample = (root / "dataset_final/african_elephant_african_elephant-0005.jpg").read_bytes()
        uploaded = checked("upload", client.post("/api/upload", headers=headers,
                            files={"image": ("cloud-smoke.jpg", sample, "image/jpeg")},
                            data={"description": "a photo of an African elephant"})).json()
        image_id = uploaded["image_id"]
        text = checked("text_search", client.post("/api/search/text", json={"query": "elephant", "limit": 5})).json()
        assert text["results"][0]["id"] == image_id
        result = checked("image_search", client.post("/api/search/image", files={"image": ("query.jpg", sample, "image/jpeg")})).json()
        assert result["results"][0]["id"] == image_id
        checked("download_image", client.get(f"/api/images/{image_id}"))
        checked("download_thumbnail", client.get(f"/api/thumbnails/{image_id}"))
        storage = checked("storage", client.get("/api/admin/storage", headers=headers)).json()
        assert storage["provider"] == "google_drive"
        assert storage["images_bucket_count"] == storage["thumbnails_bucket_count"] == 1
        checked("reject_description", client.post("/api/upload", headers=headers,
                files={"image": ("wrong.jpg", sample, "image/jpeg")},
                data={"description": "a red sports car on a city street"}), 422)
        large = io.BytesIO()
        Image.new("RGB", (2000, 2000), "white").save(large, format="JPEG")
        checked("four_megapixels", client.post("/api/search/image", files={"image": ("large.jpg", large.getvalue(), "image/jpeg")}))
        def search(_):
            return client.post("/api/search/image", files={"image": ("query.jpg", sample, "image/jpeg")}).status_code
        with ThreadPoolExecutor(max_workers=4) as workers:
            report["concurrent_image_statuses"] = list(workers.map(search, range(4)))
        assert report["concurrent_image_statuses"] == [200] * 4
        checked("delete", client.delete(f"/api/admin/images/{image_id}", headers=headers))
        image_id = None
        final = checked("health_after", client.get("/api/health")).json()
        assert final["images_in_db"] == final["vectors_in_index"] == 0
        storage = client.get("/api/admin/storage", headers=headers).json()
        assert storage["images_bucket_count"] == storage["thumbnails_bucket_count"] == 0
        report["passed"] = True
    except Exception as error:
        report["passed"] = False
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if image_id:
            client.delete(f"/api/admin/images/{image_id}", headers=headers)
        client.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
