"""O único lugar onde um degrau do funil é carimbado (Fase 7, RFC 001, ADR 0039).

Mesma forma de :mod:`portal_api.notifications`, :mod:`portal_api.conversations` e
:mod:`portal_api.retention`, e pelo mesmo motivo: se "o que conta como degrau" estiver
espalhado pelos seis caminhos que o produzem, a pergunta que a RFC 001 quer responder —
*quanto o cliente demora do ganho até o primeiro valor* — deixa de caber num arquivo, e é
justamente essa a pergunta de quem for calibrar o alerta depois.

Uma função que escreve e nenhuma que edite, e isso não é omissão: o carimbo é **imutável**
por desenho (``UniqueConstraint`` + ``ON CONFLICT DO NOTHING``), e a migração 0024 não dá
GRANT de ``UPDATE`` a ninguém. Primeira vez é primeira vez.

**Roda sob ``portal_system``, em transação própria**, no precedente do ``chat_limit.consume``.
Os degraus nascem em rotas que rodam sob ``portal_app``, e o papel de requisição não tem
policy nesta tabela — porque um caminho de requisição capaz de escrever o próprio degrau é um
caminho capaz de falsear o próprio engajamento.

**Falha em silêncio**, e é decisão declarada: medir engajamento não pode derrubar o que o
cliente veio fazer. Um degrau perdido é um dado a menos numa métrica de tendência; uma exceção
propagada seria um download que não acontece ou um dashboard que não abre.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert

from portal_api.db.session import DbRole, get_session
from portal_api.models import OnboardingStep, OnboardingStepName

logger = logging.getLogger(__name__)


def stamp(
    organization_id: uuid.UUID,
    step: OnboardingStepName,
    *,
    user_id: uuid.UUID | None = None,
    reached_at: datetime | None = None,
) -> bool:
    """Carimba a **primeira** ocorrência de ``step`` nesta organização.

    Devolve ``True`` só quando a linha nasceu agora — é o que distingue "aconteceu pela
    primeira vez" de "acontece toda vez", e é por isso que o log sai apenas no primeiro.
    Sem isso, o evento viraria uma linha por download e por pergunta, que é ruído com nome
    de sinal.

    ``reached_at`` existe para o degrau que **não** nasce agora: o do entregável chega pelo
    sync, e a data que interessa é a do fato afirmado pelo Biahflow, não a da linha.
    """
    now = reached_at or datetime.now(timezone.utc)
    try:
        with get_session(role=DbRole.system) as session:
            result = session.execute(
                pg_insert(OnboardingStep.__table__)
                .values(
                    id=uuid.uuid4(),
                    organization_id=organization_id,
                    step=step.value,
                    reached_at=now,
                    user_id=user_id,
                )
                .on_conflict_do_nothing(index_elements=["organization_id", "step"])
                # `RETURNING`, e **não** `rowcount`: medido, o driver devolve `-1` para
                # `ON CONFLICT DO NOTHING` nos dois casos, e `bool(-1)` é `True` — de modo
                # que todo carimbo se declararia "primeira vez" e o evento sairia a cada
                # download. Com `DO NOTHING`, `RETURNING` não devolve linha quando pula, que
                # é a única resposta confiável à pergunta "nasceu agora?".
                .returning(OnboardingStep.__table__.c.id)
            )
            created = result.first() is not None
    except Exception:  # noqa: BLE001 - ver o docstring do módulo: falha em silêncio
        # `exception` e não `warning`: o traceback é a única forma de descobrir por que o
        # funil parou de encher, e ninguém vai reparar na falta de uma linha.
        logger.exception(
            "onboarding.stamp_failed",
            # `getattr` e não `step.value`: o caminho de erro não pode ter erro próprio —
            # um `step` inesperado faria a linha de log estourar dentro do `except` e
            # ressuscitaria a exceção que este bloco existe para engolir.
            extra={
                "organization_id": str(organization_id),
                "step": getattr(step, "value", str(step)),
            },
        )
        return False

    if created:
        # Sem conteúdo: só o tenant e o nome do degrau. Comportamento de pessoa
        # identificada é dado sensível, e o log não é o lugar dele — o `user_id` fica na
        # linha, onde a retenção e o apagamento o alcançam.
        logger.info(
            "onboarding.step_reached",
            extra={"organization_id": str(organization_id), "step": step.value},
        )
    return created
