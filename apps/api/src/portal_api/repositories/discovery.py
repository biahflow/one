"""Discovery repositories (escopo de conta, ADR 0086).

As seis entidades do Discovery têm ``organization_id`` e **não têm**
``project_id`` — o Discovery é lido por Account no Pulse e chega em fan-out no
snapshot de todo projeto dela. ``TenantScopedRepository._tenant_filters()`` já
trata isso: ele só acrescenta o filtro de projeto quando o modelo tem a coluna, de
modo que o escopo aqui é a organização e nada precisa ser escrito para isso
acontecer.

Nascem para a busca (ADR 0087) e são a resposta ao que a ADR 0024 §2 recusou: sem
repositório, ``search.py`` teria de montar ``organization_id == ctx.organization_id``
por conta própria, e a primeira barreira passaria a existir em dois arquivos que
podem divergir sem nada ficar vermelho — a RLS continuaria certa e o teste de
isolamento, verde.

O caminho de **projeção do snapshot** (``integrations/biahflow._discovery_projection``)
continua com ``select()`` cru sob ``portal_system``, e isso não é incoerência: lá o
produtor roda com ``BYPASSRLS`` e escopa a consulta ele mesmo, aqui o consumidor
roda sob ``portal_app`` e o escopo é do repositório.
"""

from __future__ import annotations

from portal_api.models import (
    Finding,
    ImprovementOpportunity,
    PainPoint,
    Process,
    ProcessStep,
    SolutionHypothesis,
)
from portal_api.repositories.base import TenantScopedRepository


class ProcessRepository(TenantScopedRepository[Process]):
    model = Process


class ProcessStepRepository(TenantScopedRepository[ProcessStep]):
    model = ProcessStep


class FindingRepository(TenantScopedRepository[Finding]):
    model = Finding


class PainPointRepository(TenantScopedRepository[PainPoint]):
    model = PainPoint


class ImprovementOpportunityRepository(
    TenantScopedRepository[ImprovementOpportunity]
):
    model = ImprovementOpportunity


class SolutionHypothesisRepository(TenantScopedRepository[SolutionHypothesis]):
    model = SolutionHypothesis
