"""O funil de onboarding: carimbo imutável, escrito pelas rotas de verdade (RFC 001, ADR 0039).

Os degraus são exercitados **pela rota**, e não chamando ``onboarding.stamp`` direto. A
diferença foi medida na ADR 0035: uma ligação frouxa entre o teste e o caminho real deu
`POST /chat` como coberto por um 404 que era de outra rota. Aqui vale o mesmo — provar que a
função carimba não prova que alguém a chama.

O isolamento e a ausência de GRANT para o papel de requisição ficam em
``test_rls_isolation.py``, ao lado dos outros da mesma forma.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from portal_api import onboarding
from portal_api.models import OnboardingStep, OnboardingStepName

pytestmark = pytest.mark.integration


@pytest.fixture
def organization_id(migrated_engine: Engine) -> uuid.UUID:
    """Uma organização qualquer, criada e limpa por este arquivo.

    Não reusa a do ``World`` de ``test_authorization.py`` de propósito: o funil é uma linha
    por organização e por degrau, então um teste que carimbasse na organização compartilhada
    envenenaria o seguinte — e o defeito apareceria como "o segundo carimbo não criou linha",
    que é exatamente o que outro teste aqui **espera** ver.
    """
    from portal_api.models import Organization

    with Session(migrated_engine) as session:
        organization = Organization(
            name="Funil Ltda", slug=f"funil-{uuid.uuid4().hex[:8]}"
        )
        session.add(organization)
        session.commit()
        oid = organization.id
    yield oid
    with Session(migrated_engine) as session:
        session.execute(delete(OnboardingStep).where(OnboardingStep.organization_id == oid))
        session.execute(delete(Organization).where(Organization.id == oid))
        session.commit()


def _steps(migrated_engine: Engine, organization_id: uuid.UUID) -> list[OnboardingStep]:
    with Session(migrated_engine) as session:
        return list(
            session.execute(
                select(OnboardingStep)
                .where(OnboardingStep.organization_id == organization_id)
                .order_by(OnboardingStep.step)
            ).scalars()
        )


def test_the_stamp_is_immutable(migrated_engine: Engine, organization_id: uuid.UUID) -> None:
    """Primeira vez é primeira vez — o segundo carimbo não tem efeito nenhum.

    É a única métrica que interessa (o *time-to-first-value*), e reescrevê-la a destruiria.
    A garantia é a ``UniqueConstraint`` mais ``ON CONFLICT DO NOTHING``, e não a boa vontade
    de quem chama: nenhum papel tem GRANT de ``UPDATE`` nesta tabela.
    """
    primeiro = datetime.now(timezone.utc) - timedelta(days=3)

    assert onboarding.stamp(
        organization_id, OnboardingStepName.first_login, reached_at=primeiro
    ) is True
    # O retorno é o que distingue "aconteceu agora" de "acontece toda vez" — e é ele que
    # impede o evento de virar uma linha de log por download.
    assert onboarding.stamp(organization_id, OnboardingStepName.first_login) is False

    linhas = _steps(migrated_engine, organization_id)
    assert len(linhas) == 1
    assert linhas[0].reached_at == primeiro


def test_a_failure_to_stamp_never_breaks_the_caller() -> None:
    """A decisão declarada na ADR 0039: medir engajamento não derruba o que o cliente veio fazer.

    Um degrau perdido é um dado a menos numa métrica de tendência; uma exceção propagada
    seria um download que não acontece ou um dashboard que não abre.

    A falha é de banco de verdade — organização inexistente viola a chave estrangeira —, e
    não um erro de tipo: o que precisa ser provado é o caminho que a produção percorreria.
    """
    assert (
        onboarding.stamp(uuid.uuid4(), OnboardingStepName.first_login) is False
    )


def test_the_dashboard_route_stamps_the_first_login(migrated_engine: Engine) -> None:
    """O degrau pela **rota** que o cliente de fato abre, e não chamando ``stamp`` direto.

    A diferença foi medida na ADR 0035: uma ligação frouxa entre teste e caminho real deu
    ``POST /chat`` como coberto por um 404 que era de outra rota. Provar que a função
    carimba não prova que alguém a chama.

    O login é carimbado nesta rota e não em ``identity.resolve_user``, e a razão está escrita
    naquele módulo: quando o ``external_subject`` deixa de ser nulo ainda não há organização
    resolvida. Aqui há — e o degrau fica melhor definido, porque "aceitou o convite" passa a
    significar que a pessoa **entrou e viu o projeto**.
    """
    from fastapi.testclient import TestClient

    from portal_api.auth import Principal, bearer_principal
    from portal_api.integrations import biahflow
    from portal_api.main import app

    # Sessão própria e **comitada**, e não a `db_session` transacional: a rota abre conexão
    # própria e o carimbo abre uma terceira, sob `portal_system`. Montar o cenário numa
    # transação aberta faz as três disputarem lock — medido, e o teste trava sem falhar.
    with Session(migrated_engine) as setup:
        project = biahflow.sync_snapshot(setup, _snapshot(biahflow_project_id=91, client_id=87))
        biahflow.ensure_demo_client(setup, project, "funil@acme.test", "Cliente Funil")
        setup.commit()
        organization_id = project.organization_id
        project_id = project.id

    app.dependency_overrides[bearer_principal] = lambda: Principal(
        subject="sub-funil",
        email="funil@acme.test",
        full_name="Cliente Funil",
        realm_roles=frozenset({"client_member"}),
    )
    try:
        assert TestClient(app).get("/api/v1/me/dashboard").status_code == 200
    finally:
        app.dependency_overrides.clear()

    carimbados = {row.step for row in _steps(migrated_engine, organization_id)}
    assert OnboardingStepName.first_login in carimbados

    with Session(migrated_engine) as cleanup:
        from portal_api.models import Membership, Organization, Project

        cleanup.execute(
            delete(OnboardingStep).where(OnboardingStep.organization_id == organization_id)
        )
        cleanup.execute(delete(Membership).where(Membership.organization_id == organization_id))
        cleanup.execute(delete(Project).where(Project.id == project_id))
        cleanup.execute(delete(Organization).where(Organization.id == organization_id))
        cleanup.commit()


def _snapshot(*, biahflow_project_id: int, client_id: int) -> dict:
    return {
        "project": {
            "id": biahflow_project_id, "name": "Automação", "description": "",
            "status": "active", "start_date": "2026-08-01", "due_date": "2026-09-30",
            "is_overdue": False, "client": {"id": client_id, "name": "Funil Ltda"},
        },
        "completion": 50,
        "milestones": [],
        "documents": [],
    }
