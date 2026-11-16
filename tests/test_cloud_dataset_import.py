import base64

import numpy as np
import pytest

from scripts.import_cloud_dataset import record_arguments


def record(vector):
    return {"id": "image-id", "filename": "photo.jpg", "image_path": "gdrive:original",
            "thumbnail_path": "gdrive:thumbnail", "width": 256, "height": 256, "size": 100,
            "format": "JPEG", "created_at": "2026-11-16T00:00:00", "embedding_model": "pinned-model",
            "embedding_base64": base64.b64encode(vector.astype("float32").tobytes()).decode()}


def test_database_arguments_keep_drive_ids_and_valid_vector():
    vector = np.zeros(512, dtype="float32")
    vector[0] = 1
    args = record_arguments(record(vector))
    assert len(args) == 16
    assert args[3:5] == ("gdrive:original", "gdrive:thumbnail")
    assert args[13] == vector.tobytes()
    assert args[14:] == ("pinned-model", "google_drive")


@pytest.mark.parametrize("vector", [np.zeros(512), np.ones(256), np.full(512, np.nan)])
def test_invalid_embeddings_are_not_inserted(vector):
    with pytest.raises(ValueError):
        record_arguments(record(vector))


@pytest.mark.parametrize("key", ["image_path", "thumbnail_path"])
def test_missing_persistent_drive_ids_are_not_inserted(key):
    vector = np.zeros(512, dtype="float32")
    vector[0] = 1
    data = record(vector)
    data[key] = "logical-file-name.jpg"
    with pytest.raises(ValueError):
        record_arguments(data)
