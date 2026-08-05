"""O teto mensal de gasto de IA, e o custo que nasce na leitura (Fase 5, ADR 0022).

Fecha a terceira das três coisas que o ``threat-model.md`` prometia para abuso de
chat desde a Fase 1 — "rate limit, quotas e auditoria". A ADR 0021 entregou duas e
corrigiu o documento para parar de prometer esta.

O que estes testes fixam não é o número, é a **forma**: dinheiro derivado do preço
vigente no dia da chamada (nunca gravado), um razão que não subconta sob
concorrência, e uma recusa que não custa o que ela existe para evitar.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from portal_api.ai import quota
from portal_api.auth import bearer_principal
from portal_api.config import get_settings
from portal_api.main import app
from portal_api.models import (
    AiModelPrice,
    AiUsageEvent,
    ChatRateWindow,
    Conversation,
    ConversationMessage,
    MemberRole,
    Membership,
    Organization,
    OrganizationAiQuota,
    PendingItem,
    Project,
    ProjectStatus,
    User,
)
from portal_api.principal import Principal
from portal_api.repositories import TenantContext

pytestmark = pytest.mark.integration

client = TestClient(app)

QUESTION = "Qual é o status do projeto?"


@dataclass(frozen=True)
class Asker:
    organization_id: uuid.UUID
    project_id: uuid.UUID
    subject: str


@pytest.fixture
def asker(migrated_engine: Engine) -> Iterator[Asker]:
    """Sessão comitada e `dependency_overrides`, como em `test_chat_rate_limit.py`.

    As fixtures transacionais do `conftest` não servem aqui: a requisição HTTP
    abre a própria transação e não enxergaria linhas que nunca comitaram.
    """

    tag = uuid.uuid4().hex[:8]
    subject = f"sub-quota-{tag}"
    with Session(migrated_engine) as session:
        organization = Organization(name="Acme Quota", slug=f"quota-{tag}")
        session.add(organization)
        session.flush()
        project = Project(
            organization_id=organization.id,
            name="Automação",
            slug=f"quota-project-{tag}",
            status=ProjectStatus.in_implementation,
            completion_percent=50,
        )
        session.add(project)
        user = User(
            email=f"quota-{tag}@example.com",
            full_name="Quem Pergunta",
            external_subject=subject,
        )
        session.add(user)
        session.flush()
        session.add(
            Membership(
                organization_id=organization.id,
                project_id=project.id,
                user_id=user.id,
                role=MemberRole.client_member,
            )
        )
        session.commit()
        made = Asker(organization.id, project.id, subject)

    app.dependency_overrides[bearer_principal] = lambda: Principal(
        subject=subject,
        email=f"quota-{tag}@example.com",
        full_name="Quem Pergunta",
        realm_roles=frozenset({"client_member"}),
    )
    try:
        yield made
    finally:
        app.dependency_overrides.clear()
        with Session(migrated_engine) as cleanup:
            cleanup.execute(delete(ChatRateWindow).where(ChatRateWindow.subject == subject))
            cleanup.execute(
                delete(AiUsageEvent).where(AiUsageEvent.organization_id == made.organization_id)
            )
            cleanup.execute(
                delete(OrganizationAiQuota).where(
                    OrganizationAiQuota.organization_id == made.organization_id
                )
            )
            cleanup.execute(delete(Conversation).where(Conversation.project_id == made.project_id))
            cleanup.execute(delete(PendingItem).where(PendingItem.project_id == made.project_id))
            cleanup.commit()


@pytest.fixture
def spend_of(migrated_engine: Engine) -> Callable[[Asker, int, int], None]:
    """Planta consumo já gravado — o que a checagem de fato lê."""

    def _plant(who: Asker, input_tokens: int, output_tokens: int) -> None:
        with Session(migrated_engine) as session:
            session.add(
                AiUsageEvent(
                    organization_id=who.organization_id,
                    project_id=who.project_id,
                    occurred_at=datetime.now(timezone.utc),
                    model="claude-opus-5",
                    responder="anthropic",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            )
            session.commit()

    return _plant


@pytest.fixture
def limit_of(monkeypatch: pytest.MonkeyPatch) -> Callable[[int], None]:
    def _set(value: int) -> None:
        monkeypatch.setattr(get_settings(), "ai_quota_monthly_cents", value)

    return _set


def _ask() -> int:
    return client.post("/api/v1/chat", json={"question": QUESTION}).status_code


def _ctx(who: Asker) -> TenantContext:
    return TenantContext(organization_id=who.organization_id, project_id=who.project_id)


# ---------------------------------------------------------------------------
# O dinheiro nasce na leitura
# ---------------------------------------------------------------------------


def test_the_ledger_stores_tokens_and_never_money(
    asker: Asker, migrated_engine: Engine
) -> None:
    """A decisão que carrega o desenho, afirmada sobre a tabela.

    Uma coluna de custo gravada na ingestão seria mais barata de somar e passaria
    a mentir no primeiro reajuste — sem que nada notasse, porque o número já
    estaria lá. É a regra de `results.py`.
    """

    assert not hasattr(AiUsageEvent, "cost_cents")
    assert hasattr(AiUsageEvent, "input_tokens")
    assert hasattr(AiUsageEvent, "output_tokens")


def test_a_price_change_today_does_not_reprice_last_month(
    asker: Asker, spend_of, migrated_engine: Engine, db_session: Session
) -> None:
    """O motivo de `ai_model_price` ter vigência em vez de ser uma constante.

    Mesma propriedade que a ADR 0013 fixou para o valor-hora: aumentar o preço
    hoje não pode reprecificar março.
    """

    spend_of(asker, 1_000_000, 0)  # 1 Mtok de entrada, a 500 centavos/Mtok
    with Session(migrated_engine) as session:
        before = quota.spend(session, asker.organization_id)
    assert before.cost_cents == 500

    # Fecha a vigência corrente e abre outra, dez vezes mais cara, **amanhã**.
    tomorrow = date.today() + timedelta(days=1)
    with Session(migrated_engine) as session:
        current = session.execute(
            select(AiModelPrice).where(
                AiModelPrice.model == "claude-opus-5", AiModelPrice.effective_to.is_(None)
            )
        ).scalar_one()
        current.effective_to = tomorrow
        session.add(
            AiModelPrice(
                model="claude-opus-5",
                effective_from=tomorrow,
                input_cents_per_mtok=5_000,
                output_cents_per_mtok=25_000,
            )
        )
        session.commit()

    try:
        with Session(migrated_engine) as session:
            after = quota.spend(session, asker.organization_id)
        assert after.cost_cents == 500, "o consumo de hoje foi reprecificado pelo preço de amanhã"
    finally:
        with Session(migrated_engine) as undo:
            undo.execute(delete(AiModelPrice).where(AiModelPrice.effective_from == tomorrow))
            restored = undo.execute(
                select(AiModelPrice).where(AiModelPrice.model == "claude-opus-5")
            ).scalar_one()
            restored.effective_to = None
            undo.commit()


def test_a_model_without_a_price_declares_the_gap_instead_of_counting_zero(
    asker: Asker, migrated_engine: Engine
) -> None:
    """A única falha **aberta** de um repositório que falha fechado, e por quê.

    O razão guardou o fato (os tokens), então um preço que falta pode ser
    aplicado retroativamente amanhã; uma pergunta recusada hoje porque alguém
    trocou o modelo sem cadastrar o preço não volta. Zero silencioso seria o
    contrário do que `results.py` faz com base ausente.
    """

    with Session(migrated_engine) as session:
        session.add(
            AiUsageEvent(
                organization_id=asker.organization_id,
                project_id=asker.project_id,
                occurred_at=datetime.now(timezone.utc),
                model="claude-modelo-que-ninguem-cadastrou",
                responder="anthropic",
                input_tokens=9_000_000,
                output_tokens=9_000_000,
            )
        )
        session.commit()

        current = quota.spend(session, asker.organization_id)

    assert current.cost_cents == 0
    assert current.gaps, "consumo sem preço vigente precisa declarar a lacuna"
    assert "sem preço vigente" in current.gaps[0]


def test_the_offline_path_is_free_without_being_a_gap(
    asker: Asker, migrated_engine: Engine
) -> None:
    """`model IS NULL` é custo zero de verdade, não base ausente.

    Declarar lacuna aqui faria o alerta disparar toda vez que o provedor caísse —
    o que já tem evento próprio (`chat.provider_unavailable`).
    """

    with Session(migrated_engine) as session:
        session.add(
            AiUsageEvent(
                organization_id=asker.organization_id,
                project_id=asker.project_id,
                occurred_at=datetime.now(timezone.utc),
                model=None,
                responder="offline_fallback",
                input_tokens=0,
                output_tokens=0,
            )
        )
        session.commit()

        current = quota.spend(session, asker.organization_id)

    assert current.cost_cents == 0
    assert current.gaps == ()


def test_last_months_spend_does_not_count_against_this_month(
    asker: Asker, migrated_engine: Engine
) -> None:
    """O teto é mensal, e o mês é de calendário — a fatura de quem cobra vira no dia 1."""

    start, _ = quota.period_bounds(datetime.now(timezone.utc))
    with Session(migrated_engine) as session:
        session.add(
            AiUsageEvent(
                organization_id=asker.organization_id,
                project_id=asker.project_id,
                occurred_at=start - timedelta(days=1),
                model="claude-opus-5",
                responder="anthropic",
                input_tokens=10_000_000,
                output_tokens=0,
            )
        )
        session.commit()

        assert quota.spend(session, asker.organization_id).cost_cents == 0


# ---------------------------------------------------------------------------
# A recusa
# ---------------------------------------------------------------------------


def test_the_chat_answers_429_once_the_quota_is_exhausted(
    asker: Asker, spend_of, limit_of
) -> None:
    limit_of(100)
    assert _ask() == 200

    spend_of(asker, 1_000_000, 0)  # 500 centavos, bem acima do teto de 100

    assert _ask() == 429


def test_a_refused_turn_writes_no_usage_no_pendencia_and_no_message(
    asker: Asker, spend_of, limit_of, migrated_engine: Engine
) -> None:
    """A propriedade que dá sentido ao controle, na forma do teste do limite de taxa.

    Uma recusa que ainda gravasse consumo cobraria pela recusa; uma que gravasse
    pendência inundaria a caixa do time interno, que é o buraco que a ADR 0021
    fechou. A recusa não pode custar o que ela existe para evitar.
    """

    limit_of(1)
    spend_of(asker, 1_000_000, 0)

    def counts() -> tuple[int, int, int]:
        with Session(migrated_engine) as check:
            usage = check.execute(
                select(func.count()).select_from(AiUsageEvent).where(
                    AiUsageEvent.organization_id == asker.organization_id
                )
            ).scalar_one()
            pendings = check.execute(
                select(func.count()).select_from(PendingItem).where(
                    PendingItem.project_id == asker.project_id
                )
            ).scalar_one()
            messages = check.execute(
                select(func.count()).select_from(ConversationMessage).where(
                    ConversationMessage.project_id == asker.project_id
                )
            ).scalar_one()
        return usage, pendings, messages

    before = counts()

    assert _ask() == 429

    assert counts() == before


def test_the_429_points_at_the_turn_of_the_month(asker: Asker, spend_of, limit_of) -> None:
    """É o `Retry-After` que separa esta recusa da janela de um minuto.

    A tela distingue as duas pela ordem de grandeza, sem precisar ler o texto —
    e é por isso que ele aponta para quando a afirmação volta a ser verdadeira.
    """

    limit_of(1)
    spend_of(asker, 1_000_000, 0)

    response = client.post("/api/v1/chat", json={"question": QUESTION})

    assert response.status_code == 429
    retry_after = int(response.headers["Retry-After"])
    _, end = quota.period_bounds(datetime.now(timezone.utc))
    assert retry_after > 3600, "o teto mensal não pode devolver um Retry-After de janela curta"
    assert retry_after <= int((end - datetime.now(timezone.utc)).total_seconds()) + 5


def test_a_zero_limit_disables_the_control_and_a_null_column_does_not(
    asker: Asker, spend_of, limit_of, migrated_engine: Engine
) -> None:
    """Coluna nula é "usa o padrão", nunca "sem teto" — a regra da retenção.

    Para desligar existe um zero explícito, que é o que o distingue de um
    esquecimento.
    """

    spend_of(asker, 1_000_000, 0)

    limit_of(1)
    with Session(migrated_engine) as session:
        session.add(OrganizationAiQuota(organization_id=asker.organization_id))
        session.commit()
        # Coluna nula: cai no padrão, que está em 1 — e portanto recusa.
        assert quota.limit_cents(session, asker.organization_id, get_settings()) == 1
    assert _ask() == 429

    with Session(migrated_engine) as session:
        record = session.execute(
            select(OrganizationAiQuota).where(
                OrganizationAiQuota.organization_id == asker.organization_id
            )
        ).scalar_one()
        record.monthly_limit_cents = 0
        session.commit()

    assert _ask() == 200


def test_the_organization_limit_overrides_the_default(
    asker: Asker, spend_of, limit_of, migrated_engine: Engine
) -> None:
    limit_of(1)
    spend_of(asker, 1_000_000, 0)
    assert _ask() == 429

    with Session(migrated_engine) as session:
        session.add(
            OrganizationAiQuota(
                organization_id=asker.organization_id, monthly_limit_cents=100_000
            )
        )
        session.commit()

    assert _ask() == 200


# ---------------------------------------------------------------------------
# O razão, e o que o papel de requisição pode fazer com ele
# ---------------------------------------------------------------------------


def test_a_successful_turn_records_what_it_consumed(
    asker: Asker, limit_of, migrated_engine: Engine
) -> None:
    """Sem chave configurada o respondedor é o offline: zero tokens, mas **uma linha**.

    "Esta pergunta não custou nada porque o provedor estava fora" é informação, e
    apagá-la faria o mês parecer mais barato do que o serviço foi.
    """

    limit_of(100_000)
    assert _ask() == 200

    with Session(migrated_engine) as check:
        rows = list(
            check.execute(
                select(AiUsageEvent).where(
                    AiUsageEvent.organization_id == asker.organization_id
                )
            ).scalars()
        )

    assert len(rows) == 1
    assert rows[0].responder == "offline"
    assert rows[0].project_id == asker.project_id


def test_a_gap_turn_is_charged_too(asker: Asker, limit_of, migrated_engine: Engine) -> None:
    """A chamada custou tanto tendo respondido quanto tendo virado lacuna.

    Cobrar só a resposta útil ensinaria que perguntas ruins são de graça, que é o
    oposto do incentivo desejado — e a lacuna é o caminho mais caro do portal,
    porque ela ainda grava pendência e enfileira notificação.
    """

    limit_of(100_000)
    response = client.post(
        "/api/v1/chat", json={"question": "Quanto custa um trator em Marte?"}
    )
    assert response.status_code == 200
    assert response.json()["confidence"] == "insufficient_context"

    with Session(migrated_engine) as check:
        count = check.execute(
            select(func.count()).select_from(AiUsageEvent).where(
                AiUsageEvent.organization_id == asker.organization_id
            )
        ).scalar_one()

    assert count == 1


def test_the_request_path_cannot_rewrite_what_a_call_cost(
    asker: Asker, spend_of, rls_session: Session
) -> None:
    """`INSERT` sim, `UPDATE`/`DELETE` não — a forma do `agent_event` (ADR 0013).

    Ninguém reescreve o que uma chamada custou, pela mesma razão pela qual
    ninguém reescreve as citações que uma resposta mostrou (ADR 0015/0021).
    """

    from sqlalchemy.exc import ProgrammingError

    spend_of(asker, 1_000, 1_000)

    with pytest.raises(ProgrammingError):
        rls_session.execute(
            AiUsageEvent.__table__.update().values(input_tokens=0)
        )
    rls_session.rollback()

    with pytest.raises(ProgrammingError):
        rls_session.execute(AiUsageEvent.__table__.delete())
    rls_session.rollback()


def test_one_organizations_spend_is_invisible_to_another(
    asker: Asker, spend_of, db_session: Session, rls_session: Session
) -> None:
    """A RLS é a segunda barreira, e aqui ela é a que responde.

    Se a soma vazasse entre tenants, o teto de uma organização seria consumido
    pelas perguntas de outra — e a recusa apareceria para quem não gastou.
    """

    spend_of(asker, 5_000_000, 0)

    # `rls_session` roda sob `portal_app` **sem** contexto ligado: sem GUC de
    # tenant, `portal.current_org()` é NULL e a policy devolve zero linhas. É a
    # regra "contexto ausente não é leitura ampla" (ADR 0010).
    visible = rls_session.execute(select(func.count()).select_from(AiUsageEvent)).scalar_one()

    assert visible == 0
