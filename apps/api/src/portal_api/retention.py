"""O único lugar onde dado é apagado por prazo (Fase 5, ADR 0017).

Mesma forma de :mod:`portal_api.notifications` e :mod:`portal_api.conversations`,
e pelo mesmo motivo: se "o que o portal apaga, e quando" estiver espalhado, a
pergunta deixa de ter resposta que se leia num arquivo só. Aqui ela tem.

Duas operações, e elas não se confundem:

- **A poda** (:func:`purge_expired`) é por *idade*, roda sozinha no beat e nunca
  toca em documento. Um documento é a evidência que sustenta uma citação já dada;
  apagá-lo por aniversário tornaria uma resposta antiga impossível de conferir,
  o que é o avesso da regra 3 do `AGENTS.md`.
- **O expurgo** (:func:`run_erasure`) é por *decisão de alguém*, registrada numa
  linha, e aí sim leva tudo — inclusive os arquivos no storage.

Três invariantes valem para as duas, e são as mesmas que o ``drive_sync`` já
seguia. **Só se apaga o que a janela alcança**, nunca "tudo que não reconheço".
**Cada organização responde pela sua janela**, e a ausência de política é o
padrão do ``config.py``, não "guarda para sempre". E **em lotes**, porque um
acervo antigo não deve virar uma transação de horas segurando lock.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from portal_api.config import Settings
from portal_api.models import (
    AgentEvent,
    ContactEvent,
    Conversation,
    Document,
    Finding,
    ImprovementOpportunity,
    Membership,
    Notification,
    OnboardingStep,
    Organization,
    OrganizationRetentionPolicy,
    PainPoint,
    Process,
    Project,
    ValueLedgerEntry,
)

logger = logging.getLogger(__name__)


def now() -> datetime:
    """Indireção para o teste poder congelar o relógio, como no ``drive_sync``."""
    return datetime.now(timezone.utc)


@dataclass
class Windows:
    """Os prazos em vigor para uma organização, já resolvidos contra o padrão."""

    notification_days: int
    agent_event_days: int
    conversation_days: int
    onboarding_days: int


def windows_for(
    policy: OrganizationRetentionPolicy | None, settings: Settings
) -> Windows:
    """A política da organização, com o padrão preenchendo o que ela não diz.

    Coluna nula é "usa o padrão", e não "não apaga": um contrato que não fala de
    retenção não é um contrato de retenção infinita.
    """
    return Windows(
        notification_days=(
            policy.notification_days
            if policy is not None and policy.notification_days is not None
            else settings.retention_notification_days
        ),
        agent_event_days=(
            policy.agent_event_days
            if policy is not None and policy.agent_event_days is not None
            else settings.retention_agent_event_days
        ),
        onboarding_days=(
            policy.onboarding_days
            if policy is not None and policy.onboarding_days is not None
            else settings.retention_onboarding_days
        ),
        conversation_days=(
            policy.conversation_days
            if policy is not None and policy.conversation_days is not None
            else settings.retention_conversation_days
        ),
    )


@dataclass
class PurgeOutcome:
    organization_id: uuid.UUID
    removed: dict[str, int] = field(default_factory=dict)

    def as_stats(self) -> dict[str, int]:
        return dict(self.removed)


def _delete_batch(session: Session, model, *predicates, limit: int) -> int:
    """``DELETE`` limitado a um lote, pelo id.

    O ``DELETE ... LIMIT`` não existe no Postgres, então o lote é escolhido por um
    ``SELECT`` e apagado por ``IN``. Custa uma leitura a mais e é o que mantém a
    transação curta — o que sobra sai na passagem seguinte, e nenhuma passagem
    precisa terminar o trabalho para o trabalho estar correto.
    """
    ids = list(
        session.execute(select(model.id).where(*predicates).limit(limit)).scalars()
    )
    if not ids:
        return 0
    session.execute(delete(model).where(model.id.in_(ids)))
    return len(ids)


def purge_expired(
    session: Session, organization_id: uuid.UUID, settings: Settings
) -> PurgeOutcome:
    """Poda uma organização segundo a janela dela.

    Roda sob ``portal_system``: é o único papel que enxerga todas as
    organizações, e a poda não tem principal — ninguém pediu, o calendário pediu.
    """
    policy = session.execute(
        select(OrganizationRetentionPolicy).where(
            OrganizationRetentionPolicy.organization_id == organization_id
        )
    ).scalar_one_or_none()
    limits = windows_for(policy, settings)
    reference = now()
    batch = settings.retention_batch_size
    outcome = PurgeOutcome(organization_id=organization_id)

    outcome.removed["notification"] = _delete_batch(
        session,
        Notification,
        Notification.organization_id == organization_id,
        Notification.created_at < reference - timedelta(days=limits.notification_days),
        limit=batch,
    )
    # Pela janela **da notificação**, e não por uma própria (FDD 021, ADR 0042). O
    # contato registrado e o aviso são o mesmo fato visto de dois lados — um do lado
    # de dentro, outro do lado de fora —, e dar a cada um o seu relógio produziria a
    # divergência no primeiro que alguém editasse. A janela do teto é outra coisa e
    # é muito mais curta (`contact_window_days`): esta aqui decide por quanto tempo o
    # registro sobrevive, não por quanto tempo ele conta.
    outcome.removed["contact_event"] = _delete_batch(
        session,
        ContactEvent,
        ContactEvent.organization_id == organization_id,
        ContactEvent.created_at < reference - timedelta(days=limits.notification_days),
        limit=batch,
    )
    # Pelo `reached_at`, que é a data do **fato**, e não pelo `created_at` da linha: o degrau
    # do entregável chega pelo sync e pode ser carimbado depois de ter acontecido (ADR 0039).
    outcome.removed["onboarding_step"] = _delete_batch(
        session,
        OnboardingStep,
        OnboardingStep.organization_id == organization_id,
        OnboardingStep.reached_at < reference - timedelta(days=limits.onboarding_days),
        limit=batch,
    )
    # Pela data do fato, não pela da ingestão: um evento reenviado meses depois
    # descreve o dia em que aconteceu, e é esse dia que o ROI usa (ADR 0013).
    outcome.removed["agent_event"] = _delete_batch(
        session,
        AgentEvent,
        AgentEvent.organization_id == organization_id,
        AgentEvent.occurred_at < reference - timedelta(days=limits.agent_event_days),
        limit=batch,
    )
    # Por `last_message_at`, e **não** por `created_at` nem por `updated_at`.
    #
    # `created_at` apagaria o histórico debaixo de quem está usando: uma thread
    # aberta há um ano e respondida ontem é a conversa corrente de alguém.
    #
    # `updated_at` erra para o outro lado, e é o erro mais fácil de cometer. A
    # ADR 0015 separou as duas colunas justamente porque "marcar um feedback não
    # é conversar" — um polegar numa conversa morta mexe em `updated_at` e a
    # manteria viva para sempre. `last_message_at` é a coluna que significa o que
    # a poda precisa saber, e é a que `append_turn` mantém.
    #
    # As mensagens saem por CASCADE, que é como a ADR 0015 já as tinha amarrado.
    outcome.removed["conversation"] = _delete_batch(
        session,
        Conversation,
        Conversation.organization_id == organization_id,
        Conversation.last_message_at
        < reference - timedelta(days=limits.conversation_days),
        limit=batch,
    )
    return outcome


def organizations_with_data(session: Session) -> list[uuid.UUID]:
    """As organizações a visitar. Todas — a poda não tem por que adivinhar."""
    return list(session.execute(select(Organization.id)).scalars())


@dataclass
class ErasureOutcome:
    removed: dict[str, int] = field(default_factory=dict)
    storage_objects: int = 0


def storage_prefix(organization_id: uuid.UUID) -> str:
    """O prefixo que reúne todo objeto da organização.

    Existe porque ``storage.object_key`` o desenhou assim desde a ADR 0014 — "o
    prefixo permite uma política de retenção por organização na Fase 5" estava
    escrito lá antes de haver Fase 5.
    """
    return f"org/{organization_id}/"


def run_erasure(session: Session, organization_id: uuid.UUID) -> ErasureOutcome:
    """Apaga o conteúdo de uma organização. Não apaga a organização.

    A fronteira é deliberada e vale dizer por extenso:

    - **Sai** todo conteúdo de projeto — os ``project`` da organização e, por
      CASCADE, marcos, entregas, pendências, documentos, trechos, reuniões,
      decisões, eventos de agente, avisos, conversas, chaves de agente, conexão
      do Drive e as linhas de ``audit_log`` daquele projeto.
    - **Sai** a ``membership``, que é o que ligava pessoas a esta organização —
      inclusive a de escopo organizacional, que tem ``project_id`` nulo e por
      isso **não** vem no CASCADE do projeto.
    - **Sai** o ``onboarding_step`` (ADR 0039), pelo mesmo motivo e com uma armadilha
      a mais: ele é escopado por **organização**, e a linha ``organization`` fica —
      então o CASCADE não o alcança por nenhum caminho. Um funil que sobrevivesse ao
      apagamento do tenant reintroduziria exatamente o defeito que esta função fecha,
      e com o dado mais sensível que o portal guarda: comportamento de pessoa
      identificada.

    - **Sai** o ``contact_event`` (ADR 0042), pela regra abaixo e sem surpresa nenhuma:
      ele nasceu depois de a regra existir e foi escrito já contando com ela. É o dado
      da mesma classe que o funil — quantas vezes falamos com esta pessoa, e quando.

    - **Sai** o ``value_ledger_entry`` (ADR 0085), pela mesma regra e com a mesma
      armadilha do funil: ele é escopado por **Engagement**, e a linha ``engagement``
      fica de pé — o CASCADE do projeto não chega nele por caminho nenhum. O que
      sobreviveria é quantia, período e o **método de atribuição em prosa da origem**,
      que é dado do cliente por definição.

    - **Sai** o Discovery da conta (ADR 0086): ``improvement_opportunity``,
      ``pain_point``, ``finding`` e ``process``, nesta ordem — as duas tabelas de
      ligação, as etapas e as hipóteses de solução saem por CASCADE dos pais, e por
      isso não têm linha própria aqui. É a mesma armadilha das três acima e a mais
      cara delas: o Discovery é escopado por **organização** e descreve como a
      empresa do cliente trabalha por dentro — processos, gargalos, quem faz o quê e
      quanto tempo leva. Nada disso vem no CASCADE do projeto.

      São as **cinco** exclusões escritas à mão (quatro tabelas na última, uma só
      chamada de decisão), e a regra que as une é essa: o que é escopado por
      organização não vem no CASCADE do projeto. Toda tabela nova com
      ``organization_id`` e sem ``project_id`` precisa de uma linha aqui.

      O ``kpi`` **não** entra: ele é escopado por projeto e sai no CASCADE, como
      ``milestone`` e ``digital_employee``.
    - **Fica** a linha ``organization``, porque ela é a âncora do tenant e o
      próximo snapshot do Biahflow a recriaria de qualquer forma — apagá-la só
      levaria junto o registro do próprio expurgo, que é o que torna o
      apagamento auditável.
    - **Fica** a linha ``user``. A identidade é do realm, não do portal, e uma
      pessoa pode pertencer a mais de uma organização; apagar a conta por causa
      de um tenant tiraria acesso a outro. O vínculo é que se desfaz.

    Os objetos do storage são removidos pelo chamador, que tem o ``Settings`` —
    aqui só se decide o que sai do banco.
    """
    outcome = ErasureOutcome()
    # Contado antes: depois do DELETE não há o que contar, e o número é o que o
    # pedido guarda para alguém poder conferir o que aconteceu.
    outcome.removed["document"] = int(
        session.execute(
            select(func.count(Document.id)).where(
                Document.organization_id == organization_id
            )
        ).scalar_one()
    )
    # Um `DELETE` só para a árvore do projeto, e o resto vem por CASCADE: as
    # chaves estrangeiras já a descrevem, e reescrevê-la aqui criaria uma segunda
    # descrição para divergir da primeira no próximo modelo que alguém adicionar.
    result = session.execute(
        delete(Project).where(Project.organization_id == organization_id)
    )
    outcome.removed["project"] = int(result.rowcount or 0)

    membership = session.execute(
        delete(Membership).where(Membership.organization_id == organization_id)
    )
    outcome.removed["membership"] = int(membership.rowcount or 0)

    funnel = session.execute(
        delete(OnboardingStep).where(OnboardingStep.organization_id == organization_id)
    )
    outcome.removed["onboarding_step"] = int(funnel.rowcount or 0)

    contacts = session.execute(
        delete(ContactEvent).where(ContactEvent.organization_id == organization_id)
    )
    outcome.removed["contact_event"] = int(contacts.rowcount or 0)

    # O razão do mandato (ADR 0085): escopado por Engagement, e o `engagement` fica —
    # então nem o CASCADE do projeto nem o da organização o alcançam. Ver o docstring.
    ledger = session.execute(
        delete(ValueLedgerEntry).where(
            ValueLedgerEntry.organization_id == organization_id
        )
    )
    outcome.removed["value_ledger_entry"] = int(ledger.rowcount or 0)

    # O Discovery da conta (ADR 0086), em ordem de chave estrangeira. As ligações, as
    # etapas e as hipóteses saem por CASCADE dos pais — apagá-las à mão seria a
    # segunda descrição da árvore que o `DELETE` do projeto acima recusa fazer.
    for model in (ImprovementOpportunity, PainPoint, Finding, Process):
        removed = session.execute(
            delete(model).where(model.organization_id == organization_id)
        )
        outcome.removed[model.__tablename__] = int(removed.rowcount or 0)
    return outcome
