from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Uma URL por papel do Postgres (ADR 0010). `database_url` é o caminho de
    # requisição e usa portal_app, que está sujeito à RLS; os outros dois são
    # deliberadamente separados para que o privilégio fique na credencial.
    database_url: str = "postgresql+psycopg://portal_app:portal_app_local_only@localhost:5432/portal"
    database_system_url: str = (
        "postgresql+psycopg://portal_system:portal_system_local_only@localhost:5432/portal"
    )
    database_migration_url: str = (
        "postgresql+psycopg://portal_migrator:portal_migrator_local_only@localhost:5432/portal"
    )
    redis_url: str = "redis://localhost:6379/0"
    demo_mode: bool = False
    web_origin: str = "http://localhost:3000"

    # Integração com o Biahflow (ADR 0006) — fonte da verdade do status.
    biahflow_base_url: str = "http://localhost:19000/api/v1"
    biahflow_read_token: str = ""
    biahflow_webhook_secret: str = ""

    # Cliente demo provisionado ao sincronizar em demo_mode (Fase 2).
    portal_client_email: str = "marina.farias@acme.com.br"
    portal_client_name: str = "Marina Farias"

    # Chat contextual (Fase 3, ADR 0007). Sem chave → respondedor offline determinístico.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"
    chat_prompt_version: str = "chat-2026-08-03"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
