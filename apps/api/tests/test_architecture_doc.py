"""A topologia que o documento de arquitetura não conhecia (ADR 0064).

`docs/architecture.md` dizia, na seção `## Topologia de implantação`, que
"**fisicamente há dois ambientes**", e nomeava dois arquivos de compose. Entre 07 e
13/08/2026 dez ADRs (0044–0053) implantaram este repositório na GCP, e o arquivo não
contém as strings `Terraform`, `Cloud Run`, `Cloudflare`, `Neon`, `Upstash` nem
`0053` — foi tocado pela última vez em 07/08/2026, antes de a maior parte delas ser
aceita.

O `infra/terraform/README.md` tem o mesmo defeito, e o que o torna a peça central
desta guarda é que **ele já registra ter pago por isso**, na linha 20:

    `modulos/maquina-fila/` esteve listado aqui e **nunca existiu** depois da ADR
    0045: era a VM que os worker pools substituíram, e a linha sobreviveu à remoção
    do diretório.

Conserto à mão, sem portão — e divergiu de novo pelo mesmo mecanismo, duas vezes: a
fence de estrutura lista `ambientes/hml-portal/`, apagado em 13/08 (`9e2d61d`), e
`modulos/borda/`, apagado no mesmo dia (`0357be1`, quando a borda virou Cloudflare).
É literalmente a ADR 0034: correção sem guarda volta a divergir.

Quatro asserções, e **cada recorte abaixo foi medido, não argumentado**.

**(a) O casamento é por caminho inteiro, e isso é o que separa esta guarda de um
falso verde.** Casar pelo basename `hml` a deixaria verde no instante em que o
documento mencionasse `hml-biahflow`, `docs/runbooks/hml-gcp.md` ou `infra-hml.yml`
— o `.item`/`.items` da ADR 0057 outra vez. O token em backtick é separado por espaço
em branco antes de comparar, que é o que faz a forma que o documento de fato usa
(`` `+ docker-compose.homolog.yml` ``) casar sem teste de substring.

**(b) O corpus é encontrado por forma, e não digitado.** Um bloco cercado qualifica
como fence de estrutura quando ao menos três das suas linhas não-vazias começam por
um token com forma de caminho e esses são ao menos 60% do bloco. Medido sobre os
`.md` do repositório: seleciona **exatamente uma** fence,
`infra/terraform/README.md:6`, e dentro dela acusa exatamente os dois defeitos reais,
com zero falso-positivo.

Duas coisas que este recorte compra, e as duas foram medidas:

- **A nota histórica some por construção.** `modulos/maquina-fila/` mora na prosa,
  fora da fence. Sem `_HISTORICAL_NOTE`, sem allowlist e sem convenção de marcador
  nova: o documento guarda o registro do próprio erro e a guarda nunca o vê.
- **O braço de backtick inline ficou de fora, com o número.** Rodado sobre os dois
  documentos ele rende **zero** achados únicos e **um falso-vermelho**,
  `/api|/admin|/static|/healthz|/readyz`, que passa qualquer filtro de contagem de
  separadores. Alargado para todo `.md` do repositório são 32 tokens pendurados, das
  classes `INSERT/UPDATE/DELETE`, `try/except`, `America/Sao_Paulo`,
  `application/octet-stream`, `hashicorp/google` e `actions/checkout` — uma linha de
  allowlist cada, que é o defeito `.priority` da ADR 0033.

A resolução é **relativa ao diretório do documento**, e é exata: um README descreve o
diretório onde mora. Casamento por sufixo ficaria verde se um diretório de mesmo nome
existisse em qualquer outro ponto da árvore.

**(c) Guarde o número cujo denominador é artefato contável; apague o número cujo
denominador é escolha narrativa.** Por isso "há dois ambientes" **não** entra aqui: a
contagem de topologias narradas (três) não é a cardinalidade do corpus de (a)
(quatro — dois composes e dois diretórios de ambiente), porque homologação é override
sobre a base e não uma quarta coisa. Guardá-la exigiria uma segunda definição de
"ambiente", divergente da primeira, e duas definições derivam. A frase foi reescrita
para nomear as três topologias, e quem a guarda é (a).

E é **aqui**, não em (b), que mora o `_HISTORICAL_NOTE` do `test_telemetry.py`: a
convenção de correção desta casa cita o número velho — `docs/architecture.md` já
contém *"este parágrafo dizia 'Três credenciais'"* —, então a nota que esta fatia
escreveu para "três imagens" contém a string "três imagens", e sem retirar as notas
antes do casamento a guarda bloquearia a própria correção com o "ficou ambígua".

**(d) A versão ingênua foi medida e recusada.** Perguntar se o nome aparece em algum
`.tf` deixa a asserção verde sobre o defeito exato que ela existe para pegar:
`portal-api` e `keycloak` saíram da HML em 13/08 e sobrevivem em **comentários de
histórico** (`servicos.tf:14,16,25,149,218`, `main.tf:77,248,250`). As chaves são
lidas por indentação dentro de `servicos.tf`, onde um comentário não pode casar
porque começa com `#`.

Nenhuma asserção aqui precisa de banco nem de rede: são sobre arquivos. E os
auxiliares recebem `text: str`, nunca `Path` — só as funções `test_*` abrem arquivo.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ARCHITECTURE = REPO_ROOT / "docs" / "architecture.md"
INFRA_README = REPO_ROOT / "infra" / "terraform" / "README.md"

TOPOLOGY_HEADING = "## Topologia de implantação"

COMPOSE_GLOB = "docker-compose*.yml"
ENVIRONMENTS = REPO_ROOT / "infra" / "terraform" / "ambientes"
ENVIRONMENT_MARKER = "backend.tf"
SERVICES_GLOB = "*/servicos.tf"
ACCESS_VALIDATION = (
    REPO_ROOT / "infra" / "terraform" / "modulos" / "servico-cloudrun" / "main.tf"
)

#: O runbook da implantação na GCP. Entra no corpus de (c) e é o documento que as duas
#: asserções novas encontraram vermelho — ver o docstring do módulo.
RUNBOOK_HML = REPO_ROOT / "docs" / "runbooks" / "hml-gcp.md"

#: Onde mora o mapa `segredos`, que é o denominador de dois números do runbook.
SECRETS_VARIABLE = ENVIRONMENTS / "hml" / "variables.tf"

#: As superfícies de HCL que constroem nome de serviço. `.tftpl` entra junto porque o
#: worker da borda é um template: o nome atravessa para dentro dele por interpolação.
HCL_GLOBS = ("infra/**/*.tf", "infra/**/*.tftpl")

#: Diretórios que não são deste repositório, no mesmo recorte do
#: `test_supply_chain_pins.py`: varrer o `node_modules` faria o corpus de (b) depender
#: de quem instalou o quê.
_NOT_OURS = {".git", ".next", ".venv", "node_modules", "coverage", "htmlcov"}

#: Um token com **forma** de caminho: ou tem separador interno, ou termina em barra —
#: e nenhum caractere que só apareça em rota HTTP, tipo MIME ou expressão de código. É
#: a forma, e não a contagem de separadores, que mantém `/api|/admin|/static` fora.
#:
#: O ramo da barra final foi acrescentado por **mutação**, e não por previsão: com só
#: o ramo do separador interno, trocar `ambientes/hml/` por `hml/` na fence deixava a
#: guarda **verde** — o token de um segmento não era reprovado, era ignorado, e um
#: diretório de nome simples podia sumir da árvore sem nada ficar vermelho. Medido
#: antes de mudar: o ramo novo não acrescenta fence nem falso-positivo nenhum ao
#: repositório de hoje. Um token sem barra alguma (`README`) continua fora, porque
#: aquilo não afirma ser um caminho.
_PATH_SHAPED = re.compile(
    r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+/?$|^[A-Za-z0-9_.-]+/$"
)

#: As duas constantes de sintonia do detector de (b). Ficam nomeadas porque são o que
#: o `test_the_structure_fence_corpus_is_not_empty` protege: reformatar a fence pode
#: esvaziar o corpus, e corpus vazio tem de reprovar em vez de passar verde.
_FENCE_MIN_PATHS = 3
_FENCE_MIN_RATIO = 0.6

#: A nota histórica desta casa, nas quatro aberturas que os documentos usam. Retirada
#: **antes** do casamento de (c), senão a correção que cita o número velho produz uma
#: segunda ocorrência e a guarda reprova a si mesma. Mesmo mecanismo, e o mesmo
#: motivo, do `_HISTORICAL_NOTE` de `test_telemetry.py`.
#:
#: O fechamento é um asterisco **no fim da linha** e não simplesmente um asterisco não
#: seguido de outro, e isso foi medido: a nota que esta fatia escreveu contém
#: `**dois ambientes**`, e o casador do precedente terminava no segundo asterisco
#: daquele negrito — deixando o resto da nota, com o número velho, dentro do texto que
#: a guarda lê. `(?<!\*)` mantém o fim de um negrito em fim de linha fora do papel de
#: fechamento.
_HISTORICAL_NOTE = re.compile(
    r"\*(Corrigido|Acrescentado|Retificado|Emendado) em [\s\S]*?(?<!\*)\*[ \t]*$",
    re.MULTILINE,
)

#: Um bloco cercado, para ser retirado antes de qualquer casamento de crase simples.
#: Sem isto o pareamento de `` ` `` atravessa a cerca e o token seguinte sai colado ao
#: texto: medido na própria seção de topologia, onde o diagrama ASCII fazia
#: `infra/terraform/ambientes/hml/` sair como `ambientes"`.
_FENCED = re.compile(r"^```[\s\S]*?^```", re.MULTILINE)

#: Um bloco cercado **etiquetado `bash`**, que é a forma de "comandos que alguém roda".
#:
#: A etiqueta não é zelo de estilo, é o que mantém duas classes inteiras fora do
#: alcance por construção, e as duas foram medidas. A primeira é a **seção Medição de
#: uma ADR**: a 0064 cita a saída literal do próprio vermelho, que nomeia
#: `ambientes/hml-portal` — sem a etiqueta, esta guarda cobraria que o repositório
#: apagasse o registro do próprio erro, que é o que a ADR 0034 recusa. Aquele bloco é
#: ```text, e some daqui sem allowlist nenhuma. A segunda é a **prosa que cita um
#: comando**: `gcloud run services update` aparece no meio de três frases, e o casador
#: posicional tomava a palavra seguinte (`falha`, `que`) por nome de serviço.
_BASH_FENCE_OPEN = re.compile(r"^\s*```(\w*)")

#: Um ambiente do Terraform nomeado por caminho qualificado. Não precisa de escopo:
#: `ambientes/<nome>` só significa uma coisa neste repositório.
_ENVIRONMENT_QUALIFIED = re.compile(r"ambientes/([a-z][a-z0-9-]*)")

#: E nomeado como irmão, que é a forma que o runbook usa depois de já ter entrado no
#: diretório (`cd ../hml-portal`). Este **precisa** de escopo, porque `../<nome>` no
#: geral é sobre qualquer coisa: só vale dentro de fence que fale de `terraform`. Foi
#: medido — sem o escopo, `cd ../biahflow-portal` do `integracao-biahflow.md`, que é
#: um repositório irmão e não um ambiente, entra como falso-vermelho duas vezes.
_ENVIRONMENT_SIBLING = re.compile(r"(?<!\.)\.\./([a-z][a-z0-9-]*)")

#: O nome de serviço dentro de um hostname do Cloud Run. **O `run.app` é o sinal
#: estrutural**, e é o que dispensa saber o que "tem forma de nome de serviço": o
#: primeiro segmento de `<serviço>-<número>.<região>.run.app` é um serviço por
#: construção da própria URL. Vale igual no HCL que a monta por interpolação e no
#: `curl` que a escreve com o número literal — uma regra, duas espécies de arquivo.
_RUN_APP_HOST = re.compile(r"([a-z][a-z0-9-]*?)-(?:\$\{[^}]*\}|\d+)\.[^\s\"'/]*run\.app")

#: E o nome na posição de argumento de um comando `gcloud run`. Posicional, logo
#: preciso: o nome vem depois do verbo, e o verbo depois da espécie de recurso.
_GCLOUD_SERVICE = re.compile(
    r"gcloud\s+(?:beta\s+)?run\s+(?:services|jobs|worker-pools)\s+\S+\s+([a-z][a-z0-9-]*)"
)

#: Comentário de HCL, retirado antes de qualquer casamento. É o mesmo recorte que o
#: `_service_keys` já fazia por indentação, e pelo mesmo motivo medido na ADR 0064:
#: `portal-api` e `keycloak` sobrevivem em comentário de histórico, e perguntar sem
#: retirá-los deixa a guarda verde sobre exatamente o defeito que ela procura.
_HCL_COMMENT = re.compile(r"#.*$", re.MULTILINE)

#: Numeral por extenso → inteiro. É **detalhe de parser e não corpus**, no precedente
#: explícito da tabela de flags do `docker run` (ADR 0063): envelhece com a língua
#: portuguesa, não com este repositório, e um numeral que ele não conheça reprova em
#: vez de passar.
_NUMERALS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3, "tres": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
    "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14,
    "quatorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17,
    "dezoito": 18, "dezenove": 19, "vinte": 20,
}

#: **Nasce vazia**, e é de propósito: os dois ambientes de hoje não precisam de
#: isenção — a correção honesta os nomeia. Allowlist que já nasce ocupada é sedimento
#: no nascimento (ADR 0029), e foi assim que a entrada da ADR 0009 entrou na guarda do
#: roadmap com um motivo falso. Chave é o caminho relativo à raiz; valor é a prosa
#: contestável de por que aquele ambiente não pertence à topologia deste produto.
#: **Sem `review_by`**, no precedente do `PINNED_BY_EXCEPTION` (ADR 0063): quem
#: discordar escreve a linha no documento, e aí a asserção de obsolescência cobra a
#: remoção daqui.
DEPLOYED_WITHOUT_A_LINE: dict[str, str] = {}


# --- Leitura do que o repositório declara -------------------------------------------


def _service_blocks(compose: str) -> dict[str, list[str]]:
    """Nome do serviço → as linhas do bloco dele, por indentação.

    Sem `yaml`, e não por gosto: `docker-compose.homolog.yml` usa a tag `!reset`, que
    o `SafeLoader` recusa — de modo que o carregador teria de ganhar um construtor
    para uma extensão do Compose antes de contar qualquer coisa. Um comentário não
    pode virar serviço porque `#` não casa o nome.
    """
    blocks: dict[str, list[str]] = {}
    inside = False
    current: str | None = None
    for line in compose.splitlines():
        if line[:1].isalpha():
            inside = line.startswith("services:")
            current = None
            continue
        if not inside:
            continue
        found = re.match(r"^  ([A-Za-z0-9_-]+):", line)
        if found:
            current = found.group(1)
            blocks[current] = []
        elif current is not None and line.strip():
            blocks[current].append(line)
    return blocks


def _services_publishing_ports(compose: str) -> list[str]:
    """Os serviços que publicam porta no host — os que têm bloco `ports:`."""
    return sorted(
        name
        for name, body in _service_blocks(compose).items()
        if any(re.match(r"^    ports:", line) for line in body)
    )


def _build_contexts(compose: str) -> set[str]:
    """Os contextos de build distintos, que é o que conta como "imagem nossa".

    Sete serviços declaram `build:` e produzem **duas** imagens: seis compartilham
    `./apps/api` e um é o `.` do BFF.
    """
    contexts: set[str] = set()
    for body in _service_blocks(compose).values():
        for line in body:
            found = re.match(r"^\s+context:\s*(\S+)", line)
            if found:
                contexts.add(found.group(1))
    return contexts


def _access_values(module: str) -> list[str]:
    """Os valores que `acesso` aceita, lidos do `validation` do módulo.

    Do `condition` e não de qualquer `contains(..., var.acesso)`: há um segundo, no
    `google_cloud_run_v2_service_iam_member`, que lista **três** valores por decidir
    outra coisa — quem recebe `roles/run.invoker`. Contar aquele daria o número que o
    documento já dizia, pelo motivo errado.
    """
    found = re.findall(
        r"condition\s*=\s*contains\(\[([^\]]+)\],\s*var\.acesso\)", module
    )
    assert len(found) == 1, (
        "esperava exatamente um `condition = contains([...], var.acesso)` em "
        f"`{ACCESS_VALIDATION.relative_to(REPO_ROOT)}`, e encontrei {len(found)}. "
        "O bloco `validation` é a única definição de quantos valores `acesso` tem; "
        "sem ele esta guarda não teria denominador."
    )
    return re.findall(r'"([^"]+)"', found[0])


def _service_keys(servicos: str) -> list[str]:
    """As chaves de serviço de um `servicos.tf`, por indentação de quatro espaços.

    É heurística de indentação e **não** um parse de HCL — dito aqui porque a
    diferença importa: ela não sabe em qual mapa a chave está, só que é uma chave de
    serviço. O que ela precisa garantir é a direção pendurada (todo nome que o
    documento afirma existe), e para isso completude não é necessária. Um comentário
    não pode casar porque começa com `#`, que é exatamente o que a versão ingênua
    desta asserção não conseguia — ver o docstring do módulo.
    """
    return re.findall(r"^ {4}([a-z][a-z0-9-]*)\s*=\s*\{", servicos, re.MULTILINE)


def _table_service_names(readme: str) -> list[str]:
    """Os nomes que a tabela da HML afirma serem peças do ambiente.

    A primeira coluna se autosseleciona: as linhas de serviço citam o nome entre
    crases (`` `web` ``, `` `cockpit-api` ``) e as de infraestrutura são texto puro
    (Redis, documentos, Postgres, rede). Nenhuma allowlist para as segundas — elas
    nunca são extraídas.
    """
    return re.findall(r"^\| `([a-z0-9_.-]+)`[^|]*\|", readme, re.MULTILINE)


# --- O que os documentos afirmam ---------------------------------------------------


def _section(text: str, heading: str) -> str:
    """O corpo de uma seção `##`, da sua heading até a próxima do mesmo nível."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(heading)), None)
    if start is None:
        return ""
    end = next(
        (i for i, line in enumerate(lines[start + 1 :], start + 1) if line.startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start + 1 : end])


def _backticked_tokens(text: str) -> set[str]:
    """Os tokens citados entre crases, separados por espaço em branco.

    A separação é o que faz `` `+ docker-compose.homolog.yml` `` — a forma que o
    documento de fato usa — casar com o caminho inteiro sem nenhum teste de
    substring, que é o que essa guarda recusa por desenho.

    Os blocos cercados saem antes, e isso não é zelo: a seção de topologia tem um
    diagrama ASCII, e as crases da cerca dele desalinhavam todo o pareamento adiante
    — `infra/terraform/ambientes/hml/` chegava aqui como `ambientes"`, de modo que a
    asserção reprovaria um documento que já nomeava o ambiente.
    """
    tokens: set[str] = set()
    for quoted in re.findall(r"`([^`]+)`", _FENCED.sub("", text)):
        tokens.update(piece.rstrip("/") for piece in quoted.split())
    return tokens


def _structure_fences(text: str) -> list[tuple[int, list[str]]]:
    """As fences que **afirmam ser a estrutura de um diretório**, por forma.

    Um bloco cercado qualifica quando ao menos `_FENCE_MIN_PATHS` das suas linhas
    não-vazias começam por um token com forma de caminho e esses são ao menos
    `_FENCE_MIN_RATIO` do bloco. Devolve `(linha da abertura, tokens de caminho)`.

    É o que torna o corpus **encontrado e não digitado**, e o que mantém a nota
    histórica da prosa fora do alcance da guarda.
    """
    fences: list[tuple[int, list[str]]] = []
    inside = False
    opened = 0
    body: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("```"):
            if inside:
                filled = [line for line in body if line.strip()]
                pathy = [
                    line.split()[0].rstrip("/")
                    for line in filled
                    if _PATH_SHAPED.match(line.split()[0])
                ]
                if (
                    len(pathy) >= _FENCE_MIN_PATHS
                    and filled
                    and len(pathy) / len(filled) >= _FENCE_MIN_RATIO
                ):
                    fences.append((opened, pathy))
                inside = False
                body = []
            else:
                inside = True
                opened = number
        elif inside:
            body.append(line)
    return fences


# --- Os corpora, todos derivados e todos fail-closed --------------------------------


def _files(root: Path, glob: str, surface: str) -> dict[str, str]:
    """Os arquivos de uma superfície, e **glob vazio reprova**.

    O fail-closed é o ponto: um corpus que sumiu de lugar deixaria a guarda verde por
    não ter olhado, que é a forma do `dependency-review` da ADR 0033 e a razão de a
    ADR 0063 ter escrito esta mesma função para as quatro superfícies dos pinos.
    """
    paths = sorted(
        path
        for path in root.glob(glob)
        if path.is_file() and not _NOT_OURS & set(path.relative_to(REPO_ROOT).parts)
    )
    assert paths, (
        f"a superfície `{surface}` não tem nenhum arquivo: o glob `{glob}` em "
        f"`{root.relative_to(REPO_ROOT) if root != REPO_ROOT else '.'}` devolveu "
        "vazio. Ou o corpus mudou de lugar e esta guarda parou de olhar o "
        "repositório, ou os arquivos sumiram — nos dois casos o verde deixaria de "
        "significar que o documento foi conferido (ADR 0064)."
    )
    return {
        str(path.relative_to(REPO_ROOT)): path.read_text(encoding="utf-8")
        for path in paths
    }


def _deployment_environments() -> dict[str, str]:
    """Todo ambiente de implantação que o repositório declara → o que o declara.

    Duas espécies, e a chave é sempre o **caminho relativo à raiz**: um arquivo de
    compose é um ambiente porque descreve uma pilha inteira, e um diretório de
    `infra/terraform/ambientes/` é um ambiente quando tem `backend.tf` — o marcador
    é o state, porque é ele que faz daquele diretório algo que se aplica sozinho.
    """
    found = {
        name: "um arquivo de compose"
        for name in _files(REPO_ROOT, COMPOSE_GLOB, "compose")
    }
    states = _files(ENVIRONMENTS, f"*/{ENVIRONMENT_MARKER}", "ambientes do Terraform")
    for name in states:
        found[str(Path(name).parent)] = "um state do Terraform"
    return found


def _bash_fences(text: str) -> list[list[tuple[int, str]]]:
    """Os blocos cercados etiquetados `bash`, **um bloco por item**.

    Devolve `(número da linha, linha)` porque as asserções precisam apontar o sítio, e
    devolve **separado por bloco** porque o escopo de `../<nome>` é a fence e não o
    arquivo. Isso foi medido: a primeira versão juntava as linhas do arquivo inteiro
    antes de perguntar se ali se falava de `terraform`, e com isso o
    `git -C ../biahflow-portal` de uma fence de `gcloud` herdava o escopo de outra
    fence e entrava como falso-vermelho. O corpus de um predicado é o bloco em que
    ele vale.
    """
    fences: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    inside = False
    language = ""
    for number, line in enumerate(text.splitlines(), 1):
        found = _BASH_FENCE_OPEN.match(line)
        if found:
            if inside:
                if language == "bash":
                    fences.append(current)
                current = []
            else:
                language = found.group(1)
            inside = not inside
            continue
        if inside and language == "bash":
            current.append((number, line))
    return fences


def _declared_environment_names() -> set[str]:
    """Os nomes dos ambientes do Terraform — o mesmo marcador de (a), o `backend.tf`.

    Nome e não caminho, e aqui isso é correto ao contrário de (a): lá o documento
    escreve o caminho inteiro e casar por basename daria falso-verde; aqui o comando
    escreve `cd ../hml-portal`, onde o nome é tudo o que existe.
    """
    return {
        Path(name).parent.name
        for name in _files(ENVIRONMENTS, f"*/{ENVIRONMENT_MARKER}", "ambientes do Terraform")
    }


def _declared_service_names() -> set[str]:
    """Todo serviço que algum `servicos.tf` declara, por indentação e sem comentário."""
    return {
        key
        for text in _files(ENVIRONMENTS, SERVICES_GLOB, "serviços do Terraform").values()
        for key in _service_keys(text)
    }


def _secret_keys(variables: str) -> list[str]:
    """As chaves do mapa `segredos`, lidas do `default` do `variable`.

    Do `default` porque ele **é** o conjunto: nenhum `terraform.tfvars` deste
    repositório sobrescreve `segredos`, de modo que o que está aqui é o que o
    Terraform cria. Fail-closed como o `_access_values`: se o bloco deixar de ser
    encontrado, a guarda reprova em vez de contar zero e concluir que a prosa mente.
    """
    without_comments = _HCL_COMMENT.sub("", variables)
    found = re.findall(
        r'variable\s+"segredos"\s*\{[\s\S]*?default\s*=\s*\{([\s\S]*?)\n\s*\}',
        without_comments,
    )
    assert len(found) == 1, (
        'esperava exatamente um `variable "segredos"` com bloco `default` em '
        f"`{SECRETS_VARIABLE.relative_to(REPO_ROOT)}`, e encontrei {len(found)}. "
        "Aquele mapa é o único denominador de quantos segredos o Terraform cria; sem "
        "ele os números do runbook não têm contra o que ser conferidos."
    )
    return re.findall(r"^\s+([A-Z][A-Z0-9_]*)\s*=", found[0], re.MULTILINE)


def _counts() -> dict[str, int]:
    """Os denominadores: o que cada número da prosa afirma, contado na fonte."""
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    secrets = _secret_keys(SECRETS_VARIABLE.read_text(encoding="utf-8"))
    return {
        "serviços do compose local": len(_service_blocks(compose)),
        "serviços que publicam porta no host": len(_services_publishing_ports(compose)),
        "contextos de build distintos": len(_build_contexts(compose)),
        "states do Terraform": len(
            _files(ENVIRONMENTS, f"*/{ENVIRONMENT_MARKER}", "ambientes do Terraform")
        ),
        "valores de `acesso`": len(
            _access_values(ACCESS_VALIDATION.read_text(encoding="utf-8"))
        ),
        "segredos do Terraform": len(secrets),
        "segredos que carregam DSN": len([k for k in secrets if k.endswith("_URL")]),
    }


#: As frases que carregam um número cujo denominador é artefato contável. Uma linha é
#: `(documento, regex de um grupo, chave em `_counts`)`, e o fail-closed vale nos dois
#: sentidos: zero casamentos reprova ("a frase sumiu") e mais de um também ("ficou
#: ambígua"). O segundo não é zelo — sem ele, a nota de correção que cita o número
#: velho seria uma segunda ocorrência, que é por que `_HISTORICAL_NOTE` é retirado
#: antes.
COUNTED_IN_PROSE: tuple[tuple[Path, re.Pattern[str], str], ...] = (
    (ARCHITECTURE, re.compile(r"\*{0,2}(\w+)\*{0,2} serviços, dos quais"),
     "serviços do compose local"),
    (ARCHITECTURE, re.compile(r"dos quais \*{0,2}(\w+)\*{0,2} publicam porta"),
     "serviços que publicam porta no host"),
    (ARCHITECTURE, re.compile(r"as \*{0,2}(\w+)\*{0,2} imagens"),
     "contextos de build distintos"),
    (INFRA_README, re.compile(r"São \*{0,2}(\w+)\*{0,2} states"),
     "states do Terraform"),
    (ARCHITECTURE, re.compile(r"São \*{0,2}(\w+)\*{0,2} states do Terraform"),
     "states do Terraform"),
    (INFRA_README, re.compile(r"`acesso`, com \*{0,2}(\w+)\*{0,2} valores"),
     "valores de `acesso`"),
    (RUNBOOK_HML, re.compile(r"O Terraform cria os \*{0,2}(\w+)\*{0,2} segredos"),
     "segredos do Terraform"),
    (RUNBOOK_HML, re.compile(r"entram em \*{0,2}(\w+)\*{0,2} segredos"),
     "segredos que carregam DSN"),
)

#: Os documentos que descrevem a estrutura do repositório em prosa, e portanto os que
#: (b) varre. O corpus é todo `.md` nosso: as fences que valem são escolhidas por
#: forma, não por nome de arquivo.
STRUCTURE_DOCS_GLOB = "**/*.md"


# --- As asserções ------------------------------------------------------------------


def test_every_deployment_environment_is_named_in_the_topology() -> None:
    """Um ambiente que o repositório aplica e o documento de arquitetura não conhece.

    Nasceu vermelha com os **dois** diretórios do Terraform: a topologia dizia que
    "fisicamente há dois ambientes" e nomeava só os dois composes, dez ADRs depois de
    a nuvem existir como código neste repositório (ADR 0064).
    """
    section = _section(ARCHITECTURE.read_text(encoding="utf-8"), TOPOLOGY_HEADING)

    assert section.strip(), (
        f"não achei a seção `{TOPOLOGY_HEADING}` em "
        f"`{ARCHITECTURE.relative_to(REPO_ROOT)}`, ou ela está vazia. A guarda "
        "reprova em vez de passar sobre um texto que não leu: sem a seção, toda "
        "asserção de nomeação abaixo seria trivialmente sobre nada."
    )

    named = _backticked_tokens(section)
    missing = sorted(
        f"{path} ({how})"
        for path, how in _deployment_environments().items()
        if path.rstrip("/") not in named and path not in DEPLOYED_WITHOUT_A_LINE
    )

    assert missing == [], (
        "estes ambientes de implantação são declarados no repositório e a seção "
        f"`{TOPOLOGY_HEADING}` não os conhece: " + "; ".join(missing) + ". Nomeie "
        "cada um pelo caminho inteiro entre crases, ou declare em "
        "`DEPLOYED_WITHOUT_A_LINE` por que aquele ambiente não pertence à topologia "
        "deste produto. O caminho inteiro é o ponto: citar só `hml` deixaria a "
        "guarda verde por causa de `hml-biahflow` e de `hml-gcp.md` (ADR 0064)."
    )


def test_the_structure_fence_corpus_is_not_empty() -> None:
    """Fail-closed de (b): tem de existir ao menos um bloco de estrutura.

    Carrega peso e não é cerimônia. `_FENCE_MIN_PATHS` e `_FENCE_MIN_RATIO` são
    constantes de sintonia, e reformatar a fence — prosa entre as linhas, uma coluna
    de comentário a mais — poderia esvaziar o corpus **em silêncio**, deixando
    `test_every_path_a_structure_fence_names_exists` verde por não ter olhado.
    """
    docs = _files(REPO_ROOT, STRUCTURE_DOCS_GLOB, "documentos de estrutura")
    fences = [
        (name, opened)
        for name, text in docs.items()
        for opened, _ in _structure_fences(text)
    ]

    assert fences, (
        "nenhum bloco de estrutura foi encontrado em documento nenhum. O detector "
        f"exige ao menos {_FENCE_MIN_PATHS} linhas com forma de caminho e ao menos "
        f"{_FENCE_MIN_RATIO:.0%} do bloco; se a fence de "
        "`infra/terraform/README.md` foi reformatada, ajuste as constantes no mesmo "
        "commit — corpus vazio reprova em vez de passar verde (ADR 0064)."
    )


def test_every_path_a_structure_fence_names_exists() -> None:
    """A linha que sobrevive à remoção do diretório, que é o defeito da linha 20.

    Nasceu vermelha com `ambientes/hml-portal/` e `modulos/borda/`, os dois apagados
    em 13/08/2026 e os dois ainda desenhados como se fossem a estrutura. A resolução
    é relativa ao diretório do documento, e é exata — um README descreve o diretório
    onde mora.
    """
    docs = _files(REPO_ROOT, STRUCTURE_DOCS_GLOB, "documentos de estrutura")
    dangling: list[str] = []
    for name, text in sorted(docs.items()):
        home = (REPO_ROOT / name).parent
        for opened, tokens in _structure_fences(text):
            dangling.extend(
                f"{name}:{opened} desenha `{token}`"
                for token in tokens
                if not (home / token).exists()
            )

    assert dangling == [], (
        "estes caminhos são desenhados como a estrutura de um diretório e não "
        "existem: " + "; ".join(dangling) + ". Apague a linha no mesmo commit que "
        "apagou o diretório. É o defeito que o `infra/terraform/README.md` já "
        "registra ter tido uma vez, com `modulos/maquina-fila/`, e que voltou por "
        "ter sido consertado à mão e sem portão (ADR 0034/0064)."
    )


def test_every_number_the_prose_writes_matches_what_it_counts() -> None:
    """O literal que a fonte contradiz — a "Fórmula do ROI" da ADR 0033 em prosa.

    Nasceu vermelha em três das cinco linhas: "as **três** imagens" contra dois
    contextos de build, "São **três** states" contra dois `backend.tf`, e "`acesso`,
    com **três** valores" contra os quatro do `validation`.
    """
    counted = _counts()
    wrong: list[str] = []
    for document, pattern, what in COUNTED_IN_PROSE:
        where = document.relative_to(REPO_ROOT)
        text = _HISTORICAL_NOTE.sub("", document.read_text(encoding="utf-8"))
        found = pattern.findall(text)

        if len(found) != 1:
            wrong.append(
                f"{where}: a frase que conta {what} casou {len(found)} vezes com "
                f"`{pattern.pattern}`"
            )
            continue

        written = found[0].lower()
        if written not in _NUMERALS:
            wrong.append(f"{where}: `{found[0]}` não é um numeral que a guarda conheça")
        elif _NUMERALS[written] != counted[what]:
            wrong.append(
                f"{where}: a prosa diz `{found[0]}` e {what} são {counted[what]}"
            )

    assert wrong == [], (
        "estes números escritos não casam com o que a fonte conta: "
        + "; ".join(wrong)
        + ". Corrija o número, ou apague-o e nomeie o que ele contava — guarde o "
        "número cujo denominador é artefato contável, apague o número cujo "
        "denominador é escolha narrativa (ADR 0064)."
    )


def test_every_service_the_infra_readme_names_exists_in_the_terraform() -> None:
    """A tabela que descreve como HML serviços que saíram dela.

    Nasceu vermelha com cinco das seis linhas: `portal-api`, `keycloak` e `worker`
    saíram em 13/08/2026 com o produto, e `biahflow-web`/`biahflow-api` viraram
    `cockpit-*` em 19/08. Perguntar se o nome aparece em algum `.tf` **passaria
    verde**, porque `portal-api` e `keycloak` sobrevivem em comentários de histórico.
    """
    declared = {
        key
        for text in _files(ENVIRONMENTS, SERVICES_GLOB, "serviços do Terraform").values()
        for key in _service_keys(text)
    }
    named = _table_service_names(INFRA_README.read_text(encoding="utf-8"))
    missing = sorted({name for name in named if name not in declared})

    assert missing == [], (
        "a tabela de `infra/terraform/README.md` nomeia como peças de HML serviços "
        "que nenhum `servicos.tf` declara: " + ", ".join(f"`{n}`" for n in missing)
        + ". Um serviço que saiu do Terraform saiu da HML, e a linha que fica "
        "descreve um ambiente que não existe (ADR 0064)."
    )


def test_the_topology_allowlist_does_not_keep_a_line_that_stopped_being_needed() -> None:
    """O único vencimento que `DEPLOYED_WITHOUT_A_LINE` tem.

    Ela **nasce vazia**, então esta asserção nasce verde — e verde de nascença não
    prova nada (ADR 0038). Foi medida por mutação: pondo `infra/terraform/ambientes/hml`
    na lista depois de o documento passar a nomeá-lo, ela acusa *"passou a ser
    nomeado na topologia"*.
    """
    section = _section(ARCHITECTURE.read_text(encoding="utf-8"), TOPOLOGY_HEADING)
    named = _backticked_tokens(section)
    declared = _deployment_environments()

    obsolete = [
        f"{path}: passou a ser nomeado na topologia"
        if path.rstrip("/") in named
        else f"{path}: não é ambiente declarado por este repositório"
        for path in sorted(DEPLOYED_WITHOUT_A_LINE)
        if path.rstrip("/") in named or path not in declared
    ]

    assert obsolete == [], (
        "estas linhas de `DEPLOYED_WITHOUT_A_LINE` deixaram de ser necessárias: "
        + "; ".join(obsolete)
        + ". Apague-as. A isenção não tem prazo de propósito — ambiente não caduca "
        "por calendário —, então esta asserção é o único vencimento que ela tem "
        "(ADR 0064)."
    )


def test_every_terraform_environment_a_command_names_is_declared() -> None:
    """Um comando não manda entrar num ambiente que não existe (ADR 0065).

    É o alcance que a ADR 0064 deixou aberto com todas as letras. Aquela fatia
    corrigiu `cd ../hml-portal` no `infra/terraform/README.md` e chamou a linha de
    *"uma instrução que **falha**"* — e o mesmo comando sobreviveu no
    `docs/runbooks/hml-gcp.md`, porque o corpus de (b) são as fences de **estrutura** e
    um runbook não desenha diretório, ele navega até ele.

    **Isto não é o braço de crases inline que aquela ADR recusou.** Aquele lia todo
    token entre crases e rendia zero achados únicos com 32 falso-positivos das classes
    `try/except` e `application/octet-stream`. Este pergunta uma coisa só — o nome de
    um ambiente do Terraform —, e sobre as duas formas em que ele aparece: qualificado
    por `ambientes/`, que não precisa de escopo, e como irmão (`../<nome>`), que
    precisa e o tem.

    **A prosa fica fora, e foi medida.** `hml-portal` aparece corretamente em sete
    lugares de prosa — `ROADMAP.md`, `docs/architecture.md`, o próprio cabeçalho deste
    runbook — todos registrando que o ambiente **saiu** em 13/08/2026. Alargar para a
    prosa cobraria que o repositório apagasse o registro do próprio erro, que é o
    mesmo limite que a ADR 0064 impôs a (b) e a ADR 0034 à guarda de eventos.
    """
    declared = _declared_environment_names()
    named: list[str] = []
    for name, text in _files(REPO_ROOT, STRUCTURE_DOCS_GLOB, "documentos deste repositório").items():
        for fence in _bash_fences(text):
            scoped = "terraform" in "\n".join(line for _, line in fence).lower()
            for number, line in fence:
                found = list(_ENVIRONMENT_QUALIFIED.findall(line))
                if scoped:
                    found += _ENVIRONMENT_SIBLING.findall(line)
                named += [
                    f"{name}:{number} manda usar `{env}`"
                    for env in dict.fromkeys(found)
                    if env not in declared
                ]

    assert named == [], (
        "estes comandos nomeiam um ambiente do Terraform que este repositório não "
        "declara: " + "; ".join(named) + ". Um `terraform apply` ali falha com "
        "`no such file or directory`, e um procedimento que falha é pior que um "
        "procedimento ausente — quem o segue conclui que errou. Corrija o comando, "
        "ou mova a menção para a prosa se ela for registro histórico (ADR 0065)."
    )


def test_every_service_name_the_repository_builds_or_invokes_is_declared() -> None:
    """O nome que a borda monta e o que o runbook invoca são o mesmo que o Terraform declara.

    Esta é a asserção que achou o defeito que **não é de documento**. Em 19/08/2026 os
    serviços do CRM foram renomeados de `biahflow-*` para `cockpit-*` (`b4e0471`, cuja
    mensagem diz *"registra o que já está na nuvem"*), e o commit tocou **um arquivo
    só**: `ambientes/hml-biahflow/servicos.tf`. Sobrou
    `ambientes/hml/cloudflare.tf`, que monta a origem da Cloudflare como
    `biahflow-web-<número>.<região>.run.app` — nome que nenhum `servicos.tf` declara
    desde então — e daquela `local` saem o registro DNS e o template do worker da
    borda. O commit de acerto seguinte (`6a0e45f`) alinhou **outro** espelho e não
    passou por aqui; a mensagem dele nomeia este modo de falha por extenso.

    **Direção pendurada, como (d):** um serviço declarado que ninguém nomeia passa
    despercebido, e continua sendo julgamento e não contagem. O que se cobra é o
    inverso — quem nomeia, nomeia o que existe.

    **Duas formas, um predicado.** O sinal de "isto é um nome de serviço" é estrutural
    nas duas: o primeiro segmento de um hostname `run.app` é um serviço por construção
    da URL, e o argumento posicional de `gcloud run <espécie> <verbo>` também. Não há
    "forma de nome de serviço" a adivinhar, que é o que dispensa allowlist.
    """
    declared = _declared_service_names()
    named: list[str] = []

    for glob in HCL_GLOBS:
        for name, text in _files(REPO_ROOT, glob, f"HCL em `{glob}`").items():
            for number, line in enumerate(_HCL_COMMENT.sub("", text).splitlines(), 1):
                named += [
                    f"{name}:{number} constrói `{service}`"
                    for service in dict.fromkeys(_RUN_APP_HOST.findall(line))
                    if service not in declared
                ]

    for name, text in _files(REPO_ROOT, STRUCTURE_DOCS_GLOB, "documentos deste repositório").items():
        for number, line in [line for fence in _bash_fences(text) for line in fence]:
            found = _RUN_APP_HOST.findall(line) + _GCLOUD_SERVICE.findall(line)
            named += [
                f"{name}:{number} invoca `{service}`"
                for service in dict.fromkeys(found)
                if service not in declared
            ]

    assert named == [], (
        "estes sítios nomeiam um serviço do Cloud Run que nenhum `servicos.tf` "
        "declara: " + "; ".join(named) + ". Um nome que o Terraform deixou de "
        "declarar não existe na nuvem: no HCL isso aponta a borda para uma origem "
        "morta, e no runbook é um comando que falha dizendo que o recurso não existe "
        "(ADR 0065)."
    )
