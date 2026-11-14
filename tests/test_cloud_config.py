from app.config import Settings


def make_settings(**overrides):
    values = dict(postgres_url=None, postgres_host="aws-0-us-east-2.pooler.supabase.com",
                  postgres_user="postgres.example", postgres_password="p@ss:#/word", postgres_db="postgres",
                  postgres_ssl="require", storage_backend="google_drive", google_drive_client_id="public-client",
                  google_drive_client_secret="private-secret", google_drive_refresh_token="private-token")
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_password_is_encoded_by_url_builder_and_ssl_is_required():
    settings = make_settings()
    assert settings.database_url.password == "p@ss:#/word"
    assert settings.database_url.drivername == "postgresql+asyncpg"
    assert settings.database_url.query["ssl"] == "require"
    assert "private-secret" not in repr(settings)
    assert "private-token" not in repr(settings)


def test_standard_postgresql_url_is_normalized_for_asyncpg():
    settings = make_settings(postgres_url="postgresql://example:password@host:5432/db?sslmode=require")
    assert settings.database_url.drivername == "postgresql+asyncpg"
    assert settings.database_url.query == {"ssl": "require"}
