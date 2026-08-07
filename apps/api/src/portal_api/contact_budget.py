"""Quantos contatos esta pessoa já recebeu, e se cabe mais um (FDD 021, FDD 022).

Módulo próprio pela razão de :mod:`portal_api.notifications`,
:mod:`portal_api.conversations` e :mod:`portal_api.retention`: se "quanto o portal
pode falar com uma pessoa" estiver espalhado pelos canais que falam, a pergunta
deixa de caber num arquivo — e é justamente a pergunta de quem calibra o teto.

**Fatia própria, antes do primeiro consumidor**, na disciplina que a ADR 0033
deixou: escritor primeiro, leitor depois. O canal da FDD 021 é quem vem gastar
daqui, e a pesquisa da FDD 022 divide o mesmo orçamento — a frase *"teto de
frequência por pessoa, **compartilhado** com os demais avisos"* está escrita nas
duas, e um teto que morasse dentro de uma delas não seria compartilhado.

**O orçamento é da pessoa, e é um só.** Não há teto por canal somando-se a outro:
quem recebe três mensagens recebeu três mensagens, e de quem foi a cota é problema
do portal, não dele. Um canal de abertura quase total é o mais fácil de queimar.

**Nada aqui é engolido em silêncio**, ao contrário de :func:`portal_api.onboarding.stamp`.
Lá o silêncio é declarado porque medir engajamento não pode derrubar o que o cliente
veio fazer — o carimbo é um efeito colateral de outra coisa. Aqui o chamador **é** o
remetente, e uma exceção que sobe simplesmente não envia: o desfecho seguro já é o
automático, então não há o que engolir. O aviso continua no sino de qualquer forma,
que é a premissa em que a FDD 021 apoia o canal inteiro.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from portal_api import retention
from portal_api.config import Settings
from portal_api.models import ContactEvent, ContactKind

logger = logging.getLogger(__name__)


def claim(
    session: Session,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    kind: ContactKind,
    dedupe_key: str,
    settings: Settings,
) -> bool:
    """Reserva uma unidade do orçamento desta pessoa. ``False`` significa **não envie**.

    Decide **e** registra, numa chamada só. Separar em "posso?" e "gastei" criaria a
    fresta em que um chamador pergunta e esquece de gastar — e o teto passaria a
    depender de todo remetente futuro lembrar do segundo passo. É a mesma razão pela
    qual ``notifications.fan_out`` insere em vez de devolver uma lista para alguém
    inserir.

    ``session`` tem de ser de ``portal_system``: a policy da 0028 nega a tabela para
    o papel de requisição e para o de administração, por escrito.

    ``dedupe_key`` identifica **o contato**, não a pessoa, e é o que faz uma
    reentrega não custar uma segunda unidade. Sem ele, uma task reenfileirada depois
    de o provedor cair encontraria o orçamento gasto por ela mesma e o aviso sumiria
    do canal para sempre — trocando uma falha temporária do fornecedor por um
    silêncio permanente. Para o aviso da FDD 021 ele é o ``dedupe_key`` da própria
    notificação, que a ADR 0012 já desenhou estável entre passagens do sync.
    """
    now = retention.now()

    # Já reivindicado é **reentrega**, não segundo contato — e por isso passa sem
    # olhar o teto: o orçamento já foi debitado na primeira vez.
    already = session.execute(
        select(ContactEvent.id).where(
            ContactEvent.user_id == user_id,
            ContactEvent.dedupe_key == dedupe_key,
        )
    ).first()
    if already is not None:
        return True

    spent = session.execute(
        select(func.count(ContactEvent.id)).where(
            ContactEvent.user_id == user_id,
            ContactEvent.created_at >= now - timedelta(days=settings.contact_window_days),
        )
    ).scalar_one()

    if spent >= settings.contact_cap_per_window:
        # Sem ``user_id``: comportamento de pessoa identificada é dado sensível e o
        # log não é o lugar dele — a mesma regra que ``onboarding.stamp`` segue ao
        # registrar só o tenant e o nome do degrau. Quem precisa da pessoa tem a
        # linha, onde a poda e o apagamento a alcançam.
        logger.info(
            "contact.suppressed",
            extra={
                "organization_id": str(organization_id),
                "kind": kind.value,
                "reason": "window_cap",
                "cap": settings.contact_cap_per_window,
            },
        )
        return False

    session.execute(
        pg_insert(ContactEvent.__table__)
        .values(
            id=uuid.uuid4(),
            organization_id=organization_id,
            user_id=user_id,
            kind=kind.value,
            dedupe_key=dedupe_key,
            # Explícito, e não o ``server_default``: é o relógio que
            # ``retention.now()`` congela, o mesmo que a contagem acima usou. Com o
            # ``now()`` do Postgres, o teste que precisa pôr um contato oito dias
            # atrás não teria como.
            created_at=now,
            updated_at=now,
        )
        # ``DO NOTHING`` e **sem** ``RETURNING``: aqui, ao contrário do carimbo do
        # funil, "a linha nasceu agora?" não muda nada. Perder a corrida para outra
        # passagem que reivindicou o **mesmo** contato é a reentrega do primeiro ramo
        # chegando por outro caminho, e a resposta é a mesma nos dois casos — pode
        # enviar, e o orçamento foi debitado uma vez só. Foi por precisar dessa
        # distinção que a ADR 0039 teve de trocar ``rowcount`` por ``RETURNING``;
        # não precisar dela é o que dispensa os dois aqui.
        .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
    )
    return True
