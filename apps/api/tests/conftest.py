"""Shared fixtures.

Data-layer tests need a real PostgreSQL (enums, JSONB, schema-qualified DDL), so
they connect to the compose Postgres. When no database is reachable the fixtures
``pytest.skip`` so the unit suite — and any CI job without a database service —
still passes.

Three roles, three fixtures (ADR 0010):

``db_session``   runs as ``portal_system`` (BYPASSRLS). Tests that arrange data
                 across tenants, and every test written before RLS existed, use
                 it and are unaffected by the policies.
``rls_session``  runs as ``portal_app``, the credential the API actually uses.
                 This is the only way to observe the policies, so
                 ``test_rls_isolation.py`` uses it exclusively.
``migrated_engine`` runs as ``portal_migrator`` to apply the migrations.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from pydantic_settings import PydanticBaseSettingsSource
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from portal_api.db.session import DbRole, get_engine

API_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = API_ROOT / "alembic.ini"
MIGRATIONS_DIR = API_ROOT / "src" / "portal_api" / "db" / "migrations"


# --------------------------------------------------------------------------- #
# A bateria não herda **configuração** (ADR 0060)
#
# Regra única: *a bateria lê o ambiente para saber **onde está um serviço**,
# nunca para saber **como o produto se comporta***.
#
# A ADR 0058 fechou a porta do relógio e deixou esta aberta: `Settings` carrega
# `env_file=".env"` e lê `os.environ`, de modo que **toda** variável de produto
# atravessa para dentro do teste. Medido: `CONTACT_QUIET_HOURS_START=0
# CONTACT_QUIET_HOURS_END=0 pytest test_whatsapp.py` reprova cinco testes, e um
# `.env` no disco com as mesmas duas linhas reprova os mesmos cinco — são duas
# portas, não uma.
#
# A saída **não** é fixar os dois campos no `base` de `_settings()`: aquilo
# conserta 2 campos em 1 arquivo e deixa 101 campos de pé, que é a lista escrita
# à mão que a ADR 0033 mediu. A saída é trocar as *fontes* da `Settings`.
# --------------------------------------------------------------------------- #

#: O que a bateria **pode** herdar do ambiente, com o motivo por linha.
#:
#: Cada nome aqui responde "onde está um serviço", nunca "como o produto se
#: comporta", e cada um é passado ao processo de teste por um bloco `env:` do
#: `.github/workflows/ci.yml` — as duas condições são cobradas por
#: `test_battery_isolation.py`, que também reprova a linha que sobrou.
INHERITED_FROM_THE_ENVIRONMENT: dict[str, str] = {
    "DATABASE_URL": (
        "onde está o Postgres pelo caminho de requisição; o CI o aponta para o "
        "serviço do job (`ci.yml:48`) e a máquina de quem desenvolve, para o compose"
    ),
    "DATABASE_SYSTEM_URL": "o mesmo Postgres sob `portal_system` (`ci.yml:49`)",
    "DATABASE_MIGRATION_URL": "o mesmo Postgres sob `portal_migrator` (`ci.yml:50`)",
    "DATABASE_ADMIN_URL": "o mesmo Postgres sob `portal_admin` (`ci.yml:51`)",
    "STORAGE_ENDPOINT_URL": (
        "onde está o MinIO; o job `backup-restore` sobe o seu e o aponta (`ci.yml:119`)"
    ),
    "STORAGE_ACCESS_KEY": "credencial daquele MinIO, não comportamento (`ci.yml:120`)",
    "STORAGE_SECRET_KEY": "idem (`ci.yml:121`)",
}


class _OnlyWhereAServiceLives(PydanticBaseSettingsSource):
    """Envolve uma fonte do Pydantic e deixa passar só a allowlist.

    **Envolve** em vez de reconstruir: a instância que o Pydantic montou já sabe
    do ``env_file``, do ``case_sensitive`` e dos prefixos, e refazê-la aqui
    criaria um segundo lugar decidindo como uma variável vira campo — que é a
    divergência silenciosa contra a qual o ``textfold.py`` existe.

    O ``__name__`` sai do envolvido porque o laço de ``_settings_build_values``
    indexa o estado das fontes por esse nome: dois envelopes com o nome da classe
    envelope fariam a segunda fonte sobrescrever a primeira.
    """

    def __init__(self, inner: PydanticBaseSettingsSource) -> None:
        super().__init__(inner.settings_cls)
        self._inner = inner
        self.__name__ = type(inner).__name__

    def get_field_value(self, field, field_name: str):  # type: ignore[no-untyped-def]
        return self._inner.get_field_value(field, field_name)

    def _set_current_state(self, state: dict) -> None:
        super()._set_current_state(state)
        self._inner._set_current_state(state)

    def _set_settings_sources_data(self, states: dict) -> None:
        super()._set_settings_sources_data(states)
        self._inner._set_settings_sources_data(states)

    def __call__(self) -> dict:
        allowed = {name.lower() for name in INHERITED_FROM_THE_ENVIRONMENT}
        return {name: value for name, value in self._inner().items() if name in allowed}


def _seal_the_settings_sources() -> None:
    """Filtra **as duas** fontes de ambiente da ``Settings``.

    Duas e não uma: a variável exportada entra por ``env_settings`` e o ``.env``
    do disco entra por ``dotenv_settings``, e cada porta reprova sozinha os
    mesmos cinco testes de ``test_whatsapp.py`` (ADR 0060). Largar o ``dotenv``
    inteiro também não serve — quebraria quem guarda ``STORAGE_ACCESS_KEY`` no
    ``.env`` local, que é justamente o caso legítimo que a allowlist preserva.

    Roda no **nível de módulo** do conftest, e isso é medível em vez de estilo:
    ``worker.py`` chama ``get_settings()`` no import, monta o ``celery_app`` com
    ``settings.redis_url`` e deriva o ``beat_schedule`` de flags de ``Settings``.
    Uma fixture ``autouse``, ainda que de sessão, chegaria depois do import dos
    módulos de teste — tarde demais.
    """
    from portal_api.config import Settings, get_settings

    #: O arquivo **ambiente**: o `.env` que `Settings` lê sem ninguém pedir.
    ambient_env_file = Settings.model_config.get("env_file")

    @classmethod  # type: ignore[misc]
    def _customise(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # `init_settings` passa inteiro: `Settings(whatsapp_enabled=True)` é o
        # teste **declarando** o comportamento, que é o oposto de herdá-lo.
        #
        # E uma subclasse que **nomeia o próprio arquivo** também declara: é o
        # caso do `FromTemplate` de `test_homolog_config.py`, cuja pergunta
        # inteira é "o `.env.homolog.example` seria recusado?". Filtrar ali
        # responderia "sim, porque não li o arquivo", que é a resposta certa pela
        # razão errada — e foi medido: o teste ficou vermelho. O ambiente
        # continua filtrado mesmo para ela, porque `os.environ` nunca é uma
        # declaração de ninguém.
        declares_its_own_file = settings_cls.model_config.get("env_file") != ambient_env_file
        return (
            init_settings,
            _OnlyWhereAServiceLives(env_settings),
            dotenv_settings
            if declares_its_own_file
            else _OnlyWhereAServiceLives(dotenv_settings),
            file_secret_settings,
        )

    Settings.settings_customise_sources = _customise
    get_settings.cache_clear()


_seal_the_settings_sources()


def skip_unless_ci(reason: str) -> None:
    """Pula na máquina de quem desenvolve; **falha** no CI (ADR 0020).

    Um pulo é uma afirmação sobre o ambiente, não sobre o código: "aqui não dá
    para provar isto". Numa máquina sem Postgres no ar, é verdade e é útil — o
    `pytest` cru continua passando e ninguém precisa subir a pilha para rodar o
    teste de unidade.

    No CI a mesma frase é falsa, e cara: o job `api-quality` **tem** um Postgres
    de serviço, então um pulo ali não diz "não dá para provar", diz "o ambiente
    não está como se pensava" — e diz isso em verde. Foi assim que as três
    asserções de restore da ADR 0019 (policies de volta, GRANT de coluna ainda
    de coluna, uma organização sem ver a outra) deixaram de rodar sem que
    ninguém percebesse: faltavam duas variáveis no `env:` do job.

    É a regra da ADR 0017 outra vez — *`skipped` não é `clean`* —, agora
    aplicada ao próprio arsenal de testes. Vale só para os pulos que o CI deve
    cobrir; o que ele legitimamente não tem (ClamAV, chave da Voyage) continua
    pulando em silêncio, porque ali o pulo continua verdadeiro.
    """
    if os.environ.get("CI"):
        pytest.fail(f"{reason} — e no CI isto tinha de estar disponível")
    pytest.skip(reason)


@contextmanager
def captured(name: str) -> Iterator[list[logging.LogRecord]]:
    """Escuta um logger sem depender do estado global do ``logging``.

    O ``caplog`` do pytest e o nível herdado da raiz não servem: rodar a suíte
    inteira faz o Celery reconfigurar o logging da raiz ao executar uma task, e
    um teste que passa sozinho falha em conjunto. Um handler próprio, com nível
    fixado e restaurado no fim, torna a asserção independente de quem rodou
    antes.

    Mora aqui, e não ao lado do primeiro teste que precisou dela, porque a
    segunda a precisar foi a de outro módulo (o evento ``erasure.failed``, ADR
    0028) — e duplicar um utilitário cuja razão de existir é um comentário de
    dez linhas garante que uma das cópias envelheça sozinha.
    """
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger = logging.getLogger(name)
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


@pytest.fixture
def alembic_config() -> Config:
    return _alembic_config()


@pytest.fixture(scope="session")
def migrated_engine() -> Engine:
    """Apply migrations as the schema owner, then hand back the system engine.

    The skip is driven by reachability rather than by an unset ``DATABASE_URL``,
    because the settings default already points at the local compose Postgres.
    """
    migration_engine = get_engine(DbRole.migration)
    try:
        with migration_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        skip_unless_ci("PostgreSQL is not reachable; skipping database tests")

    command.upgrade(_alembic_config(), "head")
    return get_engine(DbRole.system)


@pytest.fixture(scope="session")
def app_engine(migrated_engine: Engine) -> Engine:
    """The request-path credential — subject to RLS.

    Depends on ``migrated_engine`` so the schema (and the policies) exist first.
    """
    return get_engine(DbRole.app)


def _transactional_session(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    """A ``portal_system`` session, rolled back after each test."""
    yield from _transactional_session(migrated_engine)


@pytest.fixture(scope="session")
def admin_engine(migrated_engine: Engine) -> Engine:
    """The access-administration credential (ADR 0011).

    Also subject to RLS — what it has that ``portal_app`` does not is the grant
    to write ``membership`` and a set of policies keyed on the third-stage GUC.
    """
    return get_engine(DbRole.admin)


@pytest.fixture
def admin_session(admin_engine: Engine) -> Iterator[Session]:
    """A ``portal_admin`` session, rolled back after each test."""
    yield from _transactional_session(admin_engine)


@pytest.fixture
def rls_session(app_engine: Engine) -> Iterator[Session]:
    """A ``portal_app`` session — the one the policies actually apply to.

    ``set_config(..., true)`` issued through this session lands on the outer
    transaction opened here and is reverted by the rollback in teardown, so
    tenant context never leaks between tests.
    """
    yield from _transactional_session(app_engine)


@pytest.fixture
def agent_pepper(monkeypatch: pytest.MonkeyPatch) -> str:
    """Configura o pepper do HMAC das chaves de agente (ADR 0013).

    ``hash_key`` levanta sem ele de propósito — falha fechada, para um ambiente
    mal configurado não abrir a rota de ingestão com hash previsível. Os testes
    precisam então ligá-lo explicitamente, e o valor é local a cada teste.
    """
    from portal_api.config import get_settings

    monkeypatch.setattr(get_settings(), "agent_key_pepper", "pepper-for-tests")
    return "pepper-for-tests"


@pytest.fixture
def agent_key(
    migrated_engine: Engine, agent_pepper: str
) -> Iterator[Callable[..., str]]:
    """Cria uma chave real de um projeto e devolve a chave **em claro**.

    Grava por uma sessão própria e comitada: a API responde em outra conexão e
    não enxergaria a transação aberta de um fixture rolled-back — o mesmo motivo
    pelo qual o ``world`` de ``test_authorization.py`` comita.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import delete

    from portal_api.agent_auth import generate_key, hash_key
    from portal_api.models import AgentApiKey, AgentEvent, AuditLog

    created: list[uuid.UUID] = []
    touched: set[uuid.UUID] = set()

    def _create(tenant, *, expires_in_days: int = 30, scopes=None, revoked: bool = False) -> str:
        key, prefix = generate_key()
        with Session(migrated_engine) as session:
            record = AgentApiKey(
                organization_id=tenant.organization_id,
                project_id=tenant.project_id,
                name="test key",
                key_prefix=prefix,
                key_hash=hash_key(key),
                scopes=["events:write"] if scopes is None else scopes,
                expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days),
                revoked_at=datetime.now(timezone.utc) if revoked else None,
            )
            session.add(record)
            session.commit()
            created.append(record.id)
            touched.add(tenant.project_id)
        return key

    yield _create

    # A ingestão comita — é uma requisição HTTP de verdade, não uma transação do
    # teste — então o que ela deixou para trás precisa sair aqui, ou um teste
    # posterior herda eventos e linhas de auditoria que não pediu.
    with Session(migrated_engine) as session:
        for project_id in touched:
            session.execute(delete(AgentEvent).where(AgentEvent.project_id == project_id))
            session.execute(
                delete(AuditLog).where(
                    AuditLog.project_id == project_id,
                    AuditLog.action == "agent_event.ingested",
                )
            )
        for key_id in created:
            record = session.get(AgentApiKey, key_id)
            if record is not None:
                session.delete(record)
        session.commit()


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Storage de objetos em memória (Fase 4, ADR 0014).

    O adapter real é fino e o que ele fala é S3; quem prova essa conversa é o
    ``tests/e2e/documents.spec.ts``, contra o MinIO do compose. Aqui interessa o
    que acontece com os bytes **depois** — extração, chunking, embeddings — e
    para isso um dicionário basta e não exige um serviço no ar.
    """
    from portal_api import storage

    objects: dict[str, bytes] = {}
    content_types: dict[str, str | None] = {}

    def _put(_settings, key: str, data: bytes, content_type: str | None) -> None:
        objects[key] = data
        content_types[key] = content_type

    def _get(_settings, key: str) -> bytes:
        if key not in objects:
            raise storage.StorageError(f"Falha ao ler {key}")
        return objects[key]

    def _delete(_settings, key: str) -> None:
        objects.pop(key, None)
        content_types.pop(key, None)

    def _fetch(_settings, key: str) -> storage.StoredObject:
        return storage.StoredObject(
            key=key, data=_get(_settings, key), content_type=content_types.get(key)
        )

    def _iter_keys(_settings, prefix: str = ""):
        return iter(sorted(k for k in objects if k.startswith(prefix)))

    monkeypatch.setattr(storage, "put_object", _put)
    monkeypatch.setattr(storage, "get_object", _get)
    monkeypatch.setattr(storage, "delete_object", _delete)
    # O backup (ADR 0019) lê pelos dois abaixo; ficam no mesmo fake para não
    # existirem dois storages de mentira que possam discordar um do outro.
    monkeypatch.setattr(storage, "fetch_object", _fetch)
    monkeypatch.setattr(storage, "iter_keys", _iter_keys)
    return objects


@pytest.fixture
def queued_ingestions(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Intercepta o enfileiramento, para o teste rodar a task quando quiser.

    Sem isto o upload publicaria de verdade no Redis do compose, e o worker que
    estiver de pé pegaria a task no meio do teste.

    Intercepta as **duas** portas. Desde a ADR 0017 quem enfileira o documento
    novo é ``queue_document_scan``, e ``queue_document_ingestion`` passou a ser
    chamada só pela varredura depois do veredito — deixar uma de fora faria a
    task escapar para o broker de verdade em metade dos caminhos.
    """
    from portal_api import worker

    queued: list[str] = []
    monkeypatch.setattr(worker, "queue_document_scan", queued.append)
    monkeypatch.setattr(worker, "queue_document_ingestion", queued.append)
    return queued


@dataclass(frozen=True)
class NoisyNeighbour:
    """Os ids do vizinho, para o teste poder afirmar a **ausência** deles."""

    organization_id: uuid.UUID
    project_id: uuid.UUID
    drive_connection_id: uuid.UUID
    notification_id: uuid.UUID
    internal_user_id: uuid.UUID
    client_user_id: uuid.UUID


@pytest.fixture
def noisy_neighbour(migrated_engine: Engine) -> Iterator[NoisyNeighbour]:
    """Uma organização estrangeira que **toda** varredura global encontra (ADR 0060).

    As cinco varreduras do ``beat_schedule`` são globais por desenho — o
    ``sync_due_drive_connections`` procura toda conexão habilitada, o
    ``send_due_whatsapp_notices`` todo projeto com aviso pendente, o
    ``alert_stuck_onboarding`` toda organização com projeto vivo. Não há o que
    consertar nelas; o que estava errado eram as asserções que tratavam o
    resultado de uma varredura global como se fosse do tenant do teste, e ficavam
    verdes porque o banco de quem rodava estava vazio.

    Este vizinho é o que torna essa frouxidão visível. Comitado de verdade, e não
    por uma sessão transacional: a task abre conexão própria e não enxergaria uma
    transação ainda aberta — a mesma razão do ``world`` de
    ``test_authorization.py``.

    O ``refresh_token_sealed`` **não** é um ciphertext de verdade, e é uma
    escolha: nenhuma varredura o abre — o tick só seleciona ids e enfileira —, e
    um teste que executasse o sync deste vizinho quebraria aqui. Quebrar é a
    resposta certa: o vizinho existe para ser encontrado e ignorado, não para ser
    processado.

    A pessoa do cliente fica **sem** ``external_subject`` e com o convite recuado,
    que é o que a deixa travada no primeiro degrau do funil — a corroboração de
    login que a ADR 0040 acrescentou é justamente o ``external_subject``.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import delete

    from portal_api.models import (
        ContactEvent,
        MemberRole,
        Membership,
        Notification,
        NotificationKind,
        OnboardingStep,
        Organization,
        Project,
        ProjectDriveConnection,
        ProjectStatus,
        User,
    )

    tag = uuid.uuid4().hex[:8]
    with Session(migrated_engine) as session:
        organization = Organization(name="Vizinho Barulhento", slug=f"vizinho-{tag}")
        session.add(organization)
        session.flush()
        project = Project(
            organization_id=organization.id,
            name="Projeto do Vizinho",
            slug=f"vizinho-projeto-{tag}",
            status=ProjectStatus.in_implementation,
        )
        internal = User(
            email=f"interno-vizinho-{tag}@labs.test",
            full_name="Interno do Vizinho",
            is_internal=True,
        )
        client_person = User(
            email=f"cliente-vizinho-{tag}@vizinho.test", full_name="Cliente do Vizinho"
        )
        session.add_all([project, internal, client_person])
        session.flush()
        session.add_all(
            [
                Membership(
                    organization_id=organization.id,
                    project_id=None,
                    user_id=internal.id,
                    role=MemberRole.internal_admin,
                ),
                Membership(
                    organization_id=organization.id,
                    project_id=project.id,
                    user_id=client_person.id,
                    role=MemberRole.client_member,
                    # Convidado há muito tempo e nunca entrou: é o que o alerta do
                    # funil procura, e o que faz esta organização aparecer na conta
                    # de quem contar totais.
                    created_at=datetime.now(timezone.utc) - timedelta(days=400),
                ),
            ]
        )
        connection = ProjectDriveConnection(
            organization_id=organization.id,
            project_id=project.id,
            folder_id=f"pasta-do-vizinho-{tag}",
            folder_name="Pasta do Vizinho",
            google_account_email="vizinho@exemplo.test",
            refresh_token_sealed="selado-do-vizinho-nunca-aberto",
            granted_scope="https://www.googleapis.com/auth/drive.readonly",
            connected_at=datetime.now(timezone.utc),
            enabled=True,
        )
        notification = Notification(
            organization_id=organization.id,
            project_id=project.id,
            user_id=client_person.id,
            kind=NotificationKind.milestone_done,
            title="Aviso do vizinho",
            occurred_at=datetime.now(timezone.utc),
            dedupe_key=f"vizinho-{tag}",
        )
        session.add_all([connection, notification])
        session.commit()
        built = NoisyNeighbour(
            organization_id=organization.id,
            project_id=project.id,
            drive_connection_id=connection.id,
            notification_id=notification.id,
            internal_user_id=internal.id,
            client_user_id=client_person.id,
        )

    yield built

    with Session(migrated_engine) as cleanup:
        cleanup.execute(
            delete(ProjectDriveConnection).where(
                ProjectDriveConnection.organization_id == built.organization_id
            )
        )
        cleanup.execute(
            delete(ContactEvent).where(ContactEvent.organization_id == built.organization_id)
        )
        cleanup.execute(
            delete(Notification).where(Notification.organization_id == built.organization_id)
        )
        cleanup.execute(
            delete(OnboardingStep).where(
                OnboardingStep.organization_id == built.organization_id
            )
        )
        cleanup.execute(
            delete(Membership).where(Membership.organization_id == built.organization_id)
        )
        cleanup.execute(delete(Project).where(Project.id == built.project_id))
        cleanup.execute(
            delete(User).where(User.id.in_([built.internal_user_id, built.client_user_id]))
        )
        cleanup.execute(delete(Organization).where(Organization.id == built.organization_id))
        cleanup.commit()


@pytest.fixture(autouse=True)
def published_tasks(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple, dict]]:
    """A bateria não alcança broker de verdade (ADR 0060).

    ``autouse`` e na **porta única**: todo ``.delay()`` do repositório desce por
    ``Task.apply_async`` até ``celery_app.send_task``, então interceptar ali cobre
    os nove ``queue_*`` de hoje e o décimo que alguém escrever amanhã. É o padrão
    da ADR 0035 — a lista escrita à mão vira predicado derivado.

    O repositório já sabia do defeito e o consertou num sítio só: o docstring de
    :func:`queued_ingestions` diz, com todas as letras, *"sem isto o upload
    publicaria de verdade no Redis do compose, e o worker que estiver de pé
    pegaria a task no meio do teste"*. O que faltava era a porta.

    E o preço de não a ter foi medido: com o contêiner ``worker`` de pé,
    ``test_a_client_only_sees_and_reads_their_own_notifications`` reprovava porque
    outro teste do mesmo arquivo faz ``POST /chat`` de verdade, a pendência é
    publicada, o worker a consome contra o **mesmo banco** e insere na caixa do
    cliente uma notificação que aquele teste não criou. Parar o worker fazia o
    mesmo teste, no mesmo banco, passar — logo não era resíduo de corrida
    anterior, era o processo ao lado escrevendo durante a corrida.

    A lista devolvida é o que o teste inspeciona quando quer afirmar sobre o
    enfileiramento; quem não a declara continua protegido do mesmo jeito.
    """
    from portal_api import worker

    published: list[tuple[str, tuple, dict]] = []

    def _send_task(name, args=None, kwargs=None, **options):  # type: ignore[no-untyped-def]
        published.append((name, tuple(args or ()), dict(kwargs or {})))
        # Um objeto com `id`, que é o contrato que `AsyncResult` cumpre para quem
        # guarda o retorno. Nenhum `queue_*` guarda hoje, e devolver `None` faria
        # o primeiro que guardasse falhar por uma razão que não é a dele.
        return SimpleNamespace(id=options.get("task_id") or str(uuid.uuid4()))

    monkeypatch.setattr(worker.celery_app, "send_task", _send_task)
    return published


@pytest.fixture
def bind_context(rls_session: Session) -> Callable[..., None]:
    """Set the RLS GUCs on ``rls_session``.

    Mirrors what ``db.session.bind_principal``/``bind_user``/``bind_tenant`` do
    at runtime, but lets a test set any subset — including none, to assert the
    fail-closed behaviour.
    """

    def _bind(
        *,
        subject: str | None = None,
        email: str | None = None,
        user_id: uuid.UUID | None = None,
        organization_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
    ) -> None:
        values = {
            "portal.subject": subject or "",
            "portal.email": (email or "").lower(),
            "portal.user_id": str(user_id) if user_id else "",
            "portal.organization_id": str(organization_id) if organization_id else "",
            "portal.project_id": str(project_id) if project_id else "",
        }
        for name, value in values.items():
            rls_session.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": name, "value": value},
            )

    return _bind


@pytest.fixture
def bind_admin_context(admin_session: Session) -> Callable[..., None]:
    """Set the GUCs on ``admin_session`` — including the third stage (ADR 0011).

    Same idea as ``bind_context``: any subset, so a test can assert what is
    visible *before* ``portal.admin_organization_id`` is published, which is the
    window in which the endpoint verifies the caller's own role.
    """

    def _bind(
        *,
        subject: str | None = None,
        email: str | None = None,
        user_id: uuid.UUID | None = None,
        admin_organization_id: uuid.UUID | None = None,
        invitee_subject: str | None = None,
    ) -> None:
        values = {
            "portal.subject": subject or "",
            "portal.email": (email or "").lower(),
            "portal.user_id": str(user_id) if user_id else "",
            "portal.admin_organization_id": (
                str(admin_organization_id) if admin_organization_id else ""
            ),
            "portal.invitee_subject": invitee_subject or "",
        }
        for name, value in values.items():
            admin_session.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": name, "value": value},
            )

    return _bind
