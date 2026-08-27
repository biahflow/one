"""O único lugar onde o aceite de um entregável é escrito (ADR 0077).

Mesmo desenho de :mod:`portal_api.pending_comments`, de
:mod:`portal_api.conversations` e de :mod:`portal_api.notifications`, e pela
mesma razão declarada lá: se "quem grava a decisão do cliente" estiver
espalhado, a pergunta deixa de ter resposta que se lê num arquivo — e aqui ela é
a pergunta cara, porque **este registro é a fonte da verdade do aceite** e o
retorno ao Pulse é uma projeção dele, nunca o contrário.

Duas funções. :func:`record_acceptance` escreve; :func:`list_for_deliverable`
lê. **Não há função que edite nem apague**, e não é esquecimento: ``portal_app``
recebeu ``SELECT, INSERT`` na migração 0035 e nada mais, então o GRANT recusaria
de qualquer forma. Uma segunda decisão **acrescenta** uma linha; a anterior fica
superada na leitura — nunca reescrita.

**O vínculo é o ``external_ref``, não o uuid do read model.**
``integrations/biahflow.sync_snapshot`` apaga e recria ``phase_deliverable`` a
cada webhook, de modo que uma chave estrangeira daqui para lá seria destruída no
sync seguinte, levando junto a decisão do cliente. O ``external_ref`` chega pelo
caminho da URL, o que faz dele o "identificador fornecido pelo cliente" da regra
1 do ``AGENTS.md``: a validação do vínculo é o repositório escopado, e a policy é
a segunda barreira embaixo dele.

**O que este módulo não faz.** Ele não conclui a entrega: ``accepted`` autoriza o
outro lado a transicionar para ``ACCEPTED``, e só o lifecycle de Delivery declara
``DONE`` (ADR 0067). E ele não devolve nada ao Pulse — o mecanismo do retorno é
decisão em aberto (ADR 0077 §Aberto), e o desenho é justamente que o evento não
espere por ela.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from portal_api.models import (
    DeliverableAcceptance,
    DeliverableAcceptanceAction,
    ProjectPhase,
    User,
)
from portal_api.repositories import PhaseDeliverableRepository, TenantContext

#: Teto de decisões devolvidas numa listagem. Corte pelo **começo**, como no fio
#: da pendência: o histórico de aceite de um entregável tem unidades de linhas, e
#: o que importa é a decisão em vigor, que é a última.
ACCEPTANCE_LIMIT = 200

#: Rótulo de quem decidiu e depois saiu do projeto. A decisão fica; a
#: procedência também, porque ``actor_label`` é denormalizado na escrita — isto
#: cobre só a linha que nunca teve rótulo.
REMOVED_ACTOR = "Participante removido"


def actor_label(user: User) -> str:
    """Como o outro lado vê quem decidiu.

    O nome, e não o e-mail, pelo argumento de :func:`pending_comments.author_label`:
    o registro é projetado para fora e o e-mail de quem decidiu não é dado que o
    produto precise expor ali.
    """
    return user.full_name or REMOVED_ACTOR


def record_acceptance(
    session: Session,
    ctx: TenantContext,
    *,
    deliverable_external_ref: str,
    actor: User,
    action: DeliverableAcceptanceAction,
    comment: str | None = None,
) -> DeliverableAcceptance | None:
    """Grava a decisão, ou devolve ``None`` se o entregável não é alcançável.

    ``None`` e não exceção: quem chama traduz para 404, que é a negação padrão do
    portal. A checagem passa pelo repositório escopado, então um entregável de
    outro projeto não é encontrado nem quando o ``external_ref`` está correto.

    O nome da fase e o do entregável são copiados **agora**, no momento da
    decisão: o sync recria essas linhas e pode deixar de trazê-las, e um registro
    que não diz sobre o quê alguém decidiu não serve ao outro lado nem ao
    cliente.
    """
    deliverable = PhaseDeliverableRepository(session, ctx).by_external_ref(
        deliverable_external_ref
    )
    if deliverable is None:
        return None

    phase = session.get(ProjectPhase, deliverable.phase_id)
    decision = DeliverableAcceptance(
        organization_id=ctx.organization_id,
        project_id=ctx.project_id,
        deliverable_external_ref=deliverable_external_ref,
        phase_name=phase.name if phase is not None else "",
        deliverable_name=deliverable.name,
        action=action,
        actor_user_id=actor.id,
        actor_label=actor_label(actor),
        actor_is_internal=bool(actor.is_internal),
        comment=(comment or "").strip() or None,
    )
    session.add(decision)
    session.flush()
    return decision


def list_for_deliverable(
    session: Session,
    ctx: TenantContext,
    deliverable_external_ref: str,
    *,
    limit: int = ACCEPTANCE_LIMIT,
) -> list[DeliverableAcceptance] | None:
    """O histórico do entregável, do mais antigo para o mais novo.

    ``None`` quando o entregável não é alcançável, pela razão de
    :func:`record_acceptance` — e é o que faz a listagem de outro projeto ser 404
    em vez de uma lista vazia, que diria "existe e ninguém decidiu".

    A ordem é a da escrita porque é o que torna a supersessão legível sem coluna
    nenhuma: a última linha é a decisão em vigor, e as anteriores continuam lá
    para dizer o que foi decidido antes.
    """
    if PhaseDeliverableRepository(session, ctx).by_external_ref(
        deliverable_external_ref
    ) is None:
        return None

    rows = session.execute(
        select(DeliverableAcceptance)
        .where(
            DeliverableAcceptance.deliverable_external_ref == deliverable_external_ref,
            DeliverableAcceptance.organization_id == ctx.organization_id,
            DeliverableAcceptance.project_id == ctx.project_id,
        )
        .order_by(DeliverableAcceptance.created_at, DeliverableAcceptance.id)
        .limit(limit)
    ).scalars()
    return list(rows)

