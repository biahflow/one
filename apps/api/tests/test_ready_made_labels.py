"""Os rótulos que a API manda prontos são os que a tela desenha (ADR 0087).

A busca resolve **na API** o que o cliente lê: o `tab` desde a ADR 0024, o
`item_anchor` desde a ADR 0057, e agora dois rótulos de conteúdo — o estado
epistêmico de um achado e o estado de uma reunião. A razão é sempre a mesma, e está
escrita na ADR 0024: *um segundo mapa do lado do navegador envelheceria sozinho*.

O preço também é sempre o mesmo, e é o do ``textfold.py``: o mesmo literal em dois
deployables que **têm de ser idênticos**, com a divergência não deixando nada
vermelho. Este arquivo é o portão dos dois, e é um só pela razão de o ``alerts.md``
ter uma guarda só — duas guardas sobre a mesma afirmação divergem.

Arquivo próprio e **não** extensão do ``test_tabs.py``, pela razão que o
``test_item_anchor.py`` já escreveu: aquele tem docstring específico sobre o rótulo
da **aba**, e a pergunta daqui é outra. A técnica é a mesma — ler o outro lado do
repositório e comparar.

## O que cada asserção segura

- **epistêmico, paridade**: a §3 do Language Map diz que uma hipótese aparece
  *rotulada* como hipótese ou não aparece, nunca como fato. Mapas divergentes fariam
  o mesmo achado sair "Hipótese" na aba e outra coisa na busca.
- **epistêmico, completude**: um estado do enum sem linha no mapa. É ela que permite
  ao produtor indexar direto — num ``.get(..., "")`` o esquecimento **apagaria** o
  rótulo, que é a leitura de fato por omissão.
- **epistêmico, produtor**: o rótulo é o ``detail`` do ``Hit``, não um campo que a
  tela poderia ignorar.
- **reunião, paridade**: o defeito anterior que a fatia achou. A busca mandava
  ``held``/``scheduled`` cru enquanto a aba escreve "Realizada"/"Agendada" — o mesmo
  valor com dois nomes conforme a porta por onde o cliente chega.
- **reunião, queda**: os dois lados caem para o **código cru** no estado que a tabela
  não conhece. É a metade da paridade que uma comparação de mapas não pega, e é a
  que importa quando a origem acrescenta vocabulário.
"""

from __future__ import annotations

import re
from pathlib import Path

from portal_api import search
from portal_api.models import EpistemicStatus

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DASHBOARD = _REPO_ROOT / "app" / "DashboardClient.tsx"
_PAGE = _REPO_ROOT / "app" / "page.tsx"

_ENTRY = re.compile(r'(\w+):\s*"([^"]+)"')


def _screen_map(path: Path, name: str) -> dict[str, str]:
    """O ``Record<string, string>`` chamado ``name`` naquele arquivo do BFF.

    Um casador para os dois mapas, e não dois: eles têm a mesma forma, e duas
    expressões regulares para a mesma coisa é a duplicação que este arquivo existe
    para cobrar dos outros.
    """
    source = path.read_text(encoding="utf-8")
    block = re.search(rf"const {name}:[^=]*=\s*\{{(.*?)\}};", source, re.DOTALL)
    assert block is not None, (
        f"não achei `const {name}` em {path.name}. Se ele mudou de nome ou de forma, "
        "esta guarda parou de olhar para o outro lado — decida, não conserte o "
        "casador para o vermelho sumir."
    )
    return dict(_ENTRY.findall(block.group(1)))


def test_the_python_epistemic_labels_are_the_ones_the_discovery_tab_draws() -> None:
    """Mesmas chaves e mesmos rótulos, nos dois deployables.

    A comparação é de dicionário inteiro e não de conjunto de valores: trocar
    ``hypothesis`` por ``unknown`` de um lado só produziria os mesmos três textos com
    o significado invertido — a hipótese saindo como "Pergunta em aberto" e a lacuna
    como "Hipótese" —, que é a pior forma desta falha e a que um conjunto não pega.
    """
    published = {status.value: label for status, label in search.EPISTEMIC_LABEL.items()}

    assert published == _screen_map(_DASHBOARD, "EPISTEMIC_LABEL"), (
        "o rótulo epistêmico divergiu entre a API e a tela. A busca manda o rótulo "
        "pronto no `detail` (ADR 0087) e a aba Discovery o desenha no `StatePill`: os "
        "dois mapas são o mesmo vocabulário, e um valor trocado de um lado só faz o "
        "mesmo achado ter dois nomes sem nada ficar vermelho."
    )


def test_every_epistemic_state_has_a_label_to_be_read_by() -> None:
    """Nenhum estado do enum chega ao cliente sem palavra.

    O enum é a §4 do Language Map (D6) e tem três membros — e ``unknown`` atravessa
    de propósito, porque um levantamento que só mostrasse o que ficou sabido
    esconderia do cliente o que ainda não se sabe. Um quarto estado sem linha no mapa
    reprova aqui, e é isso que permite ao produtor do rótulo indexar direto em vez de
    cair num `.get()` que apagaria a palavra.
    """
    missing = sorted(
        status.value for status in EpistemicStatus if status not in search.EPISTEMIC_LABEL
    )
    assert missing == [], (
        f"estes estados epistêmicos não têm rótulo: {', '.join(missing)}. Acrescente "
        "a linha em `search.EPISTEMIC_LABEL` **e** no `EPISTEMIC_LABEL` de "
        "`app/DashboardClient.tsx` — sem ela o achado chega ao cliente sem dizer se é "
        "fato, hipótese ou pergunta em aberto, que é a leitura de fato por omissão."
    )


def test_no_finding_hit_is_built_without_the_label() -> None:
    """E o rótulo é o ``detail`` do hit, não um campo que a tela poderia ignorar.

    A construção é o elo: o ``Hit`` de ``finding`` sai de um lugar só, e o que a tela
    renderiza abaixo do título é ``[location, detail]``. Um ``detail=""`` ali passaria
    por todas as outras guardas — a âncora estaria certa, o namespace declarado, a aba
    correta — e entregaria a afirmação crua, que é o defeito que a ADR 0086 existe
    para impedir reaparecendo por uma porta que ela não olhou.
    """
    source = Path(search.__file__).read_text(encoding="utf-8")
    block = re.search(r'Hit\(\s*kind="finding",(.*?)\)', source, re.DOTALL)
    assert block is not None, "a busca deixou de construir `Hit(kind=\"finding\", …)`"

    assert "detail=EPISTEMIC_LABEL[" in block.group(1), (
        "o resultado de busca de um achado deixou de carregar o estado epistêmico no "
        "`detail`. Sem ele a busca entrega o `statement` cru — uma afirmação sem "
        "rótulo, que é como o cliente lê um fato."
    )


def test_the_python_meeting_labels_are_the_ones_the_meetings_tab_draws() -> None:
    """O defeito anterior que esta fatia achou, virado portão.

    A busca mandava ``detail=meeting.status`` — ``held``, ``scheduled`` — e a aba
    Reuniões desenha "Realizada" e "Agendada", traduzidas pelo BFF em
    ``app/page.tsx``. **O mesmo valor com dois nomes**, conforme a porta por onde o
    cliente chega, e nenhum teste ficava vermelho: é a ADR 0033 numa direção que
    ninguém tinha olhado — não um painel sobre campo sem escritor, e sim dois
    escritores discordando sobre a mesma palavra.

    O mapa da API é lido do TSX e não digitado aqui, pela razão de sempre: uma lista
    escrita à mão dentro da guarda a faria comparar o Python com ela mesma.
    """
    assert search.MEETING_STATUS_LABEL == _screen_map(_PAGE, "MEETING_STATUS_LABELS"), (
        "o rótulo de estado de reunião divergiu entre a API e o BFF. A busca manda o "
        "rótulo pronto no `detail` e a aba Reuniões o desenha a partir do mesmo "
        "vocabulário: um valor trocado de um lado só devolve a mesma reunião com dois "
        "nomes, conforme a porta por onde o cliente chegou."
    )


def test_an_unknown_meeting_status_falls_back_to_the_raw_code_on_both_sides() -> None:
    """A metade da paridade que a comparação de mapas não alcança.

    ``Meeting.status`` é ``String`` por decisão escrita no modelo — *"para que uma
    nova opção lá não exija migração de enum aqui"* —, então não há domínio fechado a
    enumerar e nenhuma guarda de completude é possível. O que resta é as duas portas
    **caírem igual**: o BFF faz ``MEETING_STATUS_LABELS[s] ?? s``, e a busca precisa
    fazer o mesmo, senão a fatia trocaria "dois nomes para o mesmo valor" por "um
    nome e um vazio", que é a mesma classe de defeito com outra cara.

    A queda é para o código cru e **nunca** para vazio: sumir com o valor esconderia
    do cliente que a origem passou a dizer algo que este lado ainda não sabe ler.
    """
    assert search._meeting_label("held") == "Realizada"
    assert search._meeting_label("scheduled") == "Agendada"
    assert search._meeting_label("cancelled") == "cancelled"
    assert search._meeting_label(None) == ""
    assert search._meeting_label("") == ""

    # E o BFF cai do mesmo jeito, afirmado sobre a linha dele: o `??` é o que torna a
    # asserção acima uma afirmação sobre **as duas** portas, e não só sobre uma.
    page = _PAGE.read_text(encoding="utf-8")
    assert re.search(
        r"MEETING_STATUS_LABELS\[meeting\.status\]\s*\?\?\s*meeting\.status", page
    ), (
        "o BFF deixou de cair para o código cru no estado que a tabela não conhece. "
        "Se a queda mudou de lado, ela muda nos dois — senão a mesma reunião volta a "
        "ter duas leituras conforme a porta."
    )
