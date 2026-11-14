from pydantic_settings import BaseSettings
from pydantic import SecretStr, model_validator
from sqlalchemy.engine import URL, make_url
from typing import List, Literal, Optional


class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    
    # CLIP Model
    clip_backend: Literal["onnx", "torch"] = "onnx"
    clip_model: str = "ViT-B-32"
    clip_pretrained: str = "openai"
    clip_checkpoint: Optional[str] = None
    cache_dir: str = "./model_cache"
    onnx_model_dir: str = "./model_cache/onnx"
    onnx_precision: Literal["uint8", "fp16", "mixed", "q4f16", "q8f16"] = "q8f16"
    inference_threads: int = 1
    max_concurrent_inference: int = 1
    
    # POSTGRES_URL remains supported; separate fields avoid password URL escaping.
    postgres_url: Optional[SecretStr] = None
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "visiontext"
    postgres_user: str = "visiontext"
    postgres_password: Optional[SecretStr] = None
    postgres_ssl: Optional[Literal["disable", "require", "verify-full"]] = None

    storage_backend: Literal["s3", "google_drive"] = "s3"
    google_drive_client_id: str = ""
    google_drive_client_secret: Optional[SecretStr] = None
    google_drive_refresh_token: Optional[SecretStr] = None
    google_drive_folder_id: str = ""
    google_drive_folder_name: str = "VisionText"
    google_drive_namespace: str = "visiontext-rallvjbmmlezptdhtfzx"
    storage_timeout_seconds: int = 20
    
    # MinIO / S3
    minio_endpoint: str = "visiontext-minio:9000"
    minio_access_key: str = ""
    minio_secret_key: SecretStr = SecretStr("")
    minio_secure: bool = False
    minio_bucket_images: str = "visiontext-images"
    minio_bucket_thumbnails: str = "visiontext-thumbnails"
    
    # FAISS
    faiss_index_path: str = "./faiss_indices/faiss_index.bin"
    
    # Search & Upload
    max_upload_size: int = 10485760  # 10MB
    max_image_pixels: int = 4000000
    max_image_dimension: int = 1600
    embedding_batch_size: int = 32
    thumbnail_size: int = 256
    default_search_limit: int = 20
    text_search_threshold: float = 0.18  # Default para texto
    image_search_threshold: float = 0.65  # Default para imagen
    
    # Similarity validation for upload
    similarity_threshold: float = 0.20  # 20% de similitud mínima imagen-texto
    
    # CORS
    cors_origins: str 
    
    # Base URL
    base_url: str = "http://localhost:8000" 
    
    # Admin
    admin_username: str
    admin_password: str
    jwt_secret_key: str

    # Límite de intentos fallidos de login (ventana deslizante)
    login_max_attempts_per_ip: int = 5
    login_max_attempts_per_username: int = 10
    login_window_seconds: int = 900  # 15 minutos

    @model_validator(mode="after")
    def validate_connections(self):
        if not self.postgres_url and not self.postgres_password:
            raise ValueError("Configura POSTGRES_PASSWORD y los datos de conexión, o POSTGRES_URL")
        if self.storage_backend == "s3" and not (self.minio_access_key and self.minio_secret_key.get_secret_value()):
            raise ValueError("S3 requiere MINIO_ACCESS_KEY y MINIO_SECRET_KEY")
        if self.storage_backend == "google_drive" and not (
            self.google_drive_client_id and self.google_drive_client_secret
            and self.google_drive_client_secret.get_secret_value()
            and self.google_drive_refresh_token and self.google_drive_refresh_token.get_secret_value()
        ):
            raise ValueError("Google Drive requiere CLIENT_ID, CLIENT_SECRET y REFRESH_TOKEN; ejecuta scripts/authorize_google_drive.py")
        return self

    @property
    def database_url(self) -> URL:
        if self.postgres_url:
            url = make_url(self.postgres_url.get_secret_value())
            if url.drivername not in {"postgres", "postgresql", "postgresql+asyncpg"}:
                raise ValueError("POSTGRES_URL debe ser una conexión PostgreSQL")
            url = url.set(drivername="postgresql+asyncpg")
        else:
            url = URL.create("postgresql+asyncpg", username=self.postgres_user,
                             password=self.postgres_password.get_secret_value(),
                             host=self.postgres_host, port=self.postgres_port, database=self.postgres_db)
        query = dict(url.query)
        if "sslmode" in query:
            query["ssl"] = query.pop("sslmode")
        if self.postgres_ssl:
            query["ssl"] = self.postgres_ssl
        return url.set(query=query)
    
    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # .env can also contain Docker Compose's POSTGRES_PASSWORD.
        hide_input_in_errors = True


settings = Settings()
