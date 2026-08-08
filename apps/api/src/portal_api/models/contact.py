"""Cada contato que **saiu** do portal para uma pessoa (Fase 7, FDD 021 e FDD 022).

O teto de frequência é a primitiva que as duas features pediam pelo nome e nenhuma
das duas podia hospedar: a FDD 021 escreve *"teto de frequência por pessoa,
compartilhado com os demais avisos **e com a pesquisa da FDD 022**"*, e a FDD 022
repete a frase do outro lado. Um teto que mora dentro de um dos dois consumidores
não é compartilhado — é o teto daquele consumidor com um nome maior.

**Razão, e não contador.** A escolha é a mesma que a ADR 0022 fez para a conta de
IA, contra o precedente do ``chat_rate_window``, e o argumento de lá vale aqui
literalmente: um contador incrementado **subconta** sob concorrência. No chat isso
é aceitável — subcontar deixa passar uma pergunta a mais num limite de abuso. Aqui
subcontar deixa passar **uma mensagem a mais para uma pessoa**, que é exatamente o
dano que o teto existe para impedir, e num canal que a FDD 021 descreve como "o
mais fácil de queimar". Um ``INSERT`` por contato não disputa; a soma é um
``COUNT``.

O preço da razão está declarado e pago: ela é registro de comportamento de pessoa
identificada — o dado mais sensível que o portal guarda, na classificação que a
FDD 020 estabeleceu —, então carrega ``organization_id``, tem policy na mesma
migração, é podada por idade e é alcançada pelo apagamento por decisão. Um contador
de três colunas escaparia dessas quatro obrigações por não guardar histórico
nenhum, e é essa a troca.

**Sem coluna de data própria.** O funil tem ``reached_at`` separado do
``created_at`` porque lá quem carimba pode não ser quem observou — o degrau do
Biahflow chega retroativo. Aqui não existe contato retroativo: a linha nasce no
instante do envio, e uma segunda coluna significando o mesmo que ``created_at``
seria uma que pode divergir dela.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TenantMixin, TimestampMixin


class ContactKind(str, enum.Enum):
    """As espécies de contato que gastam o teto.

    **Só entra espécie que tem produtor**, e a regra vem de duas cicatrizes deste
    repositório: a ADR 0033 achou um painel publicado sobre um campo que nunca teve
    escritor, e a ADR 0039 manteve ``artifact_accepted`` **fora** do enum do funil
    justamente por isso — com a condição escrita, *"ele entra quando o outro lado o
    afirmar"*, que foi cumprida na ADR 0041.

    Aqui a condição é a mesma e vale para ``survey_invite``: o convite de pesquisa
    da FDD 022 **não** está neste enum porque aquela FDD ainda não tem escritor, e
    ela própria está bloqueada até o laço de ação do funil fechar. Ele entra no dia
    em que a pesquisa passar a enviar convite — e entra com uma regra a mais, que a
    emenda daquela FDD registra: o teto global **não** satisfaz sozinho o critério
    de aceite (2) de lá, porque "um segundo evento na mesma semana não gera segundo
    convite" é uma afirmação sobre *aquela espécie*, e não sobre o volume total.
    """

    #: O aviso 1:1 por WhatsApp (FDD 021). O produtor é a task do worker.
    whatsapp_notice = "whatsapp_notice"


class ContactEvent(Base, TenantMixin, TimestampMixin):
    """Um contato que saiu, com a pessoa, a espécie e a organização a que se refere.

    **O sino nunca entra aqui.** O teto vale para o que sai do portal — a mensagem
    no canal externo, o convite de pesquisa. Suprimir o sino esconderia do cliente
    um fato que é dele, e é justamente a premissa em que a FDD 021 apoia o canal:
    *"a falha do provedor não perde o aviso, porque a notificação já existe no
    portal"*. Um teto que alcançasse o sino tornaria essa frase falsa.
    """

    __tablename__ = "contact_event"
    __table_args__ = (
        # A mesma forma de ``uq_notification_user_dedupe_key``, e pelo mesmo motivo
        # com uma consequência a mais: aqui ela não serve só para não duplicar a
        # linha, serve para uma **reentrega** não gastar uma segunda unidade do
        # teto. Sem ela, uma task reenfileirada depois de o provedor cair acharia o
        # orçamento já gasto por ela mesma e o aviso sumiria do canal para sempre.
        UniqueConstraint("user_id", "dedupe_key", name="uq_contact_event_user_dedupe_key"),
        # A consulta do teto é sempre "esta pessoa, desta data para cá".
        Index("ix_contact_event_user_created", "user_id", "created_at"),
    )

    #: A quem o contato foi. ``CASCADE`` e não ``SET NULL``, ao contrário do funil:
    #: lá a linha continua significando alguma coisa sem a pessoa (o degrau foi
    #: alcançado), e aqui uma linha sem destinatário não conta para orçamento
    #: nenhum — seria lixo que a poda ainda teria de visitar.
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ContactKind] = mapped_column(
        Enum(ContactKind, name="contact_kind", native_enum=True), nullable=False
    )
    #: O que este contato é, de forma estável entre tentativas. Para o aviso é o
    #: ``dedupe_key`` da própria notificação, que a ADR 0012 já desenhou estável.
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
