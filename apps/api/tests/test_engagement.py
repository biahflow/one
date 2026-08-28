"""O Engagement entre a conta e o projeto (Language Map v1.1, ADR 0079).

Três coisas são provadas aqui, e as três são sobre **não afirmar o que a origem não
disse**:

1. o programa chega pelo snapshot e aponta o projeto;
2. a ausência da chave **não** apaga um vínculo já afirmado (é o argumento do
   ``artifact_accepted_at``, e o oposto do do ``archived_at``);
3. ``account`` vence ``client`` na leitura e **o slug não muda** — órfãoar toda
   organização já sincronizada é o preço que um rename de chave de persistência cobra.

A isolação entre tenants tem casa própria em ``test_rls_isolation.py``: aqui o
``db_session`` roda sob ``portal_system``, que é ``BYPASSRLS`` por desenho e não
observa policy nenhuma.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from portal_api.auth import bearer_principal
from portal_api.integrations import biahflow
from portal_api.main import app
from portal_api.models import (
    Engagement,
    EngagementStatus,
    MemberRole,
    Membership,
    Organization,
    Project,
    User,
)
from portal_api.principal import Principal
from test_biahflow_integration import _snapshot

client = TestClient(app)


def _with_engagement(
    snapshot: dict[str, Any], *, engagement_id: int, name: str, status: str = "active"
) -> dict[str, Any]:
    snapshot["project"]["engagement"] = {
        "id": engagement_id,
        "name": name,
        "status": status,
    }
    return snapshot


# --- unidade: a identidade do programa --------------------------------------


def test_o_slug_do_engagement_sai_do_id_da_origem() -> None:
    assert biahflow.engagement_slug(12) == "biahflow-engagement-12"


def test_o_slug_da_organizacao_continua_historico() -> None:
    """O termo canônico virou Account e a **chave** não muda (Language Map §5, ADR 0079).

    Esta asserção existe para o rename ser uma decisão e não um acidente: trocar o
    literal aqui faz ``sync_snapshot`` deixar de achar toda organização já gravada e
    criar uma nova ao lado — órfã de membership, de projeto e de índice.
    """
    assert biahflow.org_slug(3) == "biahflow-client-3"


# --- integração: a ingestão -------------------------------------------------


@pytest.mark.integration
def test_o_snapshot_com_engagement_cria_o_programa_e_aponta_o_projeto(
    db_session: Session,
) -> None:
    project = biahflow.sync_snapshot(
        db_session,
        _with_engagement(
            _snapshot(biahflow_project_id=8101, client_id=8100),
            engagement_id=8110,
            name="Transformação Financeira",
        ),
    )

    engagement = db_session.get(Engagement, project.engagement_id)
    assert engagement is not None
    assert engagement.organization_id == project.organization_id
    assert engagement.slug == "biahflow-engagement-8110"
    assert engagement.name == "Transformação Financeira"
    assert engagement.status is EngagementStatus.active


@pytest.mark.integration
def test_o_upsert_do_engagement_e_idempotente_e_atualiza_nome_e_estado(
    db_session: Session,
) -> None:
    """Duas passagens, uma linha — e o rename do programa chega.

    O upsert é por ``(organization_id, slug)`` como o do projeto, então repetir o
    webhook não multiplica programa.
    """
    first = biahflow.sync_snapshot(
        db_session,
        _with_engagement(
            _snapshot(biahflow_project_id=8201, client_id=8200),
            engagement_id=8210,
            name="Programa",
        ),
    )
    second = biahflow.sync_snapshot(
        db_session,
        _with_engagement(
            _snapshot(biahflow_project_id=8201, client_id=8200),
            engagement_id=8210,
            name="Programa renomeado",
            status="paused",
        ),
    )

    assert first.id == second.id
    assert first.engagement_id == second.engagement_id
    rows = (
        db_session.execute(
            select(Engagement).where(Engagement.organization_id == second.organization_id)
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].name == "Programa renomeado"
    assert rows[0].status is EngagementStatus.paused


@pytest.mark.integration
def test_um_status_de_engagement_que_o_mapa_nao_conhece_cai_em_active(
    db_session: Session,
) -> None:
    """Vocabulário novo do outro lado não derruba o sync — o padrão do ``PROJECT_STATUS_MAP``."""
    project = biahflow.sync_snapshot(
        db_session,
        _with_engagement(
            _snapshot(biahflow_project_id=8301, client_id=8300),
            engagement_id=8310,
            name="Programa",
            status="hibernando",
        ),
    )

    engagement = db_session.get(Engagement, project.engagement_id)
    assert engagement is not None
    assert engagement.status is EngagementStatus.active


@pytest.mark.integration
def test_um_snapshot_sem_engagement_nao_cria_programa_nenhum(db_session: Session) -> None:
    """O Biahflow anterior a esta fatia manda o corpo sem a chave, e isso é válido."""
    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=8401, client_id=8400)
    )

    assert project.engagement_id is None
    assert (
        db_session.execute(
            select(Engagement).where(Engagement.organization_id == project.organization_id)
        )
        .scalars()
        .all()
        == []
    )


@pytest.mark.integration
def test_a_ausencia_da_chave_nao_apaga_o_vinculo_ja_afirmado(db_session: Session) -> None:
    """**Ausência não é negação.**

    É a diferença deliberada em relação ao ``archived_at``, cuja atribuição é
    incondicional porque lá ``None`` é um valor que a origem sabe desfazer. Aqui um
    snapshot calado é só um snapshot calado — zerar o vínculo faria o projeto perder o
    programa a cada webhook de um Biahflow parcialmente atualizado.
    """
    linked = biahflow.sync_snapshot(
        db_session,
        _with_engagement(
            _snapshot(biahflow_project_id=8501, client_id=8500),
            engagement_id=8510,
            name="Programa",
        ),
    )
    engagement_id = linked.engagement_id
    assert engagement_id is not None

    again = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=8501, client_id=8500)
    )

    assert again.engagement_id == engagement_id


@pytest.mark.integration
def test_a_chave_account_vence_a_client_e_o_slug_da_organizacao_nao_muda(
    db_session: Session,
) -> None:
    """O vocabulário muda na leitura; a chave de persistência, não (ADR 0079).

    O Biahflow manda as duas chaves em paralelo até a ``/api/v2/`` dele. O nome que
    prevalece é o de ``account``, e a organização continua sendo **a mesma linha** —
    é isso que impede o rename de vocabulário de órfãoar o tenant.
    """
    before = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=8601, client_id=8600)
    )
    snapshot = _snapshot(biahflow_project_id=8601, client_id=8600)
    snapshot["project"]["account"] = {"id": 8600, "name": "Acme Brasil S.A."}
    after = biahflow.sync_snapshot(db_session, snapshot)

    assert after.organization_id == before.organization_id
    organization = db_session.get(Organization, after.organization_id)
    assert organization is not None
    assert organization.slug == "biahflow-client-8600"
    assert organization.name == "Acme Brasil S.A."


@pytest.mark.integration
def test_um_snapshot_sem_account_e_sem_client_falha_alto(db_session: Session) -> None:
    """Sem organização não há tenant, e inventar um é o que a regra 1 proíbe."""
    snapshot = _snapshot(biahflow_project_id=8701, client_id=8700)
    del snapshot["project"]["client"]

    with pytest.raises(KeyError):
        biahflow.sync_snapshot(db_session, snapshot)


# --- integração: a projeção -------------------------------------------------


@pytest.mark.integration
def test_o_dashboard_projeta_o_programa_e_diz_none_quando_nao_ha(
    db_session: Session,
) -> None:
    with_program = biahflow.sync_snapshot(
        db_session,
        _with_engagement(
            _snapshot(biahflow_project_id=8801, client_id=8800),
            engagement_id=8810,
            name="Transformação Financeira",
            status="paused",
        ),
    )
    without = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=8802, client_id=8800)
    )

    projected = biahflow.build_dashboard(db_session, with_program)["engagement"]
    assert projected == {
        "id": str(with_program.engagement_id),
        "name": "Transformação Financeira",
        "status": "paused",
    }
    # E a ausência é dita, não omitida: `extra="forbid"` do `DashboardOut` recusaria a
    # chave faltando, e a tela precisa distinguir "sem programa" de "campo sumiu".
    assert biahflow.build_dashboard(db_session, without)["engagement"] is None


# --- integração: a rota que alimenta o seletor ------------------------------


@pytest.fixture
def two_projects_one_program(migrated_engine: Engine) -> Iterator[tuple[str, uuid.UUID]]:
    """Uma conta, um programa, dois projetos — e um deles fora do programa.

    É a forma que o seletor tem de saber agrupar: um grupo com cabeçalho e o grupo sem
    cabeçalho no fim. O tenant é sorteado pelo argumento escrito na fixture ``homonyms``
    de ``test_dashboard_scope.py``: ``org_slug`` chaveia por número, e um número fixo é
    uma linha compartilhada com todo teste que use o mesmo.
    """
    tag = uuid.uuid4().hex[:8]
    subject, email = f"sub-engagement-{tag}", f"engagement-{tag}@example.com"
    account_id = 900_000 + int(tag, 16) % 90_000
    with Session(migrated_engine) as session:
        inside = biahflow.sync_snapshot(
            session,
            _with_engagement(
                _snapshot(biahflow_project_id=account_id + 1, client_id=account_id),
                engagement_id=account_id + 500,
                name="Transformação Financeira",
            ),
        )
        outside = biahflow.sync_snapshot(
            session, _snapshot(biahflow_project_id=account_id + 2, client_id=account_id)
        )
        organization_id = inside.organization_id
        user = User(email=email, full_name="Cliente Programa", external_subject=subject)
        session.add(user)
        session.flush()
        session.add(
            Membership(
                organization_id=organization_id,
                project_id=None,
                user_id=user.id,
                role=MemberRole.client_member,
            )
        )
        session.commit()
        engagement_id = inside.engagement_id
        assert engagement_id is not None
        assert outside.engagement_id is None

    app.dependency_overrides[bearer_principal] = lambda: Principal(
        subject=subject,
        email=email,
        full_name="Cliente Programa",
        realm_roles=frozenset({"client_member"}),
    )
    try:
        yield email, engagement_id
    finally:
        app.dependency_overrides.clear()
        with Session(migrated_engine) as cleanup:
            cleanup.execute(delete(Organization).where(Organization.id == organization_id))
            cleanup.execute(delete(User).where(User.email == email))
            cleanup.commit()


@pytest.mark.integration
def test_o_me_devolve_o_programa_de_cada_projeto(
    two_projects_one_program: tuple[str, uuid.UUID],
) -> None:
    """E devolve **sob a policy do papel de requisição**, que é a metade que quase ficou cega.

    ``access.visible_projects`` documenta que não fixa tenant, então uma policy de
    ``engagement`` chaveada em ``portal.current_org()`` devolveria zero linhas aqui — o
    nome viria nulo em todo projeto, na única rota que o seletor lê. O predicado é por
    vínculo (migração 0037), e é isto que esta asserção prova.
    """
    _, engagement_id = two_projects_one_program

    body = client.get("/api/v1/me")
    assert body.status_code == 200
    listed = body.json()["projects"]

    assert len(listed) == 2
    by_id = {project["engagement_id"] for project in listed}
    assert by_id == {str(engagement_id), None}
    named = [project for project in listed if project["engagement_id"] is not None]
    assert named[0]["engagement_name"] == "Transformação Financeira"
    loose = [project for project in listed if project["engagement_id"] is None]
    assert loose[0]["engagement_name"] is None


@pytest.mark.integration
def test_o_projeto_sem_programa_continua_na_lista(
    two_projects_one_program: tuple[str, uuid.UUID],
) -> None:
    """Ausência de programa **não** esconde o projeto — o seletor o mostra sem cabeçalho."""
    listed = client.get("/api/v1/me").json()["projects"]

    assert any(project["engagement_id"] is None for project in listed)
    assert all(project["name"] for project in listed)


@pytest.mark.integration
def test_apagar_o_programa_nao_apaga_o_projeto(db_session: Session) -> None:
    """``ondelete='SET NULL'``, e é decisão: o projeto do cliente sobrevive ao programa."""
    project = biahflow.sync_snapshot(
        db_session,
        _with_engagement(
            _snapshot(biahflow_project_id=8901, client_id=8900),
            engagement_id=8910,
            name="Programa",
        ),
    )
    engagement_id = project.engagement_id
    project_id = project.id

    db_session.execute(delete(Engagement).where(Engagement.id == engagement_id))
    db_session.flush()
    db_session.expire_all()

    survivor = db_session.get(Project, project_id)
    assert survivor is not None
    assert survivor.engagement_id is None


# --- o link do aviso, depois do rename de rota (ADR 0080) -------------------


def test_o_link_gravado_no_aviso_e_o_mesmo_que_a_migracao_reescreveu() -> None:
    """A migração 0038 conserta o **dado**; este teste impede que os dois divirjam.

    ``notification.link`` é gravado, não resolvido na leitura: `fan_out` congela a URL
    na linha (ADR 0043). A ADR 0079 renomeou a rota sem redirect, e a 0080 reescreveu as
    linhas antigas. Se alguém renomear a rota de novo e esquecer a migração, o produtor
    passa a escrever um valor que o histórico não tem — e o defeito é mudo, porque um
    ``href`` para rota inexistente renderiza igual.
    """
    root = Path(__file__).resolve().parents[1] / "src" / "portal_api"
    produced = re.search(r'link="(/admin/[^"]+)"', (root / "onboarding.py").read_text())
    migrated = re.search(
        r"NEW_LINK = '(/admin/[^']+)'",
        (root / "db/migrations/versions/0038_notification_link_rename.py").read_text(),
    )

    assert produced is not None, "`onboarding.py` deixou de gravar um link explícito"
    assert migrated is not None, "a migração 0038 deixou de declarar `NEW_LINK`"
    assert produced.group(1) == migrated.group(1)
