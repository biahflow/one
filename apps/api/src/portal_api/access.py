"""Project authorization for the portal (ADR 0002/0006/0010).

The membership — not the realm role — decides what a caller reaches: a realm role
cannot say *which project*. Every miss returns ``None`` so the caller answers 404
and never leaks which projects exist.

**Every resolver here binds the tenant context on the happy path.** That is a
deliberate side effect: the RLS policies on the project-scoped tables read
``portal.organization_id``/``portal.project_id``, so an endpoint that resolved a
project without binding would go on to read zero rows — a silent empty dashboard
instead of an error. Keeping the bind next to the authorization decision means no
endpoint has to remember it.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from portal_api.db.session import bind_tenant
from portal_api.models import MemberRole, Membership, Organization, Project, User
from portal_api.repositories import MembershipRepository, TenantContext

logger = logging.getLogger(__name__)

ANY_MEMBER = frozenset(MemberRole)
ADMIN_ONLY = frozenset({MemberRole.internal_admin})


def _denied(reason: str, user: User, **context: object) -> None:
    """Registra a negação, que até a ADR 0034 não deixava rastro nenhum.

    `docs/observability.md` lista "anomalias de autorização" entre os
    indicadores desde a Fase 1, e este arquivo — que é onde a decisão acontece —
    não tinha uma linha de log. As duas primeiras ameaças do `threat-model.md`
    ("cliente acessa outro projeto", "IDOR em arquivo/documento") descrevem um
    chamador **autenticado** passeando por ids alheios, e isso produzia apenas
    um `http.request` com `status: 404` e o *template* da rota — sem ator. Não
    havia como responder "quantas negações o sujeito X disparou em cinco
    minutos", que é a pergunta que separa um link velho de uma enumeração.

    Fica aqui, e não nas rotas: elas só traduzem ``None`` em 404, e são vinte e
    três. O `reason` distingue dois fatos operacionais diferentes, do mesmo jeito
    que o `auth.rejected` da autenticação faz com o dele.

    **O prefixo do `sub`, nunca o `sub` inteiro** — o precedente é literal, do
    `chat_limit.py`: o bastante para saber *quem* está em laço, sem o log virar
    um rastro estável por pessoa.

    Nada disso muda o que o chamador recebe: a resposta continua sendo o mesmo
    404 opaco, porque o sinal é para dentro (ADR 0010).
    """
    logger.warning(
        "authz.denied",
        extra={
            "reason": reason,
            "subject_prefix": (user.external_subject or "")[:8],
            **context,
        },
    )


def require_project(
    session: Session,
    user: User,
    project_id: uuid.UUID,
    allowed: frozenset[MemberRole] = ANY_MEMBER,
) -> Project | None:
    """The project, if the user holds one of ``allowed`` roles on it.

    ``session.get`` is already filtered by the ``project`` policy, so a
    non-member gets ``None`` from the database itself; the role check on top is
    what turns "is a member" into "may do *this*".
    """
    project = session.get(Project, project_id)
    if project is None:
        # Id inexistente e id de outro tenant são indistinguíveis daqui — a
        # policy não devolve a linha nos dois casos —, e é justamente por isso
        # que este é *o* sinal de acesso cruzado.
        _denied("not_a_member", user, project_id=str(project_id))
        return None

    memberships = MembershipRepository(session, TenantContext(project.organization_id))
    if not memberships.roles_for_project(user.id, project.id) & allowed:
        # Outro fato: é membro, e o papel não basta. Escalada **dentro** do
        # próprio tenant, que leva a outra investigação.
        _denied("role_insufficient", user, project_id=str(project_id))
        return None

    bind_tenant(session, TenantContext(project.organization_id, project.id))
    return project


def scoped_project(
    session: Session, user: User, project_id: uuid.UUID
) -> Project | None:
    """The project by id, for any kind of membership."""
    return require_project(session, user, project_id, ANY_MEMBER)


def require_organization(
    session: Session,
    user: User,
    organization_id: uuid.UUID,
    allowed: frozenset[MemberRole] = ADMIN_ONLY,
) -> Organization | None:
    """A organização, se o usuário tem um dos papéis de ``allowed`` **nela**.

    Existe para a retenção (Fase 5, ADR 0017), que é a primeira coisa do portal
    cujo escopo é a organização inteira e não um projeto: "por quanto tempo os
    dados ficam" e "apague tudo" não são perguntas que se façam projeto a
    projeto.

    Vale qualquer vínculo de administração dentro da organização — o de escopo
    organizacional (``project_id IS NULL``) ou o de um projeto qualquer dela. Um
    ``internal_admin`` de um projeto já administra dados daquela organização; o
    que a rota exige a mais, ela exige por conta própria.

    Não chama ``bind_tenant``: não há projeto a fixar. Quem escreve chama
    ``bind_admin_org``, como todo o resto de ``admin.py``.
    """
    organization = session.get(Organization, organization_id)
    if organization is None:
        _denied("not_a_member", user, organization_id=str(organization_id))
        return None

    roles = set(
        session.execute(
            select(Membership.role).where(
                Membership.user_id == user.id,
                Membership.organization_id == organization_id,
            )
        ).scalars()
    )
    if not roles & allowed:
        _denied("role_insufficient", user, organization_id=str(organization_id))
        return None
    return organization


def administered_organizations(
    session: Session,
    user: User,
    allowed: frozenset[MemberRole] = ADMIN_ONLY,
) -> list[Organization]:
    """The organizations the caller administers — the plural of ``require_organization``.

    Exists because the six organization-scoped admin routes are keyed on an
    ``organization_id`` that **no response in the API returned** (ADR 0027):
    ``MeOut.organization`` is the organization's *name*, and nothing else
    carried the uuid. They were not merely unscreened — they had no reachable
    caller at all.

    Same membership rule as ``require_organization``: an admin link of either
    scope counts, the organization-wide one (``project_id IS NULL``) or one on
    any project of it.

    Like ``visible_projects``, it binds **no** tenant: the listing spans
    organizations while the GUCs hold one. It also runs before any
    ``bind_admin_org``, and that is the point rather than an omission — at that
    stage the transaction sees only the caller's own memberships, which is the
    same property that keeps ``_authorized_org`` from being circular. There is
    no organization to pin when the question is *which* organizations.
    """
    organization_ids = set(
        session.execute(
            select(Membership.organization_id).where(
                Membership.user_id == user.id,
                Membership.role.in_(allowed),
            )
        ).scalars()
    )
    if not organization_ids:
        return []

    return list(
        session.execute(
            select(Organization)
            .where(Organization.id.in_(organization_ids))
            .order_by(Organization.name)
        ).scalars()
    )


def default_project(session: Session, user: User) -> Project | None:
    """The project to show when the caller did not name one.

    A client has a direct membership and that is the answer. Internal staff
    usually carry an organization-wide membership (``project_id IS NULL``), which
    used to resolve to nothing at all — they now land on the organization's most
    recent project.
    """
    # The membership policy already restricts this to the caller's own rows.
    memberships = list(
        session.execute(
            select(Membership)
            .where(Membership.user_id == user.id)
            .order_by(Membership.created_at.desc())
        ).scalars()
    )

    project: Project | None = None
    direct = next((m for m in memberships if m.project_id is not None), None)
    if direct is not None:
        project = session.get(Project, direct.project_id)
    else:
        org_wide = next((m for m in memberships if m.project_id is None), None)
        if org_wide is not None:
            project = session.execute(
                select(Project)
                .where(Project.organization_id == org_wide.organization_id)
                .order_by(Project.created_at.desc())
            ).scalars().first()

    if project is None:
        return None

    bind_tenant(session, TenantContext(project.organization_id, project.id))
    return project


def visible_projects(
    session: Session, user: User
) -> list[tuple[Project, set[MemberRole]]]:
    """Every project the caller can reach, with the roles held on each.

    Feeds ``GET /api/v1/me``, and deliberately does **not** bind a tenant: the
    listing spans projects while the stage-2 GUCs hold exactly one.
    """
    memberships = list(
        session.execute(
            select(Membership).where(Membership.user_id == user.id)
        ).scalars()
    )
    organizations = {m.organization_id for m in memberships}
    if not organizations:
        return []

    # The project policy already narrows this to what the memberships cover.
    projects = list(
        session.execute(
            select(Project)
            .where(Project.organization_id.in_(organizations))
            .order_by(Project.created_at.desc())
        ).scalars()
    )
    return [
        (
            project,
            {
                m.role
                for m in memberships
                if m.organization_id == project.organization_id
                and m.project_id in (None, project.id)
            },
        )
        for project in projects
    ]
