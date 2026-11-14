"""Select file storage independently from the catalog database and inference engine."""
from app.config import settings


if settings.storage_backend == "google_drive":
    from app.services.google_drive import DriveConfig, GoogleDriveStorage
    storage_service = GoogleDriveStorage(DriveConfig(
        client_id=settings.google_drive_client_id,
        client_secret=settings.google_drive_client_secret.get_secret_value(),
        refresh_token=settings.google_drive_refresh_token.get_secret_value(),
        folder_id=settings.google_drive_folder_id,
        folder_name=settings.google_drive_folder_name,
        namespace=settings.google_drive_namespace,
        timeout=settings.storage_timeout_seconds,
    ))
else:
    from app.services.minio import minio_service as storage_service
