"""Exercise real Drive HTTP serialization, APK replacement and the public download."""
import hashlib
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.android_download import android_download_router
from app.services.google_drive import APK_MIME, DriveConfig, GoogleDriveStorage
from app.services.storage_errors import StorageError
from drive_emulator import drive_server


def storage_for(server):
    storage = GoogleDriveStorage(
        DriveConfig(client_id="fake-client", client_secret="fake-client-secret",
                    refresh_token="fake-refresh-token", token_uri=server.base + "/token", timeout=1),
        api_base=server.base + "/drive/v3", upload_base=server.base + "/upload/drive/v3")
    storage.init_buckets()
    return storage


def client_for(storage):
    app = FastAPI()
    app.include_router(android_download_router(lambda: storage))
    return TestClient(app)


def test_publish_replace_and_download_without_login():
    with drive_server() as server:
        storage = storage_for(server)
        client = client_for(storage)
        assert client.get("/api/app/download").status_code == 404
        first = storage.publish_android_release(b"apk-v1\x00\xff", "1.3", 4)
        second = storage.publish_android_release(b"apk-v2\x00\xff", "1.4", 5)
        assert first["file_id"] == second["file_id"]
        assert len(server.files) == 4  # project root, two catalog folders, one APK
        assert second["sha256"] == hashlib.sha256(b"apk-v2\x00\xff").hexdigest()
        # Rediscover the APK after a backend restart with no stored file ID.
        restarted = storage_for(server)
        response = client_for(restarted).get("/api/app/download")
        assert response.status_code == 200
        assert response.content == b"apk-v2\x00\xff"
        assert response.headers["content-type"] == APK_MIME
        assert response.headers["content-disposition"] == 'attachment; filename="VisionText.apk"'
        assert response.headers["content-length"] == str(len(response.content))
        assert response.headers["cache-control"] == "no-store"
        assert not any("permissions" in path for _, path, _ in server.calls)
        assert ("PATCH", "/upload/drive/v3/files/" + first["file_id"]) in [(m, p) for m, p, _ in server.calls]


@pytest.mark.parametrize("status", [403, 429, 503])
def test_download_reports_drive_failures_without_secrets(status):
    with drive_server() as server:
        storage = storage_for(server)
        storage.publish_android_release(b"apk", "1.3", 4)
        server.failures[("GET", "/drive/v3/files")] = [status]
        response = client_for(storage).get("/api/app/download")
        assert response.status_code == 503
        assert "fake-" not in response.text


def test_failed_update_preserves_previous_release():
    with drive_server() as server:
        storage = storage_for(server)
        release = storage.publish_android_release(b"previous", "1.3", 4)
        server.failures[("PATCH", "/upload/drive/v3/files/" + release["file_id"])] = [503]
        with pytest.raises(StorageError):
            storage.publish_android_release(b"new", "1.4", 5)
        assert client_for(storage).get("/api/app/download").content == b"previous"


def test_catalog_images_cannot_be_served_as_apk():
    with drive_server() as server:
        storage = storage_for(server)
        storage.upload_image("VisionText.apk", b"private image")
        assert client_for(storage).get("/api/app/download").status_code == 404


def test_local_s3_has_no_android_download():
    assert client_for(SimpleNamespace(provider="s3")).get("/api/app/download").status_code == 404
