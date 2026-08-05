"""O ambiente de homologação, e o que impede um segredo local de vazar para ele.

Fase 5, ADR 0022. Nenhum teste aqui precisa de banco, de rede ou de Docker: o que
se afirma são propriedades de arquivos versionados e da função que os lê.

Dois grupos, e o segundo é o que dói mais. O primeiro cobre o `preflight`, que é
a recusa em tempo de execução. O segundo cobre a **correspondência entre o que
está documentado e o que chega ao contêiner** — que é onde esta fatia encontrou
o defeito que a motivou: `ANTHROPIC_API_KEY` estava no `.env.example` desde a
Fase 3, era lida pelo `config.py`, e nenhum compose a passava. O
`AnthropicResponder` nunca rodou na pilha de pé.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from pydantic_settings import SettingsConfigDict

from portal_api.config import Settings
from portal_api.preflight import UnsafeEnvironment, check, preflight

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_COMPOSE = REPO_ROOT / "docker-compose.yml"
HOMOLOG_COMPOSE = REPO_ROOT / "docker-compose.homolog.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
ENV_HOMOLOG = REPO_ROOT / ".env.homolog.example"


def _declared_names(env_file: Path) -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", env_file.read_text(), re.M))


def _service_env(compose: Path, service: str) -> dict[str, str]:
    parsed = yaml.safe_load(compose.read_text())
    return parsed["services"][service].get("environment", {}) or {}


def _without_comments(path: Path) -> str:
    """As linhas que o compose interpreta, sem as que só explicam.

    Os dois arquivos de compose falam sobre `${VAR:?}` e `${VAR:-default}` na
    própria prosa — é o assunto deles —, e uma varredura ingênua leria o
    comentário como se fosse configuração.
    """

    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )


# ---------------------------------------------------------------------------
# O preflight
# ---------------------------------------------------------------------------


def test_local_is_the_environment_that_may_do_anything() -> None:
    """Sem isto, todo `pytest` e todo `docker compose up` cru reprovariam.

    O padrão de `Settings.environment` é `local` justamente para que a recusa
    não precise ser desligada por quem está desenvolvendo.
    """

    assert check(Settings()) == []
    preflight(Settings())  # não levanta


def test_a_serious_environment_refuses_the_example_password() -> None:
    """A propriedade central da fatia.

    Todo `${VAR}` do compose base tem default local, então um `.env` de
    homologação a que falte uma chave sobe **verde** com a senha do exemplo. É a
    forma mais cara de um controle falhar: ele produz a evidência de que existe.
    """

    problems = check(Settings(environment="homolog"))

    assert any("DATABASE_URL" in problem for problem in problems)
    assert any("local_only" in problem for problem in problems)


def test_the_refusal_lists_every_problem_at_once() -> None:
    """Quem configura um ambiente novo erra em cinco variáveis, não em uma.

    Uma recusa por vez transformaria isso em cinco ciclos de deploy.
    """

    with pytest.raises(UnsafeEnvironment) as raised:
        preflight(Settings(environment="production"))

    message = str(raised.value)
    assert message.count("\n  - ") > 5
    assert "docs/runbooks/deploy.md" in message


def test_demo_mode_cannot_be_on_outside_local() -> None:
    """As rotas de demonstração respondem sem autenticação de verdade."""

    problems = check(Settings(environment="homolog", demo_mode=True))
    assert any("DEMO_MODE" in problem for problem in problems)


def test_a_plaintext_address_is_refused() -> None:
    """`app/lib/session.ts` decide pelo esquema de `AUTH_URL` se o cookie leva o
    prefixo `__Secure-`. Em http o portal sobe, loga, e guarda o token de acesso
    num cookie sem proteção nenhuma."""

    problems = check(Settings(environment="homolog", web_origin="http://portal.exemplo"))
    assert any("WEB_ORIGIN" in problem and "https" in problem for problem in problems)


def test_an_empty_secret_is_refused_even_though_it_already_fails_closed() -> None:
    """Vazio já é fail-closed em cada um destes — sem pepper nenhuma chave de
    agente autentica (ADR 0013). Mas fail-closed **silencioso** é exatamente o
    que faz um ambiente parecer saudável com metade dele desligada."""

    problems = check(Settings(environment="homolog", agent_key_pepper=""))
    assert any("AGENT_KEY_PEPPER" in problem and "vazio" in problem for problem in problems)


def test_a_new_setting_with_a_local_default_is_covered_without_being_listed() -> None:
    """A varredura é genérica, e é o que a mantém verdadeira daqui a um ano.

    Uma lista de nomes protegeria os campos de que alguém lembrou no dia em que
    escreveu o módulo. É o idioma do `test_openapi_contract.py`, que afirma sobre
    toda rota inclusive a que ninguém escreveu ainda.
    """

    problems = check(Settings(environment="homolog", storage_bucket="bucket-local-only"))
    assert any("STORAGE_BUCKET" in problem for problem in problems)


# ---------------------------------------------------------------------------
# O template de homologação
# ---------------------------------------------------------------------------


def test_the_homolog_template_is_itself_refused() -> None:
    """O template documenta a forma de uma configuração sem poder ser uma.

    `${VAR:?}` só sabe perguntar se a variável **tem** valor, nunca se o valor é
    seu — então um `.env` copiado daqui e preenchido pela metade passaria pelo
    compose. O `CHANGEME` é sentinela do `preflight` exatamente por isso.
    """

    class FromTemplate(Settings):
        model_config = SettingsConfigDict(
            env_file=ENV_HOMOLOG, case_sensitive=False, extra="ignore"
        )

    problems = check(FromTemplate())
    assert problems, "o template de homologação precisa ser recusado, não aceito"
    assert any("changeme" in problem for problem in problems)


def test_no_secret_in_the_homolog_override_has_a_local_default() -> None:
    """A regra que carrega o `docker-compose.homolog.yml`: `${VAR:?}`, nunca
    `${VAR:-default}`. Afirmada sobre a forma, para valer para a variável que
    alguém acrescentar amanhã."""

    text = _without_comments(HOMOLOG_COMPOSE)
    hints = ("PASSWORD", "SECRET", "TOKEN", "KEY", "PEPPER")
    # A allowlist existe pela razão da de `telemetry._SECRET_ALLOWLIST`, e é o
    # mesmo formato de defeito: um nome que *contém* a palavra sem ser a coisa.
    # Estes são endereços públicos do Google — o endpoint de troca de código, que
    # tem "TOKEN" no nome e é tão secreto quanto uma URL de documentação.
    allowed = {"GOOGLE_OAUTH_TOKEN_URL"}

    offenders = [
        name
        for name, default in re.findall(r"\$\{([A-Z][A-Z0-9_]*):-([^}]*)\}", text)
        if any(hint in name for hint in hints) and name not in allowed
    ]
    assert offenders == [], (
        f"estas variáveis de segredo têm default no override de homologação: {offenders}. "
        "Um default aqui significa subir com o valor do exemplo em silêncio."
    )


def test_every_variable_the_override_requires_is_in_the_template() -> None:
    """Nos dois sentidos a falha é a mesma: alguém descobre no `up`."""

    required = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*):\?", _without_comments(HOMOLOG_COMPOSE)))
    declared = _declared_names(ENV_HOMOLOG)

    assert required - declared == set(), (
        "o override exige variáveis que o `.env.homolog.example` não lista"
    )


# ---------------------------------------------------------------------------
# O defeito que motivou a fatia
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "variable",
    ["ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "CHAT_RATE_LIMIT", "LOG_LEVEL", "LOG_FORMAT"],
)
def test_the_chat_variables_reach_the_api_container(variable: str) -> None:
    """O defeito que a ADR 0022 encontrou, travado no lugar.

    As três primeiras existem no `.env.example` desde a Fase 3, são lidas pelo
    `config.py` — e **nenhum compose e nenhum workflow as passava** ao serviço
    `api`. O `AnthropicResponder` que a ADR 0021 construiu e testou com um falso
    nunca rodou na pilha de pé: o e2e, o navegador e qualquer medição local
    exercitavam o respondedor offline, sem erro nenhum no log.

    Este teste é o que impede a fatia seguinte de medir o Postgres achando que
    mede a IA.
    """

    assert variable in _service_env(BASE_COMPOSE, "api")


def test_no_documented_variable_is_a_button_wired_to_nothing() -> None:
    """A generalização do defeito acima, e ela pegou mais doze.

    Uma variável no `.env.example` que não aparece no compose é documentação de
    um controle que não existe — a mesma família do `chat_prompt_version` que
    ninguém lia (ADR 0021) e do `trace_id` que o runbook mandava preservar sem
    que houvesse `trace_id` (ADR 0018).
    """

    # O backup é operação, não aplicação (ADR 0019): `scripts/lib.sh` lê estas
    # três do `.env` diretamente, e nenhum contêiner as recebe.
    belongs_to_scripts = {"BACKUP_DIR", "BACKUP_AGE_RECIPIENT", "BACKUP_AGE_IDENTITY"}

    compose = _without_comments(BASE_COMPOSE)
    orphans = sorted(_declared_names(ENV_EXAMPLE) - belongs_to_scripts - set(re.findall(r"[A-Z][A-Z0-9_]*", compose)))

    assert orphans == [], (
        f"documentadas no `.env.example` e ausentes do compose: {orphans}. "
        "Ou a variável chega ao contêiner, ou ela sai da documentação."
    )
