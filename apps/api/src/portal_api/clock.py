"""O fuso do produto, e o dia e a hora que ele produz, num lugar só.

Módulo folha — depende só da biblioteca padrão — pela razão de :mod:`portal_api.textfold`
e :mod:`portal_api.anchors` serem folha: o mesmo literal em dois arquivos diverge sem
nada ficar vermelho. Antes desta fatia, ``PRODUCT_TIMEZONE`` vivia só em
``integrations/whatsapp.py``, e ``integrations/biahflow.py`` decidia "marco atrasado"
com ``date.today()`` — a data da máquina, que no contêiner é UTC e adianta o corte em
até três horas em relação ao dia de São Paulo. As duas perguntas ("que dia é hoje",
"que hora é agora") passam a ter uma resposta só, aqui.

Funções puras, momento por parâmetro — na forma de ``within_quiet_hours``,
``results.py`` e ``audit.evaluate``: quem decide o relógio é quem chama, nunca o
módulo.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

#: O fuso do produto, e ele é **constante** (ADR 0026). Fuso por organização ou por
#: pessoa foi decidido contra: não há coluna, não há rota, e a tela já formata toda
#: data nesta zona. Um segundo lugar respondendo "que horas são para esta pessoa"
#: divergiria do primeiro no dia em que alguém editasse um só — que é o argumento
#: do ``textfold.py``.
PRODUCT_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def product_hour(moment: datetime) -> int:
    """A hora do relógio de São Paulo no instante ``moment`` (que é *aware* em UTC)."""
    return moment.astimezone(PRODUCT_TIMEZONE).hour


def product_date(moment: datetime) -> date:
    """O dia do calendário de São Paulo no instante ``moment`` (que é *aware* em UTC)."""
    return moment.astimezone(PRODUCT_TIMEZONE).date()
