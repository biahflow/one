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
    # Caminho de administração de acesso (ADR 0011): o único papel com escrita em
    # `membership`. Separado do `database_url` justamente para que o caminho de
    # requisição não carregue esse privilégio.
    database_admin_url: str = (
        "postgresql+psycopg://portal_admin:portal_admin_local_only@localhost:5432/portal"
    )
    redis_url: str = "redis://localhost:6379/0"
    demo_mode: bool = False
    web_origin: str = "http://localhost:3000"

    # OIDC (ADR 0010). A API é *resource server*: só valida o token, nunca faz
    # code exchange. `oidc_issuer` e `oidc_jwks_url` são separadas de propósito —
    # o `iss` do token é o endereço que o navegador usa (localhost:8080), mas o
    # container da API só alcança o Keycloak pela rede interna (keycloak:8080).
    oidc_issuer: str = "http://localhost:8080/realms/portal-local"
    oidc_jwks_url: str = "http://localhost:8080/realms/portal-local/protocol/openid-connect/certs"
    oidc_audience: str = "portal-api"
    oidc_algorithms: tuple[str, ...] = ("RS256",)
    # Clientes autorizados a emitir tokens para esta API (claim `azp`).
    oidc_allowed_azp: tuple[str, ...] = ("portal-web",)
    oidc_jwks_cache_seconds: int = 300
    oidc_leeway_seconds: int = 30

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
