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

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal_api import access, agent_auth
from portal_api.auth import CurrentPrincipal
from portal_api.config import get_settings
from portal_api.db.session import DbRole, bind_admin_org, bind_invitee, get_session
from portal_api.identity import resolve_user
from portal_api.keycloak_admin import KeycloakAdmin, KeycloakAdminError, RealmUser
from portal_api.models import (
    SCOPE_EVENTS_WRITE,
    AgentApiKey,
    AuditLog,
    MemberRole,
    Membership,
    Project,
    ProjectFinancialAssumption,
    User,
)
from portal_api.principal import Principal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

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
            data={"project_id": str(project.id)},
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
            data=data or {},
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
