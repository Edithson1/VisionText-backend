"""CI-only app: real inference/database, local HTTP Drive/OAuth stand-in.

Run explicitly with uvicorn drive_smoke_app:app --app-dir tests.
The production entrypoint main:app never imports this module.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drive_emulator import drive_server
from app.services.google_drive import DriveConfig, GoogleDriveStorage
import main

_context = drive_server()
_server = _context.__enter__()
main.storage_service = GoogleDriveStorage(
    DriveConfig(client_id="fake-client", client_secret="fake-client-secret",
                refresh_token="fake-refresh-token", token_uri=_server.base + "/token",
                namespace="visiontext-test"),
    api_base=_server.base + "/drive/v3", upload_base=_server.base + "/upload/drive/v3",
)
app = main.app


@app.get("/_test/provider")
async def test_provider_marker():
    return {"emulated_drive": True}
