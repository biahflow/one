import json
from datetime import date
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from portal_api import access
from portal_api.ai import service as chat_service
from portal_api.config import get_settings
from portal_api.db.session import DbRole, get_session
from portal_api.integrations import biahflow
from portal_api.models import Organization
from portal_api.repositories import TenantContext

settings = get_settings()
app = FastAPI(title="Portal Labs API", version="0.1.0", docs_url="/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


class AgentEventIn(BaseModel):
    event_id: UUID
    project_id: UUID
    occurred_at: date
    agent_key: str = Field(min_length=3, max_length=80)
    time_saved_seconds: int = Field(ge=0)
    avoided_cost_cents: int = Field(ge=0)
    run_reference: str = Field(min_length=1, max_length=160)


class ChatIn(BaseModel):
    question: str = Field(min_length=3, max_length=2_000)
    project_id: UUID | None = None


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
def ingest_agent_event(event: AgentEventIn) -> dict[str, str]:
    """Contract boundary. Persistence and token validation land with the auth/RLS migration."""
    if not settings.demo_mode:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Agent key required")
    return {"event_id": str(event.event_id), "status": "accepted"}


@app.post("/api/v1/chat")
def chat(message: ChatIn, request: Request) -> dict:
    """Grounded, tenant-scoped chat: cite the read model or declare the gap + pendência (ADR 0007)."""
    email = _client_identity(request)
    with get_session() as session:
        if message.project_id is not None:
            project = access.scoped_project(session, email, message.project_id)
        else:
            project = access.client_project(session, email)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        ctx = TenantContext(organization_id=project.organization_id, project_id=project.id)
        result = chat_service.answer_question(session, ctx, project, message.question, settings)
        return {
            "answer": result.answer,
            "sources": result.sources,
            "confidence": result.confidence,
            "pending_created": result.pending_created,
        }


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
        return {"status": "synced", "project_id": str(project.id)}


def _client_identity(request: Request) -> str:
    """Client email from the BFF (server-to-server). Becomes the OIDC session in production."""
    email = request.headers.get("X-Portal-User")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Client identity required")
    return email


@app.get("/api/v1/projects/{project_id}/dashboard")
def project_dashboard(project_id: UUID, request: Request) -> dict:
    """Dashboard from the read model, scoped to the client's membership (ADR 0002/0006)."""
    email = _client_identity(request)
    with get_session() as session:
        project = access.scoped_project(session, email, project_id)
        # 404 (not 403) on any miss so we never leak which projects exist.
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        return biahflow.build_dashboard(session, project)


@app.get("/api/v1/me/dashboard")
def my_dashboard(request: Request) -> dict:
    """Dashboard for the authenticated client's own project (the BFF calls this)."""
    email = _client_identity(request)
    with get_session() as session:
        project = access.client_project(session, email)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No project for client")
        organization = session.get(Organization, project.organization_id)
        data = biahflow.build_dashboard(session, project)
        data["organization"] = organization.name if organization else None
        return data
