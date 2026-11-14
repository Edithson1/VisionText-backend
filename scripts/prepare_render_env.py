"""Consolidate private Render settings without copying the local database password."""
import os
from pathlib import Path
import secrets

from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]


def prepare_render_env(root=ROOT):
    root = Path(root)
    target = root / ".env.render"
    if not target.exists():
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write((root / ".env.render.example").read_text(encoding="utf-8"))
    content = target.read_text(encoding="utf-8")
    private_header = content.replace(
        "# PLANTILLA PUBLICA: no pongas secretos reales en este archivo.\n"
        "# Genera tu archivo privado: python scripts/prepare_render_env.py",
        "# ARCHIVO PRIVADO: contiene credenciales reales. No compartir ni subir a GitHub.\n"
        "# Completa aqui POSTGRES_PASSWORD con la contraseña de PostgreSQL de Supabase.",
    )
    if private_header != content:
        target.write_text(private_header, encoding="utf-8")
    current = dotenv_values(target, interpolate=False)
    drive = dotenv_values(root / ".env.drive", interpolate=False)
    local = dotenv_values(root / ".env", interpolate=False)
    updates = {key: value for key, value in drive.items()
               if value and (key.startswith("GOOGLE_DRIVE_") or key == "STORAGE_BACKEND")}
    for key in ("ADMIN_USERNAME", "ADMIN_PASSWORD"):
        if not current.get(key) and local.get(key):
            updates[key] = local[key]
    if not current.get("JWT_SECRET_KEY"):
        updates["JWT_SECRET_KEY"] = secrets.token_urlsafe(48)
    for key, value in updates.items():
        set_key(str(target), key, value)
    return target


if __name__ == "__main__":
    prepare_render_env()
    print("Preparado .env.render sin mostrar secretos.")
    print("Completa POSTGRES_PASSWORD con la contraseña de PostgreSQL de Supabase.")
    print("Revisa ADMIN_PASSWORD, BASE_URL y CORS_ORIGINS antes de importar el archivo en Render.")
