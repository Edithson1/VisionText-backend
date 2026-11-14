import asyncio
import io
from types import SimpleNamespace

import numpy as np
from PIL import Image

from app.config import settings
from app.services.faiss import FAISSService
from app.services.image import image_processing_service
import main


def test_pixel_limit_is_checked_before_inference(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(settings, "max_image_pixels", 100)
    image = io.BytesIO()
    Image.new("RGB", (11, 10)).save(image, format="PNG")
    # No model is loaded; this must reject without trying to encode the image.
    response = TestClient(main.app).post("/api/search/image", files={"image": ("large.png", image.getvalue(), "image/png")})
    assert response.status_code == 413


def test_upload_storage_dimensions_are_bounded(monkeypatch):
    monkeypatch.setattr(settings, "max_image_dimension", 100)
    image = io.BytesIO()
    Image.new("RGB", (300, 200)).save(image, format="PNG")
    record, _, original, _ = image_processing_service.process_image(image.getvalue(), "image.png")
    with Image.open(io.BytesIO(original)) as stored:
        assert stored.size == (100, 67)
        assert (record.width, record.height) == stored.size


def test_migration_reencodes_other_model_even_with_same_dimension(monkeypatch):
    old = np.array([1, 0], dtype="float32")
    new = np.array([0, 1], dtype="float32")
    updates = []

    async def batches(_):
        yield [("old", "old.jpg", old.tobytes(), "torch"), ("current", "current.jpg", new.tobytes(), "onnx-q4")]

    async def save(rows):
        updates.extend(rows)

    service = FAISSService()
    service.initialize_index(2, "onnx-q4")
    monkeypatch.setattr(main, "faiss_service", service)
    monkeypatch.setattr(main, "db_service", SimpleNamespace(iter_embedding_batches=batches, update_embeddings=save))
    monkeypatch.setattr(main, "storage_service", SimpleNamespace(get_image=lambda _: b"image"))
    monkeypatch.setattr(main, "clip_service", SimpleNamespace(embedding_model="onnx-q4", encode_image=lambda _: new))
    asyncio.run(main.load_embeddings_from_db(2))
    assert [row[0] for row in updates] == ["old"]
    assert updates[0][2] == "onnx-q4"
    np.testing.assert_array_equal(service.index.reconstruct_n(0, 2), np.stack([new, new]))
