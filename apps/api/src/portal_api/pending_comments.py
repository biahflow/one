"""O único lugar onde um comentário de pendência é escrito (ADR 0032).

Mesmo desenho de :mod:`portal_api.conversations` e :mod:`portal_api.notifications`,
e pela mesma razão declarada lá: se "quem grava o que o cliente digitou" estiver
espalhado, a pergunta deixa de ter resposta que se lê num arquivo.

Duas funções. :func:`add_comment` escreve; :func:`list_for_pending` lê. **Não há
função que edite nem apague**, e não é esquecimento — ``portal_app`` recebeu só
``INSERT`` na migração 0021, então o GRANT recusaria de qualquer forma.

O que separa este módulo do ``conversations.py`` é o escopo, e vale registrar por
quê: a conversa é de uma **pessoa** (a policy exige
``user_id = portal.current_user_id()``, e a ADR 0030 chegou a revogar privilégio
para manter isso), enquanto o comentário é do **projeto** — ele existe para ser
lido pelo outro lado. O critério é o mesmo nos dois casos: a quem o texto foi
endereçado.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from portal_api.models import PendingItem, PendingItemComment, User
from portal_api.repositories import TenantContext
from portal_api.repositories.pending_item import PendingItemRepository

#: Teto de comentários devolvidos numa listagem. Corte pelo **começo**, ao
#: contrário do histórico do chat: numa discussão sobre o que falta fazer, o que
#: importa é o fim do fio.
COMMENT_LIMIT = 200

#: Rótulo de quem escreveu e depois saiu do projeto. O texto fica; a procedência
#: também, porque `author_label` é denormalizado na escrita — isto cobre só a
#: linha antiga que nunca teve rótulo.
REMOVED_AUTHOR = "Participante removido"


def author_label(user: User) -> str:
    """Como o outro lado vê quem escreveu.

    O nome, e não o e-mail: a aba é do cliente e o e-mail de quem atende não é
    dado que o produto precise expor ali.
    """
    return user.full_name or REMOVED_AUTHOR


def add_comment(
    session: Session,
    ctx: TenantContext,
    *,
    pending_item_id: uuid.UUID,
    author: User,
    body: str,
) -> PendingItemComment | None:
    """Escreve o comentário, ou devolve ``None`` se a pendência não é alcançável.

    ``None`` e não exceção: quem chama traduz para 404, que é a negação padrão do
    portal. A checagem passa pelo repositório escopado, então uma pendência de
    outro projeto não é encontrada nem quando o id está correto — e a policy é a
    segunda barreira embaixo disso.
    """
    pending = PendingItemRepository(session, ctx).get(pending_item_id)
    if pending is None:
        return None

    comment = PendingItemComment(
        organization_id=ctx.organization_id,
        project_id=ctx.project_id,
        pending_item_id=pending.id,
        author_user_id=author.id,
        author_label=author_label(author),
        author_is_internal=bool(author.is_internal),
        body=body.strip(),
    )
    session.add(comment)
    session.flush()
    return comment


def list_for_pending(
    session: Session,
    ctx: TenantContext,
    pending_item_id: uuid.UUID,
    *,
    limit: int = COMMENT_LIMIT,
) -> list[PendingItemComment] | None:
    """O fio da pendência, do mais antigo para o mais novo.

    ``None`` quando a pendência não é alcançável, pela razão de
    :func:`add_comment` — e é o que faz a listagem de outro projeto ser 404 em vez
    de uma lista vazia, que diria "existe e está sem comentário".
    """
    if PendingItemRepository(session, ctx).get(pending_item_id) is None:
        return None

    rows = session.execute(
        select(PendingItemComment)
        .where(
            PendingItemComment.pending_item_id == pending_item_id,
            PendingItemComment.organization_id == ctx.organization_id,
            PendingItemComment.project_id == ctx.project_id,
        )
        .order_by(PendingItemComment.created_at, PendingItemComment.id)
        .limit(limit)
    ).scalars()
    return list(rows)


def counts_for_project(
    session: Session, project_id: uuid.UUID
) -> dict[uuid.UUID, int]:
    """Quantos comentários cada pendência do projeto tem.

    Uma consulta agregada e não um ``len()`` por linha: o dashboard projeta a
    lista inteira, e uma contagem por pendência seria N+1 numa tela que já é a
    mais pesada do produto.
    """
    rows = session.execute(
        select(
            PendingItemComment.pending_item_id,
            func.count(PendingItemComment.id),
        )
        .join(PendingItem, PendingItem.id == PendingItemComment.pending_item_id)
        .where(PendingItemComment.project_id == project_id)
        .group_by(PendingItemComment.pending_item_id)
    ).all()
    return {pending_id: total for pending_id, total in rows}
