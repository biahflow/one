import json
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from portal_api import access, admin, agent_auth, results
from portal_api.ai import service as chat_service
from portal_api.auth import CurrentPrincipal
from portal_api.config import get_settings
from portal_api.db.session import DbRole, bind_tenant, get_session
from portal_api.identity import resolve_user
from portal_api.integrations import biahflow
from portal_api.models import AgentEvent, AgentEventOutcome, AuditLog, Organization
from portal_api.repositories import (
    AgentEventRepository,
    NotificationRepository,
    TenantContext,
)

settings = get_settings()
app = FastAPI(title="Portal Labs API", version="0.1.0", docs_url="/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)
# Administração de acesso (ADR 0011): conjunto coeso, e o único que roda sob o
# papel `portal_admin`, por isso em módulo próprio.
app.include_router(admin.router)


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


class NotificationsReadIn(BaseModel):
    #: Sem ids, marca tudo — é o que o sino faz ao abrir.
    ids: list[UUID] | None = None


class PreferencesIn(BaseModel):
    notify_by_email: bool | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "portal-api"}


@app.get("/api/v1/dashboard/demo")
def demo_dashboard() -> dict:
    if not settings.demo_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return {
        "project": "Automação Financeira",
        "status": "Em implementação",
        "completion": 68,
        "next_delivery": {"title": "Treinamento da operação", "date": "2026-09-18"},
        "roi_percent": 142,
        "hours_saved": 328,
    }


@app.post("/api/v1/agent-events", status_code=status.HTTP_202_ACCEPTED)
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
                    data={"agent_key": event.agent_key, "outcome": event.outcome.value},
                )
            )
    return {
        "event_id": str(event.event_id),
        "status": "accepted" if created else "duplicate",
    }


@app.post("/api/v1/chat")
def chat(message: ChatIn, principal: CurrentPrincipal) -> dict:
    """Grounded, tenant-scoped chat: cite the read model or declare the gap + pendência (ADR 0007)."""
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        if message.project_id is not None:
            project = access.scoped_project(session, user, message.project_id)
        else:
            project = access.default_project(session, user)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        ctx = TenantContext(organization_id=project.organization_id, project_id=project.id)
        result = chat_service.answer_question(
            session, ctx, project, message.question, settings, actor_user_id=user.id
        )
        project_id = project.id
        response = {
            "answer": result.answer,
            "sources": result.sources,
            "confidence": result.confidence,
            "pending_created": result.pending_created,
        }

    # Depois do commit, pelo mesmo motivo do webhook: o worker lê a pendência do
    # banco, então ela precisa existir lá antes da task rodar.
    if result.pending_id is not None:
        from portal_api.worker import queue_pending_notification

        queue_pending_notification(str(project_id), str(result.pending_id))
    return response


@app.post("/api/v1/integrations/biahflow/webhook")
async def biahflow_webhook(request: Request) -> dict:
    """Receive a signed Biahflow change notification and refresh the read model (ADR 0006)."""
    body = await request.body()
    signature = request.headers.get("X-Biahflow-Signature")
    if not biahflow.verify_signature(settings.biahflow_webhook_secret, body, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    payload = json.loads(body or b"{}")
    biahflow_project_id = payload.get("project_id")
    if not biahflow_project_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="project_id required")

    snapshot = biahflow.fetch_snapshot(
        settings.biahflow_base_url, settings.biahflow_read_token, int(biahflow_project_id)
    )
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


@app.get("/api/v1/me")
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


@app.get("/api/v1/projects/{project_id}/dashboard")
def project_dashboard(project_id: UUID, principal: CurrentPrincipal) -> dict:
    """Dashboard from the read model, scoped to the caller's membership (ADR 0002/0006)."""
    with get_session(principal) as session:
        user = resolve_user(session, principal)
        project = access.scoped_project(session, user, project_id)
        # 404 (not 403) on any miss so we never leak which projects exist.
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        return biahflow.build_dashboard(session, project)


@app.get("/api/v1/projects/{project_id}/results")
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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="`to` must be after `from`",
            )
        ctx = TenantContext(
            organization_id=project.organization_id, project_id=project.id
        )
        return results.to_payload(results.compute_results(session, ctx, period))


@app.get("/api/v1/me/dashboard")
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


@app.get("/api/v1/me/notifications")
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


@app.post("/api/v1/me/notifications/read")
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


@app.patch("/api/v1/me/preferences")
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
