from pathlib import Path

from dotenv import dotenv_values, set_key

from scripts.prepare_render_env import prepare_render_env


def test_render_configuration_keeps_local_and_cloud_database_secrets_separate(tmp_path):
    template = Path(__file__).resolve().parents[1] / ".env.render.example"
    (tmp_path / template.name).write_bytes(template.read_bytes())
    (tmp_path / ".env").write_text(
        "POSTGRES_PASSWORD=local-only-password\nADMIN_USERNAME=owner\nADMIN_PASSWORD=local-admin\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.drive").write_text(
        "STORAGE_BACKEND=google_drive\nGOOGLE_DRIVE_REFRESH_TOKEN=first-token\n"
        "GOOGLE_DRIVE_FOLDER_ID=test-folder\n", encoding="utf-8",
    )
    target = prepare_render_env(tmp_path)
    values = dotenv_values(target, interpolate=False)
    assert values["POSTGRES_PASSWORD"] == ""
    assert values["ADMIN_USERNAME"] == "owner"
    assert values["ADMIN_PASSWORD"] == "local-admin"
    assert values["GOOGLE_DRIVE_REFRESH_TOKEN"] == "first-token"
    assert values["GOOGLE_DRIVE_FOLDER_ID"] == "test-folder"
    assert values["JWT_SECRET_KEY"]
    assert "local-only-password" not in target.read_text(encoding="utf-8")
    assert target.read_text(encoding="utf-8").startswith("# ARCHIVO PRIVADO")

    cloud_password = "cloud@password#with'quotes"
    set_key(str(target), "POSTGRES_PASSWORD", cloud_password)
    set_key(str(target), "ADMIN_PASSWORD", "cloud-admin")
    set_key(str(target), "BASE_URL", "https://my-api.example.com")
    set_key(str(tmp_path / ".env.drive"), "GOOGLE_DRIVE_REFRESH_TOKEN", "renewed-token")
    prepare_render_env(tmp_path)
    updated = dotenv_values(target, interpolate=False)
    assert updated["POSTGRES_PASSWORD"] == cloud_password
    assert updated["ADMIN_PASSWORD"] == "cloud-admin"
    assert updated["BASE_URL"] == "https://my-api.example.com"
    assert updated["JWT_SECRET_KEY"] == values["JWT_SECRET_KEY"]
    assert updated["GOOGLE_DRIVE_REFRESH_TOKEN"] == "renewed-token"
