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


def chosen_project(
    session: Session, user: User, project_id: uuid.UUID | None
) -> Project | None:
    """O projeto que o chamador nomeou, ou o padrão quando ele não nomeou nenhum.

    A generalização literal do que ``POST /api/v1/chat`` já fazia à mão desde a
    Fase 3, e que nenhuma das outras rotas de ``/me/`` tinha: com id, delega a
    :func:`scoped_project`; sem id, a :func:`default_project`. Nenhuma política
    nova nasce aqui — as duas metades já existiam, e o que faltava era o lugar
    onde a escolha acontece.

    **Projeto alheio ou inexistente é ``None``, nunca queda no padrão** (ADR
    0059). Cair no padrão devolveria a lista de *outro* projeto com 200, que é o
    ``.get(kind, _CLIENT_ONLY)`` da ADR 0040 na mesma forma: o esquecimento
    entrega ao cliente a coisa errada em vez de recusar. Quem nomeia um projeto
    que não alcança recebe o mesmo 404 opaco de sempre, com a negação registrada
    por ``scoped_project``.

    Existe porque onze rotas de ``/me/`` resolviam ``default_project`` — a
    membership **mais recente** — enquanto a tela ao lado vinha de
    ``/projects/{project_id}/dashboard`` com o ``?project=`` da URL. Um cliente
    com dois projetos, vendo B, recebia o sino e a busca de A, e a pendência de B
    respondia 404 por ser procurada sob o tenant de A.
    """
    if project_id is not None:
        return scoped_project(session, user, project_id)
    return default_project(session, user)


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


def preferred_project(session: Session, user: User) -> Project | None:
    """Which project the caller lands on when they did not name one — no binding.

    A client has a direct membership and that is the answer. Internal staff
    usually carry an organization-wide membership (``project_id IS NULL``), which
    used to resolve to nothing at all — they now land on the organization's most
    recent project.

    Split out of ``default_project`` in ADR 0062 so that ``visible_projects`` can
    ask the same question. Until then "the project the dashboard serves" and "the
    first project of ``GET /me``" were two criteria with no code in common, and
    the only thing reconciling them was the project **name** — which is exactly
    what ADR 0061 had to take out of the BFF. The choice lives here; the binding
    stays in the caller, because the listing spans projects and must not pin one.
    """
    # The membership policy already restricts this to the caller's own rows.
    memberships = list(
        session.execute(
            select(Membership)
            .where(Membership.user_id == user.id)
            .order_by(Membership.created_at.desc())
        ).scalars()
    )

    direct = next((m for m in memberships if m.project_id is not None), None)
    if direct is not None:
        return session.get(Project, direct.project_id)

    org_wide = next((m for m in memberships if m.project_id is None), None)
    if org_wide is None:
        return None

    return session.execute(
        select(Project)
        .where(Project.organization_id == org_wide.organization_id)
        .order_by(Project.created_at.desc())
    ).scalars().first()


def default_project(session: Session, user: User) -> Project | None:
    """The project to show when the caller did not name one, tenant bound.

    The choice is ``preferred_project``; what this adds is the stage-2 GUCs, and
    that is the whole difference between the two functions.
    """
    project = preferred_project(session, user)
    if project is None:
        return None

    bind_tenant(session, TenantContext(project.organization_id, project.id))
    return project


def visible_projects(
    session: Session, user: User
) -> list[tuple[Project, set[MemberRole]]]:
    """Every project the caller can reach, with the roles held on each.

    Feeds ``GET /api/v1/me``, and deliberately does **not** bind a tenant: the
    listing spans projects while the stage-2 GUCs hold exactly one. That is why
    ``preferred_project`` is called here and ``default_project`` is not — the
    question is the same, the binding is not.

    **The list opens with the project the dashboard serves** (ADR 0062). The rest
    keeps ``Project.created_at.desc()``. Which project ``default_project``
    resolves does not change; only where it sits in this listing does. Until this
    the two routes ordered by unrelated criteria, and with two homonymous projects
    in one tenant the first item of ``/me`` was not the project on screen — the
    divergence ADR 0061 published ``project_id`` to survive, and left standing.
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

    preferred = preferred_project(session, user)
    if preferred is not None:
        # Moved, never added: a project the listing does not already carry is one
        # the membership does not cover, and prepending it here would publish a
        # row that `GET /me` has no basis to show.
        projects = [p for p in projects if p.id == preferred.id] + [
            p for p in projects if p.id != preferred.id
        ]

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
