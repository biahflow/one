"""Os rótulos das abas do portal, num lugar só (FDD 021, ADR 0043).

Folha pela razão de :mod:`portal_api.textfold` ser uma, e pelo mesmo modo de falha:
o mesmo literal aparece em três lugares que **têm de ser idênticos**, e uma
divergência entre eles não deixa nada vermelho.

Os três são a busca (``search.py``, desde a ADR 0024), o link do aviso
(``notifications.py``, desta fatia) e o ``navItems`` de ``app/DashboardClient.tsx``.
A tela navega **por rótulo** desde a Fase 2 — foi a decisão da busca, escrita lá:
mandar o rótulo pronto evita um segundo mapa do lado do navegador que envelheceria
sozinho. O preço é que o rótulo virou identificador, e identificador duplicado em
três arquivos é o que este módulo existe para impedir.

O que aconteceria sem isto é específico e silencioso: um rótulo trocado no
front-end faz o link do WhatsApp abrir o portal na **Visão geral** em vez da aba do
assunto. Ninguém recebe erro — o cliente recebe a mensagem, clica, e chega no lugar
errado. ``test_tabs.py`` compara esta lista com o ``navItems`` do componente.
"""

from __future__ import annotations

#: A aba inicial, e o destino de tudo o que não tem aba própria.
TAB_OVERVIEW = "Visão geral"
TAB_SCHEDULE = "Cronograma"
TAB_DOCUMENTS = "Documentos"
TAB_MEETINGS = "Reuniões"
TAB_PENDINGS = "Pendências"
TAB_RESULTS = "Resultados"

#: Na ordem em que a barra lateral as mostra, que é a ordem do ``navItems``.
ALL: tuple[str, ...] = (
    TAB_OVERVIEW,
    TAB_SCHEDULE,
    TAB_DOCUMENTS,
    TAB_MEETINGS,
    TAB_PENDINGS,
    TAB_RESULTS,
)
