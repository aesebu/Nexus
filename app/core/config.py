from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.fernet import Fernet


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEXUS_", env_file=".env")

    environment: str = "development"
    database_url: str = "sqlite:///./nexus.db"
    jwt_secret: str = "change-this-in-production"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    secret_encryption_key: SecretStr | None = None
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: SecretStr | None = None
    integration_allowed_hosts: str = ""

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        environment = self.environment.strip().lower()
        if environment not in {"development", "test", "production"}:
            raise ValueError("NEXUS_ENVIRONMENT must be development, test, or production")
        self.environment = environment
        if environment == "production":
            if self.jwt_secret == "change-this-in-production" or len(self.jwt_secret) < 32:
                raise ValueError("A strong NEXUS_JWT_SECRET is required in production")
            if self.jwt_issuer is None or not self.jwt_issuer.strip():
                raise ValueError("NEXUS_JWT_ISSUER is required in production")
            if self.jwt_audience is None or not self.jwt_audience.strip():
                raise ValueError("NEXUS_JWT_AUDIENCE is required in production")
            if self.secret_encryption_key is None:
                raise ValueError("NEXUS_SECRET_ENCRYPTION_KEY is required in production")
            try:
                Fernet(self.secret_encryption_key.get_secret_value().encode("ascii"))
            except (UnicodeEncodeError, ValueError) as exc:
                raise ValueError("NEXUS_SECRET_ENCRYPTION_KEY is invalid") from exc
        return self

    @field_validator("ai_api_key", mode="before")
    @classmethod
    def empty_ai_api_key_is_unconfigured(cls, value: str | SecretStr | None):
        if value == "":
            return None
        return value


settings = Settings()
