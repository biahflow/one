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
#: Onde o cliente aprova a entrega ou pede ajuste (FDD 027, ADR 0077). Vizinha de
#: ``TAB_PENDINGS`` de propósito: são as duas abas em que a bola está com ele, e
#: as duas carregam contador de "aguardando você" na barra lateral.
TAB_REVIEW = "Revisão"
TAB_PENDINGS = "Pendências"
TAB_DECISIONS = "Decisões"
TAB_RESULTS = "Resultados"
#: O AS-IS, os achados, as dores e o backlog de melhoria da conta (ADR 0086).
#:
#: **O rótulo fica em inglês, e é o único da barra que fica** — não é descuido nem
#: incoerência com as oito abas em português. A §1 do Language Map é normativa e
#: explícita: *"termos canônicos em inglês nas quatro superfícies… não se traduz o
#: termo, traduz-se o texto em volta dele"*, e a §2 escreve **Discovery** na coluna
#: "O One (o cliente vê)". "Descoberta" seria traduzir um termo canônico, que é o
#: erro que aquela seção nomeia com um exemplo ("A Conta tem três Compromissos").
#:
#: As outras oito não passam por isso porque nenhuma delas nomeia um termo do mapa:
#: "Cronograma", "Documentos" e "Pendências" são áreas da tela, não entidades da
#: ontologia. O precedente do rótulo em inglês na tela já existe e é o Engagement
#: (ADR 0079), que o topo mostra sem traduzir.
TAB_DISCOVERY = "Discovery"

#: Na ordem em que a barra lateral as mostra, que é a ordem do ``navItems``.
ALL: tuple[str, ...] = (
    TAB_OVERVIEW,
    TAB_SCHEDULE,
    TAB_DOCUMENTS,
    TAB_MEETINGS,
    TAB_REVIEW,
    TAB_PENDINGS,
    TAB_DECISIONS,
    TAB_RESULTS,
    TAB_DISCOVERY,
)
