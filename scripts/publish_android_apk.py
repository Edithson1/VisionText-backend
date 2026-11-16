"""Publish the signed Android APK using the project's existing private Drive OAuth."""
import argparse
import json
import os
from pathlib import Path
import sys
import zipfile

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.google_drive import DriveConfig, GoogleDriveStorage
from app.services.storage_errors import StorageError


def configured_storage(env_file):
    values = {**dotenv_values(env_file, interpolate=False), **os.environ}
    required = ("GOOGLE_DRIVE_CLIENT_ID", "GOOGLE_DRIVE_CLIENT_SECRET",
                "GOOGLE_DRIVE_REFRESH_TOKEN", "GOOGLE_DRIVE_FOLDER_ID")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError("Faltan variables de Drive: " + ", ".join(missing)
                         + ". Usa el archivo .env.drive del proyecto o configura el entorno.")
    return GoogleDriveStorage(DriveConfig(
        client_id=values[required[0]], client_secret=values[required[1]],
        refresh_token=values[required[2]], folder_id=values[required[3]],
        namespace=values.get("GOOGLE_DRIVE_NAMESPACE", "visiontext-rallvjbmmlezptdhtfzx"), timeout=120,
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.drive")
    parser.add_argument("--check", action="store_true", help="Validar Drive antes de compilar")
    parser.add_argument("--apk", type=Path)
    parser.add_argument("--version-name")
    parser.add_argument("--version-code", type=int)
    args = parser.parse_args()
    if not args.check and not (args.apk and args.version_name and args.version_code):
        parser.error("Indica --apk, --version-name y --version-code")
    try:
        storage = configured_storage(args.env_file)
        # Also validates that the configured root really is an active project folder.
        storage.init_buckets()
        if args.check:
            print("Drive autorizado; carpeta del proyecto disponible.")
            return
        with zipfile.ZipFile(args.apk) as archive:
            if not {"AndroidManifest.xml", "classes.dex"}.issubset(archive.namelist()):
                raise ValueError("El archivo no es una APK de VisionText válida")
            if archive.testzip():
                raise ValueError("La APK está dañada")
        result = storage.publish_android_release(args.apk.read_bytes(), args.version_name, args.version_code)
        result["folder_url"] = f"https://drive.google.com/drive/folders/{storage.folder_id}"
        manifest = args.apk.with_suffix(".json")
        manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"APK publicada: {result['filename']} ({result['size']:,} bytes)")
        print(f"SHA-256: {result['sha256']}")
        print(f"Carpeta: {result['folder_url']}")
        print(f"Comprobante local: {manifest}")
    except (StorageError, ValueError, OSError, zipfile.BadZipFile) as error:
        print(f"No se publicó la APK: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
