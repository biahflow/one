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

    # Qual ambiente é este (Fase 5, ADR 0022). O padrão é `local` porque é o
    # único valor que uma máquina de desenvolvimento pode afirmar sem configurar
    # nada — e porque um padrão que já se declarasse ambiente sério faria a
    # recusa de `_refuse_unsafe` disparar no primeiro `pytest`.
    #
    # Não é decoração: fora de `local`, `preflight()` recusa subir com segredo de
    # exemplo, `DEMO_MODE` ligado ou endereço em texto claro. A regra é a da ADR
    # 0017 — *um ambiente que não pode provar que está seguro não afirma que
    # está* —, e ela existe porque todo `${VAR}` do compose tem default local:
    # sem esta checagem, um `.env` de homologação a que falte uma chave sobe
    # verde com a senha do exemplo.
    environment: str = "local"

    # Telemetria (Fase 5, ADR 0018). `json` é o padrão porque é o formato que um
    # coletor lê e o que o runbook de incidente pressupõe; `text` existe para o
    # `docker compose logs` de quem está desenvolvendo, e **também** imprime os
    # campos de `extra` — descartá-los era o defeito do formato padrão do
    # `logging`, não uma escolha de formato.
    log_level: str = "INFO"
    log_format: str = "json"

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

    # Convite de acesso (ADR 0011). O endereço é o interno: é conversa
    # servidor-a-servidor, a mesma separação do par issuer/JWKS acima.
    keycloak_internal_url: str = "http://localhost:8080"
    keycloak_realm: str = "portal-local"
    keycloak_admin_client_id: str = "portal-admin"
    keycloak_admin_client_secret: str = ""
    # Client de login: é o dono do `redirect_uri` para onde o convite volta.
    keycloak_web_client_id: str = "portal-web"
    portal_web_url: str = "http://localhost:3000"
    invitation_lifespan_seconds: int = 86_400

    # Integração com o Biahflow (ADR 0006) — fonte da verdade do status.
    biahflow_base_url: str = "http://localhost:19000/api/v1"
    biahflow_read_token: str = ""
    biahflow_webhook_secret: str = ""

    # Cliente demo provisionado ao sincronizar em demo_mode (Fase 2).
    portal_client_email: str = "marina.farias@acme.com.br"
    portal_client_name: str = "Marina Farias"

    # Notificações por e-mail (Fase 2, ADR 0012). O convite sai pelo SMTP do
    # realm; este é o do próprio portal. Local é o Mailpit do compose, e em
    # produção qualquer SMTP — nenhum SDK de provedor entra por causa disso.
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    notifications_from_email: str = "portal@portallabs.local"
    notifications_from_name: str = "Portal Labs"
    # Desligado por padrão: um ambiente sem SMTP configurado não deve empilhar
    # falha de conexão a cada webhook. O compose liga.
    notifications_email_enabled: bool = False

    # API de eventos dos agentes (Fase 3, ADR 0013). O pepper entra no HMAC que
    # substitui a chave no banco: a entropia da própria chave é o que a torna
    # inquebrável, e o pepper é o que impede um vazamento **só do banco** de
    # virar chave utilizável. Vazio significa "nenhuma chave autentica" — falha
    # fechada, para um ambiente mal configurado não abrir a rota de ingestão.
    agent_key_pepper: str = ""
    #: Requisições por chave por minuto. Janela deslizante guardada na própria
    #: linha da chave, sem Redis no caminho de requisição.
    agent_events_rate_limit: int = 120
    #: Validade padrão de uma chave nova. Prazo é obrigatório: credencial de
    #: máquina sem expiração é credencial que ninguém troca.
    agent_key_lifetime_days: int = 180

    # Chat contextual (Fase 3, ADR 0007). Sem chave → respondedor offline determinístico.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"
    #: Perguntas por pessoa por minuto (Fase 5, ADR 0021). A assimetria com os 120
    #: de `agent_events_rate_limit` **é** o argumento: um agente é máquina e 120/min
    #: é vazão normal de ingestão; 20/min fica muito acima de alguém formulando uma
    #: pergunta pensada e muito abaixo do que um script precisa para inundar de
    #: pendência o time interno — que é a ameaça aqui, não a conta de token.
    chat_rate_limit: int = 20

    # Teto mensal de gasto de IA por organização, em centavos (Fase 5, ADR 0022).
    # É o **padrão**: `organization_ai_quota.monthly_limit_cents` sobrepõe por
    # organização, e coluna nula ali significa "usa este número" — nunca "sem
    # teto", que é a regra da retenção (ADR 0017).
    #
    # US$ 200/mês é folgado para um projeto conversando e apertado para um laço:
    # aos preços da 0018, são ~13 mil perguntas médias. Zero **desliga** a
    # cobrança, e é a única forma de desligar — uma decisão explícita, em vez de
    # um esquecimento que se pareça com uma.
    ai_quota_monthly_cents: int = 20_000

    # Storage dos documentos (Fase 4, ADR 0014). Local é o MinIO do compose; em
    # produção é o S3, e só estas variáveis mudam. Sem credencial o upload
    # responde 503 em vez de gravar metadado de um arquivo que não existe —
    # um `document` sem objeto seria uma linha que nunca vira evidência.
    storage_endpoint_url: str = "http://localhost:9000"
    #: O mesmo storage, pelo endereço que o **navegador** alcança. Dois endereços
    #: para um MinIO, e não é engano — é a mesma divisão de
    #: `KEYCLOAK_ISSUER`/`KEYCLOAK_INTERNAL_URL` (ADR 0010), pelo mesmo motivo: a
    #: API e o worker falam com o serviço pela rede interna do compose, e a URL
    #: assinada é aberta pelo cliente, de fora dela. A assinatura SigV4 cobre o
    #: host, então ela precisa ser gerada já contra o endereço público — trocar a
    #: URL depois de assinada a invalidaria. Vazio = usa o de cima, que é o certo
    #: quando os dois endereços coincidem (S3 gerenciado).
    storage_public_endpoint_url: str = ""
    storage_bucket: str = "portal-documents"
    storage_access_key: str = ""
    storage_secret_key: str = ""
    storage_region: str = "us-east-1"
    #: Teto do upload. Vale como primeira barreira; o tamanho real é conferido
    #: enquanto o arquivo é lido, porque `content-length` vem do cliente.
    document_max_bytes: int = 25 * 1024 * 1024
    #: Validade da URL assinada de download (Fase 5, ADR 0017). Curta de
    #: propósito: a URL não carrega sessão, então quem a tiver a usa — o que
    #: limita o estrago é ela vencer, não quem a pediu.
    document_download_ttl_seconds: int = 300

    # Varredura antimalware (Fase 5, ADR 0017). Sem `CLAMAV_HOST` o veredito é
    # `skipped`, e **não** `clean`: um scanner ausente não afirma que o arquivo
    # está limpo. Ver o docstring de `portal_api/scanner.py`.
    clamav_host: str = ""
    clamav_port: int = 3310
    #: Generoso porque a varredura roda no worker, não no caminho de requisição,
    #: e um arquivo no teto de 25 MiB leva mais que os 5s habituais.
    clamav_timeout_seconds: float = 60.0

    # Índice do projeto (Fase 4, ADR 0014). Sem VOYAGE_API_KEY o embedder é o
    # offline determinístico — mesma forma da ADR 0007 para o respondedor: CI e
    # demo rodam sem chave e sem rede, e a dimensão da coluna não muda.
    voyage_api_key: str = ""
    voyage_model: str = "voyage-3"
    #: Dimensão da coluna `document_chunk.embedding`. Mudar aqui exige migração
    #: **e** reindexação: um vetor de outra dimensão não é comparável.
    embedding_dimensions: int = 1024
    #: Chunks recuperados por pergunta.
    rag_top_k: int = 6
    #: Corte de distância de cosseno. Sem ele toda pergunta acha "o chunk menos
    #: distante" e a citação vira ruído com aparência de fonte. São dois valores
    #: porque são dois espaços: o do provedor aproxima pergunta e resposta sem
    #: palavra em comum, e o offline é lexical — num deles a distância entre uma
    #: pergunta curta e um parágrafo longo é sempre alta, mesmo quando o
    #: parágrafo responde. Um número só deixaria a demo sem citar nada ou o
    #: provedor citando ruído.
    rag_max_distance: float = 0.6
    rag_offline_max_distance: float = 0.92
    #: Tamanho alvo do chunk, em caracteres, e a sobreposição entre vizinhos.
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 150

    # Conector do Google Drive (Fase 4, ADR 0016). Sem client id/secret o portal
    # responde 503 nas rotas do conector: aqui não há caminho offline que
    # signifique alguma coisa — um "Drive determinístico" não seria o Drive de
    # ninguém —, então a falha é fechada como a do storage, e não degradada como
    # a do embedder.
    google_drive_client_id: str = ""
    google_drive_client_secret: str = ""
    #: Para onde o Google devolve o navegador depois do consentimento. Fica
    #: **fora** de `/api/` de propósito: `proxy.ts` responde 401 JSON sob `/api/`
    #: e só redireciona para `/login` fora dele, e o callback é uma navegação de
    #: navegador — uma sessão expirada durante o consentimento entregaria JSON no
    #: lugar da tela de login.
    google_drive_redirect_uri: str = "http://localhost:3000/admin/conhecimento/drive-callback"
    #: Escopo único, e somente leitura. O threat model cobra isto explicitamente
    #: ("OAuth Drive excessivo | escopo readonly e folder allowlist").
    google_drive_scope: str = "https://www.googleapis.com/auth/drive.readonly"
    #: As três bases existem separadas para poderem apontar a um stub local, do
    #: mesmo jeito que `biahflow_base_url` aponta. É o que permite ao e2e provar
    #: o conector inteiro sem credencial do Google.
    google_oauth_authorize_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    google_oauth_token_url: str = "https://oauth2.googleapis.com/token"
    google_drive_api_base_url: str = "https://www.googleapis.com/drive/v3"
    #: Chave AES-256-GCM do `crypto.py`, 32 bytes em base64url. Vazia = nenhuma
    #: conexão do Drive funciona. Ela protege o refresh token no banco, então não
    #: pode viver no banco.
    drive_token_encryption_key: str = ""
    #: A chave anterior, durante uma rotação. O pepper da ADR 0013 não precisa de
    #: par porque chave de agente se reemite; um refresh token não — girar sem
    #: janela de decifra obrigaria cada projeto a refazer o consentimento no
    #: Google. O sync seguinte re-sela com a atual e a anterior pode sair.
    drive_token_encryption_key_previous: str = ""
    #: Desligado por padrão: uma stack local sem credencial não deve acordar a
    #: cada 15 minutos para falhar contra o Google.
    drive_sync_enabled: bool = False
    drive_sync_interval_seconds: int = 900
    #: A pasta autorizada é uma árvore, não uma lista. Profundidade e teto são o
    #: que impedem uma pasta compartilhada enorme de virar um sync sem fim — e
    #: são o limite que o teste de travessia exercita.
    drive_max_depth: int = 5
    drive_max_files: int = 500
    #: Uma sincronização considerada travada depois disto pode ser recomeçada.
    #: Sem essa janela, um worker morto no meio do sync deixaria a conexão
    #: parada para sempre atrás da guarda de sobreposição.
    drive_sync_stale_after_seconds: int = 1800
    #: Validade do `state` do OAuth entre pedir o consentimento e voltar dele.
    drive_oauth_state_ttl_seconds: int = 600

    # Retenção e expurgo (Fase 5, ADR 0017). Ligado por padrão, ao contrário do
    # sync do Drive: aquele precisa de credencial de terceiro, este só precisa do
    # próprio banco — e "nunca poda" é justamente a dívida que as ADRs 0012 e
    # 0015 declararam.
    retention_enabled: bool = True
    #: De quanto em quanto tempo o beat acorda para podar. Diário: a poda é por
    #: janela de dias, então rodar de hora em hora só multiplicaria varreduras
    #: que não encontram nada.
    retention_interval_seconds: int = 24 * 60 * 60
    #: Os padrões, usados quando a organização não tem linha em
    #: `organization_retention_policy`. Nulo ali significa "usa isto", não
    #: "guarda para sempre".
    retention_notification_days: int = 180
    retention_agent_event_days: int = 730
    retention_conversation_days: int = 365
    #: Mais longo que os outros de propósito: o *time-to-first-value* só significa alguma
    #: coisa comparado com o de coortes anteriores, e uma janela curta apagaria a
    #: comparação junto com o dado (RFC 001).
    retention_onboarding_days: int = 1095
    #: Teto de linhas removidas por tabela em cada passagem. A poda é feita em
    #: lotes para um acervo antigo não virar uma transação de horas segurando
    #: lock; o que sobra sai na passagem seguinte.
    retention_batch_size: int = 5000
    #: Um expurgo em ``running`` há mais que isto pode ser recomeçado (ADR 0028).
    #: Mesmo número e mesmo motivo do `drive_sync_stale_after_seconds`, e a
    #: omissão dele aqui custava mais: uma conexão de Drive presa deixa de
    #: sincronizar, um expurgo preso deixa uma obrigação contratual por cumprir
    #: **e** tranca a tela, porque `admin.py` recusa pedido novo enquanto houver
    #: `pending` ou `running`.
    erasure_stale_after_seconds: int = 1800

    # `extra="ignore"` porque o `.env` é compartilhado com o docker compose: ele
    # carrega POSTGRES_*, MINIO_* e KC_* que são do compose, não da aplicação.
    # Sem isso, quem segue o `cp .env.example .env` do README não consegue rodar
    # pytest — o CI não tem `.env` e passava sem notar.
    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
