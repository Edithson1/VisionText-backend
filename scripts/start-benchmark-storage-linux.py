"""Start a task-local S3 server for the Linux memory test (no system install)."""
from pathlib import Path
import os
import subprocess

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
local = dotenv_values(root / ".env")
environment = os.environ.copy()
environment.update({"RUSTFS_ACCESS_KEY": local["MINIO_ACCESS_KEY"], "RUSTFS_SECRET_KEY": local["MINIO_SECRET_KEY"], "RUSTFS_CONSOLE_ENABLE": "false"})
directory = Path("/tmp/visiontext-benchmark-storage")
directory.mkdir(exist_ok=True)
(directory / "data").mkdir(exist_ok=True)
with (directory / "server.log").open("w") as log:
    process = subprocess.Popen([str(root / ".venv/rustfs-linux/rustfs"), "server", "--address", "0.0.0.0:59010", str(directory / "data")], env=environment, cwd=directory, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
(directory / "server.pid").write_text(str(process.pid))
print(f"Linux storage PID {process.pid}")
