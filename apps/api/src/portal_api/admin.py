"""Administração de acesso: quem enxerga qual projeto (ADR 0011).

O portal administra **acesso**, não catálogo: organização e projeto vêm do
snapshot do Biahflow (ADR 0006/0008), e criar projeto aqui dividiria a fonte da
verdade. O que estas rotas fazem é conceder e revogar `membership`.

Toda operação roda sob o papel `portal_admin` — o único com escrita naquela
tabela — e em uma ordem que não é acidental:

1. resolve o chamador e verifica `internal_admin` no projeto **antes** de
   publicar a GUC de administração. Nesse instante a transação enxerga apenas os
   próprios vínculos, exatamente como um usuário comum: é o que faz a verificação
   valer alguma coisa em vez de ser circular;
2. só então `bind_admin_org` abre a organização;
3. o Keycloak é consultado/atualizado antes do banco, porque é dele que sai o
   `sub` que a linha `user` precisa.

Negação é sempre 404, nunca 403 — a mesma regra do resto da API.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from portal_api import (
    access,
    agent_auth,
    crypto,
    onboarding,
    retention,
    schemas,
    storage,
)
from portal_api.ai import quota
from portal_api.auth import CurrentPrincipal
from portal_api.config import get_settings
from portal_api.db.session import DbRole, bind_admin_org, bind_invitee, get_session
from portal_api.identity import resolve_user
from portal_api.ingestion import SUPPORTED_MIME_TYPES
from portal_api.integrations import google_drive
from portal_api.keycloak_admin import KeycloakAdmin, KeycloakAdminError, RealmUser
from portal_api.models import (
    SCOPE_EVENTS_WRITE,
    AgentApiKey,
    AuditLog,
    ConversationMessage,
    ConversationRole,
    DataErasureRequest,
    Document,
    DocumentChunk,
    DocumentIngestState,
    DocumentOrigin,
    DocumentSource,
    DriveSyncState,
    ErasureState,
    MemberRole,
    Membership,
    MessageConfidence,
    MessageFeedback,
    OnboardingStepName,
    Organization,
    OrganizationAiQuota,
    OrganizationRetentionPolicy,
    Project,
    ProjectDriveConnection,
    ProjectFinancialAssumption,
    User,
)
from portal_api.principal import Principal
from portal_api.scanner import ScanState
from portal_api.telemetry import audit_data

logger = logging.getLogger(__name__)

# As duas recusas valem para as vinte e três rotas daqui, e por isso ficam no
# router em vez de repetidas em cada uma (ADR 0020). O 404 é mais forte neste
# arquivo do que no resto da API: aqui ele também é a resposta a quem *tem*
# vínculo mas não é `internal_admin` no projeto — a diferença entre "não é seu"
# e "não é seu papel" nunca chega ao cliente.
router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": schemas.ErrorOut,
            "description": "Token ausente ou inválido, com o motivo só no log.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": schemas.ErrorOut,
            "description": (
                "Sem vínculo, sem o papel `internal_admin` no projeto, ou o "
                "recurso não existe. **Nunca 403.**"
            ),
        },
    },
)

NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


class InvitationIn(BaseModel):
    # Formato de e-mail é validado pelo Keycloak, que é quem cria a conta; aqui
    # basta não deixar passar algo obviamente inútil.
    email: str = Field(min_length=5, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    full_name: str = Field(min_length=2, max_length=160)
    role: MemberRole


class MemberOut(BaseModel):
    membership_id: uuid.UUID
    email: str
    full_name: str
    role: MemberRole
    #: E-mail já confirmado no realm. `False` é convite pendente — a única forma
    #: de a tela distinguir "convidei" de "entrou". Na dúvida (provedor de
    #: identidade fora do ar) vale `True`: é rótulo, não permissão.
    active: bool


def _authorized(
    session: Session, principal: Principal, project_id: uuid.UUID
) -> tuple[User, Project]:
    """O chamador e o projeto, se ele for `internal_admin` ali. 404 em qualquer falha.

    Roda **antes** de `bind_admin_org`: neste ponto a transação ainda enxerga
    apenas os vínculos do próprio chamador, que é o que impede a verificação de
    ser circular.
    """
    user = resolve_user(session, principal)
    project = access.require_project(session, user, project_id, access.ADMIN_ONLY)
    if project is None:
        raise NOT_FOUND
    bind_admin_org(session, project.organization_id)
    return user, project


def _record(
    session: Session,
    *,
    project: Project,
    actor_user_id: uuid.UUID,
    action: str,
    membership_id: uuid.UUID,
) -> None:
    """Auditoria sem o e-mail: quem, o quê e sobre qual vínculo, nada além
    (`docs/data-classification.md`)."""
    session.add(
        AuditLog(
            organization_id=project.organization_id,
            project_id=project.id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="membership",
            entity_id=membership_id,
            data=audit_data(project_id=str(project.id)),
        )
    )


def _realm_user(admin: KeycloakAdmin, email: str, full_name: str) -> RealmUser:
    """A conta no realm, criada se ainda não existir.

    Idempotente por e-mail: reconvidar quem já tem conta não cria uma segunda,
    apenas reenvia o e-mail de ações.
    """
    try:
        existing = admin.find_by_email(email)
        return existing or admin.create_user(email, full_name)
    except KeycloakAdminError as exc:
        # 502 e não 500: o portal está de pé, o servidor de identidade é que não
        # respondeu. O motivo já foi para o log estruturado.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Identity provider unavailable"
        ) from exc


@router.get("/projects/{project_id}/members", response_model=list[MemberOut])
def list_members(project_id: uuid.UUID, principal: CurrentPrincipal) -> list[MemberOut]:
    settings = get_settings()

    with get_session(principal, role=DbRole.admin) as session:
        _, project = _authorized(session, principal, project_id)

        try:
            pending = KeycloakAdmin(settings).unverified_emails()
        except KeycloakAdminError:
            # Degrada em vez de derrubar a tela: o rótulo some, a lista fica.
            pending = set()

        rows = session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.organization_id == project.organization_id,
                (Membership.project_id == project.id) | (Membership.project_id.is_(None)),
            )
            .order_by(User.full_name)
        ).all()

        return [
            MemberOut(
                membership_id=membership.id,
                email=user.email,
                full_name=user.full_name,
                role=membership.role,
                active=user.email.lower() not in pending,
            )
            for membership, user in rows
        ]


@router.post(
    "/projects/{project_id}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
)
def invite_member(
    project_id: uuid.UUID, invitation: InvitationIn, principal: CurrentPrincipal
) -> MemberOut:
    """Convida alguém para um projeto.

    A resposta é a mesma para e-mail conhecido e desconhecido — a diferença
    revelaria quem já é cliente do portal.
    """
    settings = get_settings()
    email = invitation.email.lower()

    with get_session(principal, role=DbRole.admin) as session:
        actor, project = _authorized(session, principal, project_id)

        admin = KeycloakAdmin(settings)
        realm_user = _realm_user(admin, email, invitation.full_name)

        # Abre a linha do convidado — e só a dela — para esta transação.
        bind_invitee(session, realm_user.subject)

        user = session.execute(
            select(User).where(User.external_subject == realm_user.subject)
        ).scalar_one_or_none()
        if user is None:
            user = User(
                email=email,
                full_name=invitation.full_name,
                external_subject=realm_user.subject,
                # Da membership, não do realm: é a membership que é autoridade.
                is_internal=invitation.role is not MemberRole.client_member,
            )
            session.add(user)
            session.flush()

        membership = session.execute(
            select(Membership).where(
                Membership.user_id == user.id, Membership.project_id == project.id
            )
        ).scalar_one_or_none()
        if membership is None:
            membership = Membership(
                organization_id=project.organization_id,
                project_id=project.id,
                user_id=user.id,
                role=invitation.role,
            )
            session.add(membership)
            session.flush()
        else:
            membership.role = invitation.role

        # Depois do banco: se a escrita falhar, ninguém recebeu convite para um
        # acesso que não existe. O contrário (e-mail sem vínculo) confundiria.
        try:
            admin.send_invitation(realm_user.subject)
        except KeycloakAdminError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Identity provider unavailable",
            ) from exc

        _record(
            session,
            project=project,
            actor_user_id=actor.id,
            action="membership.invited",
            membership_id=membership.id,
        )
        return MemberOut(
            membership_id=membership.id,
            email=user.email,
            full_name=user.full_name,
            role=membership.role,
            active=realm_user.email_verified,
        )


@router.delete(
    "/projects/{project_id}/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # Explícito porque o `-> None` faz o FastAPI inferir `NoneType` como modelo
    # de resposta, e 204 não pode ter corpo.
    response_model=None,
    response_class=Response,
)
def revoke_membership(
    project_id: uuid.UUID, membership_id: uuid.UUID, principal: CurrentPrincipal
) -> None:
    """Revoga o vínculo. A conta continua existindo — some o acesso, não a pessoa.

    O projeto vem da URL de propósito: é ele que autoriza, e antes da autorização
    o vínculo alheio sequer é visível para ser localizado.
    """
    with get_session(principal, role=DbRole.admin) as session:
        user, project = _authorized(session, principal, project_id)

        membership = session.get(Membership, membership_id)
        if membership is not None and membership.project_id != project.id:
            # Existe, mas noutro projeto: para este chamador, não existe.
            membership = None
        if membership is None:
            raise NOT_FOUND
        if membership.user_id == user.id:
            # Um administrador removendo o próprio acesso perderia a tela e não
            # teria como desfazer.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot revoke your own access",
            )

        _record(
            session,
            project=project,
            actor_user_id=user.id,
            action="membership.revoked",
            membership_id=membership.id,
        )
        session.delete(membership)


# --- resultados: chaves dos agentes e premissas financeiras (ADR 0013) ------
#
# Moram aqui, e não em `main.py`, pelo mesmo motivo dos membros: são escrita sob
# `portal_admin`, e manter num arquivo só o que roda com aquele grant é o que
# torna "quem pode criar credencial" respondível lendo um arquivo.


class AgentKeyIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    #: Sem prazo explícito vale o padrão da configuração — nunca "para sempre".
    expires_in_days: int | None = Field(default=None, ge=1, le=730)


class AgentKeyOut(BaseModel):
    key_id: uuid.UUID
    name: str
    key_prefix: str
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    rotated_from_id: uuid.UUID | None
    #: Se ela ainda autentica. Decidido aqui, e não na tela, pelo mesmo motivo
    #: do `active` de `MemberOut`: quem sabe a hora é quem valida a chave.
    usable: bool


class AgentKeyCreatedOut(AgentKeyOut):
    #: A chave em claro. **Só aqui, só desta vez** — o banco guarda o HMAC, e
    #: não existe caminho para recuperá-la depois. Perdida, rotaciona-se.
    key: str


class AssumptionIn(BaseModel):
    effective_from: date
    hourly_rate_cents: int = Field(ge=0)
    monthly_investment_cents: int = Field(ge=0)
    currency: str = Field(default="BRL", min_length=3, max_length=3)
    note: str | None = Field(default=None, max_length=500)


class AssumptionOut(BaseModel):
    assumption_id: uuid.UUID
    effective_from: date
    effective_to: date | None
    hourly_rate_cents: int
    monthly_investment_cents: int
    currency: str
    note: str | None


def _audit(
    session: Session,
    *,
    project: Project,
    actor_user_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    data: dict | None = None,
) -> None:
    """Auditoria genérica. Nunca recebe a chave nem o hash — só o prefixo, que
    é público por construção (`docs/data-classification.md`)."""
    session.add(
        AuditLog(
            organization_id=project.organization_id,
            project_id=project.id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            data=audit_data(**(data or {})),
        )
    )


def _as_key_out(record: AgentApiKey) -> AgentKeyOut:
    return AgentKeyOut(
        key_id=record.id,
        name=record.name,
        key_prefix=record.key_prefix,
        expires_at=record.expires_at,
        revoked_at=record.revoked_at,
        last_used_at=record.last_used_at,
        rotated_from_id=record.rotated_from_id,
        usable=record.revoked_at is None
        and record.expires_at > datetime.now(timezone.utc),
    )


def _mint(
    session: Session,
    *,
    project: Project,
    actor_user_id: uuid.UUID,
    name: str,
    expires_in_days: int | None,
    rotated_from: AgentApiKey | None = None,
) -> tuple[AgentApiKey, str]:
    settings = get_settings()
    key, prefix = agent_auth.generate_key()
    record = AgentApiKey(
        organization_id=project.organization_id,
        project_id=project.id,
        name=name,
        key_prefix=prefix,
        key_hash=agent_auth.hash_key(key, settings),
        scopes=[SCOPE_EVENTS_WRITE],
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=expires_in_days or settings.agent_key_lifetime_days),
        created_by_user_id=actor_user_id,
        rotated_from_id=rotated_from.id if rotated_from else None,
    )
    session.add(record)
    session.flush()
    return record, key


@router.get("/projects/{project_id}/keys", response_model=list[AgentKeyOut])
def list_agent_keys(project_id: uuid.UUID, principal: CurrentPrincipal) -> list[AgentKeyOut]:
    """As chaves do projeto, sem o segredo — ele não existe mais em lugar nenhum."""
    with get_session(principal, role=DbRole.admin) as session:
        _, project = _authorized(session, principal, project_id)
        records = session.execute(
            select(AgentApiKey)
            .where(AgentApiKey.project_id == project.id)
            .order_by(AgentApiKey.created_at.desc())
        ).scalars()
        return [_as_key_out(record) for record in records]


@router.post(
    "/projects/{project_id}/keys",
    response_model=AgentKeyCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
def create_agent_key(
    project_id: uuid.UUID, payload: AgentKeyIn, principal: CurrentPrincipal
) -> AgentKeyCreatedOut:
    with get_session(principal, role=DbRole.admin) as session:
        actor, project = _authorized(session, principal, project_id)
        record, key = _mint(
            session,
            project=project,
            actor_user_id=actor.id,
            name=payload.name,
            expires_in_days=payload.expires_in_days,
        )
        _audit(
            session,
            project=project,
            actor_user_id=actor.id,
            action="agent_key.created",
            entity_type="agent_api_key",
            entity_id=record.id,
            data={"key_prefix": record.key_prefix},
        )
        return AgentKeyCreatedOut(**_as_key_out(record).model_dump(), key=key)


@router.post(
    "/projects/{project_id}/keys/{key_id}/rotate",
    response_model=AgentKeyCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
def rotate_agent_key(
    project_id: uuid.UUID, key_id: uuid.UUID, principal: CurrentPrincipal
) -> AgentKeyCreatedOut:
    """Emite a sucessora e revoga a anterior, apontando uma para a outra.

    A linha antiga não some: sem ela, "de onde veio esta chave" deixaria de ter
    resposta, e é essa cadeia que torna uma rotação reconstituível meses depois.
    """
    with get_session(principal, role=DbRole.admin) as session:
        actor, project = _authorized(session, principal, project_id)
        current = session.get(AgentApiKey, key_id)
        if current is None or current.project_id != project.id:
            raise NOT_FOUND

        record, key = _mint(
            session,
            project=project,
            actor_user_id=actor.id,
            name=current.name,
            expires_in_days=None,
            rotated_from=current,
        )
        current.revoked_at = datetime.now(timezone.utc)
        _audit(
            session,
            project=project,
            actor_user_id=actor.id,
            action="agent_key.rotated",
            entity_type="agent_api_key",
            entity_id=record.id,
            data={"from_prefix": current.key_prefix, "to_prefix": record.key_prefix},
        )
        return AgentKeyCreatedOut(**_as_key_out(record).model_dump(), key=key)


@router.delete(
    "/projects/{project_id}/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
)
def revoke_agent_key(
    project_id: uuid.UUID, key_id: uuid.UUID, principal: CurrentPrincipal
) -> None:
    """Revoga sem apagar: a linha é o rastro de que a chave existiu e foi usada."""
    with get_session(principal, role=DbRole.admin) as session:
        actor, project = _authorized(session, principal, project_id)
        record = session.get(AgentApiKey, key_id)
        if record is None or record.project_id != project.id:
            raise NOT_FOUND
        if record.revoked_at is None:
            record.revoked_at = datetime.now(timezone.utc)
            _audit(
                session,
                project=project,
                actor_user_id=actor.id,
                action="agent_key.revoked",
                entity_type="agent_api_key",
                entity_id=record.id,
                data={"key_prefix": record.key_prefix},
            )


@router.get("/projects/{project_id}/assumptions", response_model=list[AssumptionOut])
def list_assumptions(
    project_id: uuid.UUID, principal: CurrentPrincipal
) -> list[AssumptionOut]:
    with get_session(principal, role=DbRole.admin) as session:
        _, project = _authorized(session, principal, project_id)
        records = session.execute(
            select(ProjectFinancialAssumption)
            .where(ProjectFinancialAssumption.project_id == project.id)
            .order_by(ProjectFinancialAssumption.effective_from.desc())
        ).scalars()
        return [
            AssumptionOut(
                assumption_id=record.id,
                effective_from=record.effective_from,
                effective_to=record.effective_to,
                hourly_rate_cents=record.hourly_rate_cents,
                monthly_investment_cents=record.monthly_investment_cents,
                currency=record.currency,
                note=record.note,
            )
            for record in records
        ]


@router.post(
    "/projects/{project_id}/assumptions",
    response_model=AssumptionOut,
    status_code=status.HTTP_201_CREATED,
)
def open_assumption(
    project_id: uuid.UUID, payload: AssumptionIn, principal: CurrentPrincipal
) -> AssumptionOut:
    """Abre uma vigência, fechando a corrente na mesma data.

    Premissa não se edita no lugar: um indicador de três meses atrás precisa
    continuar explicável pelo valor que valia naquele dia. Por isso a operação é
    "fecha uma, abre outra" e nunca um UPDATE — e as duas coisas na mesma
    transação, senão haveria um instante com o projeto sem premissa nenhuma.
    """
    with get_session(principal, role=DbRole.admin) as session:
        actor, project = _authorized(session, principal, project_id)

        current = session.execute(
            select(ProjectFinancialAssumption).where(
                ProjectFinancialAssumption.project_id == project.id,
                ProjectFinancialAssumption.effective_to.is_(None),
            )
        ).scalar_one_or_none()
        if current is not None:
            if payload.effective_from <= current.effective_from:
                # Retroagir sobre a vigência aberta reescreveria um passado já
                # exibido ao cliente; o EXCLUDE do banco recusaria de todo jeito.
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="`effective_from` must be after the current assumption",
                )
            current.effective_to = payload.effective_from
            session.flush()

        record = ProjectFinancialAssumption(
            organization_id=project.organization_id,
            project_id=project.id,
            effective_from=payload.effective_from,
            hourly_rate_cents=payload.hourly_rate_cents,
            monthly_investment_cents=payload.monthly_investment_cents,
            currency=payload.currency.upper(),
            note=payload.note,
            created_by_user_id=actor.id,
        )
        session.add(record)
        session.flush()
        _audit(
            session,
            project=project,
            actor_user_id=actor.id,
            action="assumption.changed",
            entity_type="project_financial_assumption",
            entity_id=record.id,
            data={"effective_from": payload.effective_from.isoformat()},
        )
        return AssumptionOut(
            assumption_id=record.id,
            effective_from=record.effective_from,
            effective_to=record.effective_to,
            hourly_rate_cents=record.hourly_rate_cents,
            monthly_investment_cents=record.monthly_investment_cents,
            currency=record.currency,
            note=record.note,
        )


# --- Conhecimento do projeto (Fase 4, ADR 0014) -------------------------------
# Mora aqui pela mesma razão das chaves e das premissas: é escrita, roda sob
# `portal_admin` e é a única porta pela qual um arquivo entra no portal. O
# cliente não envia documento — ele pergunta, e a resposta cita o que foi
# indexado.


class DocumentOut(BaseModel):
    document_id: uuid.UUID
    title: str
    mime_type: str | None
    byte_size: int | None
    #: `pending` | `indexed` | `failed` | `unsupported` | `rejected`. É o que a
    #: tela mostra para explicar por que um documento ainda não responde no chat.
    ingest_state: DocumentIngestState
    ingest_error: str | None
    #: O outro eixo (ADR 0017): `clean` é "alguém capaz olhou", `skipped` é
    #: "ninguém olhou". A tela precisa dos dois separados justamente para não
    #: dizer "verificado" onde não houve verificação.
    scan_state: ScanState
    scan_error: str | None
    scanned_at: datetime | None
    chunk_count: int
    indexed_at: datetime | None
    created_at: datetime


def _as_document_out(record: Document, chunk_count: int) -> DocumentOut:
    return DocumentOut(
        document_id=record.id,
        title=record.title,
        mime_type=record.mime_type,
        byte_size=record.byte_size,
        ingest_state=record.ingest_state,
        ingest_error=record.ingest_error,
        scan_state=record.scan_state,
        scan_error=record.scan_error,
        scanned_at=record.scanned_at,
        chunk_count=chunk_count,
        indexed_at=record.indexed_at,
        created_at=record.created_at,
    )


def _resolved_mime(file: UploadFile) -> str:
    """O tipo do arquivo, conferido no servidor.

    O navegador manda `application/octet-stream` para extensões que ele não
    conhece (`.md` é o caso comum), então o palpite pelo nome existe — mas só
    como segunda tentativa, e o resultado ainda precisa passar pela allowlist.
    """
    declared = (file.content_type or "").split(";")[0].strip().lower()
    if declared and declared != "application/octet-stream":
        return declared
    name = (file.filename or "").lower()
    if name.endswith(".md") or name.endswith(".markdown"):
        return "text/markdown"
    guessed, _ = mimetypes.guess_type(name)
    return (guessed or "").lower()


@router.get("/projects/{project_id}/documents", response_model=list[DocumentOut])
def list_documents(project_id: uuid.UUID, principal: CurrentPrincipal) -> list[DocumentOut]:
    """Os documentos do projeto e o estado do índice de cada um."""
    with get_session(principal, role=DbRole.admin) as session:
        _, project = _authorized(session, principal, project_id)
        records = list(
            session.execute(
                select(Document)
                .where(Document.project_id == project.id)
                .order_by(Document.created_at.desc())
            ).scalars()
        )
        counts = dict(
            session.execute(
                select(DocumentChunk.document_id, func.count(DocumentChunk.id))
                .where(DocumentChunk.project_id == project.id)
                .group_by(DocumentChunk.document_id)
            ).all()
        )
        return [_as_document_out(record, counts.get(record.id, 0)) for record in records]


@router.post(
    "/projects/{project_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    project_id: uuid.UUID,
    principal: CurrentPrincipal,
    file: UploadFile = File(...),
    title: str = Form(default=""),
) -> DocumentOut:
    """Recebe o arquivo, guarda o objeto e enfileira a indexação.

    A ordem importa: a linha nasce primeiro (é dela que sai o id que compõe a
    chave do objeto), o objeto vai em seguida e o commit fecha por último. Assim
    um storage fora do ar derruba a transação inteira e não deixa um `document`
    apontando para um arquivo que não existe. O contrário — objeto órfão depois
    de um commit que falhou — é o erro barato: ocupa espaço e não mente.
    """
    settings = get_settings()
    mime_type = _resolved_mime(file)
    if mime_type not in SUPPORTED_MIME_TYPES:
        # 415 e não 404: aqui não há nada a esconder, o chamador já provou que
        # administra o projeto. O que ele precisa saber é que o formato não entra.
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported media type: {mime_type or 'unknown'}",
        )

    # Um a mais que o teto: é assim que se sabe que passou sem carregar o resto.
    data = file.file.read(settings.document_max_bytes + 1)
    if len(data) > settings.document_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds {settings.document_max_bytes} bytes",
        )
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Empty file"
        )

    with get_session(principal, role=DbRole.admin) as session:
        actor, project = _authorized(session, principal, project_id)
        record = Document(
            organization_id=project.organization_id,
            project_id=project.id,
            title=(title.strip() or file.filename or "Documento")[:200],
            source=DocumentSource.upload,
            origin=DocumentOrigin.portal,
            mime_type=mime_type,
            byte_size=len(data),
            author_label=actor.full_name,
            ingest_state=DocumentIngestState.pending,
        )
        session.add(record)
        session.flush()

        key = storage.object_key(
            project.organization_id, project.id, record.id, file.filename or "", storage.digest(data)
        )
        try:
            storage.put_object(settings, key, data, mime_type)
        except storage.StorageDisabled as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Document storage is not configured",
            ) from exc
        except storage.StorageError as exc:
            logger.exception("document.storage_write_failed", extra={"project_id": str(project_id)})
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="Storage unavailable"
            ) from exc

        record.storage_key = key
        _audit(
            session,
            project=project,
            actor_user_id=actor.id,
            action="document.uploaded",
            entity_type="document",
            entity_id=record.id,
            data={"mime_type": mime_type, "byte_size": len(data)},
        )
        response = _as_document_out(record, 0)

    # Fora da transação, como o webhook: o worker vai ler a linha do banco, então
    # ela precisa estar comitada antes de a task rodar. A porta é a varredura, e
    # não a ingestão — é ela que decide se o arquivo chega a virar texto
    # (ADR 0017).
    from portal_api.worker import queue_document_scan

    queue_document_scan(str(response.document_id))
    return response


@router.delete(
    "/projects/{project_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
)
def delete_document(
    project_id: uuid.UUID, document_id: uuid.UUID, principal: CurrentPrincipal
) -> None:
    """Remove documento, índice e arquivo.

    Aqui se apaga de verdade — ao contrário da chave de agente, que é revogada
    para preservar o rastro. Um documento enviado por engano é conteúdo do
    cliente no lugar errado, e mantê-lo "revogado" seria manter o problema. Os
    trechos vão junto por CASCADE; a retenção por organização é da Fase 5.
    """
    settings = get_settings()
    with get_session(principal, role=DbRole.admin) as session:
        actor, project = _authorized(session, principal, project_id)
        record = session.get(Document, document_id)
        if record is None or record.project_id != project.id:
            raise NOT_FOUND
        if record.origin != DocumentOrigin.portal:
            # Documento espelhado do Biahflow volta no próximo sync; apagá-lo
            # aqui prometeria uma remoção que o portal não tem como cumprir. Vale
            # igual para o que veio do Drive (ADR 0016): a forma de removê-lo é
            # tirá-lo da pasta, e aí o sync o remove daqui.
            raise NOT_FOUND

        storage_key = record.storage_key
        _audit(
            session,
            project=project,
            actor_user_id=actor.id,
            action="document.deleted",
            entity_type="document",
            entity_id=record.id,
            data={"mime_type": record.mime_type},
        )
        session.delete(record)

    if storage_key:
        try:
            storage.delete_object(settings, storage_key)
        except (storage.StorageDisabled, storage.StorageError):
            # A linha já se foi e é ela que a tela mostra. Objeto órfão vira
            # limpeza de retenção, não um erro na cara de quem apagou.
            logger.warning("document.object_not_removed", extra={"storage_key": storage_key})


# --- Conector do Google Drive (Fase 4, ADR 0016) -------------------------------
# Mesma vizinhança e mesma razão do bloco acima: é escrita, roda sob
# `portal_admin` e continua sendo a administração que decide o que o assistente
# enxerga. O que muda é a credencial — pela primeira vez o portal guarda um
# segredo de terceiro que precisa voltar em claro (`crypto.py`).
#
# O segredo **nunca** sai daqui. `DriveConnectionOut` não carrega o refresh token
# nem nada derivado dele, e é diferente da chave de agente de propósito: aquela
# atravessa uma vez porque quem a usa é o cliente; esta só é usada pelo servidor.


class DriveConnectionOut(BaseModel):
    #: Vai na resposta porque o callback do OAuth não sabe para onde voltar: ele
    #: chega só com `code` e `state`, e o projeto sai da linha achada pelo state.
    project_id: uuid.UUID | None
    connected: bool
    folder_id: str | None
    folder_name: str | None
    google_account_email: str | None
    enabled: bool
    sync_state: DriveSyncState | None
    last_sync_at: datetime | None
    last_sync_error: str | None
    last_sync_stats: dict[str, object] | None
    document_count: int


class DriveFolderIn(BaseModel):
    folder_id: str = Field(min_length=1, max_length=255)


class DriveFolderOut(BaseModel):
    id: str
    name: str


class DriveAuthorizeOut(BaseModel):
    authorize_url: str


class DriveCallbackIn(BaseModel):
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=512)


def _disconnected() -> DriveConnectionOut:
    return DriveConnectionOut(
        project_id=None,
        connected=False,
        folder_id=None,
        folder_name=None,
        google_account_email=None,
        enabled=False,
        sync_state=None,
        last_sync_at=None,
        last_sync_error=None,
        last_sync_stats=None,
        document_count=0,
    )


def _as_drive_out(record: ProjectDriveConnection, documents: int) -> DriveConnectionOut:
    return DriveConnectionOut(
        project_id=record.project_id,
        connected=record.refresh_token_sealed is not None,
        folder_id=record.folder_id,
        folder_name=record.folder_name,
        google_account_email=record.google_account_email,
        enabled=record.enabled,
        sync_state=record.sync_state,
        last_sync_at=record.last_sync_at,
        last_sync_error=record.last_sync_error,
        last_sync_stats=record.last_sync_stats,
        document_count=documents,
    )


def _drive_connection(session: Session, project: Project) -> ProjectDriveConnection | None:
    return session.execute(
        select(ProjectDriveConnection).where(
            ProjectDriveConnection.project_id == project.id
        )
    ).scalar_one_or_none()


def _drive_document_count(session: Session, project: Project) -> int:
    return int(
        session.execute(
            select(func.count(Document.id)).where(
                Document.project_id == project.id,
                Document.origin == DocumentOrigin.drive,
            )
        ).scalar_one()
    )


def _drive_unavailable(exc: Exception) -> HTTPException:
    """503 para "não configurado", 502 para "o Google não respondeu".

    Mesma distinção do storage, e ela importa para a tela: uma é problema de
    ambiente e a outra passa sozinha.
    """
    if isinstance(exc, google_drive.DriveDisabled):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Drive connector is not configured",
        )
    if isinstance(exc, google_drive.DriveAuthError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Google Drive authorization is no longer valid",
        )
    logger.exception("drive.unavailable")
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY, detail="Google Drive unavailable"
    )


def _drive_access_token(record: ProjectDriveConnection, settings) -> str:
    if not record.refresh_token_sealed:
        raise google_drive.DriveAuthError("connection has no refresh token")
    aad = crypto.aad_for(record.organization_id, record.project_id)
    refresh_token = crypto.unseal(record.refresh_token_sealed, aad=aad, settings=settings)
    return google_drive.refresh_access_token(
        settings, refresh_token, client=google_drive.session_client()
    )


@router.get("/projects/{project_id}/drive", response_model=DriveConnectionOut)
def get_drive_connection(
    project_id: uuid.UUID, principal: CurrentPrincipal
) -> DriveConnectionOut:
    """O estado da conexão. Responde 200 com `connected: false` quando não há.

    Projeto sem Drive não é 404: a tela precisa desenhar o botão de conectar, e
    404 aqui a faria confundir "você não administra este projeto" com "ninguém
    conectou ainda".
    """
    with get_session(principal, role=DbRole.admin) as session:
        _, project = _authorized(session, principal, project_id)
        record = _drive_connection(session, project)
        if record is None:
            return _disconnected()
        return _as_drive_out(record, _drive_document_count(session, project))


@router.post(
    "/projects/{project_id}/drive/authorize-url",
    response_model=DriveAuthorizeOut,
    status_code=status.HTTP_201_CREATED,
)
def start_drive_authorization(
    project_id: uuid.UUID, principal: CurrentPrincipal
) -> DriveAuthorizeOut:
    """Monta a URL de consentimento e guarda o lastro do `state`.

    O `state` vai em claro para o navegador e **em hash** para o banco, pela mesma
    razão da chave de agente: o valor em claro não precisa existir aqui para ser
    conferido depois. Junto dele ficam o prazo e quem pediu — o callback recusa se
    voltar tarde ou em outra sessão.
    """
    settings = get_settings()
    try:
        google_drive.ensure_configured(settings)
        # Falha cedo se a cifra não estiver configurada: conectar sem poder selar
        # o refresh token deixaria uma conexão que nunca sincroniza.
        crypto.ensure_configured(settings)
    except (google_drive.DriveDisabled, crypto.SealedSecretError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Drive connector is not configured",
        ) from exc

    state = secrets.token_urlsafe(32)
    verifier = google_drive.generate_code_verifier()

    with get_session(principal, role=DbRole.admin) as session:
        actor, project = _authorized(session, principal, project_id)
        record = _drive_connection(session, project)
        if record is None:
            record = ProjectDriveConnection(
                organization_id=project.organization_id, project_id=project.id
            )
            session.add(record)
        record.oauth_state_hash = _hash_state(state)
        record.oauth_state_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=settings.drive_oauth_state_ttl_seconds
        )
        record.oauth_code_verifier = verifier
        record.oauth_requested_by_user_id = actor.id
        session.flush()
        _audit(
            session,
            project=project,
            actor_user_id=actor.id,
            action="drive.authorize_started",
            entity_type="project_drive_connection",
            entity_id=record.id,
            data={},
        )

    return DriveAuthorizeOut(
        authorize_url=google_drive.authorize_url(
            settings, state=state, code_verifier=verifier
        )
    )


@router.post("/drive/callback", response_model=DriveConnectionOut)
def finish_drive_authorization(
    payload: DriveCallbackIn, principal: CurrentPrincipal
) -> DriveConnectionOut:
    """Fecha o consentimento: troca o código, sela o refresh token e grava.

    **Sem `project_id` no caminho**, e isso não é economia de rota: o projeto sai
    da linha encontrada pelo `state`, do mesmo jeito que o tenant da ADR 0013 sai
    da chave em vez do corpo. Um `project_id` aqui seria um identificador de fora
    para desconfiar, e não há motivo para aceitá-lo.

    O `state` é consumido **antes** da troca — quem chega em segundo não acha mais
    nada. Se a troca falhar depois disso, a pessoa reconecta; o contrário deixaria
    um `state` válido para reapresentar.
    """
    settings = get_settings()
    claimed = _claim_oauth_state(payload.state)
    if claimed is None:
        raise NOT_FOUND
    project_id, verifier, requested_by = claimed

    try:
        tokens = google_drive.exchange_code(
            settings, payload.code, verifier, client=google_drive.session_client()
        )
    except (google_drive.DriveDisabled, google_drive.DriveError, google_drive.DriveAuthError) as exc:
        raise _drive_unavailable(exc) from exc

    if not google_drive.scope_is_exactly_readonly(tokens.scope, settings):
        # Consentiu diferente do que foi pedido. Recusa sem gravar: aceitar "mais
        # do que pedi" faria do escopo somente-leitura uma intenção, não um controle.
        logger.warning("drive.scope_refused", extra={"project_id": str(project_id)})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only the read-only Drive scope is accepted",
        )
    if not tokens.refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google returned no refresh token; try connecting again",
        )

    email = None
    try:
        email = google_drive.account_email(
            settings, tokens.access_token, client=google_drive.session_client()
        )
    except (google_drive.DriveError, google_drive.DriveAuthError):
        # Rótulo, não permissão: a conexão vale mesmo sem ele.
        logger.info("drive.account_email_unavailable")

    with get_session(principal, role=DbRole.admin) as session:
        actor, project = _authorized(session, principal, project_id)
        if actor.id != requested_by:
            # O `state` prova que é o mesmo fluxo; isto prova que é a mesma pessoa.
            raise NOT_FOUND
        record = _drive_connection(session, project)
        if record is None:
            raise NOT_FOUND

        aad = crypto.aad_for(record.organization_id, record.project_id)
        record.refresh_token_sealed = crypto.seal(
            tokens.refresh_token, aad=aad, settings=settings
        )
        record.granted_scope = tokens.scope
        record.google_account_email = email
        record.connected_by_user_id = actor.id
        record.connected_at = datetime.now(timezone.utc)
        record.disconnected_at = None
        record.enabled = True
        record.sync_state = DriveSyncState.idle
        record.last_sync_error = None
        _audit(
            session,
            project=project,
            actor_user_id=actor.id,
            action="drive.connected",
            entity_type="project_drive_connection",
            entity_id=record.id,
            data={"account": email or ""},
        )
        return _as_drive_out(record, _drive_document_count(session, project))


@router.get("/projects/{project_id}/drive/folders", response_model=list[DriveFolderOut])
def list_drive_folders(
    project_id: uuid.UUID, principal: CurrentPrincipal
) -> list[DriveFolderOut]:
    """As pastas da conta conectada, para a pessoa escolher qual autorizar.

    No lugar do Google Picker: ele é script de terceiro na página, e o portal não
    carrega script externo.
    """
    settings = get_settings()
    with get_session(principal, role=DbRole.admin) as session:
        _, project = _authorized(session, principal, project_id)
        record = _drive_connection(session, project)
        if record is None or record.refresh_token_sealed is None:
            raise NOT_FOUND
        try:
            token = _drive_access_token(record, settings)
            folders = google_drive.list_folders(
                settings, token, client=google_drive.session_client()
            )
        except crypto.SealedSecretError as exc:
            raise _drive_unavailable(google_drive.DriveDisabled(str(exc))) from exc
        except (google_drive.DriveDisabled, google_drive.DriveError, google_drive.DriveAuthError) as exc:
            raise _drive_unavailable(exc) from exc
    return [DriveFolderOut(id=folder.id, name=folder.name) for folder in folders]


@router.put("/projects/{project_id}/drive/folder", response_model=DriveConnectionOut)
def set_drive_folder(
    project_id: uuid.UUID, payload: DriveFolderIn, principal: CurrentPrincipal
) -> DriveConnectionOut:
    """Fixa a pasta autorizada, conferindo antes que o id é mesmo de uma pasta.

    Trocar de pasta é ação explícita e auditada: ela é a fronteira de tudo o que o
    conector faz, e mudá-la em silêncio mudaria o que o assistente enxerga sem
    deixar rastro.
    """
    settings = get_settings()
    with get_session(principal, role=DbRole.admin) as session:
        actor, project = _authorized(session, principal, project_id)
        record = _drive_connection(session, project)
        if record is None or record.refresh_token_sealed is None:
            raise NOT_FOUND
        try:
            token = _drive_access_token(record, settings)
            folder = google_drive.get_folder(
                settings, token, payload.folder_id, client=google_drive.session_client()
            )
        except crypto.SealedSecretError as exc:
            raise _drive_unavailable(google_drive.DriveDisabled(str(exc))) from exc
        except (google_drive.DriveDisabled, google_drive.DriveError, google_drive.DriveAuthError) as exc:
            raise _drive_unavailable(exc) from exc

        record.folder_id = folder.id
        record.folder_name = folder.name
        record.enabled = True
        _audit(
            session,
            project=project,
            actor_user_id=actor.id,
            action="drive.folder_changed",
            entity_type="project_drive_connection",
            entity_id=record.id,
            data={"folder_id": folder.id},
        )
        return _as_drive_out(record, _drive_document_count(session, project))


class DriveSyncQueuedOut(BaseModel):
    status: str


@router.post(
    "/projects/{project_id}/drive/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DriveSyncQueuedOut,
    responses={
        status.HTTP_409_CONFLICT: {
            "model": schemas.ErrorOut,
            "description": "Já existe uma sincronização em andamento nesta pasta.",
        }
    },
)
def sync_drive_now(project_id: uuid.UUID, principal: CurrentPrincipal) -> dict[str, str]:
    """Enfileira uma sincronização. 202 porque quem responde é o worker."""
    with get_session(principal, role=DbRole.admin) as session:
        actor, project = _authorized(session, principal, project_id)
        record = _drive_connection(session, project)
        if record is None or record.refresh_token_sealed is None or not record.folder_id:
            raise NOT_FOUND
        if record.sync_state == DriveSyncState.running:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="A sync is already running"
            )
        record.enabled = True
        record.last_sync_error = None
        connection_id = record.id
        _audit(
            session,
            project=project,
            actor_user_id=actor.id,
            action="drive.sync_requested",
            entity_type="project_drive_connection",
            entity_id=record.id,
            data={},
        )

    # Fora da transação, como o upload: o worker lê a linha do banco.
    from portal_api.worker import queue_drive_sync

    queue_drive_sync(str(connection_id))
    return {"status": "queued"}


@router.delete(
    "/projects/{project_id}/drive",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
)
def disconnect_drive(project_id: uuid.UUID, principal: CurrentPrincipal) -> None:
    """Revoga a conexão — e revoga, não apaga.

    O segredo some da linha; a linha fica. É a mesma escolha da chave de agente:
    ela é o rastro de que este projeto leu aquele Drive, e de quando deixou de ler.
    Os documentos já indexados permanecem, porque desconectar é parar de trazer
    novidade, não apagar o que o cliente já tinha.
    """
    with get_session(principal, role=DbRole.admin) as session:
        actor, project = _authorized(session, principal, project_id)
        record = _drive_connection(session, project)
        if record is None:
            raise NOT_FOUND
        record.refresh_token_sealed = None
        record.oauth_state_hash = None
        record.oauth_state_expires_at = None
        record.oauth_code_verifier = None
        record.enabled = False
        record.disconnected_at = datetime.now(timezone.utc)
        record.sync_state = DriveSyncState.idle
        _audit(
            session,
            project=project,
            actor_user_id=actor.id,
            action="drive.disconnected",
            entity_type="project_drive_connection",
            entity_id=record.id,
            data={},
        )


def _hash_state(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _claim_oauth_state(state: str) -> tuple[uuid.UUID, str, uuid.UUID | None] | None:
    """Acha a conexão pelo `state`, confere o prazo e **consome** o lastro.

    Roda sob ``portal_system`` porque neste ponto ainda não há organização para
    ligar — ela sai da linha encontrada, exatamente como o tenant sai da chave em
    ``agent_auth.authenticate``. A autorização de verdade vem depois, no
    ``_authorized`` de sempre: o `state` não abre porta nenhuma sozinho.
    """
    now = datetime.now(timezone.utc)
    with get_session(role=DbRole.system) as session:
        record = session.execute(
            select(ProjectDriveConnection).where(
                ProjectDriveConnection.oauth_state_hash == _hash_state(state)
            )
        ).scalar_one_or_none()
        if record is None or record.oauth_state_expires_at is None:
            return None
        expires_at = record.oauth_state_expires_at
        verifier = record.oauth_code_verifier or ""
        project_id = record.project_id
        requested_by = record.oauth_requested_by_user_id

        record.oauth_state_hash = None
        record.oauth_state_expires_at = None
        record.oauth_code_verifier = None

        if expires_at <= now:
            return None
    return project_id, verifier, requested_by


# --- Retenção e expurgo (Fase 5, ADR 0017) ------------------------------------
# Mora aqui pela mesma razão das chaves, das premissas e do conector: é escrita e
# roda sob `portal_admin`. O que muda é o escopo — estas são as primeiras rotas
# do portal cuja unidade é a **organização** e não o projeto, porque "por quanto
# tempo os dados ficam" e "apague tudo" não são perguntas que se façam projeto a
# projeto.
#
# Nenhuma delas apaga nada. A rota grava a intenção; quem cumpre é o worker sob
# `portal_system` — a ADR 0015 já tinha decidido isso quando adiou o expurgo.


class RetentionPolicyIn(BaseModel):
    """Nulo é "usa o padrão", não "guarda para sempre" (ver `retention.py`)."""

    notification_days: int | None = Field(default=None, ge=1, le=3650)
    agent_event_days: int | None = Field(default=None, ge=1, le=3650)
    conversation_days: int | None = Field(default=None, ge=1, le=3650)
    #: O funil de onboarding (ADR 0039): comportamento de pessoa identificada.
    onboarding_days: int | None = Field(default=None, ge=1, le=3650)


class RetentionPolicyOut(BaseModel):
    organization_id: uuid.UUID
    #: Os prazos como foram definidos — nulo onde a organização não disse nada.
    notification_days: int | None
    agent_event_days: int | None
    conversation_days: int | None
    onboarding_days: int | None
    #: E os mesmos prazos já resolvidos contra o padrão. Os dois, de propósito: a
    #: tela precisa mostrar o que vale **e** poder distinguir "escolhido" de
    #: "herdado", senão editar o formulário fixaria o padrão sem querer.
    effective: dict[str, int]


class ErasureRequestIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    #: A confirmação por extenso. Não é teatro: é a única ação do portal cujo
    #: efeito nenhuma tela desfaz, e um `DELETE` disparado por engano num cliente
    #: certo é pior do que um clique a mais em todos os outros.
    confirm_slug: str = Field(min_length=1, max_length=80)


class ErasureRequestOut(BaseModel):
    request_id: uuid.UUID
    organization_id: uuid.UUID
    state: ErasureState
    requested_reason: str | None
    created_at: datetime
    completed_at: datetime | None
    removed: dict | None
    error: str | None


class AdministeredOrganizationOut(BaseModel):
    """A organização e o que a tela precisa para falar dela.

    O ``slug`` está aqui porque é a confirmação que `request_erasure` exige
    digitada: a tela precisa poder mostrar **qual** tenant está prestes a ser
    apagado ao lado do campo. Mostrá-lo não enfraquece a confirmação — o que
    ela protege é o erro de olhar para o tenant errado, não o segredo do nome.
    """

    organization_id: uuid.UUID
    name: str
    slug: str


@router.get("/organizations", response_model=list[AdministeredOrganizationOut])
def list_administered_organizations(
    principal: CurrentPrincipal,
) -> list[AdministeredOrganizationOut]:
    """As organizações que o chamador administra. Lista vazia, nunca 404.

    A rota que faltava para as outras seis existirem de fato (ADR 0027). Elas
    são chaveadas por ``{organization_id}`` e, até aqui, **nenhuma resposta da
    API devolvia esse uuid** — `MeOut.organization` é o *nome*. Havia rota,
    modelo, policy e teste, e nenhum caller possível que não consultasse o
    Postgres à mão.

    Lista vazia e não 404, ao contrário de todo o resto de ``admin.py``: aqui
    não há recurso nomeado cuja existência se possa vazar. "Não administro
    nenhuma" é uma resposta verdadeira sobre o chamador, do mesmo feitio que
    ``projects`` vazio em `GET /api/v1/me` — autenticar não é autorizar.

    Não chama ``bind_admin_org``, e isso é o desenho: a pergunta é *quais*
    organizações, e a GUC de terceiro estágio guarda uma. Antes dela a
    transação enxerga apenas os vínculos do próprio chamador, que é exatamente
    o recorte que esta listagem quer — a mesma propriedade que impede
    `_authorized_org` de ser circular.
    """
    with get_session(principal, role=DbRole.admin) as session:
        user = resolve_user(session, principal)
        return [
            AdministeredOrganizationOut(
                organization_id=organization.id,
                name=organization.name,
                slug=organization.slug,
            )
            for organization in access.administered_organizations(session, user)
        ]


def _authorized_org(
    session: Session, principal: Principal, organization_id: uuid.UUID
) -> tuple[User, Organization]:
    """O chamador e a organização, se ele for `internal_admin` nela. 404 sempre.

    Espelho de `_authorized`, e com a mesma ordem: a checagem acontece **antes**
    de `bind_admin_org`, quando a transação ainda enxerga apenas os vínculos do
    próprio chamador — é isso que impede a verificação de ser circular.
    """
    user = resolve_user(session, principal)
    organization = access.require_organization(session, user, organization_id)
    if organization is None:
        raise NOT_FOUND
    bind_admin_org(session, organization.id)
    return user, organization


def _policy_out(
    organization_id: uuid.UUID, record: OrganizationRetentionPolicy | None
) -> RetentionPolicyOut:
    limits = retention.windows_for(record, get_settings())
    return RetentionPolicyOut(
        organization_id=organization_id,
        notification_days=record.notification_days if record else None,
        agent_event_days=record.agent_event_days if record else None,
        conversation_days=record.conversation_days if record else None,
        onboarding_days=record.onboarding_days if record else None,
        effective={
            "notification_days": limits.notification_days,
            "agent_event_days": limits.agent_event_days,
            "conversation_days": limits.conversation_days,
            "onboarding_days": limits.onboarding_days,
        },
    )


@router.get(
    "/organizations/{organization_id}/retention", response_model=RetentionPolicyOut
)
def get_retention_policy(
    organization_id: uuid.UUID, principal: CurrentPrincipal
) -> RetentionPolicyOut:
    with get_session(principal, role=DbRole.admin) as session:
        _, organization = _authorized_org(session, principal, organization_id)
        record = session.execute(
            select(OrganizationRetentionPolicy).where(
                OrganizationRetentionPolicy.organization_id == organization.id
            )
        ).scalar_one_or_none()
        return _policy_out(organization.id, record)


@router.put(
    "/organizations/{organization_id}/retention", response_model=RetentionPolicyOut
)
def set_retention_policy(
    organization_id: uuid.UUID, payload: RetentionPolicyIn, principal: CurrentPrincipal
) -> RetentionPolicyOut:
    """Define os prazos da organização.

    ``PUT`` e não ``PATCH``: a política é uma linha só e o corpo a descreve
    inteira. Omitir um campo é dizer "volte ao padrão", que é uma decisão — e
    seria indistinguível de "não mexa" se o verbo fosse outro.

    Ao contrário da premissa financeira (ADR 0013), aqui a linha é **editada** e
    não versionada por vigência: um prazo não reprecifica o passado, ele só
    decide o que ainda existe amanhã. O rastro de quem mudou fica no `audit_log`.
    """
    with get_session(principal, role=DbRole.admin) as session:
        actor, organization = _authorized_org(session, principal, organization_id)
        record = session.execute(
            select(OrganizationRetentionPolicy).where(
                OrganizationRetentionPolicy.organization_id == organization.id
            )
        ).scalar_one_or_none()
        if record is None:
            record = OrganizationRetentionPolicy(organization_id=organization.id)
            session.add(record)

        record.notification_days = payload.notification_days
        record.agent_event_days = payload.agent_event_days
        record.conversation_days = payload.conversation_days
        record.onboarding_days = payload.onboarding_days
        record.updated_by_user_id = actor.id
        session.flush()

        session.add(
            AuditLog(
                organization_id=organization.id,
                actor_user_id=actor.id,
                action="retention.policy_updated",
                entity_type="organization_retention_policy",
                entity_id=record.id,
                data=audit_data(
                    notification_days=payload.notification_days,
                    agent_event_days=payload.agent_event_days,
                    conversation_days=payload.conversation_days,
                    onboarding_days=payload.onboarding_days,
                ),
            )
        )
        return _policy_out(organization.id, record)


class AiQuotaIn(BaseModel):
    """Nulo é "usa o padrão de ``config.py``", não "sem teto".

    Mesma regra da retenção, e pelo mesmo motivo: um contrato que não fala de
    limite não é um contrato de limite infinito. Zero desliga a cobrança, e é uma
    decisão explícita — que é justamente o que a distingue de um esquecimento.
    """

    monthly_limit_cents: int | None = Field(default=None, ge=0, le=100_000_000)


class AiQuotaOut(BaseModel):
    organization_id: uuid.UUID
    #: Como foi definido — nulo onde a organização não disse nada.
    monthly_limit_cents: int | None
    #: E o que de fato vale, resolvido contra o padrão. Os dois, pela razão da
    #: retenção: a tela precisa distinguir "escolhido" de "herdado", senão salvar
    #: o formulário fixaria o padrão sem querer.
    effective_limit_cents: int
    #: O mês corrente, calculado agora pelo preço vigente no dia de cada chamada.
    spent_cents: int
    input_tokens: int
    output_tokens: int
    calls: int
    #: O que impediu de saber o gasto por inteiro — chamadas cujo modelo não tinha
    #: preço vigente. Na forma do `gaps` de `results.py`: base ausente devolve o
    #: que dá para calcular **mais** a razão do que falta, nunca um zero silencioso.
    gaps: list[str]


def _quota_out(
    session: Session,
    organization_id: uuid.UUID,
    *,
    record: OrganizationAiQuota | None = None,
) -> AiQuotaOut:
    if record is None:
        record = session.execute(
            select(OrganizationAiQuota).where(
                OrganizationAiQuota.organization_id == organization_id
            )
        ).scalar_one_or_none()
    settings = get_settings()
    current = quota.spend(session, organization_id)
    return AiQuotaOut(
        organization_id=organization_id,
        monthly_limit_cents=record.monthly_limit_cents if record else None,
        effective_limit_cents=quota.limit_cents(session, organization_id, settings),
        spent_cents=current.cost_cents,
        input_tokens=current.input_tokens,
        output_tokens=current.output_tokens,
        calls=current.calls,
        gaps=list(current.gaps),
    )


class OnboardingFunnelOut(BaseModel):
    """Onde o cliente parou no funil, e de quem é a vez (Fase 7, RFC 001, ADR 0040).

    Os campos são exatamente os que a tela lê, e a lista é curta por isso: um campo que
    ninguém desreferencia é uma pergunta para a API, e a guarda da ADR 0033 a faz. Ficaram
    de fora, de propósito, o ``organization_id`` e o nome — seriam **eco** de quem já pôs o
    id na URL — e a escada com as seis datas, que nenhuma coluna da FDD 020 pede.
    """

    #: O primeiro degrau sem carimbo, ou nulo quando os sete foram alcançados.
    current_step: OnboardingStepName | None
    #: ``client`` ou ``us``. Enum e não texto livre porque a FDD 020 exige que os dois
    #: **nunca** sejam somados na mesma contagem, e um tipo diz isso melhor que uma
    #: convenção.
    blocked_by: onboarding.Blame | None
    #: Nulo é **lacuna**, jamais zero: um cliente sem carimbo pode não ter chegado lá ou
    #: ser anterior à instrumentação, e as duas coisas não podem sair iguais (FDD 020).
    days_stuck: int | None
    #: Para a tela escrever "9 de 7 dias" sem reimplementar o `config.py`.
    threshold_days: int
    #: Decidido pela API. A tela **não** o rederiva de `days_stuck > threshold_days`, que
    #: poria a mesma regra em dois lugares — o argumento que o docstring de
    #: `_erasure_is_claimable` já escreveu.
    stuck: bool
    next_action: str
    #: A lacuna declarada, na forma do `gaps` de `results.py` e do `AiQuotaOut` acima.
    gaps: list[str]
    #: Desde quando os dias são contados, e de onde a data saiu. Um contador que ninguém
    #: consegue refazer não é auditável.
    anchor_at: datetime
    anchor_source: str


@router.get(
    "/organizations/{organization_id}/onboarding", response_model=OnboardingFunnelOut
)
def get_onboarding_funnel(
    organization_id: uuid.UUID, principal: CurrentPrincipal
) -> OnboardingFunnelOut:
    """O estado do funil desta organização, para a lista interna de clientes travados.

    **Autoriza sob ``portal_admin`` e computa sob ``portal_system``**, em duas transações,
    e isso não é atalho. ``pending_item`` **não tem policy `TO portal_admin`** — o papel
    herda o ``SELECT`` das default privileges e lê zero linhas em silêncio, que é o mesmo
    desenho que a ADR 0039 escolheu de propósito para ``portal_app`` nesta mesma tabela.
    Sob o papel administrativo, o ``EXISTS`` de "há pendência aberta?" responderia "não"
    para **toda** organização, e todo cliente do produto apareceria rotulado "travou em
    nós" com a forma de um alerta de verdade.

    A autorização não afrouxa por isso: o ``organization_id`` que a segunda transação usa é
    o que ``_authorized_org`` acabou de provar, e não o que veio na URL. O precedente de
    abrir sessão de sistema aqui dentro é ``_claim_oauth_state``.
    """
    with get_session(principal, role=DbRole.admin) as session:
        _, organization = _authorized_org(session, principal, organization_id)
        scoped = organization.id

    with get_session(role=DbRole.system) as session:
        reading = onboarding.read_funnel(session, scoped, get_settings())

    if reading is None:  # pragma: no cover - `_authorized_org` já provou que existe
        raise NOT_FOUND
    return OnboardingFunnelOut(
        current_step=reading.current_step,
        blocked_by=reading.blame,
        days_stuck=reading.days_stuck,
        threshold_days=reading.threshold_days,
        stuck=reading.stuck,
        next_action=reading.next_action,
        gaps=reading.gaps,
        anchor_at=reading.anchor_at,
        anchor_source=reading.anchor_source,
    )


@router.get("/organizations/{organization_id}/ai-quota", response_model=AiQuotaOut)
def get_ai_quota(organization_id: uuid.UUID, principal: CurrentPrincipal) -> AiQuotaOut:
    with get_session(principal, role=DbRole.admin) as session:
        _, organization = _authorized_org(session, principal, organization_id)
        return _quota_out(session, organization.id)


@router.put("/organizations/{organization_id}/ai-quota", response_model=AiQuotaOut)
def set_ai_quota(
    organization_id: uuid.UUID, payload: AiQuotaIn, principal: CurrentPrincipal
) -> AiQuotaOut:
    """Define o teto mensal de gasto de IA da organização.

    ``PUT`` pela razão da retenção: a política é uma linha só e o corpo a descreve
    inteira. E editada no lugar, não versionada por vigência — ao contrário do
    **preço** do modelo, que é versionado justamente porque reprecificaria o
    passado. Um teto não reprecifica nada; ele decide o que ainda acontece amanhã.
    """
    with get_session(principal, role=DbRole.admin) as session:
        actor, organization = _authorized_org(session, principal, organization_id)
        record = session.execute(
            select(OrganizationAiQuota).where(
                OrganizationAiQuota.organization_id == organization.id
            )
        ).scalar_one_or_none()
        if record is None:
            record = OrganizationAiQuota(organization_id=organization.id)
            session.add(record)

        record.monthly_limit_cents = payload.monthly_limit_cents
        record.updated_by_user_id = actor.id
        session.flush()

        session.add(
            AuditLog(
                organization_id=organization.id,
                actor_user_id=actor.id,
                action="ai_quota.updated",
                entity_type="organization_ai_quota",
                entity_id=record.id,
                data=audit_data(monthly_limit_cents=payload.monthly_limit_cents),
            )
        )
        return _quota_out(session, organization.id, record=record)


@router.post(
    "/organizations/{organization_id}/erasure",
    response_model=ErasureRequestOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_erasure(
    organization_id: uuid.UUID, payload: ErasureRequestIn, principal: CurrentPrincipal
) -> ErasureRequestOut:
    """Registra o pedido de apagamento. **Não apaga.**

    202 e não 200: o trabalho ainda não aconteceu quando esta resposta sai, e
    dizer 200 sugeriria o contrário. O worker cumpre o pedido e escreve na
    própria linha o que removeu.

    A confirmação é o ``slug`` da organização, digitado. É a mesma ideia do
    "digite o nome do repositório" de qualquer serviço que apague de verdade:
    obriga quem clica a olhar **qual** tenant está na tela, que é justamente o
    erro que esta rota pode causar e nenhuma outra pode.
    """
    with get_session(principal, role=DbRole.admin) as session:
        actor, organization = _authorized_org(session, principal, organization_id)
        if payload.confirm_slug.strip() != organization.slug:
            # 422 e não 404: quem chegou aqui já provou que administra a
            # organização, e o que falhou foi a confirmação — esconder isso só
            # faria a pessoa tentar de novo às cegas.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Confirmation does not match the organization slug",
            )

        pending = session.execute(
            select(DataErasureRequest).where(
                DataErasureRequest.organization_id == organization.id,
                DataErasureRequest.state.in_(
                    (ErasureState.pending, ErasureState.running)
                ),
            )
        ).scalar_one_or_none()
        if pending is not None:
            # Pedir duas vezes é o mesmo que pedir uma. Devolve o pedido que já
            # existe em vez de enfileirar um segundo expurgo do mesmo tenant.
            return _erasure_out(pending)

        record = DataErasureRequest(
            organization_id=organization.id,
            requested_by_user_id=actor.id,
            requested_reason=payload.reason.strip(),
        )
        session.add(record)
        session.flush()
        session.add(
            AuditLog(
                organization_id=organization.id,
                actor_user_id=actor.id,
                action="retention.erasure_requested",
                entity_type="data_erasure_request",
                entity_id=record.id,
                data=audit_data(reason=payload.reason.strip()[:200]),
            )
        )
        response = _erasure_out(record)

    # Fora da transação, como o upload: o worker lê a linha do banco.
    from portal_api.worker import queue_erasure_requests

    queue_erasure_requests()
    return response


@router.get(
    "/organizations/{organization_id}/erasure", response_model=list[ErasureRequestOut]
)
def list_erasure_requests(
    organization_id: uuid.UUID, principal: CurrentPrincipal
) -> list[ErasureRequestOut]:
    """O histórico de pedidos — é o que faz o apagamento ser auditável."""
    with get_session(principal, role=DbRole.admin) as session:
        _, organization = _authorized_org(session, principal, organization_id)
        records = session.execute(
            select(DataErasureRequest)
            .where(DataErasureRequest.organization_id == organization.id)
            .order_by(DataErasureRequest.created_at.desc())
        ).scalars()
        return [_erasure_out(record) for record in records]


def _erasure_out(record: DataErasureRequest) -> ErasureRequestOut:
    return ErasureRequestOut(
        request_id=record.id,
        organization_id=record.organization_id,
        state=record.state,
        requested_reason=record.requested_reason,
        created_at=record.created_at,
        completed_at=record.completed_at,
        removed=record.removed,
        error=record.error,
    )


# --------------------------------------------------------------------------- #
# O sinal do assistente (Fase 6, ADR 0030)
#
# Leitura, e a única rota de `admin.py` cujo assunto é a conversa de outra
# pessoa. O que ela devolve é deliberadamente estreito: a avaliação, a
# calibragem e se o turno abriu pendência — nunca o que foi perguntado. A
# fronteira não é imposta aqui, e sim pelo GRANT de coluna da migração 0020: o
# papel do banco **não consegue** ler `conversation_message.text`, então um
# `select()` distraído nesta rota falha em vez de vazar.
# --------------------------------------------------------------------------- #


class RatedTurnOut(BaseModel):
    message_id: uuid.UUID
    created_at: datetime
    confidence: str | None
    feedback: str
    #: A nota que a pessoa **escolheu** escrever para quem a atende. É o único
    #: texto do cliente nesta resposta, e está aqui por ter sido endereçado ao
    #: time — ao contrário da pergunta, que foi endereçada ao assistente.
    feedback_comment: str | None
    feedback_at: datetime | None
    responder: str | None
    model: str | None
    prompt_version: str | None
    #: Se aquele turno abriu pendência por lacuna de contexto.
    opened_pending: bool


class AssistantSignalOut(BaseModel):
    project_id: uuid.UUID
    answers_total: int
    rated_total: int
    helpful: int
    not_helpful: int
    #: Turnos que declararam lacuna, com ou sem avaliação. É o outro sinal, e o
    #: mais objetivo dos dois: ninguém precisa clicar no polegar para ele contar.
    insufficient_context: int
    turns: list[RatedTurnOut]


@router.get(
    "/projects/{project_id}/assistant-signal", response_model=AssistantSignalOut
)
def get_assistant_signal(
    project_id: uuid.UUID, principal: CurrentPrincipal, limit: int = 50
) -> AssistantSignalOut:
    """Como o assistente está indo, para quem o mantém.

    Existe porque o feedback era gravado desde a ADR 0015 e **ninguém nunca o
    leu**: aquela ADR adiou a tela dizendo que "sem dado acumulado ela mostraria
    zero", e o dado acumulou. O sinal só é útil em agregado, e é por isso que a
    resposta traz contagens antes da lista.
    """
    with get_session(principal, role=DbRole.admin) as session:
        _, project = _authorized(session, principal, project_id)

        # **Nunca `select(ConversationMessage)`**, e isto não é estilo: a
        # entidade expande para todas as colunas, `text` inclusive, e o papel
        # não a tem — a primeira versão desta rota fez exatamente isso e
        # respondeu 500. É o GRANT da migração 0020 funcionando como projetado:
        # um `select()` distraído aqui **falha em vez de vazar**, e a falha
        # aparece no primeiro clique em vez de num incidente.
        answers = (
            ConversationMessage.project_id == project.id,
            ConversationMessage.role == ConversationRole.assistant,
        )
        counts = session.execute(
            select(
                func.count(),
                func.count(ConversationMessage.feedback),
                func.count(1).filter(
                    ConversationMessage.feedback == MessageFeedback.helpful
                ),
                func.count(1).filter(
                    ConversationMessage.feedback == MessageFeedback.not_helpful
                ),
                func.count(1).filter(
                    ConversationMessage.confidence
                    == MessageConfidence.insufficient_context
                ),
            ).where(*answers)
        ).one()

        rated = session.execute(
            select(
                ConversationMessage.id,
                ConversationMessage.created_at,
                ConversationMessage.confidence,
                ConversationMessage.feedback,
                ConversationMessage.feedback_comment,
                ConversationMessage.feedback_at,
                ConversationMessage.responder,
                ConversationMessage.model,
                ConversationMessage.prompt_version,
                ConversationMessage.pending_item_id,
            )
            .where(
                *answers,
                ConversationMessage.feedback.is_not(None),
            )
            .order_by(ConversationMessage.feedback_at.desc().nullslast())
            .limit(max(1, min(limit, 200)))
        ).all()

        return AssistantSignalOut(
            project_id=project.id,
            answers_total=counts[0],
            rated_total=counts[1],
            helpful=counts[2],
            not_helpful=counts[3],
            insufficient_context=counts[4],
            turns=[
                RatedTurnOut(
                    message_id=turn.id,
                    created_at=turn.created_at,
                    confidence=turn.confidence.value if turn.confidence else None,
                    feedback=turn.feedback.value,
                    feedback_comment=turn.feedback_comment,
                    feedback_at=turn.feedback_at,
                    responder=turn.responder.value if turn.responder else None,
                    model=turn.model,
                    prompt_version=turn.prompt_version,
                    opened_pending=turn.pending_item_id is not None,
                )
                for turn in rated
            ],
        )
