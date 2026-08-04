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

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal_api import access
from portal_api.auth import CurrentPrincipal
from portal_api.config import get_settings
from portal_api.db.session import DbRole, bind_admin_org, bind_invitee, get_session
from portal_api.identity import resolve_user
from portal_api.keycloak_admin import KeycloakAdmin, KeycloakAdminError, RealmUser
from portal_api.models import AuditLog, MemberRole, Membership, Project, User
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
    #: Já entrou pelo menos uma vez (tem `sub` gravado). Convite pendente é
    #: `False`, e é a única forma de a tela distinguir os dois estados.
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
    with get_session(principal, role=DbRole.admin) as session:
        _, project = _authorized(session, principal, project_id)

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
                active=user.external_subject is not None,
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
            active=user.external_subject is not None and realm_user.email_verified,
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
