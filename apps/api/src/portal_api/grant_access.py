"""O primeiro vínculo de uma organização, e só ele (Fase 6, ADR 0025).

Existe por uma lacuna que só apareceu quando a segunda organização passou a
existir. A ADR 0011 fechou a escrita de ``membership`` em ``portal_admin``, e
``admin.py`` exige ``access.require_project(..., ADMIN_ONLY)`` — isto é, **já
ser** ``internal_admin`` naquele projeto. Enquanto toda organização vinha do
seed isso bastava; no dia em que o sync do Biahflow cria uma organização nova
(ADR 0006), ela nasce sem membership nenhuma e o projeto fica invisível para
todo mundo, inclusive para quem administra o portal. Não há tela que resolva,
e não deve haver.

Três decisões, todas com precedente:

1. **Não é rota HTTP, e isso é a decisão.** Mesma regra que a ADR 0017 aplicou
   ao expurgo — nenhuma rota apaga um tenant, o worker é que executa o pedido
   gravado. Aqui é a simétrica: nenhuma rota cria do nada o primeiro
   administrador de uma organização, porque é exatamente esse caminho que a GUC
   de terceiro estágio da ADR 0011 existe para fechar. Quem tem shell no
   servidor já alcança o banco; quem tem só a web, não.
2. **Roda sob ``portal_system``**, pelo argumento do ``seed.py``: é um caminho
   que *inaugura* um tenant, então não há contexto a fixar e a RLS negaria a
   escrita — corretamente.
3. **Recusa quando a organização já tem um ``internal_admin``.** Aí o caso
   deixou de ser bootstrap: existe alguém que alcança ``/admin``, que é
   auditável, tem tela e não pede shell. Um CLI que continua funcionando depois
   de desnecessário vira o caminho preferido por conveniência, e a ADR 0011
   passa a valer só no papel.

E grava ``audit_log``, porque o vínculo mais poderoso do sistema não pode ser o
único que não deixa rastro.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from portal_api.db.session import DbRole, get_session
from portal_api.models import AuditLog, MemberRole, Membership, Organization, User

logger = logging.getLogger(__name__)

#: Os papéis que fazem sentido conceder aqui. ``client_member`` fica de fora de
#: propósito: cliente entra por convite em ``/admin``, que cria a conta no realm
#: e manda o e-mail — este caminho não faz nada disso e criaria um vínculo para
#: alguém que não consegue entrar.
BOOTSTRAP_ROLES = (MemberRole.internal_admin, MemberRole.internal_member)


class GrantRefused(RuntimeError):
    """O bootstrap não se aplica — e a mensagem diz o caminho que se aplica."""


@dataclass(frozen=True)
class Granted:
    """O que aconteceu, para quem chama poder relatar sem reconsultar."""

    organization_slug: str
    email: str
    role: MemberRole
    created: bool


def grant(
    session: Session, *, email: str, organization_slug: str, role: MemberRole
) -> Granted:
    """Concede o vínculo de escopo organizacional (``project_id IS NULL``).

    Organizacional e não por projeto: o sync do Biahflow cria um projeto novo a
    cada projeto de lá, e um vínculo por projeto obrigaria a repetir o bootstrap
    a cada um. ``MembershipRepository.roles_for_project`` já soma o vínculo
    org-wide ao do projeto, então quem recebe isto administra a organização
    inteira — que é o que "primeiro administrador" quer dizer.
    """
    if role not in BOOTSTRAP_ROLES:
        raise GrantRefused(
            f"papel {role.value} não é de bootstrap; cliente entra por convite em /admin"
        )

    organization = session.execute(
        select(Organization).where(Organization.slug == organization_slug)
    ).scalar_one_or_none()
    if organization is None:
        raise GrantRefused(f"organização {organization_slug} não existe")

    user = session.execute(
        select(User).where(func.lower(User.email) == email.lower())
    ).scalar_one_or_none()
    if user is None:
        raise GrantRefused(
            f"{email} não tem linha em `user` — entre uma vez no portal, ou convide pelo /admin"
        )

    existing = session.execute(
        select(Membership).where(
            Membership.organization_id == organization.id,
            Membership.user_id == user.id,
            Membership.project_id.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Idempotente como o seed: repetir não duplica, e não é erro.
        return Granted(organization_slug, user.email, existing.role, created=False)

    # A recusa que mantém isto sendo bootstrap, e não uma porta paralela.
    # Depois do `existing`, de propósito: rodar duas vezes o mesmo comando tem de
    # continuar sendo no-op mesmo depois de a organização passar a ter admin.
    admin_ja_existe = session.execute(
        select(Membership.id).where(
            Membership.organization_id == organization.id,
            Membership.role == MemberRole.internal_admin,
        )
    ).first()
    if admin_ja_existe is not None:
        raise GrantRefused(
            f"{organization_slug} já tem internal_admin — use /admin, que é auditável e tem tela"
        )

    membership = Membership(
        organization_id=organization.id,
        project_id=None,
        user_id=user.id,
        role=role,
    )
    session.add(membership)
    session.flush()

    session.add(
        AuditLog(
            organization_id=organization.id,
            # Sem projeto: o vínculo é da organização inteira.
            project_id=None,
            # Quem operou é um shell, não uma sessão. O ator é a pessoa que
            # *recebeu* o vínculo, e o `data` diz que veio daqui — inventar um
            # ator seria pior do que dizer a verdade.
            actor_user_id=user.id,
            action="membership.bootstrapped",
            entity_type="membership",
            entity_id=membership.id,
            data={"role": role.value, "via": "grant_access", "organization": organization_slug},
        )
    )
    return Granted(organization_slug, user.email, role, created=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m portal_api.grant_access",
        description=(
            "Concede o primeiro vínculo administrativo de uma organização. "
            "Para todo o resto, use /admin."
        ),
    )
    parser.add_argument("--email", required=True, help="pessoa que já entrou no portal ao menos uma vez")
    parser.add_argument(
        "--organization", required=True, dest="organization_slug",
        help="slug da organização (ex.: biahflow-client-1)",
    )
    parser.add_argument(
        "--role", default=MemberRole.internal_admin.value,
        choices=[role.value for role in BOOTSTRAP_ROLES],
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args(argv)

    with get_session(role=DbRole.system) as session:
        try:
            result = grant(
                session,
                email=args.email,
                organization_slug=args.organization_slug,
                role=MemberRole(args.role),
            )
        except GrantRefused as refusal:
            # Falha fechada e com código de saída: isto costuma rodar dentro de
            # um script de implantação, onde um erro silencioso viraria "achei
            # que tinha concedido".
            logger.error("grant.refused %s", refusal)
            return 1

    if result.created:
        logger.info(
            "grant.applied organization=%s email=%s role=%s",
            result.organization_slug, result.email, result.role.value,
        )
        projects = " (o projeto já sincronizado passa a ser visível)"
    else:
        logger.info(
            "grant.unchanged organization=%s email=%s role=%s",
            result.organization_slug, result.email, result.role.value,
        )
        projects = " (o vínculo já existia)"
    logger.info("pronto%s", projects)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
