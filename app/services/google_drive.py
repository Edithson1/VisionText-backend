"""Private Drive file storage; the catalog and embeddings remain in PostgreSQL."""
from dataclasses import dataclass, field
import json
import threading
from urllib.parse import quote
import uuid

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import requests
from app.services.storage_errors import StorageError

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKEN_URI = "https://oauth2.googleapis.com/token"
FOLDER_MIME = "application/vnd.google-apps.folder"


@dataclass(frozen=True)
class DriveConfig:
    client_id: str
    client_secret: str = field(repr=False)
    refresh_token: str = field(repr=False)
    folder_id: str = ""
    folder_name: str = "VisionText"
    namespace: str = "visiontext-rallvjbmmlezptdhtfzx"
    timeout: int = 20
    token_uri: str = TOKEN_URI


class TimedAuthRequest(Request):
    def __init__(self, session, timeout):
        super().__init__(session=session)
        self.timeout = timeout

    def __call__(self, *args, **kwargs):
        kwargs["timeout"] = self.timeout
        return super().__call__(*args, **kwargs)


class GoogleDriveStorage:
    provider = "google_drive"

    def __init__(self, config: DriveConfig, *, api_base="https://www.googleapis.com/drive/v3",
                 upload_base="https://www.googleapis.com/upload/drive/v3"):
        self.config = config
        self.api_base, self.upload_base = api_base.rstrip("/"), upload_base.rstrip("/")
        self._session = requests.Session()
        self._credentials = Credentials(token=None, refresh_token=config.refresh_token,
                                        client_id=config.client_id, client_secret=config.client_secret,
                                        token_uri=config.token_uri)
        self._auth_request = TimedAuthRequest(self._session, config.timeout)
        self._lock = threading.RLock()
        self.folder_id = config.folder_id
        self.folders = {}

    def _refresh(self):
        try:
            self._credentials.refresh(self._auth_request)
        except (GoogleAuthError, requests.RequestException):
            raise StorageError("No se pudo autorizar Google Drive. Revisa sus variables o vuelve a autorizar la cuenta.") from None

    def _request(self, method, path, *, upload=False, missing_ok=False, **kwargs):
        with self._lock:
            base_headers = dict(kwargs.pop("headers", {}))
            for attempt in range(2):
                if not self._credentials.valid:
                    self._refresh()
                headers = base_headers.copy()
                headers["Authorization"] = f"Bearer {self._credentials.token}"
                url = (self.upload_base if upload else self.api_base) + path
                try:
                    response = self._session.request(method, url, headers=headers,
                                                     timeout=(5, self.config.timeout), **kwargs)
                except requests.RequestException:
                    raise StorageError("Google Drive no respondió. Intenta la operación de nuevo.") from None
                if response.status_code == 401 and attempt == 0:
                    response.close()
                    self._refresh()
                    continue
                if response.status_code == 404 and missing_ok:
                    response.close()
                    return None
                if not 200 <= response.status_code < 300:
                    status = response.status_code
                    response.close()
                    raise StorageError(f"Google Drive rechazó la operación (HTTP {status}). Revisa permisos y cuota.")
                return response
        raise StorageError("Google Drive rechazó la autorización")

    @staticmethod
    def _q(value):
        return str(value).replace("\\", "\\\\").replace("'", "\\'")

    def _list(self, query):
        page_token = None
        while True:
            params = {"q": query, "pageSize": 1000,
                      "fields": "nextPageToken,files(id,name,mimeType,parents,appProperties,trashed)"}
            if page_token:
                params["pageToken"] = page_token
            response = self._request("GET", "/files", params=params)
            try:
                body = response.json()
            finally:
                response.close()
            yield from body.get("files", [])
            page_token = body.get("nextPageToken")
            if not page_token:
                break

    def _tag_query(self):
        return "trashed = false and appProperties has { key='visiontext_project' and value='" + self._q(self.config.namespace) + "' }"

    def _folder(self, name, role, parent=None):
        query = self._tag_query() + " and mimeType = '" + FOLDER_MIME + "'"
        query += " and appProperties has { key='visiontext_kind' and value='" + self._q(role) + "' }"
        if parent:
            query += " and '" + self._q(parent) + "' in parents"
        found = list(self._list(query))
        if len(found) > 1:
            raise StorageError("Hay carpetas duplicadas de VisionText. Configura GOOGLE_DRIVE_FOLDER_ID.")
        if found:
            return found[0]["id"]
        metadata = {"name": name, "mimeType": FOLDER_MIME,
                    "appProperties": {"visiontext_project": self.config.namespace, "visiontext_kind": role}}
        if parent:
            metadata["parents"] = [parent]
        response = self._request("POST", "/files", params={"fields": "id"}, json=metadata)
        try:
            return response.json()["id"]
        finally:
            response.close()

    def init_buckets(self):
        """Compatibility with S3 startup: find/create the private folder tree."""
        with self._lock:
            if self.folder_id:
                response = self._request("GET", "/files/" + quote(self.folder_id, safe=""),
                                         params={"fields": "id,mimeType,trashed"})
                try:
                    metadata = response.json()
                finally:
                    response.close()
                if metadata.get("trashed") or metadata.get("mimeType") != FOLDER_MIME:
                    raise StorageError("GOOGLE_DRIVE_FOLDER_ID no corresponde a una carpeta activa")
            else:
                self.folder_id = self._folder(self.config.folder_name, "root")
            self.folders = {"images": self._folder("imagenes", "images", self.folder_id),
                            "thumbnails": self._folder("miniaturas", "thumbnails", self.folder_id)}

    def _key_id(self, key, kind):
        if key.startswith("gdrive:"):
            return key.removeprefix("gdrive:")
        # Recover logical keys after an upload whose response was interrupted.
        query = self._tag_query() + " and '" + self._q(self.folders[kind]) + "' in parents"
        query += " and name = '" + self._q(key) + "'"
        found = list(self._list(query))
        if len(found) > 1:
            raise StorageError("Hay archivos duplicados con el mismo identificador")
        return found[0]["id"] if found else None

    def _upload(self, name, data, kind, content_type):
        with self._lock:
            existing = self._key_id(name, kind)
            if existing:
                return "gdrive:" + existing
            metadata = {"name": name, "parents": [self.folders[kind]],
                        "appProperties": {"visiontext_project": self.config.namespace, "visiontext_kind": kind}}
            boundary = uuid.uuid4().hex
            body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
                    + json.dumps(metadata).encode() + f"\r\n--{boundary}\r\nContent-Type: {content_type}\r\n\r\n".encode()
                    + data + f"\r\n--{boundary}--\r\n".encode())
            response = self._request("POST", "/files", upload=True, params={"uploadType": "multipart", "fields": "id"},
                                     headers={"Content-Type": f"multipart/related; boundary={boundary}"}, data=body)
            try:
                return "gdrive:" + response.json()["id"]
            finally:
                response.close()

    def upload_image(self, image_id, data, content_type="image/jpeg"):
        return self._upload(f"{image_id}.jpg", data, "images", content_type)

    def upload_thumbnail(self, image_id, data):
        return self._upload(f"{image_id}_thumb.jpg", data, "thumbnails", "image/jpeg")

    def _get(self, key, kind):
        with self._lock:
            file_id = self._key_id(key, kind)
            if not file_id:
                return None
            response = self._request("GET", "/files/" + quote(file_id, safe=""), params={"alt": "media"}, missing_ok=True)
            if response is None:
                return None
            try:
                return response.content
            finally:
                response.close()

    def get_image(self, key):
        return self._get(key, "images")

    def get_thumbnail(self, key):
        return self._get(key, "thumbnails")

    def _delete(self, key, kind):
        with self._lock:
            file_id = self._key_id(key, kind)
            if file_id:
                response = self._request("DELETE", "/files/" + quote(file_id, safe=""), missing_ok=True)
                if response is not None:
                    response.close()
            return True

    def delete_image(self, key):
        return self._delete(key, "images")

    def delete_thumbnail(self, key):
        return self._delete(key, "thumbnails")

    def ping(self):
        try:
            if not self.folder_id or len(self.folders) != 2:
                return False
            response = self._request("GET", "/files/" + quote(self.folder_id, safe=""),
                                     params={"fields": "id,trashed"})
            try:
                return not response.json().get("trashed", False)
            finally:
                response.close()
        except StorageError:
            return False

    def status(self):
        with self._lock:
            if not self.ping():
                raise StorageError("Google Drive no está disponible")
            counts = {kind: sum(1 for _ in self._list(self._tag_query() + " and '" + self._q(folder) + "' in parents"))
                      for kind, folder in self.folders.items()}
            return {"status": "connected", "provider": self.provider, "folder_id": self.folder_id,
                    "folder_url": f"https://drive.google.com/drive/folders/{self.folder_id}",
                    "folders": self.folders.copy(), "buckets": ["imagenes", "miniaturas"],
                    "images_bucket_count": counts["images"], "thumbnails_bucket_count": counts["thumbnails"]}
