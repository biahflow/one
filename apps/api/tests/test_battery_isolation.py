"""O que a bateria herda de fora (ADR 0060).

Um arquivo só porque o sujeito é um só: **o verde da bateria não pode depender do
ambiente em que ela roda**. Herança de duas espécies, e as duas foram medidas:

*Configuração.* ``Settings`` lê ``os.environ`` e um ``.env`` do disco, então
qualquer variável de produto atravessa para dentro do teste. Com
``CONTACT_QUIET_HOURS_START=0``/``END=0`` — exportadas **ou** escritas num
``.env`` — cinco testes de ``test_whatsapp.py`` reprovam. A ADR 0058 fechou a
porta do relógio e não viu esta; a costura fica em ``conftest.py``, e as guardas
1, 1b e 1c a cobram.

*Estado.* Um ``.delay()`` publica no Redis do compose de verdade, e o contêiner
``worker`` consome contra o **mesmo banco**. Foi assim que
``test_a_client_only_sees_and_reads_their_own_notifications`` passou a reprovar:
89 linhas antes, no mesmo ``world``, outro teste faz ``POST /chat`` de verdade e
o worker insere a notificação da pendência na caixa do cliente. Não é resíduo de
corrida anterior — o ``world`` é etiquetado com um ``uuid`` a cada sessão —, e
parar o worker faz o mesmo teste, no mesmo banco, passar. As guardas 2a, 2b e 3
cobram a outra metade: a porta única do ``send_task`` e um vizinho barulhento que
toda varredura global encontra.

A forma das listas é a da casa (``NOT_AN_ALERT``, ``ANCHORLESS``,
``NOT_CONSUMED``): motivo escrito por linha e asserção de obsolescência.
"""

from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from sqlalchemy import Engine

from conftest import INHERITED_FROM_THE_ENVIRONMENT, NoisyNeighbour
from portal_api.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
WORKER_SOURCE = REPO_ROOT / "apps" / "api" / "src" / "portal_api" / "worker.py"
TESTS_DIR = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- #
# Metade A — a bateria não herda configuração
# --------------------------------------------------------------------------- #

#: Campos que o envenenador **não sabe** alterar, com o motivo por linha.
#:
#: Está vazia hoje, e isso é uma medição e não um descuido: os 103 campos de
#: ``Settings`` são ``str``, ``bool``, ``int``, ``float`` e ``tuple[str, ...]``,
#: e para os cinco tipos existe um valor válido diferente do default. Um campo
#: novo com tipo restrito (``Literal``, ``SecretStr``, enum, URL validada) pode
#: precisar de linha aqui — e enquanto não tiver, a guarda de completude reprova
#: em vez de deixá-lo sair da medição em silêncio.
CANNOT_BE_POISONED: dict[str, str] = {}


def _poison_for(field: Any) -> str | None:
    """Um valor de ambiente válido e **diferente** do default, ou ``None``.

    ``None`` quer dizer "não sei envenenar este tipo" — e é o que a guarda de
    completude transforma em vermelho. Devolver o default por engano seria pior
    que não medir: a asserção passaria afirmando isolamento que não existe.
    """
    annotation = field.annotation
    default = field.default
    if annotation is bool:
        return "false" if default else "true"
    if annotation is int:
        return str(int(default) + 7)
    if annotation is float:
        return str(float(default) + 7.5)
    if annotation is str:
        return f"{default}-envenenado" if default else "envenenado"
    if annotation == tuple[str, ...]:
        return json.dumps(["ENVENENADO"])
    return None


def _poisonable() -> dict[str, str]:
    """Campo → valor de ambiente, para todo campo que não é herdável.

    Deriva de ``Settings.model_fields`` — 103 campos, zero lista à mão. É a
    diferença entre esta guarda e a correção que a ADR 0058 poderia ter feito no
    ``base`` de ``_settings()``: aquela cobre os campos que alguém lembrou.
    """
    allowed = {name.lower() for name in INHERITED_FROM_THE_ENVIRONMENT}
    poisoned: dict[str, str] = {}
    for name, field in Settings.model_fields.items():
        if name in allowed or name in CANNOT_BE_POISONED:
            continue
        value = _poison_for(field)
        if value is not None:
            poisoned[name] = value
    return poisoned


def _drifted(built: Settings, poisoned: dict[str, str]) -> list[str]:
    return sorted(
        f"{name}={getattr(built, name)!r} (default {Settings.model_fields[name].default!r})"
        for name in poisoned
        if getattr(built, name) != Settings.model_fields[name].default
    )


def test_no_product_variable_reaches_a_settings_built_in_a_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A primeira porta: ``os.environ``.

    A guarda **envenena ela mesma** o ambiente, campo a campo, e cobra que a
    ``Settings`` construída em teste continue no default. Envenenar é o que
    distingue esta asserção de uma que só olhasse duas variáveis conhecidas: o
    defeito da ADR 0058 era ``CONTACT_QUIET_HOURS_*``, mas o *mecanismo* era todo
    campo de produto, e é o mecanismo que precisa ficar vermelho.
    """
    poisoned = _poisonable()
    for name, value in poisoned.items():
        monkeypatch.setenv(name.upper(), value)

    built = Settings()

    drifted = _drifted(built, poisoned)
    assert drifted == [], (
        f"{len(drifted)} de {len(poisoned)} campos de produto atravessaram do"
        " ambiente para uma `Settings` construída em teste: "
        + ", ".join(drifted[:8])
        + ("…" if len(drifted) > 8 else "")
        + ". A costura fica em `conftest.INHERITED_FROM_THE_ENVIRONMENT` —"
        " a bateria lê o ambiente para saber onde está um serviço, nunca para"
        " saber como o produto se comporta."
    )


def test_no_product_variable_reaches_a_settings_built_from_a_dotenv_file(
    tmp_path: Path,
) -> None:
    """A segunda porta, que a ADR 0058 não viu: o ``.env`` do disco.

    ``model_config`` carrega ``env_file=".env"``, e quem segue o ``cp
    .env.example .env`` do README tem um. Filtrar só ``env_settings`` deixaria
    esta metade aberta — medido: um ``.env`` com as duas linhas do horário de
    silêncio reprova **os mesmos cinco** testes que a variável exportada.

    O arquivo é escrito no ``tmp_path`` e entregue por ``_env_file=``, e não na
    raiz do repositório: um ``.env`` esquecido no disco é exatamente o estado que
    esta guarda existe para tornar inofensivo, e criá-lo aqui trocaria a prova
    pelo defeito.
    """
    poisoned = _poisonable()
    dotenv = tmp_path / "dot-env-envenenado"
    dotenv.write_text(
        "".join(f"{name.upper()}={value}\n" for name, value in poisoned.items()),
        encoding="utf-8",
    )

    built = Settings(_env_file=str(dotenv))

    drifted = _drifted(built, poisoned)
    assert drifted == [], (
        f"{len(drifted)} de {len(poisoned)} campos de produto atravessaram de um"
        " `.env` do disco para uma `Settings` construída em teste: "
        + ", ".join(drifted[:8])
        + ("…" if len(drifted) > 8 else "")
        + ". As fontes são duas (`env_settings` e `dotenv_settings`) e a costura"
        " precisa filtrar as duas."
    )


def test_the_poisoner_reaches_every_field_of_the_settings() -> None:
    """Completude do envenenador — sem isto a medição encolhe em silêncio.

    Um campo cujo tipo ``_poison_for`` não souber alterar sairia da conta sem
    nada ficar vermelho, e as duas guardas acima continuariam verdes sobre um
    universo menor. É o ``.priority`` da ADR 0033 na forma que a ADR 0038 mediu —
    *a cobertura de um portão é a dos ramos que a amostra percorre* —, e a
    resposta é a mesma: a amostra é parte do portão.
    """
    allowed = {name.lower() for name in INHERITED_FROM_THE_ENVIRONMENT}
    covered = set(_poisonable()) | allowed | set(CANNOT_BE_POISONED)
    missing = sorted(set(Settings.model_fields) - covered)

    assert missing == [], (
        "estes campos de `Settings` não entram na medição de isolamento: "
        + ", ".join(missing)
        + ". Ensine `_poison_for` a alterar o tipo, ou declare o campo em"
        " `CANNOT_BE_POISONED` com o motivo escrito."
    )


def test_the_poisoner_has_no_dead_exemption() -> None:
    """A isenção vence, como a do ``advisories.json`` e a do ``NOT_AN_ALERT``.

    Um campo que sumiu de ``Settings``, ou que ganhou tipo envenenável, e
    continua listado é allowlist que ninguém revisa — sedimento, na palavra da
    ADR 0033 — e a próxima pessoa a ler concluirá que a lacuna ali é decisão em
    vigor.
    """
    stale = sorted(
        name
        for name in CANNOT_BE_POISONED
        if name not in Settings.model_fields
        or _poison_for(Settings.model_fields[name]) is not None
    )

    assert stale == [], (
        "estes campos estão em `CANNOT_BE_POISONED` sem precisar: "
        + ", ".join(stale)
        + ". Tire a linha."
    )


#: Subclasses de ``Settings`` que a bateria pode construir lendo um arquivo que
#: elas mesmas nomeiam, com o motivo por linha.
#:
#: A costura deixa passar o ``dotenv`` de quem **nomeia o próprio arquivo**,
#: porque nomear é declarar — e sem essa saída um teste cuja pergunta é "este
#: template seria recusado?" responderia "sim, porque não li o template", que é a
#: resposta certa pela razão errada. A saída é estreita de propósito: o
#: ``os.environ`` continua filtrado até para elas, e uma subclasse nova entra
#: aqui com motivo escrito ou reprova.
DECLARES_ITS_OWN_ENV_FILE = {
    "FromTemplate": (
        "`test_homolog_config.py`; a pergunta dela é literalmente *o "
        "`.env.homolog.example` seria recusado pelo preflight?*, e o arquivo é o "
        "sujeito do teste — não o ambiente da máquina (ADR 0022)"
    ),
}


def _settings_subclasses_naming_a_file() -> dict[str, str]:
    """Toda ``class X(Settings)`` do diretório de testes que fixa um ``env_file``.

    Por AST, e não por ``Settings.__subclasses__()``: a classe é definida **dentro
    de uma função** de teste, então ela só existiria depois de aquele teste rodar
    — e uma guarda cuja amostra depende da ordem de execução mede o escalonador.
    """
    found: dict[str, str] = {}
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(
                isinstance(base, ast.Name) and base.id == "Settings" for base in node.bases
            ):
                continue
            names_a_file = any(
                keyword.arg == "env_file"
                for body in node.body
                for call in ast.walk(body)
                if isinstance(call, ast.Call)
                for keyword in call.keywords
            )
            if names_a_file:
                found[node.name] = f"{path.name}:{node.lineno}"
    return found


def test_every_settings_subclass_that_names_a_file_is_declared() -> None:
    """A saída da costura é estreita, e escrita.

    Uma subclasse de ``Settings`` com ``env_file`` próprio é a **única** forma de
    um arquivo do disco voltar a alcançar uma configuração de teste. Sem esta
    guarda a saída seria invisível: bastaria alguém escrever a subclasse para o
    isolamento sumir num arquivo, em verde — que é a forma do ``dependency-review``
    da ADR 0023, um portão que existe e não pergunta o que importa.
    """
    undeclared = sorted(
        f"{name} ({where})"
        for name, where in _settings_subclasses_naming_a_file().items()
        if name not in DECLARES_ITS_OWN_ENV_FILE
    )

    assert undeclared == [], (
        "estas subclasses de `Settings` nomeiam o próprio `env_file` e não estão"
        f" declaradas: {', '.join(undeclared)}. A costura deixa o `dotenv` delas"
        " passar inteiro — declare em `DECLARES_ITS_OWN_ENV_FILE` por que aquele"
        " arquivo é uma declaração do teste, e não herança do ambiente."
    )


def test_the_declared_subclass_list_has_no_dead_entries() -> None:
    """A isenção vence, como as outras três deste arquivo."""
    existing = _settings_subclasses_naming_a_file()
    stale = sorted(name for name in DECLARES_ITS_OWN_ENV_FILE if name not in existing)

    assert stale == [], (
        "estas linhas de `DECLARES_ITS_OWN_ENV_FILE` não nomeiam subclasse"
        f" nenhuma: {', '.join(stale)}. Tire a linha."
    )


def _ci_env_names() -> set[str]:
    """Toda variável declarada num bloco ``env:`` do workflow do CI.

    Varredura por indentação, e não ``yaml.safe_load``: o que interessa é o nome
    aparecer sob um ``env:``, em qualquer um dos sete jobs, e a estrutura do
    arquivo já responde isso sem uma dependência a mais.
    """
    names: set[str] = set()
    block_indent: int | None = None
    for raw in CI_WORKFLOW.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if raw.strip() == "env:":
            block_indent = indent
            continue
        if block_indent is None:
            continue
        if indent <= block_indent:
            block_indent = None
            continue
        key = raw.strip().split(":", 1)[0]
        if key.replace("_", "").isalnum() and key.isupper():
            names.add(key)
    return names


def test_the_inherited_allowlist_keeps_no_unnecessary_line() -> None:
    """Cada nome herdado é campo de ``Settings`` **e** vem de um ``env:`` do CI.

    As duas metades são o que impede a lista de virar a porta de trás da costura.
    Sem a primeira, um nome digitado errado isentaria nada e ninguém notaria; sem
    a segunda, bastaria acrescentar ``CONTACT_QUIET_HOURS_START`` aqui para o
    defeito da ADR 0058 voltar **por dentro da própria guarda** — que é a forma da
    allowlist vazia da ADR 0029, aquela que nada consultava.
    """
    ci_names = _ci_env_names()

    not_a_field = sorted(
        name for name in INHERITED_FROM_THE_ENVIRONMENT if name.lower() not in Settings.model_fields
    )
    assert not_a_field == [], (
        "estes nomes estão em `INHERITED_FROM_THE_ENVIRONMENT` e não são campo de"
        f" `Settings`: {', '.join(not_a_field)}. Isentam nada."
    )

    not_in_ci = sorted(name for name in INHERITED_FROM_THE_ENVIRONMENT if name not in ci_names)
    assert not_in_ci == [], (
        "estes nomes estão em `INHERITED_FROM_THE_ENVIRONMENT` e nenhum bloco"
        f" `env:` do `ci.yml` os passa ao processo de teste: {', '.join(not_in_ci)}."
        " A lista é para onde está um serviço, e um serviço que o CI não aponta"
        " não é herança — é comportamento de produto entrando pela porta de trás."
    )


# --------------------------------------------------------------------------- #
# Metade B — a bateria não herda estado
# --------------------------------------------------------------------------- #


def test_the_battery_never_reaches_a_real_broker(
    published_tasks: list[tuple[str, tuple, dict]],
) -> None:
    """Todo ``.delay()`` da bateria para na lista, e nunca no Redis do compose.

    A porta é única — ``Task.apply_async`` chama ``celery_app.send_task`` — e é
    por isso que a fixture intercepta ali em vez de nas nove funções ``queue_*``:
    uma lista escrita à mão envelheceria no décimo enfileiramento, que é a forma
    de defeito que a ADR 0035 mediu.

    O repositório já sabia disto e consertou **um** sítio: o docstring de
    ``queued_ingestions`` diz com todas as letras que "sem isto o upload
    publicaria de verdade no Redis do compose, e o worker que estiver de pé
    pegaria a task no meio do teste". O que faltava era a porta, e não o remendo.

    Sem a interceptação esta asserção fica vermelha nos **dois** ambientes, por
    motivos opostos: com o broker de pé a task foi publicada de verdade e a lista
    fica vazia; com ele parado o ``except`` de ``queue_pending_notification``
    engoliu a falha e a lista fica vazia do mesmo jeito.
    """
    from portal_api import worker

    project_id = str(uuid.uuid4())
    pending_id = str(uuid.uuid4())

    worker.queue_pending_notification(project_id, pending_id)

    assert [(name, args) for name, args, _ in published_tasks] == [
        ("portal_api.notify_pending_created", (project_id, pending_id))
    ], (
        "o enfileiramento não parou na bateria: `celery_app.send_task` não está"
        " interceptado, e o que este teste publicou foi para o broker de verdade"
        " — de onde o contêiner `worker`, que fala com o **mesmo banco**, o"
        " consome no meio da corrida."
    )


def _beat_sweeps() -> set[str]:
    """As varreduras globais do produto, derivadas do **AST** de ``worker.py``.

    Do AST e não do ``celery_app.conf.beat_schedule`` avaliado, e a diferença foi
    medida: cada entrada do agendador mora dentro de um ``if settings.<flag>``, e
    ``whatsapp_enabled`` é ``False`` por default — o agendador avaliado devolve
    quatro varreduras, ``send_due_whatsapp_notices`` some, e os dois testes que a
    acionam escapariam desta guarda **em verde**. É a forma da ADR 0038: a
    cobertura de um portão é a dos ramos que a amostra percorre, e aqui a amostra
    seria a configuração da máquina que roda a bateria — exatamente a herança que
    esta fatia existe para cortar.
    """
    tree = ast.parse(WORKER_SOURCE.read_text(encoding="utf-8"))
    sweeps: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            if ast.unparse(target.value) != "celery_app.conf.beat_schedule":
                continue
            for key, value in zip(node.value.keys, node.value.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "task"
                    and isinstance(value, ast.Constant)
                ):
                    sweeps.add(str(value.value).rsplit(".", 1)[-1])
    return sweeps


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if isinstance(func, ast.Attribute):
            names.add(func.attr)
        elif isinstance(func, ast.Name):
            names.add(func.id)
    return names


def test_every_test_that_triggers_a_global_sweep_declares_the_noisy_neighbour() -> None:
    """Quem aciona uma varredura global declara o vizinho barulhento.

    As cinco varreduras do beat são globais **por desenho** — ``purge_expired_data``
    visita toda organização, ``sync_due_drive_connections`` toda conexão
    habilitada, ``send_due_whatsapp_notices`` todo projeto com aviso pendente —, e
    isso não é defeito a consertar: o defeito é a asserção que trata o resultado
    de uma varredura global como se fosse do tenant do teste. ``assert queued ==
    []`` é a forma dele, e ficou verde por anos só porque o banco de quem rodava
    estava vazio.

    O vizinho é o que torna essa frouxidão **visível**: com ele no banco, uma
    asserção sobre total global reprova na hora, e a única forma de ficar verde é
    afirmar sobre a linha que o próprio teste criou.

    ``ast.walk`` e não ``tree.body``, pelo motivo já escrito em
    ``test_whatsapp.py``: um teste dentro de classe é teste.
    """
    sweeps = _beat_sweeps()
    assert sweeps, "nenhuma varredura derivada do `beat_schedule` — a guarda ficaria vazia"

    violations: list[str] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
                continue
            triggered = sorted(_called_names(node) & sweeps)
            if not triggered:
                continue
            declared = {arg.arg for arg in node.args.args} | {
                arg.arg for arg in node.args.kwonlyargs
            }
            if "noisy_neighbour" not in declared:
                violations.append(
                    f"{path.name}:{node.lineno} {node.name} (aciona {', '.join(triggered)})"
                )

    assert violations == [], (
        "teste(s) que acionam uma varredura global sem o vizinho barulhento no"
        " banco: " + "; ".join(violations) + ". Declare a fixture `noisy_neighbour`"
        " e afirme sobre as linhas que o próprio teste criou — uma asserção sobre"
        " total global mede também o que outro tenant deixou lá."
    )


#: Varreduras que o vizinho barulhento **não** alcança, com o motivo por linha.
#:
#: Uma linha aqui é uma afirmação, não uma omissão: sem ela a guarda de controle
#: positivo abaixo daria a varredura como coberta por não ter probe nenhum, que é
#: a allowlist vazia da ADR 0029 outra vez.
NOT_REACHED_BY_THE_NEIGHBOUR = {
    "run_erasure_requests": (
        "seleciona só pedido de apagamento que alguém **gravou**, e dar um ao "
        "vizinho o apagaria — a varredura cumpre uma decisão de pessoa (ADR 0017), "
        "não visita tenant. O ruído dele ali é por ausência, e é o certo"
    ),
}


@pytest.mark.integration
def test_the_noisy_neighbour_is_found_by_every_global_sweep(
    migrated_engine: Engine,
    noisy_neighbour: NoisyNeighbour,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Controle positivo: o vizinho é mesmo barulhento.

    Sem esta metade, ``noisy_neighbour`` poderia virar uma fixture que não é
    encontrada por varredura nenhuma e a Guarda 2b passaria a exigir um parâmetro
    decorativo — verde sobre nada, que é o modo de falha que a ADR 0033 mediu e a
    0035 repetiu ao dar ``POST /chat`` como coberto por um 404 de outra rota.

    O conjunto de varreduras sai do mesmo ``_beat_sweeps()`` da guarda 2b, e a
    completude é cobrada: toda varredura ou tem probe aqui, ou tem linha em
    ``NOT_REACHED_BY_THE_NEIGHBOUR`` com o motivo escrito.
    """
    from sqlalchemy.orm import Session

    from portal_api import onboarding, retention, worker
    from portal_api.config import Settings

    probed: dict[str, bool] = {}

    # --- sync_due_drive_connections: a conexão habilitada do vizinho ---------
    fanned_out: list[str] = []
    monkeypatch.setattr(worker, "queue_drive_sync", fanned_out.append)
    worker.sync_due_drive_connections()
    probed["sync_due_drive_connections"] = str(noisy_neighbour.drive_connection_id) in fanned_out

    # --- purge_expired_data: a poda visita toda organização ------------------
    with Session(migrated_engine) as session:
        probed["purge_expired_data"] = noisy_neighbour.organization_id in (
            retention.organizations_with_data(session)
        )

    # --- alert_stuck_onboarding: organização com projeto vivo e degrau parado -
    with Session(migrated_engine) as session:
        watched = noisy_neighbour.organization_id in onboarding.organizations_to_watch(session)
        reading = onboarding.read_funnel(session, noisy_neighbour.organization_id, Settings())
    probed["alert_stuck_onboarding"] = watched and reading is not None and reading.stuck

    # --- send_due_whatsapp_notices: projeto com aviso pendente ---------------
    # O canal é **declarado** pelo teste (`Settings(...)`), nunca herdado do
    # ambiente: é a regra da metade A aplicada à própria guarda.
    swept: list[str] = []
    channel = Settings(
        whatsapp_enabled=True,
        whatsapp_api_base="https://provider.test/v1",
        whatsapp_phone_number_id="55500",
        whatsapp_api_token="tok-local-only",
        # Janela de silêncio desligada: valores iguais, que é como um ambiente diz
        # "aqui pode a qualquer hora" (ADR 0043).
        contact_quiet_hours_start=0,
        contact_quiet_hours_end=0,
    )
    monkeypatch.setattr(worker, "get_settings", lambda: channel)
    monkeypatch.setattr(
        worker, "send_whatsapp_notices", lambda project_id: swept.append(project_id) or {"sent": 0}
    )
    worker.send_due_whatsapp_notices()
    probed["send_due_whatsapp_notices"] = str(noisy_neighbour.project_id) in swept

    sweeps = _beat_sweeps()
    uncovered = sorted(sweeps - set(probed) - set(NOT_REACHED_BY_THE_NEIGHBOUR))
    assert uncovered == [], (
        "estas varreduras do `beat_schedule` não são exercitadas contra o vizinho: "
        + ", ".join(uncovered)
        + ". Dê probe a cada uma, ou declare em `NOT_REACHED_BY_THE_NEIGHBOUR` por"
        " que ela não visita tenant."
    )

    deaf = sorted(name for name, found in probed.items() if not found)
    assert deaf == [], (
        "o vizinho barulhento não é encontrado por: "
        + ", ".join(deaf)
        + ". A fixture parou de fazer barulho, e a guarda 2b passou a exigir um"
        " parâmetro decorativo."
    )


def test_the_unreached_sweep_list_has_no_dead_entries() -> None:
    """A isenção vence, como a do ``NOT_AN_ALERT`` e a do ``ANCHORLESS``."""
    sweeps = _beat_sweeps()
    stale = sorted(name for name in NOT_REACHED_BY_THE_NEIGHBOUR if name not in sweeps)

    assert stale == [], (
        "estas linhas de `NOT_REACHED_BY_THE_NEIGHBOUR` não nomeiam varredura do"
        f" `beat_schedule`: {', '.join(stale)}. Tire a linha."
    )
