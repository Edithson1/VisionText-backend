import asyncio
import io
from types import SimpleNamespace

from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest

from app.config import settings
from app.services.google_drive import DriveConfig, GoogleDriveStorage, StorageError
from app.services.faiss import FAISSService
from drive_emulator import drive_server
import main


def make_storage(server, **overrides):
    config = DriveConfig(client_id="fake-client", client_secret="fake-client-secret",
                         refresh_token="fake-refresh-token", token_uri=server.base + "/token", **overrides)
    return GoogleDriveStorage(config, api_base=server.base + "/drive/v3", upload_base=server.base + "/upload/drive/v3")


def test_private_folder_tree_is_reused_after_restart_and_files_remain_readable():
    with drive_server() as server:
        storage = make_storage(server)
        storage.init_buckets()
        assert len(server.files) == 3
        names = {item["name"] for item in server.files.values()}
        assert names == {"VisionText", "imagenes", "miniaturas"}
        image_id = storage.upload_image("example", b"image bytes")
        thumbnail_id = storage.upload_thumbnail("example", b"thumbnail bytes")
        assert image_id.startswith("gdrive:")
        restarted = make_storage(server)
        restarted.init_buckets()
        assert restarted.folder_id == storage.folder_id
        assert len(server.files) == 5
        assert restarted.get_image(image_id) == b"image bytes"
        assert restarted.get_thumbnail(thumbnail_id) == b"thumbnail bytes"
        assert restarted.status()["images_bucket_count"] == 1
        assert restarted.delete_image(image_id)
        assert restarted.delete_image(image_id)
        assert restarted.delete_thumbnail(thumbnail_id)
        assert restarted.get_image(image_id) is None
        assert len(server.files) == 3
        assert not any("permissions" in path for _, path, _ in server.calls)


def test_upload_retry_reuses_logical_key_and_preserves_multipart_after_401():
    with drive_server() as server:
        storage = make_storage(server)
        storage.init_buckets()
        server.failures[("POST", "/upload/drive/v3/files")] = [401]
        key = storage.upload_image("retry", b"bytes\x00\xff")
        assert storage.get_image(key) == b"bytes\x00\xff"
        assert storage.upload_image("retry", b"bytes\x00\xff") == key
        assert len(server.files) == 4
        assert server.refreshes == 2


def test_pagination_counts_files_in_the_correct_folders():
    with drive_server() as server:
        storage = make_storage(server)
        storage.init_buckets()
        for index in range(5):
            storage.upload_image(str(index), b"image")
        storage.upload_thumbnail("0", b"thumbnail")
        result = storage.status()
        assert result["images_bucket_count"] == 5
        assert result["thumbnails_bucket_count"] == 1
        assert result["provider"] == "google_drive"


@pytest.mark.parametrize("status", [403, 429, 503])
def test_remote_failures_do_not_report_success_or_leak_tokens(status):
    with drive_server() as server:
        storage = make_storage(server)
        storage.init_buckets()
        server.failures[("POST", "/upload/drive/v3/files")] = [status]
        with pytest.raises(StorageError) as error:
            storage.upload_image("failure", b"image")
        assert "fake-client-secret" not in str(error.value)
        assert "fake-refresh-token" not in str(error.value)
        assert len(server.files) == 3


def test_timeout_is_bounded_and_reported_as_unavailable():
    with drive_server() as server:
        storage = make_storage(server, timeout=1)
        storage.init_buckets()
        server.delays[("GET", "/drive/v3/files/" + storage.folder_id)] = 2
        assert not storage.ping()


def test_oauth_failure_is_sanitized():
    with drive_server() as server:
        config = DriveConfig(client_id="fake", client_secret="secret-never-log",
                             refresh_token="bad-refresh", token_uri=server.base + "/token")
        storage = GoogleDriveStorage(config, api_base=server.base + "/drive/v3")
        with pytest.raises(StorageError) as error:
            storage.init_buckets()
        assert "secret-never-log" not in str(error.value)
        assert "bad-refresh" not in str(error.value)


def test_api_saves_drive_ids_and_retains_catalog_on_remote_delete_failure(monkeypatch, tmp_path):
    with drive_server() as server:
        storage = make_storage(server)
        storage.init_buckets()
        records = {}

        async def insert(record, embedding, embedding_model):
            records[record.id] = record
            return True

        async def get(image_id):
            return records.get(image_id)

        async def delete(image_id):
            records.pop(image_id)
            return True

        fake_db = SimpleNamespace(insert_image=insert, get_image=get, delete_image=delete)
        index = FAISSService()
        index.initialize_index(2, "test")
        monkeypatch.setattr(settings, "faiss_index_path", str(tmp_path / "faiss.bin"))
        monkeypatch.setattr(main, "storage_service", storage)
        monkeypatch.setattr(main, "db_service", fake_db)
        monkeypatch.setattr(main, "faiss_service", index)
        monkeypatch.setattr(main, "clip_service", SimpleNamespace(encode_image=lambda _: np.array([1, 0], dtype="float32"), embedding_model="test"))
        client = TestClient(main.app)
        token = client.post("/api/admin/login", data={"username": settings.admin_username, "password": settings.admin_password}).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        image = io.BytesIO()
        Image.new("RGB", (8, 8), "white").save(image, format="PNG")
        response = client.post("/api/upload", headers=headers, files={"image": ("image.png", image.getvalue(), "image/png")})
        assert response.status_code == 200, response.text
        image_id = response.json()["image_id"]
        assert records[image_id].image_path.startswith("gdrive:")
        assert records[image_id].thumbnail_path.startswith("gdrive:")
        assert client.get(f"/api/images/{image_id}").status_code == 200
        assert client.get("/api/admin/storage", headers=headers).json()["provider"] == "google_drive"
        path = "/drive/v3/files/" + records[image_id].image_path.removeprefix("gdrive:")
        server.failures[("DELETE", path)] = [503]
        assert client.delete(f"/api/admin/images/{image_id}", headers=headers).status_code == 503
        assert image_id in records and index.get_count() == 1
        assert client.delete(f"/api/admin/images/{image_id}", headers=headers).status_code == 200
        assert not records and index.get_count() == 0
        assert len(server.files) == 3


@pytest.mark.parametrize("thumbnail_failure", [True, False])
def test_api_cleans_drive_files_when_thumbnail_or_database_write_fails(monkeypatch, thumbnail_failure):
    with drive_server() as server:
        storage = make_storage(server)
        storage.init_buckets()
        if thumbnail_failure:
            server.reject_upload_suffix = "_thumb.jpg"

        async def not_inserted(*args):
            return False

        async def no_record(*args):
            return None

        monkeypatch.setattr(main, "storage_service", storage)
        monkeypatch.setattr(main, "db_service", SimpleNamespace(insert_image=not_inserted, get_image=no_record))
        monkeypatch.setattr(main, "clip_service", SimpleNamespace(encode_image=lambda _: np.array([1, 0], dtype="float32"), embedding_model="test"))
        client = TestClient(main.app)
        token = client.post("/api/admin/login", data={"username": settings.admin_username, "password": settings.admin_password}).json()["access_token"]
        image = io.BytesIO()
        Image.new("RGB", (8, 8)).save(image, format="PNG")
        response = client.post("/api/upload", headers={"Authorization": "Bearer " + token},
                               files={"image": ("image.png", image.getvalue(), "image/png")})
        assert response.status_code == (503 if thumbnail_failure else 500)
        assert len(server.files) == 3
