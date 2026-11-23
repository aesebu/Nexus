from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEXUS_", env_file=".env")

    database_url: str = "sqlite:///./nexus.db"
    jwt_secret: str = "change-this-in-production"
    jwt_algorithm: str = "HS256"
    secret_encryption_key: SecretStr | None = None
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: SecretStr | None = None

    @field_validator("ai_api_key", mode="before")
    @classmethod
    def empty_ai_api_key_is_unconfigured(cls, value: str | SecretStr | None):
        if value == "":
            return None
        return value


settings = Settings()
