"""Os pinos que o runbook mandava revisar e que ninguém conferia (ADR 0063).

`docs/runbooks/dependency-advisory.md` afirma, sobre o que o `npm audit` e o
`pip-audit` **não** alcançam, que "as imagens estão fixadas em versão exata
(ADR 0022)" e que "quem revisa dependência revisa essas duas listas junto, porque
nada mais o fará". Medido, as três partes da frase estavam erradas ao mesmo tempo:

- **não existia lista.** Nem no runbook, nem em lugar nenhum do repositório;
- **nada verificava** a instrução — ela é prosa, e prosa não reprova;
- e a afirmação era **falsa**: `docker-compose.yml:78` era `minio/minio:latest`,
  que é o oposto de versão exata.

Inventário no dia da fatia, produzido por este arquivo contra a árvore ainda não
pinada: **25 linhas `uses:` em tag móvel e zero pinadas por SHA**, e **16
referências de imagem e zero com digest**. Uma tag é um ponteiro que quem publica
reescreve: `actions/checkout@v4` hoje e amanhã são o que o dono do repositório
disser, e um `image:` sem digest é a mesma promessa com outro dono.

É o padrão da ADR 0034 pela enésima vez — o runbook nomeando um estado que o
repositório não tinha —, com a diferença que a ADR 0062 acabara de **desligar o
Dependabot**: sem robô que abra o PR, a única coisa que sobra é detecção, e
detecção que não reprova não existe. Esta guarda é o portão; `scripts/pins.mjs` é
a lista que o runbook mandava revisar e o atualizador deliberado que a mantém.

**O corpus é derivado por glob, nunca digitado** (ADR 0033/0035), em quatro
superfícies — workflows, Dockerfiles, compose e Terraform — e cada uma é
**fail-closed**: glob que devolve zero arquivos reprova, dizendo que o corpus
sumiu. É o argumento do `_adrs` do `test_roadmap_index.py` e o defeito que a
ADR 0033 achou no `dependency-review`: guarda que fica verde por não achar
arquivo é indistinguível, no verde do CI, de guarda desligada.

Nenhuma asserção aqui precisa de banco nem de rede: são sobre arquivos. E os
auxiliares recebem `text: str`, nunca `Path` — só as funções `test_*` abrem
arquivo —, que é o que permite medi-los contra texto arbitrário, inclusive
contra o estado pré-pinagem sem tocar no working tree.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[3]

WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
WORKFLOW_GLOBS = ("*.yml", "*.yaml")
COMPOSE_GLOBS = ("docker-compose*.yml", "docker-compose*.yaml")
DOCKERFILE_GLOB = "Dockerfile*"
TERRAFORM_DIR = REPO_ROOT / "infra" / "terraform"
TERRAFORM_GLOB = "**/*.tf"

#: Diretórios que a varredura de `Dockerfile*` não atravessa. São artefato de
#: instalação e de build, não código deste repositório: um `Dockerfile` dentro de
#: `node_modules` é dependência de terceiro, e cobrar pino dele seria cobrar do
#: repositório o que ele não escreve.
_NOT_OURS = {".venv", "node_modules", ".next", ".git", "test-results"}


class Reference(NamedTuple):
    """Uma referência de terceiro achada num arquivo.

    `text` é a **linha inteira**, e não só a referência, porque o predicado 2
    pergunta pelo comentário de versão que mora ao lado do pino.
    """

    line: int
    ref: str
    text: str


#: `uses:` de workflow, com ou sem o hífen de item de lista. O valor é tudo até o
#: primeiro espaço, o que deixa o comentário `# v4` de fora da referência e
#: dentro da linha — que é como o predicado 2 consegue perguntar pelos dois.
#:
#: Deliberadamente **não** casa `uses` sem os dois-pontos, nem `uses:` no meio de
#: uma linha (só no começo, depois da indentação), que é onde um `run:` de várias
#: linhas poderia escrever a palavra dentro de um script.
_USES = re.compile(r"^[ \t]*(?:-[ \t]+)?uses:[ \t]*(?P<ref>\S+)", re.MULTILINE)

#: Ação **local** (`./.github/actions/…`) não é dependência de terceiro: é código
#: deste repositório, e o SHA dela é o do commit que a guarda está avaliando.
#: Hoje não há nenhuma; a cláusula existe para que a primeira não nasça vermelha
#: por um motivo que não se pode atender.
_LOCAL_ACTION = re.compile(r"^\.{1,2}/")

#: `image:` de compose **e** dos blocos `services:` de workflow. É um casador só,
#: de propósito: as `services:` do `ci.yml` são a mesma coisa que um serviço de
#: compose — uma imagem de terceiro que sobe ao lado do job —, e uma superfície
#: separada para elas seria uma segunda lista para envelhecer em paralelo.
_IMAGE = re.compile(r"^[ \t]*(?:-[ \t]+)?image:[ \t]*(?P<ref>\S+)", re.MULTILINE)

#: `FROM` de Dockerfile, com o `AS <etapa>` opcional. O nome da etapa é lido
#: porque ele é o que separa imagem de referência interna — ver `_from_images`.
_FROM = re.compile(
    r"^FROM[ \t]+(?:--platform=\S+[ \t]+)?(?P<ref>\S+)(?:[ \t]+AS[ \t]+(?P<stage>\S+))?",
    re.MULTILINE | re.IGNORECASE,
)

#: Abertura de bloco `variable` cujo **nome** fala de imagem. O casamento é por
#: nome da variável, e não pela forma do valor, e isso foi decidido medindo: um
#: casador de literal em HCL casaria toda URL do repositório
#: (`"https://console.cloud.google.com/run"`, `"biahflow.ai"`, o id da zona do
#: Cloudflare) e a guarda nasceria com dezenas de falsos positivos que ninguém
#: pode pinar. Hoje casa exatamente uma linha —
#: `infra/terraform/ambientes/hml-biahflow/variables.tf:51`.
_TF_IMAGE_VARIABLE = re.compile(
    r"^variable[ \t]+\"(?P<name>[^\"]*(?:imagem|image)[^\"]*)\"",
    re.MULTILINE | re.IGNORECASE,
)

#: O `default` de dentro daquele bloco, **só quando é literal não vazio**.
#: `default = ""` não casa (é o `tag_imagem`, que significa "primeiro apply"), e
#: interpolação também não: a imagem de deploy é composta com `tag_imagem`, que é
#: o SHA do commit, e pedir digest a um `${…}` seria pedir pino a um template.
_TF_DEFAULT = re.compile(r"^[ \t]+default[ \t]*=[ \t]*\"(?P<ref>[^\"$]+)\"", re.MULTILINE)

#: O fim do bloco: a próxima linha que **começa na coluna zero**. Serve para o
#: bloco de várias linhas (termina no `}` sozinho) e para o de uma linha só
#: (`variable "imagem" { type = string }`, dos módulos, cujo bloco acaba nela
#: mesma e que portanto não tem `default` nenhum). Um contador de chaves teria de
#: saber ler heredoc — `<<-TXT … TXT` —, e o conteúdo do heredoc é indentado,
#: então a coluna zero já responde a pergunta.
_TOP_LEVEL = re.compile(r"^\S", re.MULTILINE)

#: Pino de ação: SHA de commit de 40 hexadecimais **minúsculos**. Uma tag (`@v4`),
#: um branch (`@main`) ou um SHA curto não casam.
_ACTION_PIN = re.compile(r"^(?P<name>[^@\s]+)@(?P<sha>[0-9a-f]{40})$")

#: A versão ao lado do pino, na mesma linha: `# v4`, `# v4.2.0`, `# v2.1.13`. O
#: `v` é exigido porque sem ele qualquer comentário passaria a valer como versão
#: — e o que se quer é que a lista seja **legível por uma pessoa**, não que ela
#: tenha um comentário.
_VERSION_COMMENT = re.compile(r"#[ \t]*(?P<version>v\d[\w.\-+]*)")

#: Pino de imagem: nome, tag **e** digest, nessa ordem. `name` é ganancioso, o
#: que deixa a porta de um registro (`localhost:5000/foo:tag`) dentro do nome e a
#: tag no último grupo de dois-pontos.
_IMAGE_PIN = re.compile(
    r"^(?P<name>[^@\s]+):(?P<tag>[A-Za-z0-9_][\w.\-]*)@sha256:(?P<digest>[0-9a-f]{64})$"
)

#: A tag que não diz nada. Um digest ao lado dela é tecnicamente um pino, e
#: mesmo assim reprova: a tag existe para ser lida por uma pessoa, e
#: `minio/minio:latest@sha256:…` não conta a ninguém em que versão o portal está.
_MOVING_TAG = "latest"

#: `docker run|pull|create` dentro de um `run:` de workflow — a única forma de
#: imagem que não aparece em `image:`, `FROM` nem `default` de Terraform, e o
#: comando que o CI **de fato** puxa (ao contrário de um `image:` de
#: `services:`, que o runner resolve por fora). Só estes três subcomandos:
#: `docker build` não nomeia uma imagem de terceiro para pinar, nomeia um
#: `Dockerfile` — que `from_images` já cobre —, e `docker exec`/`docker stop`
#: recebem nome de contêiner, não de imagem.
_DOCKER_RUN = re.compile(r"\bdocker[ \t]+(?:run|pull|create)\b")

#: A **forma** de uma referência de imagem, e não mais uma tabela de flags
#: digitada à mão (ADR 0063, pendência medida e fechada nesta fatia). Nome com
#: namespace opcional, tag opcional, digest opcional — e a exigência de conter
#: `/` **ou** `@sha256:`, que é o que separa uma referência de imagem de um
#: valor de flag: `9000:9000`, `512m` e `FOO=bar` casam "nome" ou "nome:tag" na
#: sintaxe solta, mas nenhum tem `/` nem digest. Uma imagem oficial de nome
#: curto sem digest (`postgres:17`) fica **de fora de propósito** por essa
#: mesma exigência — a forma canônica é `library/postgres:17`, e é essa que a
#: mensagem de erro abaixo ensina a escrever.
_IMAGE_REFERENCE_FORM = re.compile(
    r"^(?P<name>[\w.\-]+(?:/[\w.\-]+)*)"
    r"(?::(?P<tag>[\w][\w.\-]*))?"
    r"(?:@sha256:(?P<digest>[0-9a-f]{64}))?$"
)


def _looks_like_image_reference(token: str) -> bool:
    """Se `token` tem a forma de uma referência de imagem — ver `_IMAGE_REFERENCE_FORM`."""
    if "/" not in token and "@sha256:" not in token:
        return False
    return _IMAGE_REFERENCE_FORM.match(token) is not None


#: Referência → por que ela **não** é pinada, em prosa longa e contestável.
#:
#: **Sem `review_by`**, ao contrário do `docs/security/advisories.json` (ADR 0023)
#: e pelo argumento que o `test_roadmap_index.py` já escreveu: isenção de pino não
#: caduca por prazo — o vencimento dela é
#: `test_the_pin_allowlist_does_not_keep_a_line_that_stopped_being_needed`, que
#: reprova no dia em que a referência sai do repositório **ou** passa a estar
#: corretamente pinada. Quem discordar do motivo pina a referência, e a asserção
#: de obsolescência cobra a remoção da linha.
#:
#: A chave é o **nome** da referência (sem tag e sem digest), e não a linha
#: literal: é o que permite a entrada morrer por ter sido pinada, em vez de a
#: pinagem simplesmente criar uma chave nova e deixar a antiga como sedimento
#: (ADR 0029).
PINNED_BY_EXCEPTION: dict[str, str] = {
    "us-docker.pkg.dev/cloudrun/container/hello": (
        "O placeholder oficial do Cloud Run, e o Google o publica **só em "
        "`latest`** — não há tag de versão para pôr ao lado de um digest, então "
        "o pino nem teria a forma que esta guarda exige. Ele entra na *criação* "
        "do serviço, antes de existir imagem nossa no registro "
        "(`imagem_bootstrap`, e o `lifecycle.ignore_changes` do módulo só vale "
        "em update, nunca em create), é substituído no primeiro deploy e a "
        "partir daí fica protegido por "
        "`infra/terraform/modulos/servico-cloudrun/main.tf:199`. Pinar por "
        "digest congelaria um placeholder que **nunca serve tráfego** e que "
        "some na primeira revisão — e o congelamento apareceria como deriva "
        "num `plan` que se lê procurando `must be replaced`."
    ),
}


# --- os auxiliares puros ----------------------------------------------------
#
# Todos recebem `text: str`. Nenhum abre arquivo, nenhum conhece caminho: é o
# que permite medi-los contra um recorte, contra `git show` ou contra um caso
# construído, e é a forma do `test_roadmap_index.py`.


def _references(pattern: re.Pattern[str], text: str) -> list[Reference]:
    """As referências que um casador de linha acha, com número de linha e linha."""
    lines = text.splitlines()
    found: list[Reference] = []
    for match in pattern.finditer(text):
        number = text.count("\n", 0, match.start()) + 1
        found.append(
            Reference(
                line=number,
                ref=match.group("ref").strip("\"'"),
                text=lines[number - 1] if number <= len(lines) else "",
            )
        )
    return found


def actions(text: str) -> list[Reference]:
    """As ações de terceiro que um workflow usa."""
    return [
        reference
        for reference in _references(_USES, text)
        if not _LOCAL_ACTION.match(reference.ref)
    ]


def images(text: str) -> list[Reference]:
    """As imagens que um `image:` nomeia — compose e `services:` de workflow."""
    return _references(_IMAGE, text)


def from_images(text: str) -> list[Reference]:
    """As imagens que os `FROM` de um Dockerfile nomeiam.

    **Um `FROM <etapa>` não é imagem.** Referenciar uma etapa declarada antes com
    `AS` no mesmo arquivo é apontar para dentro do próprio build, e cobrar digest
    dela seria cobrar o digest de algo que ainda não existe. Hoje não ocorre — as
    duas imagens deste repositório encadeiam por `COPY --from=builder`, não por
    `FROM builder` —, e sem a cláusula a guarda reprovaria no primeiro que
    encadeasse. `FROM scratch` é a outra referência que não é imagem: é a
    ausência de uma.
    """
    lines = text.splitlines()
    stages: set[str] = set()
    found: list[Reference] = []
    for match in _FROM.finditer(text):
        number = text.count("\n", 0, match.start()) + 1
        ref = match.group("ref").strip("\"'")
        stage = match.group("stage")
        if ref.lower() not in stages and ref.lower() != "scratch":
            found.append(
                Reference(
                    line=number,
                    ref=ref,
                    text=lines[number - 1] if number <= len(lines) else "",
                )
            )
        if stage:
            stages.add(stage.strip("\"'").lower())
    return found


def terraform_images(text: str) -> list[Reference]:
    """As imagens que um `.tf` traz como `default` de variável de imagem.

    O recorte é **por nome da variável** e o valor tem de ser literal não vazio;
    ver o comentário de `_TF_IMAGE_VARIABLE` para o falso positivo que a forma
    oposta produziria.
    """
    lines = text.splitlines()
    found: list[Reference] = []
    for match in _TF_IMAGE_VARIABLE.finditer(text):
        end = _TOP_LEVEL.search(text, match.end())
        block = text[match.end() : end.start() if end else len(text)]
        default = _TF_DEFAULT.search(block)
        if not default:
            continue
        number = text.count("\n", 0, match.end() + default.start()) + 1
        found.append(
            Reference(
                line=number,
                ref=default.group("ref").strip(),
                text=lines[number - 1] if number <= len(lines) else "",
            )
        )
    return found


def docker_run_images(text: str) -> list[Reference]:
    """As imagens que um `docker run|pull|create` nomeia dentro de um `run:` de workflow.

    O comando pode se estender por continuação de linha (`\\` no fim), como o
    `Boot MinIO` do `ci.yml`. A partir do subcomando, os tokens são
    percorridos: quem começa com `-` é flag e consome **um** token — não há
    mais tabela de flags de valor separado — e o primeiro token que não
    começa com `-` é o candidato a imagem. A linha reportada é a de onde a
    imagem está — não a do início do comando, que pode ficar do outro lado de
    uma continuação.

    O candidato só vira imagem se tiver **forma** de referência de imagem
    (`_looks_like_image_reference`); do contrário a varredura reprova nomeando
    o token, em vez de tomá-lo por imagem "provavelmente" — que era o defeito
    medido na ADR 0063: `docker run --memory 512m minio/minio:…` tomava
    `512m` por imagem e a imagem real saía do corpus sem que nada dissesse
    isso. A saída legítima é escrever a flag na forma colada
    (`--memory=512m`, `--env=FOO=bar`, `--publish=9000:9000`), que nunca
    produz um token separado para confundir.

    **Fail-closed, nas duas direções:** se nenhum token sobrar depois do
    subcomando, é o comando que não nomeia imagem nenhuma; se um token sobrar
    e não tiver forma de imagem, é o valor de uma flag que este casador não
    reconheceu. Nos dois casos a guarda reprova nomeando o comando (e, no
    segundo, o token), em vez de deixar passar em silêncio ou adivinhar qual
    token é a imagem — é o mesmo argumento do `skipped` não ser `clean` no
    `scanner.py`, e do fail-closed do `_files` acima.
    """
    lines = text.splitlines()
    found: list[Reference] = []
    for match in _DOCKER_RUN.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        first_line_idx = text.count("\n", 0, match.start())
        offset_in_line = match.end() - line_start

        tokens: list[tuple[str, int]] = []
        idx = first_line_idx
        remainder = lines[idx][offset_in_line:]
        while True:
            stripped = remainder.rstrip()
            continues = stripped.endswith("\\")
            content = stripped[:-1] if continues else stripped
            tokens.extend((token, idx + 1) for token in content.split())
            if not continues:
                break
            idx += 1
            if idx >= len(lines):
                break
            remainder = lines[idx]

        candidate: tuple[str, int] | None = None
        i = 0
        while i < len(tokens):
            token, token_line = tokens[i]
            if token.startswith("-"):
                i += 1
                continue
            candidate = (token, token_line)
            break

        command_text = " ".join(token for token, _ in tokens)
        assert candidate is not None, (
            "não consegui achar a imagem depois de `docker run|pull|create` em "
            f"`{lines[first_line_idx].strip()}` (linha {first_line_idx + 1}): "
            f"`{command_text}`. Ou o comando não nomeia imagem nenhuma, ou usa uma "
            "flag que este casador não conhece — as duas exigem revisão humana, "
            "porque \"não consegui achar a imagem\" não pode valer como \"não há "
            "imagem aqui\" (ADR 0063)."
        )

        # As aspas saem **antes** da conferência de forma, e não depois: um
        # `docker run "minio/minio:…"` é forma legítima, e conferir a forma com
        # a aspa ainda no token reprovaria a imagem verdadeira — trocar um
        # falso-verde por um falso-vermelho não é o negócio desta fatia.
        candidate_token, candidate_line = candidate
        ref = candidate_token.strip("\"'")
        assert _looks_like_image_reference(ref), (
            f"`{ref}` (linha {candidate_line}) não tem forma de referência de "
            "imagem — nome com `/` ou digest `@sha256:` — e por isso não é a "
            "imagem de `docker run|pull|create` em "
            f"`{lines[first_line_idx].strip()}` (linha {first_line_idx + 1}): "
            f"`{command_text}`. Provavelmente é o valor de uma flag escrita na "
            "forma separada; escreva-a colada (`--memory=512m`, "
            "`--env=FOO=bar`, `--publish=9000:9000`) para que o casador não "
            "tome o valor por imagem (ADR 0063)."
        )

        found.append(
            Reference(
                line=candidate_line,
                ref=ref,
                text=lines[candidate_line - 1] if candidate_line <= len(lines) else "",
            )
        )
    return found


def bare_name(ref: str) -> str:
    """A referência sem tag e sem digest — a chave da allowlist.

    `redis:7.4.10-alpine@sha256:…` e `redis:7-alpine` dão o mesmo nome, que é o
    que faz a isenção morrer quando a referência é pinada em vez de a pinagem
    criar uma chave nova.
    """
    name = ref.split("@", 1)[0]
    head, slash, last = name.rpartition("/")
    if ":" in last:
        last = last.split(":", 1)[0]
    return f"{head}{slash}{last}"


def action_is_pinned(reference: Reference) -> bool:
    """SHA de commit de 40 hexadecimais, e nada além disso."""
    return _ACTION_PIN.match(reference.ref) is not None


def action_names_its_version(reference: Reference) -> bool:
    """A versão legível ao lado do pino, na mesma linha."""
    return _VERSION_COMMENT.search(reference.text) is not None


def image_is_pinned(reference: Reference) -> bool:
    """Digest **e** tag, e a tag não pode ser `latest`."""
    match = _IMAGE_PIN.match(reference.ref)
    return match is not None and match.group("tag") != _MOVING_TAG


# --- as bordas: só as funções `test_*` abrem arquivo ------------------------


def _files(root: Path, globs: tuple[str, ...], surface: str) -> dict[str, str]:
    """Os arquivos de uma superfície, e **reprova se não achar nenhum**.

    Este é o ponto mais importante do arquivo, e é o argumento do `_adrs` do
    `test_roadmap_index.py`: uma guarda que fica verde por não achar arquivo é o
    `dependency-review` da ADR 0033 outra vez — mecanismo publicado, verde a cada
    push, sem nunca ter olhado o que dizia olhar.
    """
    paths = sorted(
        path
        for glob in globs
        for path in root.glob(glob)
        if path.is_file() and not _NOT_OURS & set(path.relative_to(REPO_ROOT).parts)
    )
    assert paths, (
        f"a superfície `{surface}` não tem nenhum arquivo: o glob "
        f"{', '.join(globs)} em `{root}` devolveu vazio. "
        "Ou o corpus mudou de lugar e esta guarda parou de olhar o repositório, "
        "ou os arquivos sumiram — nos dois casos o verde deixaria de significar "
        "que os pinos foram conferidos, que é o defeito do `dependency-review` "
        "da ADR 0033 (ADR 0063)."
    )
    return {
        str(path.relative_to(REPO_ROOT)): path.read_text(encoding="utf-8")
        for path in paths
    }


def _all_actions() -> list[tuple[str, Reference]]:
    return [
        (name, reference)
        for name, text in _files(WORKFLOW_DIR, WORKFLOW_GLOBS, "workflows").items()
        for reference in actions(text)
    ]


def _all_images() -> list[tuple[str, Reference]]:
    """As quatro fontes de imagem, numa lista só.

    Elas se somam em vez de virarem quatro testes porque a pergunta é a mesma —
    "esta referência está pinada?" — e um predicado por superfície faria a quinta
    superfície nascer sem predicado.
    """
    found: list[tuple[str, Reference]] = []
    for name, text in _files(WORKFLOW_DIR, WORKFLOW_GLOBS, "workflows").items():
        found.extend((name, reference) for reference in images(text))
        found.extend((name, reference) for reference in docker_run_images(text))
    for name, text in _files(REPO_ROOT, COMPOSE_GLOBS, "compose").items():
        found.extend((name, reference) for reference in images(text))
    for name, text in _files(REPO_ROOT, (f"**/{DOCKERFILE_GLOB}",), "Dockerfiles").items():
        found.extend((name, reference) for reference in from_images(text))
    for name, text in _files(TERRAFORM_DIR, (TERRAFORM_GLOB,), "Terraform").items():
        found.extend((name, reference) for reference in terraform_images(text))
    return found


def _exempt(reference: Reference) -> bool:
    return bare_name(reference.ref) in PINNED_BY_EXCEPTION


def _where(name: str, reference: Reference) -> str:
    return f"{name}:{reference.line} → {reference.ref}"


def test_every_action_is_pinned_by_commit_sha() -> None:
    """Uma tag de action é um ponteiro que o dono do repositório reescreve.

    Nasceu vermelha com **25** — todas as 25 linhas `uses:` dos três workflows,
    nenhuma pinada. `actions/checkout@v4` é o que o dono da `actions/checkout`
    disser que é no dia em que o CI rodar, e o CI deste repositório tem
    credencial de deploy (`deploy-hml.yml`) e de infraestrutura
    (`infra-hml.yml`).
    """
    unpinned = [
        _where(name, reference)
        for name, reference in _all_actions()
        if not action_is_pinned(reference) and not _exempt(reference)
    ]

    assert unpinned == [], (
        "estas actions estão em tag ou branch, e não em SHA de commit: "
        + "; ".join(unpinned)
        + ". Rode `node scripts/pins.mjs --update`, que resolve o SHA da tag e "
        "reescreve a linha mantendo a versão ao lado — ou declare a isenção em "
        "`PINNED_BY_EXCEPTION` com o motivo. Tag é ponteiro mutável, e desde a "
        "ADR 0062 não há robô que abra o PR que conserta (ADR 0063)."
    )


def test_every_action_pin_names_its_version_on_the_same_line() -> None:
    """Sem a versão ao lado, o pino é ruído hexadecimal e a lista não é revisável.

    **Nasceu verde, e isso é da forma do predicado, não frouxidão:** ele só
    pergunta de pinos, e na árvore pré-fatia não havia nenhum — as 25 linhas
    `uses:` estavam em tag, e uma tag já diz a versão. Ele existe para o *depois*,
    e por isso foi medido por mutação: apagando o ` # v4` de
    `deploy-hml.yml:47`, acusa
    `actions/checkout@11d5960a326750d5838078e36cf38b85af677262`.

    A frase que esta fatia existe para tornar verdadeira — "quem revisa
    dependência revisa essas duas listas junto" — pressupõe que a lista **se
    leia**, e um SHA sozinho não conta a ninguém de que versão se trata. Trocar
    tag por SHA sem esta asserção seria trocar um pino móvel e legível por um
    pino fixo e ilegível, o que resolve metade do problema e cria a outra.
    """
    anonymous = [
        _where(name, reference)
        for name, reference in _all_actions()
        if action_is_pinned(reference) and not action_names_its_version(reference)
    ]

    assert anonymous == [], (
        "estes pinos de action não dizem de que versão são: "
        + "; ".join(anonymous)
        + ". Escreva a versão no fim da mesma linha, na forma `# v4` ou "
        "`# v4.2.0` — é ela que faz a lista ser revisável por uma pessoa, que é "
        "o que o `dependency-advisory.md` manda fazer e nada mais fará "
        "(ADR 0063)."
    )


def test_every_image_is_pinned_by_digest_with_its_tag() -> None:
    """A imagem base é dependência, e uma tag não a fixa.

    Nasceu vermelha com **15** das 16 referências de imagem — as quatro `FROM`
    das duas imagens deste repositório, as oito do compose (base e homologação),
    as duas dos blocos `services:` do `ci.yml` e a que o `docker run` do MinIO
    no job `backup-restore` nomeia —, sendo a décima sexta o placeholder do
    Cloud Run, isento por escrito. Zero tinham digest, e duas delas eram
    `minio/minio:latest` — no compose e no próprio `docker run` que o puxa —,
    no mesmo repositório cujo runbook afirma que "as imagens estão fixadas em
    versão exata".

    As três formas de reprovar são deliberadas: só tag não é pino; digest sem tag
    é pino que ninguém lê; e `latest` com digest é as duas coisas ao mesmo tempo.
    """
    unpinned = [
        _where(name, reference)
        for name, reference in _all_images()
        if not image_is_pinned(reference) and not _exempt(reference)
    ]

    assert unpinned == [], (
        "estas imagens não estão fixadas por digest com a tag ao lado: "
        + "; ".join(unpinned)
        + ". A forma é `nome:tag@sha256:<64 hex>` — `latest` reprova mesmo com "
        "digest, porque a tag existe para ser lida por uma pessoa. Rode "
        "`node scripts/pins.mjs --update` para resolver o digest do índice "
        "multi-arquitetura, ou declare a isenção em `PINNED_BY_EXCEPTION` "
        "(ADR 0063)."
    )


def test_the_pin_allowlist_does_not_keep_a_line_that_stopped_being_needed() -> None:
    """Uma isenção tem duas formas de morrer, e as duas reprovam aqui.

    A referência sumiu do repositório, ou passou a estar corretamente pinada. O
    precedente é o `_CANNOT_ANSWER_404` do `test_authorization.py`, o `stale` do
    `scripts/audit.mjs` e o `FOUNDATION_WITHOUT_A_LINE` do
    `test_roadmap_index.py`: allowlist que só cresce deixa de descrever o
    repositório, e a isenção que sobrevive ao motivo é a lista escrita à mão que
    a ADR 0033 existe para pegar.

    **Nasce verde**, e por isso foi medida: apagando o digest de
    `axllent/mailpit` e acrescentando `axllent/mailpit` à allowlist, ela passa —
    é o caso legítimo; devolvendo o digest, ela acusa *"já está corretamente
    pinada"*; e trocando a chave da entrada do Cloud Run por um nome que não
    existe, ela acusa *"não aparece em superfície nenhuma"*.
    """
    everything = [reference for _, reference in _all_actions() + _all_images()]

    obsolete: list[str] = []
    for key in sorted(PINNED_BY_EXCEPTION):
        occurrences = [
            reference for reference in everything if bare_name(reference.ref) == key
        ]
        if not occurrences:
            obsolete.append(f"{key}: não aparece em superfície nenhuma")
        elif all(
            action_is_pinned(reference) or image_is_pinned(reference)
            for reference in occurrences
        ):
            obsolete.append(f"{key}: já está corretamente pinada")

    assert obsolete == [], (
        "estas linhas de `PINNED_BY_EXCEPTION` deixaram de ser necessárias: "
        + "; ".join(obsolete)
        + ". Apague-as. A isenção não tem prazo de propósito — pino não caduca "
        "por calendário —, então esta asserção é o único vencimento que ela "
        "tem (ADR 0063)."
    )
