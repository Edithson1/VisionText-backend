"""Local HTTP stand-in for the Drive/OAuth operations used by this backend.

Based on Google's files.create/list/get/delete and OAuth refresh contracts.
It deliberately does not model account permissions, consent, or Google quotas.
"""
from contextlib import contextmanager
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading
import time
from urllib.parse import parse_qs, unquote, urlparse


class DriveState:
    def __init__(self):
        self.files = {}
        self.tokens = set()
        self.refreshes = 0
        self.calls = []
        self.failures = {}
        self.delays = {}
        self.counter = 0
        self.reject_upload_suffix = None

    def create(self, metadata, data=b""):
        self.counter += 1
        file_id = f"fake-drive-file-{self.counter}"
        self.files[file_id] = {**metadata, "id": file_id, "trashed": False, "data": data}
        return file_id


def match_query(item, query):
    def decode(value):
        return value.replace("\\'", "'").replace("\\\\", "\\")
    for field in ("name", "mimeType"):
        condition = re.search(field + r"\s*=\s*'((?:\\.|[^'])*)'", query)
        if condition and item.get(field) != decode(condition[1]):
            return False
    for parent in re.findall(r"'((?:\\.|[^'])*)'\s+in parents", query):
        if decode(parent) not in item.get("parents", []):
            return False
    for key, value in re.findall(r"appProperties has\s*\{\s*key='((?:\\.|[^'])*)'\s+and\s+value='((?:\\.|[^'])*)'\s*\}", query):
        if item.get("appProperties", {}).get(decode(key)) != decode(value):
            return False
    return not item.get("trashed")


@contextmanager
def drive_server():
    state = DriveState()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body=None, media=False):
            data = body if media else json.dumps(body or {}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "image/jpeg" if media else "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            self.handle_call("POST")

        def do_GET(self):
            self.handle_call("GET")

        def do_DELETE(self):
            self.handle_call("DELETE")

        def handle_call(self, method):
            parsed = urlparse(self.path)
            path, params = parsed.path, parse_qs(parsed.query)
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state.calls.append((method, path, params))
            if path == "/token":
                values = parse_qs(body.decode())
                if values.get("client_secret") != ["fake-client-secret"] or values.get("refresh_token") != ["fake-refresh-token"]:
                    return self.reply(400, {"error": "invalid_grant"})
                state.refreshes += 1
                token = f"fake-access-{state.refreshes}"
                state.tokens.add(token)
                return self.reply(200, {"access_token": token, "token_type": "Bearer", "expires_in": 3600})
            if self.headers.get("Authorization", "").removeprefix("Bearer ") not in state.tokens:
                return self.reply(401)
            key = (method, path)
            failures = state.failures.get(key, [])
            if failures:
                return self.reply(failures.pop(0), {"error": {"message": "simulated upstream failure"}})
            if key in state.delays:
                time.sleep(state.delays[key])
            if method == "POST" and path.endswith("/files"):
                if path.startswith("/upload/"):
                    if not self.headers.get("Content-Type", "").startswith("multipart/related;"):
                        return self.reply(400, {"error": "expected multipart/related"})
                    message = BytesParser(policy=default).parsebytes(
                        ("Content-Type: " + self.headers["Content-Type"] + "\r\n\r\n").encode() + body)
                    parts = list(message.iter_parts())
                    metadata = json.loads(parts[0].get_payload(decode=True))
                    data = parts[1].get_payload(decode=True)
                else:
                    metadata, data = json.loads(body), b""
                if state.reject_upload_suffix and metadata.get("name", "").endswith(state.reject_upload_suffix):
                    return self.reply(503)
                return self.reply(200, {"id": state.create(metadata, data)})
            if method == "GET" and path == "/drive/v3/files":
                files = [{k: v for k, v in item.items() if k != "data"} for item in state.files.values()
                         if match_query(item, params.get("q", [""])[0])]
                offset = int(params.get("pageToken", ["0"])[0])
                result = {"files": files[offset:offset + 2]}
                if offset + 2 < len(files):
                    result["nextPageToken"] = str(offset + 2)
                return self.reply(200, result)
            if path.startswith("/drive/v3/files/"):
                file_id = unquote(path.removeprefix("/drive/v3/files/"))
                item = state.files.get(file_id)
                if item is None:
                    return self.reply(404)
                if method == "DELETE":
                    del state.files[file_id]
                    return self.reply(204)
                if params.get("alt") == ["media"]:
                    return self.reply(200, item["data"], media=True)
                return self.reply(200, {k: v for k, v in item.items() if k != "data"})
            return self.reply(501, {"error": "operation not modeled"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    state.base = f"http://127.0.0.1:{server.server_port}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
