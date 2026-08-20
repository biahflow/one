"""Os espaços de nomes da âncora, num lugar só (ADR 0056, ADR 0057).

Folha pela razão de :mod:`portal_api.tabs` e :mod:`portal_api.textfold` serem
folhas, e pelo mesmo modo de falha: o mesmo literal aparece em lugares que **têm
de ser idênticos**, e uma divergência entre eles não deixa nada vermelho.

Nasceu em ``notifications.py`` na ADR 0056, quando os consumidores eram dois — o
mapa por espécie de aviso e o ``data-item`` do ``app/DashboardClient.tsx``. Mudou
de casa aqui na ADR 0057, e **nenhum valor mudou**: a busca virou o terceiro
consumidor, e a essa altura o vocabulário deixou de ser do aviso.

O que o namespace resolve é uma ambiguidade real e só uma: a "Visão geral"
hospeda **duas** listas — as fases da jornada e os entregáveis de cada fase —, e
um rótulo solto não diria qual delas. Ele é inglês porque é identificador de
código (`AGENTS.md`); o que vem depois do ``:`` é o rótulo em PT-BR que o cliente
lê, e o separador **não** tem escape de propósito: rótulos contêm dois-pontos, e
um esquema de escape seria o segundo vocabulário que a ADR 0024 recusou. Quem
consome compara a string inteira e nunca a divide.

O que aconteceria sem este módulo é específico e silencioso, e é o mesmo de
``tabs.py``: um namespace escrito de um jeito no aviso e de outro na busca faz o
cliente chegar na aba certa e **nada acontecer** — sem erro, sem log, sem teste
vermelho. ``test_item_anchor.py`` compara esta lista com os ``data-item`` do
componente e com as duas tabelas que a povoam.
"""

from __future__ import annotations

#: As duas listas da "Visão geral": a jornada e os entregáveis da fase.
ANCHOR_PHASE = "phase"
ANCHOR_DELIVERABLE = "deliverable"
ANCHOR_MILESTONE = "milestone"
ANCHOR_DOCUMENT = "document"
ANCHOR_MEETING = "meeting"
ANCHOR_PENDING = "pending"

#: Todo espaço de nomes que os dois deployables conhecem.
#:
#: Não é a união de ``ITEM_ANCHOR`` com ``HIT_ANCHOR`` calculada em tempo de
#: execução, e a diferença é o que se prova: aquela união é o que o código
#: **faz**, esta tupla é o que alguém **declarou**, e a guarda compara as duas
#: com os ``data-item`` do TSX. Um namespace novo entra aqui no mesmo commit em
#: que ganha escritor, ou a igualdade reprova.
ALL: tuple[str, ...] = (
    ANCHOR_PHASE,
    ANCHOR_DELIVERABLE,
    ANCHOR_MILESTONE,
    ANCHOR_DOCUMENT,
    ANCHOR_MEETING,
    ANCHOR_PENDING,
)
