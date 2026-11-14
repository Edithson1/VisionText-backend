"""Authorize your Drive once, create VisionText's folders, and save private env values."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CLIENT_ID = "671243718941-v9qphoe5a4ipkefbj897q5ev543b3uiu.apps.googleusercontent.com"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    from google_auth_oauthlib.flow import InstalledAppFlow
    from app.services.google_drive import DriveConfig, GoogleDriveStorage, DRIVE_SCOPE, TOKEN_URI

    client_id = os.getenv("GOOGLE_DRIVE_CLIENT_ID", CLIENT_ID)
    client_secret = os.getenv("GOOGLE_DRIVE_CLIENT_SECRET") or getpass.getpass("Secreto del cliente Google (no se mostrará): ")
    if not client_secret.strip():
        raise SystemExit("Falta GOOGLE_DRIVE_CLIENT_SECRET")
    redirect = f"http://localhost:{args.port}/"
    print(f"Registra antes esta URI exacta en tu cliente OAuth Web: {redirect}")
    config = {"web": {"client_id": client_id, "client_secret": client_secret,
                      "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": TOKEN_URI,
                      "redirect_uris": [redirect]}}
    flow = InstalledAppFlow.from_client_config(config, scopes=[DRIVE_SCOPE], autogenerate_code_verifier=True)
    credentials = flow.run_local_server(
        host="localhost", port=args.port, open_browser=False, timeout_seconds=300,
        access_type="offline", prompt="consent",
        authorization_prompt_message="Abre este enlace y autoriza la cuenta que guardará las imágenes:\n{url}",
        success_message="Cuenta autorizada. Puedes cerrar esta pestaña y volver a la terminal.",
    )
    if not credentials.refresh_token:
        raise SystemExit("Google no entregó REFRESH_TOKEN. Vuelve a ejecutar y autorizar el acceso sin conexión.")
    storage = GoogleDriveStorage(DriveConfig(client_id=client_id, client_secret=client_secret,
                                            refresh_token=credentials.refresh_token,
                                            folder_name=os.getenv("GOOGLE_DRIVE_FOLDER_NAME", "VisionText"),
                                            namespace=os.getenv("GOOGLE_DRIVE_NAMESPACE", "visiontext-rallvjbmmlezptdhtfzx")))
    storage.init_buckets()
    values = {"STORAGE_BACKEND": "google_drive", "GOOGLE_DRIVE_CLIENT_ID": client_id,
              "GOOGLE_DRIVE_CLIENT_SECRET": client_secret, "GOOGLE_DRIVE_REFRESH_TOKEN": credentials.refresh_token,
              "GOOGLE_DRIVE_FOLDER_ID": storage.folder_id, "GOOGLE_DRIVE_FOLDER_NAME": storage.config.folder_name,
              "GOOGLE_DRIVE_NAMESPACE": storage.config.namespace}
    output = ROOT / ".env.drive"
    # Owner-only creation on Unix; .env.drive is excluded from Git and Docker.
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        target.write("# Privado: copia estas variables a Render; no publiques este archivo.\n")
        for key, value in values.items():
            target.write(f"{key}={json.dumps(value)}\n")
    print(f"Carpetas listas: https://drive.google.com/drive/folders/{storage.folder_id}")
    print(f"Variables guardadas en {output.name}. Copia sus VALORES a Render (sin las comillas del archivo).")
    print("El secreto y el refresh token no se imprimen. La base de datos se configura por separado.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # OAuth exceptions can contain authorization codes and credential payloads.
        raise SystemExit("No se pudo completar la conexión. Revisa cliente Web, URI de retorno y Drive API habilitada; vuelve a intentarlo.") from None
