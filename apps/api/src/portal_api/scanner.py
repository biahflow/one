"""Varredura do arquivo antes de ele virar texto (Fase 5, ADR 0017).

`docs/security.md` promete "varredura antimalware **antes de indexar**" desde a
Fase 1, e `docs/threat-model.md` repete na linha "Upload malicioso". Este módulo
é onde a promessa passa a existir.

Mesma forma de :mod:`portal_api.ai.embeddings` e :mod:`portal_api.ai.responder`:
adapter real quando há serviço configurado, caminho determinístico quando não há.
Mas a analogia para aqui, e a diferença é a decisão central deste arquivo.

**Um scanner ausente não devolve "limpo".** O embedder offline é uma resposta
pior à mesma pergunta; um antivírus offline seria uma resposta *inventada* a uma
pergunta que ninguém fez — exatamente o que a regra 3 do `AGENTS.md` proíbe do
assistente, e não há motivo para o portal se permitir em segurança o que proíbe
na IA. Por isso o veredito tem três estados e não dois: ``clean`` é "alguém
capaz olhou e não achou nada", ``skipped`` é "ninguém que pudesse afirmar isso
olhou". Quem lê o estado sabe a diferença.

O que o caminho sem ClamAV faz é reconhecer o **EICAR** — a cadeia de teste
padrão da indústria, inofensiva por construção, que existe precisamente para
provar que a varredura está ligada. É o suficiente para o CI e o e2e exercitarem
a rejeição sem antivírus e sem rede, do mesmo jeito que o ``drive-stub`` prova o
conector sem credencial do Google. Não é um antivírus, e não se apresenta como
um: fora do EICAR ele responde ``skipped``, que é a verdade.

Transporte falado direto no socket, sem SDK, como o adapter do Drive: o INSTREAM
do clamd são três linhas de enquadramento, e uma dependência a mais custaria mais
do que elas.
"""

from __future__ import annotations

import logging
import socket
import struct
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from portal_api.config import Settings

logger = logging.getLogger(__name__)


class ScanState(str, Enum):
    """O que se sabe sobre o arquivo — não o que se torce para que ele seja.

    Espelha ``document.scan_state``. É enum próprio e não um valor a mais em
    ``DocumentIngestState`` porque as perguntas são diferentes: "este arquivo é
    seguro" e "este arquivo virou texto citável" podem ter respostas opostas no
    mesmo documento, e juntá-las tornaria uma revarredura — assinatura nova sobre
    arquivo antigo — inexprimível.
    """

    pending = "pending"
    clean = "clean"
    infected = "infected"
    #: Não havia scanner capaz de responder. Deliberadamente diferente de
    #: ``clean``: ver o docstring do módulo.
    skipped = "skipped"
    #: Havia scanner e ele não respondeu (fora do ar, arquivo grande demais para
    #: o limite do daemon, protocolo inesperado). Nunca vira ``clean``.
    error = "error"


@dataclass(frozen=True)
class ScanVerdict:
    state: ScanState
    #: Nome da assinatura, quando houve uma. É o que a tela de administração
    #: mostra — e é seguro mostrar, porque nomeia o malware, não o conteúdo.
    signature: str = ""
    #: Motivo, para ``error``. Só a mensagem, nunca trecho do arquivo
    #: (`docs/data-classification.md`).
    detail: str = ""


class Scanner(Protocol):
    @property
    def name(self) -> str: ...

    def scan(self, data: bytes) -> ScanVerdict: ...


# A cadeia EICAR, montada em pedaços de propósito.
#
# Escrita inteira e literal, ela faria todo antivírus de verdade acusar este
# arquivo-fonte — o checkout do desenvolvedor, o runner do CI, o layer da
# imagem. A cadeia só é reconhecida contígua, então montá-la em tempo de import
# mantém o repositório varrível e o teste honesto: o que o scanner compara é a
# cadeia real, não uma abreviação dela.
_EICAR = (
    "X5O!P%@AP[4\\PZX54(P^)7CC)7}$"
    "EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
    "!$H+H*"
).encode("ascii")


class OfflineScanner:
    """Reconhece o EICAR, e nada além disso — e diz que é isso que faz."""

    @property
    def name(self) -> str:
        return "offline-eicar-v1"

    def scan(self, data: bytes) -> ScanVerdict:
        if _EICAR in data:
            return ScanVerdict(ScanState.infected, signature="Eicar-Test-Signature")
        return ScanVerdict(
            ScanState.skipped,
            detail="Nenhum antivírus configurado (CLAMAV_HOST vazio)",
        )


class ClamavScanner:
    """INSTREAM do clamd sobre TCP.

    O protocolo: ``zINSTREAM\\0``, depois o arquivo em blocos precedidos do
    tamanho em 4 bytes big-endian, depois um tamanho zero para fechar. A resposta
    é uma linha — ``stream: OK``, ``stream: <assinatura> FOUND`` ou algo com
    ``ERROR``.

    Toda falha de transporte vira ``error`` e nunca ``clean``: um daemon fora do
    ar não é um arquivo limpo, e tratar os dois igual anularia a barreira
    exatamente no dia em que ela é mais necessária.
    """

    #: 32 KiB por bloco. O clamd aceita mais, mas o ganho some rápido e blocos
    #: grandes só aumentam o pico de memória do worker.
    _CHUNK = 32 * 1024

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

    @property
    def name(self) -> str:
        return f"clamav:{self._host}:{self._port}"

    def scan(self, data: bytes) -> ScanVerdict:
        try:
            response = self._instream(data)
        except OSError as exc:
            # Nome estável, e aqui isso não é estilo: esta linha é o **único**
            # sinal de que o antivírus caiu, e até a ADR 0034 o `alerts.md`
            # mandava vigiar `scan_state=skipped` para descobrir isso — um
            # estado que este objeto nunca produz (ver o docstring do módulo).
            logger.warning(
                "document.scan_unavailable",
                extra={"host": self._host, "port": self._port, "detail": str(exc)},
            )
            return ScanVerdict(ScanState.error, detail=f"clamd indisponível: {exc}")

        if response.endswith("OK"):
            return ScanVerdict(ScanState.clean)
        if response.endswith("FOUND"):
            # "stream: Eicar-Test-Signature FOUND" → o nome no meio.
            signature = response.rsplit(" ", 1)[0].split(":", 1)[-1].strip()
            return ScanVerdict(ScanState.infected, signature=signature or "desconhecida")
        # Inclui o "INSTREAM size limit exceeded" do clamd, que é o caso comum de
        # um arquivo maior que o `StreamMaxLength` do daemon.
        return ScanVerdict(ScanState.error, detail=response or "resposta vazia do clamd")

    def _instream(self, data: bytes) -> str:
        with socket.create_connection((self._host, self._port), timeout=self._timeout) as sock:
            sock.settimeout(self._timeout)
            sock.sendall(b"zINSTREAM\0")
            for start in range(0, len(data), self._CHUNK):
                block = data[start : start + self._CHUNK]
                sock.sendall(struct.pack("!I", len(block)) + block)
            sock.sendall(struct.pack("!I", 0))

            received = bytearray()
            while b"\0" not in received:
                block = sock.recv(4096)
                if not block:
                    break
                received.extend(block)
        return bytes(received).split(b"\0", 1)[0].decode("utf-8", "replace").strip()


def get_scanner(settings: Settings) -> Scanner:
    if settings.clamav_host:
        return ClamavScanner(
            settings.clamav_host, settings.clamav_port, settings.clamav_timeout_seconds
        )
    return OfflineScanner()
