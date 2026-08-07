import json
import logging
from datetime import date, datetime, timedelta, timezone
from time import perf_counter
from uuid import UUID

import httpx
import redis
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy import text

from portal_api import (
    access,
    admin,
    agent_auth,
    chat_limit,
    conversations,
    pending_comments,
    results,
    schemas,
    search,
    storage,
)
from portal_api.ai import quota
from portal_api.ai import service as chat_service
from portal_api.auth import CurrentPrincipal
from portal_api.config import get_settings
from portal_api.db.session import DbRole, bind_tenant, get_session
from portal_api.identity import resolve_user
from portal_api.integrations import biahflow
from portal_api.models import (
    AgentEvent,
    AgentEventOutcome,
    AuditLog,
    ConversationMessage,
    Document,
    Organization,
    Project,
)
from portal_api.preflight import preflight
from portal_api.repositories import (
    AgentEventRepository,
    ConversationMessageRepository,
    ConversationRepository,
    NotificationRepository,
    TenantContext,
)
from portal_api.scanner import ScanState
from portal_api.telemetry import TRACE_HEADER, TraceMiddleware, audit_data, configure_logging

logger = logging.getLogger(__name__)

settings = get_settings()
# Antes de qualquer coisa: sem isto os `extra={...}` deste módulo e dos outros
# não chegam ao stdout, que era o estado que o runbook de eventos descrevia como
# se não fosse (ADR 0018).
configure_logging()
# E logo depois: fora de `ENVIRONMENT=local`, recusa continuar com segredo de
# exemplo, `DEMO_MODE` ligado ou endereço em texto claro (ADR 0022). Na
# importação e não numa rota de saúde — um processo que já respondeu uma
# requisição com a senha do `.env.example` não tem como desfazer isso.
preflight(settings)
app = FastAPI(title="Portal Labs API", version="0.1.0", docs_url="/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type", TRACE_HEADER],
    # Sem isto o `fetch` do navegador não enxerga o header de volta. Hoje quem
    # chama a API é o BFF, que lê tudo; a exposição é para a resposta poder
    # carregar o id até a tela no dia em que algo no navegador falar direto.
    expose_headers=[TRACE_HEADER],
)
# Registrado **depois** do CORS e por isso executado **antes** dele: o Starlette
# empilha na ordem inversa do registro. É o que faz uma requisição barrada no
# CORS ainda aparecer no log com um `trace_id`.
app.add_middleware(TraceMiddleware)


#: Os únicos campos que um item de ``detail`` de 422 carrega (ADR 0023).
#:
#: Mora numa constante porque `openapi.py` a lê para podar o componente
#: ``ValidationError`` do esquema: o handler abaixo e o contrato publicado têm de
#: concordar, e a regra do `schemas.py` — *o modelo declara o que a rota devolve*
#: — não admite um esquema anunciando um campo que a resposta não traz. Foi
#: exatamente esse o defeito que a ADR 0020 recusou acrescentar ao repositório,
#: só que na direção oposta.
VALIDATION_DETAIL_FIELDS = ("type", "loc", "msg")


@app.exception_handler(RequestValidationError)
async def _validation_error_without_echo(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 diz **o que** está errado, nunca devolve o que foi enviado (ADR 0023).

    Achado ao subir o FastAPI para fechar os avisos do Starlette: a partir do
    ``0.141`` cada item de ``detail`` inclui ``ctx`` e ``input``, e ``input`` é o
    corpo inteiro da requisição. Numa API cujos corpos fossem todos inócuos isso
    seria só verborragia. Aqui não são: ``DriveCallbackIn`` tem ``code`` e
    ``state`` (`admin.py`), e o ``code`` é o authorization code do Google —
    trocável pelo refresh token que a ADR 0016 sela com AES-256-GCM justamente
    por ser o único segredo reversível do portal. Bastava o ``state`` estourar o
    tamanho para o 422 devolver o ``code`` em claro, num corpo de erro que cai no
    log de quem chamou e no access log de todo proxy no meio.

    Fica o que o produtor precisa para consertar a requisição — ``type``, ``loc``
    e ``msg`` — e sai o que ele já tem. Deliberadamente **não** é redação por
    nome de campo como a de `telemetry.py`: ali procura-se o campo suspeito entre
    muitos inócuos, e aqui *todo* ``input`` é o corpo de quem chamou. Uma
    allowlist por nome só adiaria o dia em que um corpo novo passa a carregar
    segredo — e nem pegaria estes dois, já que ``code`` e ``state`` não casam com
    nenhuma das dicas de `_SECRET_HINTS`.
    """
    detail = [
        {field: item.get(field) for field in VALIDATION_DETAIL_FIELDS}
        for item in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": detail}
    )


# Administração de acesso (ADR 0011): conjunto coeso, e o único que roda sob o
# papel `portal_admin`, por isso em módulo próprio.
app.include_router(admin.router)

#: A assinatura do webhook do Biahflow, declarada pelo mesmo motivo que as
#: outras duas (ADR 0020): ela é conferida imperativamente em
#: :func:`biahflow_webhook`, e o esquema não tinha como saber que a rota é
#: autenticada.
_WEBHOOK_SCHEME = APIKeyHeader(
    name="X-Biahflow-Signature",
    scheme_name="BiahflowSignature",
    auto_error=False,
    description="HMAC do corpo, com o segredo compartilhado (ADR 0006).",
)

#: As duas recusas que toda rota de cliente pode dar, escritas uma vez só.
#:
#: O texto é a parte que importa. A regra "404, nunca 403" está em `AGENTS.md`,
#: no `docs/api-contracts.md` e em quase todo docstring deste arquivo, e mesmo
#: assim não estava em lugar nenhum que uma ferramenta pudesse ler — quem
#: gerasse um cliente a partir do esquema trataria o 404 como "recurso
#: inexistente" e o 403 como possível. Aqui ele passa a ser uma propriedade do
#: contrato, e `test_openapi_contract.py` recusa qualquer rota que declare 403.
CLIENT_ERRORS: dict[int | str, dict[str, object]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": schemas.ErrorOut,
        "description": (
            "Token ausente, inválido, expirado, de outro emissor ou com e-mail "
            "não verificado. A resposta é sempre a mesma, e o motivo vive só no "
            "log (`auth.rejected`): distinguir os casos aqui permitiria sondar "
            "qual claim falhou."
        ),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": schemas.ErrorOut,
        "description": (
            "O chamador não tem vínculo com o recurso — ou ele não existe. "
            "**A API nunca responde 403**: um 403 confirmaria que o projeto "
            "existe a quem não deveria saber disso."
        ),
    },
}

#: A recusa por projeto sem escrita, declarada só nas rotas que escrevem (ADR 0036,
#: estendida na 0037 para o projeto apagado na origem).
#:
#: **Não entra em `CLIENT_ERRORS`**: aquele dicionário é o que toda rota de cliente
#: responde, e a maioria delas continua servindo um projeto arquivado — é o que
#: "visível e só leitura" quer dizer.
#:
#: 409, e a escolha tem argumento. 404 seria mentira e, pior, mentira cara: neste
#: contrato ele significa **exatamente** a ausência de vínculo, é a única resposta
#: que `test_authorization.py` verifica em toda rota escopada, e usá-lo aqui
#: tornaria "você não tem acesso" indistinguível de "este projeto acabou". 403 não
#: existe nesta API. O precedente é o 429 da quota (ADR 0022), que também recusou
#: sem ser sobre permissão: o código sai do **motivo**, e o motivo aqui é o estado
#: do recurso, que é o que 409 nomeia.
READ_ONLY_PROJECT_ERROR: dict[int | str, dict[str, object]] = {
    status.HTTP_409_CONFLICT: {
        "model": schemas.ErrorOut,
        "description": (
            "O projeto foi encerrado ou apagado no Biahflow e está em modo de "
            "consulta. A leitura continua aberta — o histórico é a evidência das "
            "respostas já dadas —, mas nada novo é escrito nele."
        ),
    },
}

#: Uma mensagem por motivo, e não uma só para os dois: quem lê o corpo é a tela, e
#: "encerrado" e "apagado na origem" pedem frases diferentes ao cliente. O código é o
#: mesmo porque o motivo é o mesmo tipo de coisa — o estado do recurso.
ARCHIVED_PROJECT_DETAIL = "Project archived"
DELETED_PROJECT_DETAIL = "Project deleted at source"


def _refuse_when_read_only(project: Project) -> None:
    """Fecha a escrita num projeto que o Biahflow encerrou ou apagou (ADR 0036/0037).

    Chamada **depois** do 404 em toda rota que a usa, e a ordem não é estilo: a
    recusa confirma que o projeto existe, então ela só pode acontecer depois de o
    vínculo do chamador ter sido estabelecido.

    A exclusão é verificada primeiro porque é o estado mais forte: um projeto pode ter
    sido encerrado e depois apagado, e aí a frase útil ao cliente é a segunda.
    """
    if project.source_deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=DELETED_PROJECT_DETAIL
        )
    if project.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=ARCHIVED_PROJECT_DETAIL
        )


class AgentEventIn(BaseModel):
    event_id: UUID
    project_id: UUID
    occurred_at: datetime
    agent_key: str = Field(min_length=3, max_length=80)
    time_saved_seconds: int = Field(ge=0)
    avoided_cost_cents: int = Field(ge=0)
    run_reference: str = Field(min_length=1, max_length=160)
    #: Desfecho da execução. Sem ele não há como dar fonte a precisão do fluxo
    #: nem a exceções tratadas — os dois cards que a Fase 3 tira da demonstração.
    outcome: AgentEventOutcome = AgentEventOutcome.success
    human_intervention: bool = False
    event_type: str = Field(default="agent_run", min_length=3, max_length=120)


class ChatIn(BaseModel):
    question: str = Field(min_length=3, max_length=2_000)
    project_id: UUID | None = None
    #: A thread a continuar. Ausente abre uma nova — é assim que "nova conversa"
    #: funciona sem endpoint próprio (ADR 0015).
    conversation_id: UUID | None = None


class FeedbackIn(BaseModel):
    helpful: bool
    #: Opcional, e o campo mais informativo do conjunto: o polegar diz que
    #: errou, o comentário diz o quê.
    comment: str | None = Field(default=None, max_length=500)


class NotificationsReadIn(BaseModel):
    #: Sem ids, marca tudo — é o que o sino faz ao abrir.
    ids: list[UUID] | None = None


class PreferencesIn(BaseModel):
    notify_by_email: bool | None = None


@app.get("/health", response_model=schemas.HealthOut)
def health() -> dict[str, str]:
    """Vivacidade: o processo respondeu. Não toca em dependência nenhuma."""
    return {"status": "ok", "service": "portal-api"}


@app.get(
    "/health/ready",
    response_model=schemas.ReadyOut,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": schemas.ReadyOut,
            "description": "Postgres ou Redis não responderam. Qual dos dois vai para o log.",
        }
    },
)
def health_ready(response: Response) -> dict[str, object]:
    """Prontidão: o Postgres e o Redis respondem (Fase 5, ADR 0018).

    Separado do ``/health`` porque as duas perguntas têm respostas diferentes e
    consequências diferentes: um processo vivo com o banco fora **não** deve
    receber tráfego, e um processo morto deve ser reiniciado. Só este é que serve
    de healthcheck no compose — o outro sempre diria "ok".

    **A rota é pública e o corpo é sim/não.** Sem versão, sem hostname, sem DSN,
    sem a mensagem do driver e sem dizer *qual* dependência caiu: quem não está
    autenticado não ganha um mapa da infraestrutura. Um `down` é indistinguível
    de outro, que é a mesma escolha do 401 opaco da `auth.py` — e, como lá, o
    motivo vai inteiro para o log, agora com o ``trace_id`` para ser encontrado.
    """
    ready = True

    try:
        with get_session(role=DbRole.app) as session:
            session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("health.database_unavailable")
        ready = False

    try:
        client = redis.Redis.from_url(settings.redis_url, socket_timeout=2)
        try:
            client.ping()
        finally:
            client.close()
    except Exception:
        logger.exception("health.broker_unavailable")
        ready = False

    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "down"}


@app.post(
    "/api/v1/agent-events",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=schemas.AgentEventAcceptedOut,
    # Só a chave, e é o esquema dizendo o que a ADR 0013 decidiu: a rota não
    # depende de `CurrentPrincipal`, então o Bearer não aparece aqui.
    dependencies=[Depends(agent_auth.SCHEME)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": schemas.ErrorOut,
            "description": (
                "Chave ausente, desconhecida, revogada, expirada ou sem escopo — "
                "sempre a mesma resposta, com o motivo em `agent_key.rejected`."
            ),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": schemas.ErrorOut,
            "description": (
                "O `project_id` do corpo não é o projeto da chave. O tenant é "
                "propriedade da credencial, então o do corpo é conferido, nunca "
                "acreditado."
            ),
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": schemas.ErrorOut,
            "description": (
                "Ritmo acima do limite da chave, com `Retry-After`. É o único "
                "caso que **não** é opaco: o produtor precisa distinguir ritmo "
                "de credencial para saber se deve tentar de novo."
            ),
        },
    },
)
def ingest_agent_event(event: AgentEventIn, request: Request) -> dict[str, str]:
    """Recebe um evento de execução, autenticado por chave de projeto (ADR 0013).

    A rota é **só por chave**: um agente não tem sessão de usuário, e o Bearer
    humano que valia até a Fase 2 deixou de valer aqui. Quem responde "qual
    projeto" é a credencial, então o ``projectId`` do corpo é conferido contra
    ela — discordar é 404, nunca 403, como no resto da API.

    A gravação roda em outra transação, sob ``portal_app`` com o tenant ligado,
    para o banco continuar sendo a segunda barreira na única rota que recebe
    identificador de fora.
    """
    identity = agent_auth.authenticate(request)
    if event.project_id != identity.project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    ctx = TenantContext(
        organization_id=identity.organization_id, project_id=identity.project_id
    )
    occurred_at = event.occurred_at
    if occurred_at.tzinfo is None:
        # Sem fuso, o instante seria interpretado pelo relógio do servidor e o
        # evento poderia cair no período errado. UTC é o contrato.
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)

    with get_session(role=DbRole.app) as session:
        bind_tenant(session, ctx)
        stored, created = AgentEventRepository(session, ctx).ingest(
            AgentEvent(
                event_type=event.event_type,
                occurred_at=occurred_at,
                external_event_id=str(event.event_id),
                agent_key=event.agent_key,
                outcome=event.outcome,
                human_intervention=event.human_intervention,
                time_saved_seconds=event.time_saved_seconds,
                avoided_cost_cents=event.avoided_cost_cents,
                run_reference=event.run_reference,
            )
        )
        if created:
            # Sem payload e sem a chave: `docs/data-classification.md` proíbe
            # segredo e dado confidencial no log de auditoria.
            session.add(
                AuditLog(
                    organization_id=ctx.organization_id,
                    project_id=ctx.project_id,
                    action="agent_event.ingested",
                    entity_type="agent_event",
                    entity_id=stored.id,
                    data=audit_data(
                        agent_key=event.agent_key, outcome=event.outcome.value
                    ),
                )
            )
    return {
        "event_id": str(event.event_id),
        "status": "accepted" if created else "duplicate",
    }


@app.post(
    "/api/v1/chat",
    response_model=schemas.ChatOut,
    responses={
        **CLIENT_ERRORS,
        **READ_ONLY_PROJECT_ERROR,
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": (
                "Perguntas demais na janela de um minuto (ADR 0021), ou teto mensal "
                "de gasto de IA da organização atingido (ADR 0022). Não é opaco de "
                "propósito, como o 429 da rota de eventos: quem pergunta precisa "
                "distinguir 'seu ritmo' de 'sua permissão' para saber se vale tentar "
                "de novo. O `Retry-After` diz em quantos segundos, e é o que separa "
                "os dois casos — segundos para o ritmo, o resto do mês para o teto."
            )
        },
    },
)
def chat(message: ChatIn, principal: CurrentPrincipal) -> dict:
    """Grounded, tenant-scoped chat: cite the read model or declare the gap + pendência (ADR 0007)."""
    # Antes da transação abrir (ADR 0021): o contador vive em transação própria,
    # para nenhum lock atravessar a chamada ao modelo. O preço é que um token
    # válido sem projeto vê 429 antes de 404 — que não conta nada sobre projeto
    # nenhum, só que a pessoa está autenticada, o que ela já sabe.
    chat_limit.consume(principal.subject, settings)

    with get_session(principal) as session:
        user = resolve_user(session, principal)
        if message.project_id is not None:
            project = access.scoped_project(session, user, message.project_id)
        else:
            project = access.default_project(session, user)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        # Depois do 404 e antes da quota (ADR 0036): não há o que cobrar por uma pergunta que
        # não será respondida. O limite de taxa lá em cima já contou, e isso é aceito — ele é
        # anterior a saber que projeto é, exatamente como no caso do 404.
        _refuse_when_read_only(project)
        ctx = TenantContext(organization_id=project.organization_id, project_id=project.id)
        # **Depois** do 404, ao contrário do limite de taxa acima, e a diferença
        # de ordem é deliberada (ADR 0022): sem projeto não há organização a que
        # cobrar, e recusar antes contaria a quem não tem vínculo que a
        # organização existe. Levanta 429 sem gravar nada — nem razão, nem
        # pendência, nem mensagem —, que é o que dá sentido ao controle: a
        # recusa não pode custar o que ela existe para evitar.
        quota.check(session, ctx, settings)
        result = chat_service.answer_question(
            session, ctx, project, message.question, settings, actor_user_id=user.id
        )
        # Persistido na mesma transação da resposta (ADR 0015): um turno
        # respondido e não gravado apareceria na tela e sumiria no reload, que é
        # pior do que não ter histórico.
        conversation, answer = conversations.append_turn(
            session,
            ctx,
            user_id=user.id,
            conversation_id=message.conversation_id,
            question=message.question,
            result=result,
        )
        project_id = project.id
        response = {
            "answer": result.answer,
            "sources": result.sources,
            # A citação com o ponteiro para o arquivo, quando ela veio de um
            # (ADR 0017). Mesma forma do histórico, para a tela não ter dois
            # caminhos de renderização para a mesma coisa.
            "citations": [
                {"label": item.citation, "document_id": item.document_id or None}
                for item in result.cited
            ],
            "confidence": result.confidence,
            "pending_created": result.pending_created,
            "conversation_id": str(conversation.id),
            "message_id": str(answer.id),
        }

    # Depois do commit, pelo mesmo motivo do webhook: o worker lê a pendência do
    # banco, então ela precisa existir lá antes da task rodar.
    if result.pending_id is not None:
        from portal_api.worker import queue_pending_notification

        queue_pending_notification(str(project_id), str(result.pending_id))
    return response


@app.post(
    "/api/v1/integrations/biahflow/webhook",
    response_model=schemas.WebhookSyncedOut,
    dependencies=[Depends(_WEBHOOK_SCHEME)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": schemas.ErrorOut,
            "description": "Assinatura ausente ou que não confere com o corpo.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": schemas.ErrorOut,
            "description": "Corpo sem `project_id`.",
        },
    },
)
async def biahflow_webhook(request: Request) -> dict:
    """Receive a signed Biahflow change notification and refresh the read model (ADR 0006)."""
    body = await request.body()
    signature = request.headers.get("X-Biahflow-Signature")
    if not biahflow.verify_signature(settings.biahflow_webhook_secret, body, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    payload = json.loads(body or b"{}")
    biahflow_project_id = payload.get("project_id")
    if not biahflow_project_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="project_id required")

    # O primeiro leitor que `event` teve (ADR 0037). O Biahflow manda `event` e `object_type` em
    # todo webhook desde a ADR 0006, e este lado nunca olhou nenhum dos dois — sempre buscou o
    # snapshot. Para a exclusão isso não serve: **não há snapshot depois dela**, e o 404 que a
    # busca traria não distingue "foi apagado" de "id de outra base" (ADR 0036). O fato só existe
    # no corpo, então é o corpo que precisa ser lido.
    if payload.get("event") == "deleted" and payload.get("object_type") == "project":
        with get_session(role=DbRole.system) as session:
            deleted = biahflow.mark_project_deleted(session, int(biahflow_project_id))
            project_ids = [str(project.id) for project in deleted]
        if not project_ids:
            # Nada a marcar: o portal nunca conheceu esse projeto. Mesma resposta do 404 abaixo,
            # e pelo mesmo motivo — não há o que reconciliar, e criar linha para um projeto que
            # já morreu seria inventar tenant.
            logger.warning(
                "biahflow.snapshot_missing",
                extra={"biahflow_project_id": str(biahflow_project_id)},
            )
            return {"status": "unknown_project", "project_id": None}
        logger.warning(
            "biahflow.project_deleted",
            extra={
                "biahflow_project_id": str(biahflow_project_id),
                "project_id": project_ids[0],
                "marked": len(project_ids),
            },
        )
        return {"status": "deleted", "project_id": project_ids[0]}

    try:
        snapshot = biahflow.fetch_snapshot(
            settings.biahflow_base_url, settings.biahflow_read_token, int(biahflow_project_id)
        )
    except httpx.HTTPStatusError as exc:
        # 404 aqui não é erro desta API, e virar 500 escondia isso atrás de um traceback
        # anônimo (ADR 0036). O caso que motivou o evento era arquivar um projeto, e esse
        # está resolvido do outro lado — o snapshot agora existe e declara `archived_at`.
        # O que sobra é id que nunca existiu ou base errada, e aí não há nada a reconciliar:
        # nomear e sair é mais honesto do que estourar.
        if exc.response.status_code != status.HTTP_404_NOT_FOUND:
            raise
        logger.warning(
            "biahflow.snapshot_missing",
            extra={"biahflow_project_id": str(biahflow_project_id)},
        )
        return {"status": "unknown_project", "project_id": None}
    # portal_system (BYPASSRLS): this is the path that creates the tenant, so
    # there is no context to bind and the write would be denied otherwise.
    with get_session(role=DbRole.system) as session:
        project = biahflow.sync_snapshot(session, snapshot)
        if settings.demo_mode:
            biahflow.ensure_demo_client(
                session, project, settings.portal_client_email, settings.portal_client_name
            )
        project_id = str(project.id)

    # Fora da transação: o e-mail só pode falar de notificações já comitadas.
    # Importado aqui porque `worker` traz o Celery junto, e a API não deve
    # depender do broker para subir.
    from portal_api.worker import queue_project_digests

    queue_project_digests(project_id)
    return {"status": "synced", "project_id": project_id}


@app.get(
    "/api/v1/me",
    response_model=schemas.MeOut,
    # Sem o 404 do bloco comum: esta é a única rota de cliente que **não** o
    # responde. Quem autentica e não tem vínculo recebe 200 com `projects`
    # vazio, e o esquema precisa dizer isso — é a diferença entre "não te
    # conheço" e "você ainda não tem projeto".
    responses={
        status.HTTP_401_UNAUTHORIZED: CLIENT_ERRORS[status.HTTP_401_UNAUTHORIZED]
    },
)
def me(principal: CurrentPrincipal) -> dict:
    """Who the caller is and what they can reach — the BFF renders the chrome from this.

    Returns 200 with an empty ``projects`` for an authenticated user who holds no
    membership: authentication is not authorization, and the portal has to be able
    to say "you have no project yet" instead of pretending the user is unknown.
    """
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        visible = access.visible_projects(session, user)

        organization = None
        if visible:
            record = session.get(Organization, visible[0][0].organization_id)
            organization = record.name if record else None

        return {
            "email": user.email,
            "full_name": user.full_name,
            "is_internal": user.is_internal,
            "notify_by_email": user.notify_by_email,
            "organization": organization,
            "projects": [
                {
                    "id": str(project.id),
                    "name": project.name,
                    "slug": project.slug,
                    "status": project.status.value,
                }
                for project, _ in visible
            ],
            "roles": sorted({role.value for _, roles in visible for role in roles}),
        }


@app.get(
    "/api/v1/projects/{project_id}/dashboard",
    response_model=schemas.DashboardOut,
    responses=CLIENT_ERRORS,
)
def project_dashboard(project_id: UUID, principal: CurrentPrincipal) -> dict:
    """Dashboard from the read model, scoped to the caller's membership (ADR 0002/0006)."""
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        project = access.scoped_project(session, user, project_id)
        # 404 (not 403) on any miss so we never leak which projects exist.
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        return biahflow.build_dashboard(session, project)


@app.get(
    "/api/v1/projects/{project_id}/results",
    response_model=schemas.ResultsOut,
    responses={
        **CLIENT_ERRORS,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": schemas.ErrorOut,
            "description": "`to` anterior ou igual a `from`.",
        },
    },
)
def project_results(
    project_id: UUID,
    principal: CurrentPrincipal,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
) -> dict:
    """O detalhamento por trás de cada número da aba Resultados (ADR 0013).

    Devolve o indicador **e** a premissa que o produziu, mais as lacunas quando
    falta base — é aqui que "o cliente vê a origem e a premissa de todo
    indicador" deixa de ser promessa. Leitura pelo caminho normal: a premissa é
    client-safe, o `portal_app` tem SELECT nela e a RLS escopa o resto.
    """
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        project = access.scoped_project(session, user, project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        period = (
            results.Period(start=from_, end=to)
            if from_ is not None and to is not None
            else results.Period.last_days()
        )
        if period.days <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="`to` must be after `from`",
            )
        ctx = TenantContext(
            organization_id=project.organization_id, project_id=project.id
        )
        return results.to_payload(results.compute_results(session, ctx, period))


@app.get(
    "/api/v1/me/documents/{document_id}/download",
    response_model=schemas.DocumentDownloadOut,
    responses={
        **CLIENT_ERRORS,
        status.HTTP_502_BAD_GATEWAY: {
            "model": schemas.ErrorOut,
            "description": "O storage recusou assinar a URL.",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": schemas.ErrorOut,
            "description": "Não há storage configurado.",
        },
    },
)
def document_download(document_id: UUID, principal: CurrentPrincipal) -> dict:
    """A URL temporária do documento que a IA citou (Fase 5, ADR 0017).

    Rota do **cliente**, e não da administração, porque quem precisa abrir o
    arquivo é quem leu "Documento: Contrato — página 3" e quer conferir a página
    3. Até aqui a citação apontava para uma evidência que só a equipe interna
    conseguia ver, o que é uma forma discreta de pedir confiança em vez de
    mostrar a fonte.

    Escopada em ``/me/`` como a caixa de avisos e o histórico da conversa, e pelo
    mesmo motivo prático: a citação nasce no chat, que já roda sobre o projeto
    que ``access.default_project`` resolve. O navegador não manda identificador
    de projeto nenhum — e o que ele não manda é o que ninguém precisa validar
    (regra 1 do `AGENTS.md`).

    Devolve endereço, não bytes (ver ``storage.presigned_get_url``).

    **Só entrega o que passou pela varredura.** Documento em `pending`, `error`
    ou `infected` não tem URL — e a resposta é o mesmo 404 de sempre, sem
    distinguir "não existe" de "não passou": o cliente não precisa saber que o
    portal recebeu um arquivo infectado, e a tela de administração já explica
    isso a quem é da casa.
    """
    settings = get_settings()
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        project = access.default_project(session, user)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

        # A RLS já escopa o `SELECT` ao projeto corrente, e a comparação abaixo é
        # a segunda barreira — a mesma dupla checagem da pasta do Drive.
        document = session.get(Document, document_id)
        if (
            document is None
            or document.project_id != project.id
            or not document.storage_key
            or document.scan_state not in (ScanState.clean, ScanState.skipped)
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

        try:
            url = storage.presigned_get_url(
                settings, document.storage_key, settings.document_download_ttl_seconds
            )
        except storage.StorageDisabled as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Document storage is not configured",
            ) from exc
        except storage.StorageError as exc:
            logger.exception("document.signing_failed", extra={"document_id": str(document_id)})
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="Storage unavailable"
            ) from exc

        # `docs/security.md` já listava download entre os eventos auditáveis, e
        # esta é a primeira rota que o torna possível. Sem o nome do arquivo: o
        # título é conteúdo do cliente e o id já identifica a linha.
        session.add(
            AuditLog(
                organization_id=project.organization_id,
                project_id=project.id,
                actor_user_id=user.id,
                action="document.downloaded",
                entity_type="document",
                entity_id=document.id,
                data=audit_data(ttl_seconds=settings.document_download_ttl_seconds),
            )
        )

    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.document_download_ttl_seconds
    )
    return {"url": url, "expires_at": expires_at.isoformat()}


@app.get(
    "/api/v1/me/dashboard",
    response_model=schemas.MyDashboardOut,
    responses=CLIENT_ERRORS,
)
def my_dashboard(principal: CurrentPrincipal) -> dict:
    """Dashboard for the caller's own project (the BFF calls this)."""
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        project = access.default_project(session, user)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No project for client")
        organization = session.get(Organization, project.organization_id)
        data = biahflow.build_dashboard(session, project)
        data["organization"] = organization.name if organization else None
        return data


@app.get(
    "/api/v1/me/notifications",
    response_model=schemas.NotificationsOut,
    responses=CLIENT_ERRORS,
)
def my_notifications(
    principal: CurrentPrincipal, unread_only: bool = False, limit: int = 50
) -> dict:
    """Avisos do projeto atual, do próprio destinatário (ADR 0012).

    Escopado ao projeto como o dashboard, e não à conta inteira: as policies de
    RLS leem as GUCs de organização/projeto, que só existem depois que
    ``access.default_project`` resolveu *um* projeto. Uma listagem que
    atravessasse projetos rodaria sem esse contexto — e sem contexto a policy
    devolve zero linhas, que é o comportamento certo, mas não a tela certa.
    """
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        project = access.default_project(session, user)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No project for client")
        repository = NotificationRepository(
            session, TenantContext(project.organization_id, project.id)
        )
        items = repository.list_for_user(
            user.id, unread_only=unread_only, limit=max(1, min(limit, 100))
        )
        return {
            "unread_count": repository.unread_count(user.id),
            "items": [
                {
                    "id": str(item.id),
                    "kind": item.kind.value,
                    "title": item.title,
                    "detail": item.detail,
                    "link": item.link,
                    "occurred_at": item.occurred_at.isoformat(),
                    "read": item.read_at is not None,
                }
                for item in items
            ],
        }


@app.get(
    "/api/v1/me/search",
    response_model=schemas.SearchOut,
    responses=CLIENT_ERRORS,
)
def my_search(principal: CurrentPrincipal, q: str = "") -> dict:
    """A busca dentro do projeto do chamador (Fase 6, ADR 0024).

    Sem identificador de projeto no caminho, como o dashboard, a caixa de avisos
    e o download da citação: o projeto sai de ``access.default_project``, que já
    fixa o contexto de tenant. O navegador não manda id de projeto — e o que ele
    não manda é o que ninguém precisa validar (regra 1 do `AGENTS.md`).

    A regra da fatia está em ``search.py`` e não aqui: esta função resolve o
    projeto e serializa. O termo digitado **não** entra no log — é conteúdo do
    cliente (`docs/data-classification.md`), e o evento leva só quantos
    resultados saíram e de que espécies.
    """
    started = perf_counter()
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        project = access.default_project(session, user)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No project for client")
        hits = search.search_project(
            session,
            TenantContext(project.organization_id, project.id),
            q,
        )

    logger.info(
        "search.performed",
        extra={
            "hits": len(hits),
            "kinds": sorted({hit.kind for hit in hits}),
            # O comprimento, nunca o termo: saber que alguém digitou duas letras
            # explica uma lista vazia sem gravar o que a pessoa procurava.
            "term_length": len(q.strip()),
            "duration_ms": round((perf_counter() - started) * 1000, 1),
        },
    )
    return {"results": [hit.to_payload() for hit in hits]}


@app.post(
    "/api/v1/me/notifications/read",
    response_model=schemas.NotificationsReadOut,
    responses=CLIENT_ERRORS,
)
def read_notifications(payload: NotificationsReadIn, principal: CurrentPrincipal) -> dict:
    """Marca avisos como lidos. Sem ``ids``, marca todos os do projeto atual."""
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        project = access.default_project(session, user)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No project for client")
        marked = NotificationRepository(
            session, TenantContext(project.organization_id, project.id)
        ).mark_read(user.id, payload.ids)
        return {"marked": marked}


# --- conversas do chat (Fase 4, ADR 0015) ----------------------------------


def _citation_label(source: str, location: str) -> str:
    """O rótulo exibido, na mesma forma de ``Evidence.citation``."""
    return f"{source} — {location}" if location else source


def _message_payload(message: ConversationMessage) -> dict:
    stored = message.citations or []
    return {
        "id": str(message.id),
        "role": message.role.value,
        "text": message.text,
        "confidence": message.confidence.value if message.confidence else None,
        # O rótulo exibido é remontado das partes gravadas para o histórico
        # mostrar exatamente o que a resposta mostrou na hora.
        "sources": [
            _citation_label(item["source"], item.get("location", "")) for item in stored
        ],
        # A mesma lista, com o ponteiro para o arquivo quando há um (ADR 0017).
        # `sources` continua existindo como projeção de exibição: quem só quer
        # imprimir o rótulo não precisa saber o que é clicável.
        "citations": [
            {
                "label": _citation_label(item["source"], item.get("location", "")),
                "document_id": item.get("document_id"),
            }
            for item in stored
        ],
        "pending_created": message.pending_item_id is not None,
        "feedback": message.feedback.value if message.feedback else None,
    }


class PendingCommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


def _comment_payload(comment) -> dict:
    return {
        "id": str(comment.id),
        "author_label": comment.author_label,
        "author_is_internal": comment.author_is_internal,
        "body": comment.body,
        "created_at": comment.created_at.isoformat(),
    }


@app.get(
    "/api/v1/me/pendings/{pending_item_id}/comments",
    response_model=schemas.PendingCommentsOut,
    responses=CLIENT_ERRORS,
)
def list_pending_comments(
    pending_item_id: UUID, principal: CurrentPrincipal
) -> dict:
    """O fio de uma pendência do projeto atual (ADR 0032).

    Pendência de outro projeto é **404 e não lista vazia**: uma lista vazia diria
    "existe e ninguém comentou", que é informação sobre um recurso que o chamador
    não alcança.
    """
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        project = access.default_project(session, user)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No project for client")
        ctx = TenantContext(project.organization_id, project.id)
        comments = pending_comments.list_for_pending(session, ctx, pending_item_id)
        if comments is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        return {
            "pending_item_id": str(pending_item_id),
            "items": [_comment_payload(comment) for comment in comments],
        }


@app.post(
    "/api/v1/me/pendings/{pending_item_id}/comments",
    response_model=schemas.PendingCommentOut,
    status_code=status.HTTP_201_CREATED,
    responses={**CLIENT_ERRORS, **READ_ONLY_PROJECT_ERROR},
)
def add_pending_comment(
    pending_item_id: UUID, payload: PendingCommentIn, principal: CurrentPrincipal
) -> dict:
    """Escreve um comentário. Cliente e equipe interna, os dois (ADR 0032).

    É a **terceira** escrita que o caminho de requisição origina, depois da
    conversa e do feedback — e a primeira cujo escopo é o projeto e não a pessoa,
    porque ela existe para ser lida pelo outro lado.

    O aviso sai por task, como a pendência que a IA abre: ``portal_app`` não tem
    ``INSERT`` em ``notification``, e essa ausência é o desenho.
    """
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        project = access.default_project(session, user)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No project for client")
        _refuse_when_read_only(project)
        ctx = TenantContext(project.organization_id, project.id)
        comment = pending_comments.add_comment(
            session,
            ctx,
            pending_item_id=pending_item_id,
            author=user,
            body=payload.body,
        )
        if comment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        response = _comment_payload(comment)
        queued = (str(project.id), str(comment.id))

    # Fora da transação, como o upload e o expurgo: o worker lê a linha do banco.
    from portal_api.worker import queue_pending_comment_notification

    queue_pending_comment_notification(*queued)
    return response


@app.get(
    "/api/v1/me/conversations/latest",
    response_model=schemas.ConversationOut,
    # A única rota que serializa por `exclude_unset`, e por um motivo estreito:
    # sem conversa nenhuma o corpo não traz `title`, e declará-lo com padrão
    # `None` acrescentaria uma chave nula que hoje não existe. Esta fatia
    # descreve o payload; não o reescreve.
    response_model_exclude_unset=True,
    responses=CLIENT_ERRORS,
)
def my_latest_conversation(principal: CurrentPrincipal) -> dict:
    """A thread corrente do projeto atual, para o chat voltar como estava.

    Escopada ao projeto pela mesma razão da caixa de avisos (:func:`my_notifications`):
    as policies leem as GUCs de organização/projeto, que só existem depois que
    ``access.default_project`` resolveu *um* projeto.

    Sem conversa nenhuma, devolve ``conversation_id: null`` e lista vazia — não é
    404, porque "ainda não perguntei nada" não é ausência de recurso.
    """
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        project = access.default_project(session, user)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No project for client")
        ctx = TenantContext(project.organization_id, project.id)
        conversation = ConversationRepository(session, ctx).latest_for_user(user.id)
        if conversation is None:
            return {"conversation_id": None, "messages": []}
        messages = ConversationMessageRepository(session, ctx).list_for_conversation(
            conversation.id, user.id, limit=conversations.HISTORY_LIMIT
        )
        return {
            "conversation_id": str(conversation.id),
            "title": conversation.title,
            "messages": [_message_payload(message) for message in messages],
        }


@app.get(
    "/api/v1/me/conversations/{conversation_id}",
    response_model=schemas.ConversationOut,
    response_model_exclude_unset=True,
    responses=CLIENT_ERRORS,
)
def my_conversation(conversation_id: UUID, principal: CurrentPrincipal) -> dict:
    """Uma thread nomeada, para o cliente voltar à pergunta que abriu a pendência.

    Existe por causa da ADR 0031: a pendência aberta pela IA aponta um turno, e
    ele quase nunca está na thread **corrente** — o histórico do chat é de uma
    conversa só (ADR 0015), então sem esta rota o caminho de volta abriria o
    painel e não mostraria nada.

    Conversa de outra pessoa é 404 pelo caminho normal do portal, e a checagem
    não é escrita aqui: ``ConversationRepository.get_for_user`` filtra por
    ``user_id`` e a policy de `conversation` exige
    ``user_id = portal.current_user_id()``. As duas barreiras, como sempre.
    """
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        project = access.default_project(session, user)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No project for client")
        ctx = TenantContext(project.organization_id, project.id)
        conversation = ConversationRepository(session, ctx).get_for_user(
            conversation_id, user.id
        )
        if conversation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        messages = ConversationMessageRepository(session, ctx).list_for_conversation(
            conversation.id, user.id, limit=conversations.HISTORY_LIMIT
        )
        return {
            "conversation_id": str(conversation.id),
            "title": conversation.title,
            "messages": [_message_payload(message) for message in messages],
        }


@app.post(
    "/api/v1/me/conversations/messages/{message_id}/feedback",
    response_model=schemas.FeedbackOut,
    responses=CLIENT_ERRORS,
)
def rate_answer(message_id: UUID, payload: FeedbackIn, principal: CurrentPrincipal) -> dict:
    """Avalia uma resposta do assistente. Mensagem de outra pessoa é 404, como sempre.

    O id da mensagem basta: ele já pertence a uma conversa, que já pertence a uma
    pessoa. Pedir o id da conversa junto seria pedir ao cliente um dado que o
    servidor não usaria para decidir nada.
    """
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        project = access.default_project(session, user)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No project for client")
        message = conversations.record_feedback(
            session,
            TenantContext(project.organization_id, project.id),
            user_id=user.id,
            message_id=message_id,
            helpful=payload.helpful,
            comment=payload.comment,
        )
        if message is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
        return {"id": str(message.id), "feedback": message.feedback.value}


@app.patch(
    "/api/v1/me/preferences",
    response_model=schemas.PreferencesOut,
    responses={
        # Como `/api/v1/me`, escreve na própria linha e não depende de projeto.
        status.HTTP_401_UNAUTHORIZED: CLIENT_ERRORS[status.HTTP_401_UNAUTHORIZED]
    },
)
def update_preferences(payload: PreferencesIn, principal: CurrentPrincipal) -> dict:
    """Preferências da própria conta. Hoje só o e-mail das notificações.

    Escreve na própria linha de ``user`` — a policy ``user_self_link`` da
    migração 0007 já cobre isso, e é o único UPDATE que o caminho de requisição
    fazia antes das notificações existirem.
    """
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        if payload.notify_by_email is not None:
            user.notify_by_email = payload.notify_by_email
        session.flush()
        return {"notify_by_email": user.notify_by_email}
