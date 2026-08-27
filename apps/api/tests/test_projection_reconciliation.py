"""A projeção não desaprende o que já observou (Fase 7, ADR 0076).

O sync do Biahflow é idempotente por **substituição**: o webhook ignora o corpo e re-busca o
snapshot inteiro, apagando e reinserindo fases, marcos, decisões e pendências. Isso torna o
caminho seguro contra duplicação e completamente **inseguro contra ordem**: um webhook
atrasado ou reentregue dispara um fetch, e até esta fatia o fetch de um estado mais velho era
aplicado por cima do mais novo — sem erro, sem log e sem teste que percebesse.

O que estes testes fixam é a recusa, e ela não é o portal decidindo a fase (ele continua sem
originar status, ADR 0006/0008): é o portal não desaprendendo.

Arquivo próprio, e não mais um bloco em `test_biahflow_integration.py`, pela razão de o
`backup-restore` ter job próprio: a reconciliação é a peça central da fatia e merece o
próprio vermelho.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from conftest import captured
from portal_api.integrations import biahflow
from portal_api.models import Milestone, Organization, Project

from test_biahflow_integration import _snapshot


def _versionado(
    *,
    biahflow_project_id: int,
    client_id: int,
    version: int,
    observed_at: str = "2026-08-20T09:00:00+00:00",
) -> dict[str, Any]:
    """Um snapshot com o envelope carimbado pela origem."""
    snapshot = _snapshot(biahflow_project_id=biahflow_project_id, client_id=client_id)
    snapshot["projection_version"] = version
    snapshot["observed_at"] = observed_at
    return snapshot


# --------------------------------------------------------------------------- #
# O predicado, sem banco
# --------------------------------------------------------------------------- #


def _projeto(*, version: int | None = None, observed_at: Any = None) -> Project:
    return Project(name="x", slug="x", projection_version=version, observed_at=observed_at)


def test_versao_menor_regride_e_versao_maior_nao() -> None:
    aplicado = _projeto(version=5)

    assert biahflow._regression(aplicado, 4, None) == "version"
    assert biahflow._regression(aplicado, 6, None) is None


def test_versao_igual_desempata_pela_observacao_da_origem() -> None:
    """O empate é o caso que a ADR 0076 nomeia, e é por isso que há dois critérios."""
    from datetime import datetime, timezone

    agora = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    antes = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    aplicado = _projeto(version=5, observed_at=agora)

    assert biahflow._regression(aplicado, 5, antes) == "observed_at"
    assert biahflow._regression(aplicado, 5, agora) is None  # duplicado exato: idempotente
    assert biahflow._regression(aplicado, 5, None) is None


def test_versao_maior_vence_um_relogio_que_regrediu() -> None:
    """O motivo de a versão existir separada da hora (ADR 0076 §1).

    Ordenar só por `observed_at` não sobrevive a um relógio de origem que anda para trás; o
    inteiro monotônico sobrevive, e por isso ele decide antes.
    """
    from datetime import datetime, timezone

    aplicado = _projeto(
        version=5, observed_at=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    )

    assert biahflow._regression(
        aplicado, 6, datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    ) is None


def test_versao_so_de_um_lado_nao_recusa_nada() -> None:
    """A armadilha declarada: tratar ausência como "menor" barraria snapshot legítimo.

    Ausência é ausência de afirmação, nunca versão zero — uma origem que ainda não numera
    continua sincronizando, que é o comportamento atual e é o que a ADR 0076 mantém.
    """
    assert biahflow._regression(_projeto(version=5), None, None) is None
    assert biahflow._regression(_projeto(), 1, None) is None
    assert biahflow._regression(_projeto(), None, None) is None


def test_a_hora_da_copia_nao_entra_na_comparacao() -> None:
    """`synced_at` é `now()` por construção: ordena as *cópias*, não os *estados*.

    Comparar por ele nunca recusaria nada e **pareceria** proteção — o modo de falha que a
    ADR 0033 nomeou. O limite é declarado, não fingido: um projeto cujo frescor é só a hora
    da cópia não tem defesa contra ordem, e este teste é a afirmação disso.
    """
    from datetime import datetime, timezone

    aplicado = _projeto()
    aplicado.synced_at = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)

    assert biahflow._regression(
        aplicado, None, None
    ) is None


# --------------------------------------------------------------------------- #
# O sync, com banco
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_snapshot_fora_de_ordem_nao_regride_a_projecao(db_session: Session) -> None:
    """O caso que a fatia existe para fechar, ponta a ponta.

    Versão N chega; versão N-1 chega depois (webhook atrasado, fetch que cruzou). O estado
    tem de continuar sendo o de N — **inclusive as entidades substituídas**, que é onde o
    dano seria invisível: o snapshot velho apagaria os marcos novos e reinseriria os velhos.
    """
    snap = _versionado(biahflow_project_id=71, client_id=67, version=9)
    snap["completion"] = 80
    snap["project"]["status"] = "completed"
    projeto = biahflow.sync_snapshot(db_session, snap)
    assert projeto.completion_percent == 80

    velho = _versionado(
        biahflow_project_id=71,
        client_id=67,
        version=8,
        observed_at="2026-08-19T09:00:00+00:00",
    )
    velho["completion"] = 10
    velho["project"]["status"] = "active"
    velho["project"]["name"] = "Nome de um snapshot que ficou para trás"
    velho["milestones"] = []

    devolvido = biahflow.sync_snapshot(db_session, velho)

    assert devolvido.id == projeto.id
    assert devolvido.completion_percent == 80
    assert devolvido.projection_version == 9
    assert devolvido.name == projeto.name
    marcos = db_session.execute(
        select(Milestone).where(Milestone.project_id == projeto.id)
    ).scalars().all()
    assert len(marcos) == 2, "o snapshot recusado apagou os marcos do estado mais novo"


@pytest.mark.integration
def test_a_recusa_nao_renomeia_a_organizacao(db_session: Session) -> None:
    """Uma recusa que aplica metade do snapshot não é uma recusa.

    O rename da organização acontecia **antes** de o projeto ser sequer procurado, então sem
    esta asserção o snapshot velho seguiria mudando o nome do cliente na tela.
    """
    snap = _versionado(biahflow_project_id=72, client_id=68, version=4)
    projeto = biahflow.sync_snapshot(db_session, snap)
    organizacao = db_session.get(Organization, projeto.organization_id)
    assert organizacao is not None
    nome = organizacao.name

    velho = _versionado(
        biahflow_project_id=72,
        client_id=68,
        version=3,
        observed_at="2026-08-19T09:00:00+00:00",
    )
    velho["project"]["client"]["name"] = "Nome antigo do cliente"
    biahflow.sync_snapshot(db_session, velho)

    db_session.refresh(organizacao)
    assert organizacao.name == nome


@pytest.mark.integration
def test_snapshot_duplicado_e_idempotente(db_session: Session) -> None:
    """Mesma versão, mesma observação: o webhook reentregue não duplica nem regride.

    É o que o sync já prometia por substituição, e que a recusa **não pode quebrar** — barrar
    o duplicado exato faria a reconciliação recusar a reentrega que o Biahflow faz de
    propósito quando o portal responde erro.
    """
    snap = _versionado(biahflow_project_id=73, client_id=69, version=2)
    primeiro = biahflow.sync_snapshot(db_session, snap)
    segundo = biahflow.sync_snapshot(db_session, snap)

    assert primeiro.id == segundo.id
    assert segundo.projection_version == 2
    marcos = db_session.execute(
        select(Milestone).where(Milestone.project_id == segundo.id)
    ).scalars().all()
    assert len(marcos) == 2


@pytest.mark.integration
def test_o_snapshot_mais_novo_continua_sendo_aplicado(db_session: Session) -> None:
    """A metade que impede a guarda de virar um `return` cedo demais."""
    snap = _versionado(biahflow_project_id=74, client_id=70, version=2)
    biahflow.sync_snapshot(db_session, snap)

    novo = _versionado(
        biahflow_project_id=74,
        client_id=70,
        version=3,
        observed_at="2026-08-21T09:00:00+00:00",
    )
    novo["completion"] = 95
    projeto = biahflow.sync_snapshot(db_session, novo)

    assert projeto.completion_percent == 95
    assert projeto.projection_version == 3


@pytest.mark.integration
def test_a_recusa_emite_o_evento_nomeado_com_o_detalhe_em_extra(db_session: Session) -> None:
    """O nome do evento é fixo e o detalhe vai em `extra` (ADR 0018/0034).

    Uma mensagem interpolada produziria um `event` novo por ocorrência, e o limiar que o
    `alerts.md` promete deixaria de valer. O runbook manda ler `reason`, `applied_version` e
    `rejected_version`; nenhum deles cai na heurística de segredo do `JsonFormatter`.
    """
    snap = _versionado(biahflow_project_id=75, client_id=71, version=6)
    projeto = biahflow.sync_snapshot(db_session, snap)

    velho = _versionado(
        biahflow_project_id=75,
        client_id=71,
        version=5,
        observed_at="2026-08-19T09:00:00+00:00",
    )
    with captured("portal_api.integrations.biahflow") as registros:
        biahflow.sync_snapshot(db_session, velho)

    linhas = [r for r in registros if r.getMessage() == "projection.stale_rejected"]
    assert len(linhas) == 1
    assert linhas[0].reason == "version"
    assert linhas[0].applied_version == 6
    assert linhas[0].rejected_version == 5
    assert linhas[0].project_id == str(projeto.id)
    assert linhas[0].biahflow_project_id == 75


@pytest.mark.integration
def test_um_sync_aceito_nao_emite_a_recusa(db_session: Session) -> None:
    """Senão o limiar do runbook contaria o curso normal."""
    snap = _versionado(biahflow_project_id=76, client_id=72, version=1)
    with captured("portal_api.integrations.biahflow") as registros:
        biahflow.sync_snapshot(db_session, snap)

    assert [r for r in registros if r.getMessage() == "projection.stale_rejected"] == []
