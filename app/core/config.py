from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All settings come from environment variables (or a .env file)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Vandi Ottunar User Service"
    environment: str = "development"  # development | production
    auto_create_tables: bool = False  # dev convenience; use Alembic in real deployments

    database_url: str = "postgresql+asyncpg://vandi:vandi@localhost:5432/vandi_users"

    # Auth
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 24 * 7
    file_token_minutes: int = 5
    admin_phones: str = ""  # comma-separated, e.g. "+919876543210,+919812345678"

    # OTP
    otp_length: int = 6
    otp_ttl_seconds: int = 300
    otp_resend_seconds: int = 30
    otp_max_attempts: int = 5

    # SMS
    sms_provider: str = "console"  # console | msg91
    msg91_auth_key: str = ""
    msg91_template_id: str = ""

    # Document storage
    storage_backend: str = "local"  # local | s3
    local_storage_dir: str = "./uploads"
    s3_bucket: str = ""
    aws_region: str = "ap-south-1"
    max_upload_mb: int = 5

    # Licence OCR on the server: "none" (the app reads the photo on the device) or "textract" (AWS Textract)
    ocr_provider: str = "none"

    # Shared secret other services (order-service) send as X-Service-Token to call /internal/*
    service_token: str = ""

    # Consent (DPDP Act) — bump when the driver notice text changes
    consent_version: str = "2026-10-v1"

    cors_origins: str = "http://localhost:5173"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def admin_phone_set(self) -> set[str]:
        return {p.strip() for p in self.admin_phones.split(",") if p.strip()}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_for_runtime(self) -> None:
        if self.is_production:
            if self.jwt_secret in ("", "change-me") or len(self.jwt_secret) < 32:
                raise RuntimeError("JWT_SECRET must be set to a long random value in production")
            if self.sms_provider == "console":
                raise RuntimeError("SMS_PROVIDER=console is not allowed in production")
            if self.service_token and len(self.service_token) < 32:
                raise RuntimeError("SERVICE_TOKEN must be a long random value in production")
            if self.storage_backend == "s3" and not self.s3_bucket:
                raise RuntimeError("S3_BUCKET is required when STORAGE_BACKEND=s3")


@lru_cache
def get_settings() -> Settings:
    return Settings()
