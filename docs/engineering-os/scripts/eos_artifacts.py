"""Leitura dos artefatos que os contratos desta camada definem.

Um artefato aqui é Markdown escrito por um executor, não JSON emitido por uma ferramenta.
O que estes checkers conferem é **forma declarada**: campo presente, valor dentro do
enum, seção que existe. O que eles não conseguem conferir está escrito, em cada checker,
na lista de condições não verificáveis — um checker que desse verde sugerindo ter
conferido tudo seria o mesmo falso verde que ele existe para impedir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Finding:
    """Um problema num artefato, com o suficiente para alguém consertar sem perguntar."""

    path: Path
    line: int
    message: str

    def render(self, root: Path | None = None) -> str:
        where = self.path
        if root is not None:
            try:
                where = self.path.relative_to(root)
            except ValueError:
                pass
        return f"{where}:{self.line}: {self.message}"


@dataclass
class Document:
    path: Path
    text: str
    lines: list[str] = field(default_factory=list)

    @classmethod
    def read(cls, path: Path) -> Document:
        text = path.read_text(encoding="utf-8")
        return cls(path=path, text=text, lines=text.splitlines())

    def line_of(self, needle: str) -> int:
        """A primeira linha que contém `needle`, 1-based; 0 quando não há."""
        for number, line in enumerate(self.lines, 1):
            if needle in line:
                return number
        return 0

    def headings(self) -> dict[str, int]:
        """Títulos ATX normalizados para minúsculas, mapeados para a linha onde abrem."""
        found: dict[str, int] = {}
        for number, line in enumerate(self.lines, 1):
            match = re.match(r"^#{1,6}\s+(.*?)\s*$", line)
            if match:
                found.setdefault(match.group(1).strip().lower(), number)
        return found

    def section_body(self, opened: int) -> list[str]:
        """As linhas sob um título, até o próximo título de nível igual ou superior.

        Parar no primeiro título de qualquer nível esvaziaria toda seção que abre com
        uma subseção — e foi o que este método fez até um pacote de evidência real, com
        `### Desvio de plano` logo abaixo de `## 8.`, ser lido como seção vazia.
        """
        opening = re.match(r"^(#{1,6})\s+", self.lines[opened - 1] if opened else "")
        level = len(opening.group(1)) if opening else 6
        body: list[str] = []
        for line in self.lines[opened:]:
            deeper = re.match(r"^(#{1,6})\s+", line)
            if deeper and len(deeper.group(1)) <= level:
                break
            body.append(line)
        return body

    def section_is_empty(self, opened: int) -> bool:
        """Verdadeiro quando a seção só tem branco, ou só o marcador do template."""
        content = [line.strip() for line in self.section_body(opened) if line.strip()]
        if not content:
            return True
        joined = " ".join(content)
        return bool(PLACEHOLDER.fullmatch(joined))

    def has_heading(self, *candidates: str) -> int:
        """A linha do primeiro título que casa por prefixo, 0 quando nenhum casa."""
        headings = self.headings()
        for candidate in candidates:
            needle = candidate.lower()
            for heading, number in headings.items():
                if heading == needle or heading.startswith(needle):
                    return number
        return 0


#: `Campo: valor` numa linha, com o valor podendo ser vazio — é o vazio que interessa,
#: porque o contrato manda escrever `none` e não deixar em branco.
#:
#: Aceita `Files changed` e `feature_id`: os contratos usam as duas formas, e uma primeira
#: versão exigindo inicial maiúscula não casava nenhum campo `snake_case` — dava "campo
#: ausente" em artefato que declarava o campo, que é falso vermelho, o irmão do falso verde.
FIELD = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _/-]*?)\s*:\s*(.*?)\s*$")

#: Marcadores de template que sobreviveram à cópia. Um contrato entregue com
#: `<value>` no lugar do valor é um contrato que ninguém preencheu.
PLACEHOLDER = re.compile(r"<[a-z][a-z0-9 _/|-]*>", re.IGNORECASE)


def first_token(value: str) -> str:
    """O primeiro token de um valor, que é onde o enum mora.

    Um contrato real escreve `COMMIT: forbidden — a entrega é o diff na árvore mais o
    BUILD REPORT`. O valor do enum é `forbidden`; o resto é a explicação, e exigir
    igualdade exata reprovaria o contrato por ter explicado a si mesmo.
    """
    return value.split()[0].strip(".,;:") if value.split() else ""


def fields_in(block: list[str]) -> dict[str, tuple[str, int]]:
    """Os pares `Campo: valor` de um bloco, com a linha relativa de cada um.

    O valor pode ser **multi-linha**, e é assim que os relatórios reais são escritos:

        Files changed:
          - apps/web/src/route.ts — a porta de entrada ganha representação…
          - apps/web/src/App.tsx — …

    Uma linha mais indentada que a do campo é continuação dele. Ler só a linha do campo
    daria "em branco" num relatório que listou dez arquivos — falso vermelho, e foi o que
    uma primeira versão deste módulo fez contra os BUILD REPORTs de uma feature real.
    """
    found: dict[str, tuple[str, int]] = {}
    for offset, line in enumerate(block):
        match = FIELD.match(line)
        if not match:
            continue
        name, value = match.group(1), match.group(2)
        if name in found:
            continue
        indent = len(line) - len(line.lstrip())
        continuation: list[str] = []
        for following in block[offset + 1 :]:
            if not following.strip():
                continue
            if len(following) - len(following.lstrip()) <= indent:
                break
            continuation.append(following.strip())
        found[name] = (" ".join([value, *continuation]).strip(), offset)
    return found


def fenced_blocks(document: Document, language: str = "text") -> list[tuple[int, list[str]]]:
    """Os blocos cercados da linguagem pedida, como (linha de abertura, conteúdo)."""
    blocks: list[tuple[int, list[str]]] = []
    opened: int | None = None
    body: list[str] = []
    for number, line in enumerate(document.lines, 1):
        stripped = line.strip()
        if opened is None and stripped.startswith("```"):
            if stripped[3:].strip() in ("", language):
                opened, body = number, []
            else:
                opened, body = -number, []
            continue
        if opened is not None and stripped.startswith("```"):
            if opened > 0:
                blocks.append((opened, body))
            opened, body = None, []
            continue
        if opened is not None:
            body.append(line)
    return blocks
