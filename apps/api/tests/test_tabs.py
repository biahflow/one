"""O rótulo da aba é identificador, e ele mora em dois deployables (ADR 0043).

Guarda no formato do ``test_telemetry.py``: lê o outro lado do repositório e compara.
Existe porque a alternativa é uma divergência **silenciosa** — o link do aviso vai
para uma aba que o front-end não reconhece, o `useState` cai na visão geral, e o
cliente que clicou na mensagem chega no lugar errado sem erro nenhum em lugar
nenhum.

É o mesmo argumento que fez o ``textfold.py`` existir: a expressão precisa ser
idêntica em três lugares ou o índice deixa de ser usado sem nada ficar vermelho.
Aqui o terceiro lugar é a busca, que importa de :mod:`portal_api.tabs` desde esta
fatia — então o Python já é uma fonte só, e o que sobra a conferir é a fronteira
com o TypeScript.
"""

from __future__ import annotations

import re
from pathlib import Path

from portal_api import notifications, tabs
from portal_api.models import NotificationKind

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DASHBOARD = _REPO_ROOT / "app" / "DashboardClient.tsx"

#: `const navItems = [ { label: "…" }, … ]`, que é a declaração que a barra lateral
#: usa e a mesma que o `switch` de `activeNav` casa.
_NAV_BLOCK = re.compile(r"const navItems = \[(.*?)\];", re.DOTALL)
_LABEL = re.compile(r'label:\s*"([^"]+)"')


def _nav_labels() -> list[str]:
    block = _NAV_BLOCK.search(_DASHBOARD.read_text(encoding="utf-8"))
    assert block is not None, "não achei `const navItems` em app/DashboardClient.tsx"
    return _LABEL.findall(block.group(1))


def test_the_python_labels_are_exactly_the_navigation_ones() -> None:
    """Mesmos rótulos e **mesma ordem**.

    A ordem entra na asserção de propósito: ela é a da barra lateral, e uma
    divergência de ordem é o sintoma barato de alguém ter acrescentado uma aba de
    um lado só — que é exatamente o caso que produz o link quebrado.
    """
    assert list(tabs.ALL) == _nav_labels()


def test_every_link_points_at_a_tab_that_exists() -> None:
    """Nenhuma entrada do ``LINK_TAB`` aponta para uma aba que a tela não tem."""
    unknown = sorted(
        {tab for tab in notifications.LINK_TAB.values() if tab not in tabs.ALL}
    )
    assert unknown == [], f"abas inexistentes no LINK_TAB: {unknown}"


def test_every_client_notice_knows_which_screen_it_opens() -> None:
    """Toda espécie que o cliente recebe tem link — senão ela não sai pelo canal.

    Esta é a guarda que a FDD 021 pediu sem saber: o critério de aceite (4) exige
    que o aviso caia "na coisa exata, nunca na home", e o remetente cumpre isso
    **calando-se** quando não há link. Sem esta asserção, uma espécie nova sem
    entrada no ``LINK_TAB`` sairia do sino para o canal e simplesmente não sairia —
    com um `whatsapp.skipped_without_link` que ninguém procura.

    A audiência é o critério, não a espécie: quem é ``_INTERNAL_ONLY`` não abre aba
    de cliente. O ``onboarding_stuck`` traz `/admin/funil` por conta própria, e o
    ``whatsapp_reply`` aponta para as pendências, onde o time responde.
    """
    client_kinds = {
        kind
        for kind in NotificationKind
        if notifications.AUDIENCE.get(kind, notifications._CLIENT_ONLY)
        != notifications._INTERNAL_ONLY
    }
    without_link = sorted(
        kind.value for kind in client_kinds if kind not in notifications.LINK_TAB
    )
    assert without_link == [], (
        "estas espécies chegam ao cliente e não sabem que tela abrem: "
        + ", ".join(without_link)
        + ". Acrescente uma linha em `notifications.LINK_TAB` — sem ela o aviso"
        " fica só no sino e o canal se cala."
    )
