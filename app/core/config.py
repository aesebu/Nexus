from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEXUS_", env_file=".env")

    database_url: str = "sqlite:///./nexus.db"
    jwt_secret: str = "change-this-in-production"
    jwt_algorithm: str = "HS256"


settings = Settings()
