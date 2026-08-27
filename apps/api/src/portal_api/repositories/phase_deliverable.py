"""Phase deliverable repository (project-scoped)."""

from __future__ import annotations

from portal_api.models import PhaseDeliverable
from portal_api.repositories.base import TenantScopedRepository


class PhaseDeliverableRepository(TenantScopedRepository[PhaseDeliverable]):
    model = PhaseDeliverable

    def by_external_ref(self, external_ref: str) -> PhaseDeliverable | None:
        """O entregável que a origem chama assim, ou ``None``.

        Passa por ``matching()`` e não por um ``select`` montado no chamador pelo
        motivo que a busca já registrou (ADR 0024): o filtro de tenant fica aqui
        dentro, senão a primeira barreira estaria reimplementada em outro arquivo
        e uma divergência entre as duas não deixaria nada vermelho — a RLS
        continuaria certa e o teste de isolamento, verde.

        ``external_ref`` vem do caminho da URL, isto é, é o "identificador
        fornecido pelo cliente" da regra 1 do ``AGENTS.md``: não alcançar a linha
        é a resposta certa para um id de outro projeto, e quem chama traduz para
        404.
        """
        found = self.matching(
            PhaseDeliverable.external_ref == external_ref,
            order_by=(PhaseDeliverable.position, PhaseDeliverable.created_at),
            limit=1,
        )
        return found[0] if found else None
