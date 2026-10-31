from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # PG* имената са без долни черти (конвенция на libpq/asyncpg env)
    pg_host: str = Field(default="postgres", validation_alias="PGHOST")
    pg_port: int = Field(default=5432, validation_alias="PGPORT")
    pg_user: str = Field(default="meshgate", validation_alias="PGUSER")
    pg_password: str = Field(default="meshgate", validation_alias="PGPASSWORD")
    pg_database: str = Field(default="meshgate", validation_alias="PGDATABASE")

    meshgate_secret_key: str = "dev-only-secret"
    meshgate_admin_user: str = "admin"
    meshgate_admin_password: str = "admin"

    emqx_host: str = "emqx"
    emqx_api_port: int = 18083
    emqx_dashboard_user: str = "admin"
    emqx_dashboard_password: str = "public"
    emqx_ingest_user: str = "meshgate-ingest"
    emqx_ingest_password: str = "meshgate-ingest"

    retention_packets_raw: int = 14
    retention_events: int = 365

    # Т7: цикъл на критичния evaluator в секунди (тестов профил го смъква)
    critical_tick_s: float = 30.0

    # Демо емулатор (профил "demo"): api подготвя MQTT потребителя му при старт
    meshgate_emulator_user: str = ""
    meshgate_emulator_password: str = ""

    # SMTP за имейл известия (празен host = имейл каналите дават ясна грешка)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""


@lru_cache
def settings() -> Settings:
    return Settings()
