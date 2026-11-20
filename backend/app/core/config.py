from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "输煤取样数字孪生系统"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://coal_sampling:coal_sampling@localhost:5432/coal_sampling"
    jwt_secret: str = "change-this-development-secret"
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "change-this-development-password"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
