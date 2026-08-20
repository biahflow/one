"""A regra 4 do `AGENTS.md`, que era a única sem portão (ADR 0066).

*"Migrações são aditivas e revisadas; alterações de tenant, autenticação, RAG ou
retenção exigem ADR/RFC."* — `AGENTS.md`, princípio 4.

A ADR 0035 derivou guarda para as regras 1, 2, 3, 5 e 6 e deixou esta de fora com o
argumento escrito: *"'Migrações são aditivas' não é verificável por `alembic check` —
nada impede um `op.drop_column` dentro de um `upgrade()` — e 'exige ADR/RFC' é
julgamento."*

**Metade daquele argumento se refuta com medição, e é o que este arquivo entrega.** O
`alembic check` de fato não vê: ele compara modelos com migrações e um `drop_column`
declarado nos dois lados passa verde. O **AST** vê. E "exige ADR/RFC" deixa de ser
julgamento quando o gatilho é estrutural: uma migração que executa `CREATE POLICY`,
`GRANT` ou `ENABLE ROW LEVEL SECURITY` está mexendo em tenancy **por construção**, não
por opinião — é o mesmo sinal que dispensou allowlist em (f) da ADR 0065, onde o
primeiro segmento de um hostname `run.app` é um serviço por construção da própria URL.

**As duas asserções nascem verdes, e isso está escrito aqui em vez de escondido.** A
medição, sobre as 30 migrações do disco em 20/08/2026:

- `upgrade()` com `op.drop_table`/`op.drop_column`: **zero**;
- `upgrade()` com SQL destrutivo de dado: **zero**;
- `downgrade()` com `drop_*`: **23 arquivos** — por definição, e é isso que obriga o
  escopo do predicado a ser a **função** e não o arquivo;
- migrações que tocam policy/`GRANT`/RLS: **15**; que citam ADR ou RFC: **15 de 15**;
- citações penduradas: **nenhuma**.

Verde de nascença não prova nada (ADR 0033), então o que prova aqui é a mutação, e a
ADR 0066 traz a saída literal de cada uma. As mutações que têm de ficar **verdes**
provam mais que as vermelhas: o `0013_drive_connector.py` recria um enum no
`upgrade()` com `DROP DEFAULT` e `DROP TYPE …_old`, e é essa amostra que separa esta
guarda de uma versão ingênua que reprovasse todo `DROP`.

**O que fica de fora, declarado.** A regra 4 nomeia quatro áreas, e só duas delas —
tenant e autenticação — têm sinal estrutural no SQL. RAG e retenção não: cobrá-las
exigiria uma lista de nomes de tabela escrita à mão, que é o defeito da ADR 0033 e o
que estas guardas existem para não repetir. É a mesma assimetria declarada de (d) na
ADR 0064 e da direção pendurada de (f) na ADR 0065 — o portão cobre o que consegue
computar, e diz o que não cobre.

Nenhuma asserção precisa de banco: são sobre arquivos, ao contrário de
`test_migration.py`, que é de integração. Os auxiliares recebem `text: str` e nunca
`Path`, no precedente do `test_roadmap_index.py`, que é o que permite medi-los contra
um recorte ou contra um caso construído sem tocar no working tree.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from test_roadmap_index import _accepted, _adrs, _read_adrs

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS = REPO_ROOT / "apps" / "api" / "src" / "portal_api" / "db" / "migrations" / "versions"
VERSIONS_GLOB = "[0-9]*.py"
RFC_DIR = REPO_ROOT / "docs" / "rfc"
RFC_GLOB = "[0-9][0-9][0-9]-*.md"

#: Os métodos do Alembic que apagam dado. `drop_index`, `drop_constraint` e
#: `alter_column` **não** entram: mudam regime, não linhas — um índice se recria e a
#: tabela continua lá. O casamento é pelo **nome do atributo** e não pelo receptor,
#: de modo que o `batch_op.drop_column` de um `batch_alter_table` cai aqui igual ao
#: `op.drop_column`; perguntar por `op.` deixaria a forma menos usada de fora, que é
#: a definição de casador frouxo.
_DESTRUCTIVE_CALLS = {"drop_table", "drop_column"}

#: E o mesmo em SQL cru, porque `op.execute` é a porta pela qual metade das
#: migrações deste repositório fala com o Postgres. Só o que destrói **dado**:
#: `DROP POLICY`, `DROP TYPE` e `DROP DEFAULT` ficam de fora de propósito, e a
#: amostra que fixa essa fronteira é o `0013_drive_connector.py`, que recria o enum
#: `document_origin` no `upgrade()` sem perder uma linha sequer.
_DESTRUCTIVE_SQL = re.compile(r"\bDROP\s+(?:TABLE|COLUMN)\b|\bTRUNCATE\b", re.IGNORECASE)

#: O gatilho de "isto é mudança de tenant ou de autenticação", e ele é estrutural:
#: policy, RLS e privilégio são as três formas de o Postgres dizer *quem alcança
#: qual linha*. É a segunda barreira da ADR 0010 sendo escrita ou reescrita, e o
#: `AGENTS.md` pede decisão registrada para isso.
_TENANCY_SQL = re.compile(
    r"\b(?:CREATE|ALTER|DROP)\s+POLICY\b|\bROW\s+LEVEL\s+SECURITY\b|\bGRANT\b|\bREVOKE\b",
    re.IGNORECASE,
)

#: A citação da decisão, nas formas que as migrações de fato usam (`ADR 0010`,
#: `ADR-0010`, `RFC 001`). Procurada no arquivo **inteiro**, comentários e docstring
#: incluídos, porque é lá que ela mora — o corpo executável não é lugar de citar
#: decisão.
#:
#: **Larguras diferentes, e não é descuido:** ADR tem quatro dígitos e RFC tem três,
#: que é como este repositório os numera. Um casador único de três a quatro dígitos
#: leria `RFC 7231` — o HTTP — como decisão daqui e reprovaria por ela não existir,
#: transformando uma referência normativa correta em vermelho.
_ADR_CITATION = re.compile(r"\bADR[\s-]?(\d{4})\b")
_RFC_CITATION = re.compile(r"\bRFC[\s-]?(\d{3})\b")

#: **Sem ocupante hoje, e a meta é que continue.** Uma migração que precise apagar
#: dado entra aqui com o motivo em prosa e **sem prazo**, no precedente do
#: `PINNED_BY_EXCEPTION` (ADR 0063) e não no do `advisories.json` (ADR 0023):
#: migração aplicada não caduca por calendário — o que vence a linha é
#: `test_the_additive_allowlist_does_not_keep_a_line_that_stopped_being_needed`,
#: que reprova quando o arquivo some ou deixa de ser destrutivo.
#:
#: A chave é o **nome do arquivo** da migração, que é imutável depois de aplicada
#: (a regra 4 diz "aditivas e revisadas", e o guardrail global proíbe mexer em
#: migração já aplicada fora do ambiente local).
ADDITIVE_BY_EXCEPTION: dict[str, str] = {}


# --- os auxiliares puros ----------------------------------------------------
#
# Todos recebem `text: str`. Nenhum abre arquivo: é o que permite medi-los contra
# um caso construído, que é como as mutações da ADR 0066 foram feitas.


def _docstring_lines(tree: ast.AST) -> set[int]:
    """As linhas ocupadas por docstring, em qualquer nível.

    Existe porque o predicado lê literais de string, e a prosa deste repositório
    fala de `DROP` e de `GRANT` o tempo todo — o docstring do `0007_rls_tenant_context`
    explica as policies que ele cria. Contar a explicação como se fosse a operação
    faria a guarda acusar exatamente quem documentou bem, que é o inverso do que ela
    existe para incentivar.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if not node.body or not isinstance(node.body[0], ast.Expr):
            continue
        first = node.body[0].value
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


def _sql_literals(node: ast.AST, skip: set[int]) -> list[tuple[int, str]]:
    """Todo literal de string sob um nó, menos os que são docstring."""
    return [
        (child.lineno, child.value)
        for child in ast.walk(node)
        if isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and child.lineno not in skip
    ]


def destructive_upgrades(text: str) -> list[str]:
    """O que a função `upgrade()` apaga, e **só** ela.

    O escopo é a função porque `downgrade()` é destrutivo por definição: 23 das 30
    migrações do disco derrubam ali o que criaram acima, e um predicado de arquivo
    inteiro acusaria as 23 — nasceria vermelho sobre o comportamento correto, que é
    a forma de guarda que se desliga na primeira semana. É a mesma lição do "corpus
    de um predicado é o bloco em que ele vale" da ADR 0065, onde uma fence de
    `gcloud` herdava o escopo de outra.
    """
    tree = ast.parse(text)
    skip = _docstring_lines(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "upgrade":
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in _DESTRUCTIVE_CALLS
            ):
                found.append(f"linha {child.lineno}: `{child.func.attr}`")
        for line, sql in _sql_literals(node, skip):
            match = _DESTRUCTIVE_SQL.search(sql)
            if match:
                found.append(f"linha {line}: SQL `{match.group(0).upper()}`")
    return found


def touches_tenancy(text: str) -> bool:
    """A migração escreve ou reescreve quem alcança qual linha.

    Lê literais do módulo inteiro, e não só do `upgrade()`: várias migrações montam
    o SQL em constante de módulo ou em auxiliar próprio, e perguntar apenas dentro
    de `upgrade()` deixaria essas de fora — aqui o predicado só decide *se* a
    decisão precisa estar citada, então abranger mais é fail-closed e não custa
    falso-positivo caro.
    """
    tree = ast.parse(text)
    skip = _docstring_lines(tree)
    return any(_TENANCY_SQL.search(sql) for _, sql in _sql_literals(tree, skip))


def citations(text: str) -> set[tuple[str, int]]:
    """As decisões que a migração cita, como `("ADR", 10)`."""
    found = {("ADR", int(number)) for number in _ADR_CITATION.findall(text)}
    return found | {("RFC", int(number)) for number in _RFC_CITATION.findall(text)}


# --- as bordas impuras ------------------------------------------------------


def _migrations() -> dict[str, str]:
    """As migrações do repositório, e **glob vazio reprova**.

    Fail-closed pelo argumento da ADR 0064: um corpus que mudou de lugar deixaria a
    guarda verde por não ter olhado, que é a forma do `dependency-review` da ADR
    0023.
    """
    paths = sorted(path for path in VERSIONS.glob(VERSIONS_GLOB) if path.is_file())
    assert paths, (
        f"o glob `{VERSIONS_GLOB}` em `{VERSIONS.relative_to(REPO_ROOT)}` não "
        "devolveu nenhuma migração. Ou o diretório mudou de lugar e esta guarda "
        "parou de olhar o repositório, ou as migrações sumiram — nos dois casos o "
        "verde deixaria de significar que a regra 4 foi conferida (ADR 0066)."
    )
    return {path.name: path.read_text(encoding="utf-8") for path in paths}


def _decisions_on_disk() -> set[tuple[str, int]]:
    """As decisões que existem e valem: ADR não recusada por escrito, e RFC.

    Reusa `_adrs`/`_accepted` do `test_roadmap_index.py` em vez de reler o
    diretório, pelo motivo que aquele arquivo já registrou: duas leituras do mesmo
    corpus divergem sobre o que conta como aceita, e a divergência não deixa nada
    vermelho.
    """
    accepted = {("ADR", number) for number in _accepted(_adrs(_read_adrs()))}
    rfcs = {("RFC", int(path.name[:3])) for path in RFC_DIR.glob(RFC_GLOB)}
    return accepted | rfcs


def test_every_migration_is_additive() -> None:
    """A primeira metade da regra 4, e o `alembic check` não a vê.

    Aquele gate compara modelos com migrações: apagar a coluna nos dois lados passa
    verde nele. O que reprova aqui é a operação, não a deriva.

    **Nasce verde** — zero achados nas 30 migrações —, e por isso o que a sustenta é
    a mutação: `op.drop_column` num `upgrade()` acusa, o mesmo `drop_column` movido
    para `downgrade()` fica verde, e o `DROP TYPE`/`DROP DEFAULT` do
    `0013_drive_connector.py` fica verde. A saída literal das três está na ADR 0066.
    """
    destructive: list[str] = []
    for name, text in _migrations().items():
        if name in ADDITIVE_BY_EXCEPTION:
            continue
        destructive += [f"{name} {where}" for where in destructive_upgrades(text)]

    assert destructive == [], (
        "estas migrações apagam dado no `upgrade()`: "
        + "; ".join(destructive)
        + ". A regra 4 do `AGENTS.md` diz que migrações são aditivas: quem aplicou "
        "a anterior não recupera a coluna, e o `downgrade()` não é recuperação — "
        "ele devolve o esquema, nunca as linhas. Escreva a mudança como adição, ou "
        "declare a exceção em `ADDITIVE_BY_EXCEPTION` com o motivo (ADR 0066)."
    )


def test_every_migration_that_touches_tenancy_cites_a_decision() -> None:
    """A segunda metade, e o gatilho é estrutural em vez de julgamento.

    Policy, RLS e privilégio são as três formas de o Postgres dizer quem alcança
    qual linha — quem as escreve está mexendo na segunda barreira da ADR 0010, e o
    `AGENTS.md` pede decisão registrada para isso.

    **Nasce verde**: 15 migrações disparam o gatilho e as 15 citam. A mutação que a
    sustenta é tirar a citação de uma delas, e a ADR 0066 traz a saída.

    **RAG e retenção ficam de fora**, e é limite declarado, não esquecimento: as
    duas não têm sinal estrutural no SQL, e cobrá-las exigiria uma lista de nomes de
    tabela digitada à mão — o defeito da ADR 0033.
    """
    uncited: list[str] = []
    for name, text in _migrations().items():
        if touches_tenancy(text) and not citations(text):
            uncited.append(name)

    assert uncited == [], (
        "estas migrações mexem em policy, RLS ou privilégio e não citam decisão "
        "nenhuma: " + ", ".join(uncited) + ". A regra 4 do `AGENTS.md` exige ADR ou "
        "RFC para alteração de tenant e de autenticação; escreva a citação no "
        "docstring da migração, apontando para a decisão que ela implementa "
        "(ADR 0066)."
    )


def test_every_decision_a_migration_cites_exists() -> None:
    """A direção inversa, no precedente da ADR 0034: as duas direções já falharam.

    Uma citação pendurada é o defeito das ADRs 0064 e 0065 na superfície que
    ninguém tinha olhado — lá era um comando apontando para ambiente apagado, aqui
    seria uma migração apontando para decisão que não existe. **Nasce verde**, e a
    mutação é trocar um número por `ADR 0099`.

    Reusa o corpus de `_accepted`: uma ADR **recusada por escrito** não serve de
    justificativa para mudança de tenancy, e é por isso que o predicado não é
    "o arquivo existe".
    """
    valid = _decisions_on_disk()
    dangling: list[str] = []
    for name, text in _migrations().items():
        dangling += [
            f"{name} → {kind} {number:04d}"
            for kind, number in sorted(citations(text) - valid)
        ]

    assert dangling == [], (
        "estas migrações citam decisão que não existe (ou que foi recusada por "
        "escrito): " + "; ".join(dangling) + ". Corrija o número — uma citação "
        "pendurada faz a revisão exigida pela regra 4 parecer feita (ADR 0066)."
    )


def test_the_additive_allowlist_does_not_keep_a_line_that_stopped_being_needed() -> None:
    """Isenção tem duas formas de morrer, e as duas reprovam aqui.

    O arquivo sumiu, ou deixou de apagar dado. O precedente é o
    `PINNED_BY_EXCEPTION` da ADR 0063 e o `FOUNDATION_WITHOUT_A_LINE` da ADR 0054:
    allowlist que só cresce deixa de descrever o repositório, e entrada obsoleta é
    isenção que ninguém decidiu manter.
    """
    migrations = _migrations()
    obsolete = [
        f"{name}: {'o arquivo não existe mais' if name not in migrations else 'o `upgrade()` deixou de apagar dado'}"
        for name in ADDITIVE_BY_EXCEPTION
        if name not in migrations or not destructive_upgrades(migrations[name])
    ]

    assert obsolete == [], (
        "estas linhas de `ADDITIVE_BY_EXCEPTION` deixaram de ser necessárias: "
        + "; ".join(obsolete)
        + ". Apague a entrada: sem `review_by` para vencê-la, esta asserção é o "
        "único vencimento que ela tem (ADR 0066)."
    )
