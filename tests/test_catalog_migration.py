import pytest

from scripts.migrate_local_catalog import matching_record


def test_existing_catalog_record_is_reused_without_overwriting():
    source = {"id": "local-id", "filename": "photo.jpg", "description": None}
    existing = {"id": "cloud-id", "filename": "photo.jpg", "description": ""}
    assert matching_record(source, [existing]) is existing
    assert matching_record(source, [{"filename": "other.jpg"}]) is None


@pytest.mark.parametrize("existing", [
    [{"filename": "photo.jpg", "description": "different description"}],
    [{"filename": "photo.jpg"}, {"filename": "photo.jpg"}],
])
def test_conflicting_cloud_records_are_never_silently_reused(existing):
    with pytest.raises(RuntimeError):
        matching_record({"filename": "photo.jpg", "description": None}, existing)
