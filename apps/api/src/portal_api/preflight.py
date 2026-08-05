"""O que o processo confere sobre si mesmo antes de aceitar tráfego (Fase 5, ADR 0022).

Um só lugar decide se esta configuração pode ser a de um ambiente sério, na forma
de ``notifications.py`` e ``conversations.py``: se "o que impede a homologação de
subir com a senha do exemplo" estiver espalhado, a pergunta deixa de ter resposta
que se leia num arquivo.

**Por que isto existe.** Todo ``${VAR}`` do ``docker-compose.yml`` tem default
local — ``AGENT_KEY_PEPPER:-agent-pepper-local-only``,
``AUTH_SECRET:-portal_auth_local_only``, e assim por diante. É a escolha certa
para a stack de desenvolvimento, que precisa subir com ``cp .env.example .env``,
e é uma armadilha para qualquer outra: um ``.env`` de homologação a que falte uma
chave **sobe verde, com o segredo do exemplo**. Nada fica vermelho, nada avisa, e
o portal fica publicamente acessível com uma senha que está num arquivo
versionado. É a forma mais cara de um controle falhar, porque ele produz a
evidência de que existe — a mesma que a ADR 0021 encontrou na setting de versão
de prompt que ninguém lia.

O ``docker-compose.homolog.yml`` fecha metade disso exigindo as variáveis na
forma ``${VAR:?}``, que faz o **compose** recusar. Este módulo fecha a outra
metade, e as duas são necessárias por razões diferentes: o compose só protege
quem sobe pelo compose, e o valor pode estar presente e ainda assim ser o do
exemplo — presença não é qualidade.

**A regra é a da ADR 0017**, aplicada à configuração em vez de ao antivírus: um
ambiente que não consegue provar que está seguro não afirma que está. Lá,
``skipped`` não é ``clean``; aqui, "a variável está definida" não é "o segredo é
seu".

Duas escolhas de forma que valem registrar:

*A varredura por sentinela é genérica, não uma lista de campos.* Ela olha **todo**
valor de texto das settings à procura das marcas do exemplo, então uma setting
acrescentada amanhã com um default local já nasce coberta — o idioma do
``test_openapi_contract.py``, que afirma sobre toda rota inclusive a que ninguém
escreveu ainda. Uma lista de nomes protegeria exatamente os campos de que alguém
lembrou.

*A recusa junta todos os problemas numa mensagem só.* Quem está configurando um
ambiente novo erra em cinco variáveis, não em uma, e uma recusa por vez transforma
isso em cinco ciclos de deploy.
"""

from __future__ import annotations

import logging

from portal_api.config import Settings

logger = logging.getLogger(__name__)

#: O ambiente que pode tudo. É o único valor em que este módulo não faz nada, e
#: é o padrão de ``Settings.environment`` — de modo que um `pytest` cru e um
#: `docker compose up` sem `.env` seguem funcionando como sempre funcionaram.
LOCAL = "local"

#: As marcas que o repositório usa nos valores de exemplo. Estão no
#: `.env.example`, nos defaults do `config.py` e nos `${VAR:-...}` do compose;
#: qualquer uma delas num ambiente sério significa que a variável não foi
#: fornecida e o default entrou no lugar.
#:
#: ``changeme`` cobre o outro caminho, que é o do `.env.homolog.example`: um
#: template preenchido pela metade passa pela exigência do compose (a variável
#: **tem** valor) e falharia em silêncio sem esta marca. É por ela que o próprio
#: template é um arquivo que o `preflight` recusa — ele documenta a forma sem
#: poder ser usado como configuração.
_SENTINELS = ("local_only", "local-only", "localhost", "127.0.0.1", "changeme")

#: Segredos cuja **ausência** é falha de configuração fora de `local`.
#:
#: Vazio já é fail-closed em cada um destes — sem pepper nenhuma chave de agente
#: autentica (ADR 0013), sem chave de cifra o conector do Drive responde 503
#: (ADR 0016) —, mas fail-closed silencioso é justamente o que faz um ambiente
#: parecer saudável enquanto metade dele está desligada. Aqui a falha passa a ter
#: hora marcada: a subida.
_REQUIRED_SECRETS = (
    "agent_key_pepper",
    "drive_token_encryption_key",
    "keycloak_admin_client_secret",
    "biahflow_webhook_secret",
    "storage_secret_key",
    "storage_access_key",
)

#: Endereços que o navegador usa. Em texto claro, o cookie de sessão do Auth.js
#: não recebe o prefixo `__Secure-` (`app/lib/session.ts` decide isso pelo
#: esquema de `AUTH_URL`) e o token de acesso trafega exposto.
_MUST_BE_HTTPS = (
    "web_origin",
    "portal_web_url",
    "oidc_issuer",
)


class UnsafeEnvironment(RuntimeError):
    """Esta configuração não pode ser a de um ambiente sério.

    Levantada na importação do módulo da aplicação, e não numa rota de saúde, de
    propósito: um processo que já aceitou uma requisição com a senha do exemplo
    não tem como desfazer isso. O `/health/ready` responderia depois do fato.
    """


def _sentinel_in(value: str) -> str | None:
    lowered = value.lower()
    for sentinel in _SENTINELS:
        if sentinel in lowered:
            return sentinel
    return None


def check(settings: Settings) -> list[str]:
    """Devolve todos os problemas desta configuração. Lista vazia é o verde.

    Separada de :func:`preflight` para poder ser testada sem derrubar o
    processo, e para o runbook de deploy poder listar o que falta sem tentar
    subir.
    """

    if settings.environment.strip().lower() == LOCAL:
        return []

    problems: list[str] = []

    if settings.demo_mode:
        problems.append(
            "DEMO_MODE está ligado — as rotas de demonstração respondem sem "
            "autenticação de verdade e o dashboard tem uma porta para dado fabricado"
        )

    dumped = settings.model_dump()
    for field, value in sorted(dumped.items()):
        if not isinstance(value, str) or not value:
            continue
        sentinel = _sentinel_in(value)
        if sentinel is not None:
            why = (
                "o template não foi preenchido"
                if sentinel == "changeme"
                else "a variável não foi fornecida e o default local entrou no lugar"
            )
            problems.append(
                f"{field.upper()} ainda carrega o valor de exemplo "
                f"(contém {sentinel!r}) — {why}"
            )

    for field in _REQUIRED_SECRETS:
        if not getattr(settings, field, "").strip():
            problems.append(
                f"{field.upper()} está vazio — o controle que ele sustenta falha "
                f"fechado e em silêncio, que é pior do que não subir"
            )

    for field in _MUST_BE_HTTPS:
        value = getattr(settings, field, "")
        if value and not value.startswith("https://"):
            problems.append(
                f"{field.upper()} não é https — sem TLS o cookie de sessão perde o "
                f"prefixo `__Secure-` e o token de acesso trafega em claro"
            )

    return problems


def preflight(settings: Settings) -> None:
    """Recusa continuar se esta configuração não puder ser a de um ambiente sério."""

    problems = check(settings)
    if not problems:
        # Só diz algo quando há o que dizer sobre um ambiente que não é o local:
        # uma linha por processo local seria ruído em toda `pytest`.
        if settings.environment.strip().lower() != LOCAL:
            logger.info(
                "preflight.ok",
                extra={"environment": settings.environment},
            )
        return

    listed = "\n".join(f"  - {problem}" for problem in problems)
    logger.error(
        "preflight.refused",
        extra={"environment": settings.environment, "problems": len(problems)},
    )
    raise UnsafeEnvironment(
        f"ENVIRONMENT={settings.environment} e esta configuração não sustenta "
        f"esse nome:\n{listed}\n"
        "Ver docs/runbooks/deploy.md. Para uma máquina de desenvolvimento, o "
        "valor certo é ENVIRONMENT=local."
    )
