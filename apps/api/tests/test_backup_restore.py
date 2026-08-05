"""Backup e restore (Fase 5, ADR 0019).

O que estes testes precisam provar não é "o dump roda". É que o backup **falha
quando deveria** e que o restore devolve as garantias, não só as linhas:

- a credencial de requisição não consegue tirar um backup, e a flag que cala a
  recusa devolve um dump vazio de sucesso — o modo de falha que o script existe
  para impedir;
- depois do restore, a RLS está de pé, os GRANTs de coluna continuam sendo de
  coluna, e uma organização não vê a outra. Um restore que traz os dados e perde
  as policies devolve um portal em que tudo parece funcionar.

A metade do storage é exercitada sem rede: o que interessa nela é o índice e o
SHA-256, não a conversa com o S3 — essa quem prova é o e2e, contra o MinIO.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from conftest import skip_unless_ci
from portal_api import backup, storage
from portal_api.config import Settings
from portal_api.db.session import DbRole, get_engine

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"
RESTORE_DB = "portal_backup_test"


# --- os objetos: sem banco e sem rede ---------------------------------------


def test_a_member_name_that_is_not_a_tenant_key_is_refused() -> None:
    """A chave é o que diz de quem é o objeto (ADR 0014); fora dela, não diz.

    Nada aqui é extraído para disco, então travessia de caminho não é a ameaça —
    a ameaça é gravar no bucket sob uma chave que nenhum tenant descreve, e que
    portanto o expurgo por prefixo da ADR 0017 nunca alcançaria.
    """
    for name in ("/org/1/x", "org/../../etc/passwd", "org//x", "", "../x"):
        with pytest.raises(backup.BackupError):
            backup._validate_member_name(name)


def test_objects_round_trip_preserving_bytes_and_content_type(
    fake_storage: dict[str, bytes], tmp_path: Path
) -> None:
    """Dois tenants entram, o bucket é esvaziado, os dois voltam.

    O content type volta junto porque a citação da ADR 0017 é um link: um PDF
    restaurado como ``application/octet-stream`` faz o navegador baixar o arquivo
    em vez de abrir a página citada.
    """
    settings = Settings()
    acme, globex = uuid.uuid4(), uuid.uuid4()
    storage.put_object(settings, f"org/{acme}/doc.pdf", b"contrato da acme", "application/pdf")
    storage.put_object(settings, f"org/{globex}/doc.txt", b"nota da globex", "text/plain")

    archive = tmp_path / "objects.tar"
    dumped = backup.dump_objects(settings, archive)
    assert dumped.objects == 2

    fake_storage.clear()
    restored = backup.restore_objects(settings, archive)

    assert restored.objects == 2
    assert fake_storage[f"org/{acme}/doc.pdf"] == b"contrato da acme"
    assert storage.fetch_object(settings, f"org/{acme}/doc.pdf").content_type == (
        "application/pdf"
    )


def test_a_prefix_backs_up_one_organization_only(
    fake_storage: dict[str, bytes], tmp_path: Path
) -> None:
    """O prefixo do tenant serve ao backup pelo mesmo motivo que serve ao expurgo."""
    settings = Settings()
    acme, globex = uuid.uuid4(), uuid.uuid4()
    storage.put_object(settings, f"org/{acme}/doc.pdf", b"acme", None)
    storage.put_object(settings, f"org/{globex}/doc.pdf", b"globex", None)

    result = backup.dump_objects(settings, tmp_path / "acme.tar", prefix=f"org/{acme}/")

    assert result.objects == 1
    with tarfile.open(tmp_path / "acme.tar") as tar:
        assert f"org/{globex}/doc.pdf" not in tar.getnames()


def test_a_corrupted_object_is_refused_instead_of_restored(
    fake_storage: dict[str, bytes], tmp_path: Path
) -> None:
    """Bytes que não batem com o hash não voltam ao bucket.

    Restaurar um arquivo corrompido é pior que falhar: a citação continuaria
    abrindo um link, só que para algo que não é mais o que foi citado.
    """
    settings = Settings()
    key = f"org/{uuid.uuid4()}/doc.pdf"
    storage.put_object(settings, key, b"conteudo original", "application/pdf")
    archive = tmp_path / "objects.tar"
    backup.dump_objects(settings, archive)

    _rewrite_tar_member(archive, key, b"conteudo adulterado")
    fake_storage.clear()

    with pytest.raises(backup.BackupError, match="sha256 divergente"):
        backup.restore_objects(settings, archive)
    assert fake_storage == {}


def test_a_tar_without_an_index_is_not_a_backup(tmp_path: Path) -> None:
    archive = tmp_path / "qualquer.tar"
    with tarfile.open(archive, "w") as tar:
        info = tarfile.TarInfo(name="org/1/doc.pdf")
        info.size = 3
        tar.addfile(info, io.BytesIO(b"abc"))

    with pytest.raises(backup.BackupError, match="não tem índice"):
        backup.restore_objects(Settings(), archive)


def _rewrite_tar_member(archive: Path, key: str, data: bytes) -> None:
    """Troca o conteúdo de um membro preservando o índice — a corrupção real."""
    with tarfile.open(archive) as tar:
        members = {m.name: (m, tar.extractfile(m.name).read()) for m in tar.getmembers()}  # type: ignore[union-attr]
    members[key] = (members[key][0], data)
    with tarfile.open(archive, "w") as tar:
        for name, (info, payload) in members.items():
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))


# --- o banco: precisa de Postgres e de um cliente da mesma versão ------------


def _server_major(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text("SHOW server_version_num")).scalar_one()) // 10000


def _client_major(binary: str) -> int | None:
    resolved = shutil.which(binary) or (binary if Path(binary).exists() else None)
    if resolved is None:
        return None
    out = subprocess.run([resolved, "--version"], capture_output=True, text=True)
    try:
        return int(out.stdout.split()[-1].split(".")[0])
    except (IndexError, ValueError):
        return None


@pytest.fixture(scope="module")
def pg_tools(migrated_engine: Engine) -> dict[str, str]:
    """Os binários do Postgres, se houver algum compatível com o servidor.

    ``pg_dump`` recusa um servidor mais novo que ele, então o teste **pula** em
    vez de falhar quando o cliente da máquina é antigo — mesma decisão do
    ``conftest`` para a ausência de banco. As variáveis permitem apontar para o
    binário do contêiner; o runbook mostra como.
    """
    tools = {
        "PSQL": os.environ.get("PSQL", "psql"),
        "PG_DUMP": os.environ.get("PG_DUMP", "pg_dump"),
        "PG_RESTORE": os.environ.get("PG_RESTORE", "pg_restore"),
    }
    server = _server_major(migrated_engine)
    for name, binary in tools.items():
        client = _client_major(binary)
        if client is None:
            skip_unless_ci(f"{binary} não encontrado; defina {name}")
        if client < server:
            skip_unless_ci(f"{binary} é {client} e o servidor é {server}")
    return tools


@pytest.fixture(scope="module")
def script_env(pg_tools: dict[str, str]) -> dict[str, str]:
    """O ambiente dos scripts, derivado das mesmas URLs que o pytest já usa."""
    settings = Settings()
    env = {**os.environ, **pg_tools}
    env.update(
        {
            "DATABASE_URL": settings.database_url,
            "DATABASE_SYSTEM_URL": settings.database_system_url,
            "DATABASE_MIGRATION_URL": settings.database_migration_url,
            "PYTHONPATH": str(REPO_ROOT / "apps" / "api" / "src"),
        }
    )
    for key in ("POSTGRES_USER", "POSTGRES_PASSWORD"):
        env.setdefault(key, "")
    return env


def _libpq(url: str) -> str:
    return url.replace("+psycopg", "")


def test_the_request_credential_cannot_take_a_backup(
    pg_tools: dict[str, str], migrated_engine: Engine
) -> None:
    """O modo de falha que motiva o script inteiro, nas duas metades.

    Sem a flag, o Postgres **recusa**: a RLS se aplica às consultas que o
    ``pg_dump`` emite, e ele não aceita produzir um dump que sabe estar
    filtrado. Com a flag que cala a recusa, ele produz — e o que produz é um
    backup limpo, bem-sucedido e **vazio**, sem aviso nenhum. Nenhum operador
    olha duas vezes para um comando que saiu com zero.
    """
    url = _libpq(Settings().database_url)  # portal_app: o caminho de requisição
    common = [pg_tools["PG_DUMP"], url, "--schema=portal", "--data-only",
              "--table=portal.organization"]

    refused = subprocess.run(common, capture_output=True, text=True)
    assert refused.returncode != 0
    assert "row-level security" in refused.stderr

    silenced = subprocess.run(
        [*common, "--enable-row-security"], capture_output=True, text=True
    )
    assert silenced.returncode == 0, silenced.stderr
    assert "COPY portal.organization" in silenced.stdout
    assert _copy_rows(silenced.stdout) == 0, "o dump vazio deveria ser o ponto do teste"


def _copy_rows(dump: str) -> int:
    """Conta as linhas de dados entre o ``COPY`` e o ``\\.`` que o fecha."""
    rows, inside = 0, False
    for line in dump.splitlines():
        if line.startswith("COPY portal."):
            inside = True
        elif inside and line == r"\.":
            inside = False
        elif inside:
            rows += 1
    return rows


@pytest.fixture(scope="module")
def two_tenants(migrated_engine: Engine) -> Iterator[dict[str, uuid.UUID]]:
    """Duas organizações com um membro cada, gravadas **antes** do backup.

    O seed local tem membros numa organização só, e a afirmação que interessa é
    sobre a fronteira — sem a segunda organização o teste de isolamento passaria
    por não ter o que separar, que é a forma mais silenciosa de não testar nada.
    """
    from portal_api.models import MemberRole, Membership, Organization, Project, ProjectStatus, User

    tag = uuid.uuid4().hex[:8]
    ids: dict[str, uuid.UUID] = {}
    with Session(migrated_engine) as session:
        for label in ("acme", "globex"):
            organization = Organization(name=label.title(), slug=f"{label}-bkp-{tag}")
            session.add(organization)
            session.flush()
            project = Project(
                organization_id=organization.id,
                name=f"Projeto {label}",
                slug=f"{label}-bkp-project-{tag}",
                status=ProjectStatus.in_implementation,
            )
            session.add(project)
            user = User(
                email=f"cliente-{label}-{tag}@example.com",
                full_name=f"Cliente {label.title()}",
                external_subject=f"sub-bkp-{label}-{tag}",
            )
            session.add(user)
            session.flush()
            session.add(
                Membership(
                    organization_id=organization.id,
                    project_id=project.id,
                    user_id=user.id,
                    role=MemberRole.client_member,
                )
            )
            ids[f"{label}_org"] = organization.id
            ids[f"{label}_user"] = user.id
        session.commit()

    yield ids

    with Session(migrated_engine) as session:
        for label in ("acme", "globex"):
            session.execute(
                text("DELETE FROM portal.membership WHERE organization_id = :org"),
                {"org": ids[f"{label}_org"]},
            )
            session.execute(
                text("DELETE FROM portal.project WHERE organization_id = :org"),
                {"org": ids[f"{label}_org"]},
            )
            session.execute(
                text("DELETE FROM portal.\"user\" WHERE id = :who"),
                {"who": ids[f"{label}_user"]},
            )
            session.execute(
                text("DELETE FROM portal.organization WHERE id = :org"),
                {"org": ids[f"{label}_org"]},
            )
        session.commit()


@pytest.fixture(scope="module")
def restored(
    script_env: dict[str, str],
    two_tenants: dict[str, uuid.UUID],
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Engine]:
    """Roda backup.sh e restore.sh de verdade e devolve o banco restaurado.

    Escopo de módulo porque o par custa alguns segundos e as afirmações sobre o
    resultado são muitas — o que se prova aqui é um restore, não seis.
    """
    if not script_env.get("POSTGRES_PASSWORD"):
        # Este era o pulo mais caro do repositório: silencioso, em toda execução
        # do CI, e justamente sobre as três afirmações que dão sentido ao
        # backup (ADR 0019). Hoje ele falha no CI (ADR 0020).
        skip_unless_ci("POSTGRES_USER/POSTGRES_PASSWORD não definidos (restore cria banco)")

    out = tmp_path_factory.mktemp("backup")
    env = {**script_env, "TMPDIR": str(out)}

    made = subprocess.run(
        [str(SCRIPTS / "backup.sh"), "--out", str(out / "snapshot"), "--allow-plaintext"],
        capture_output=True, text=True, env=env, cwd=REPO_ROOT,
    )
    assert made.returncode == 0, made.stderr

    put_back = subprocess.run(
        [str(SCRIPTS / "restore.sh"), str(out / "snapshot"), "--database", RESTORE_DB],
        capture_output=True, text=True, env=env, cwd=REPO_ROOT,
    )
    assert put_back.returncode == 0, put_back.stderr
    assert "censo confere" in put_back.stdout + put_back.stderr

    app_url = _swap_database(Settings().database_url, RESTORE_DB)
    engine = create_engine(app_url)
    yield engine
    engine.dispose()


def _swap_database(url: str, database: str) -> str:
    head, _, _ = url.rpartition("/")
    return f"{head}/{database}"


def test_the_restored_database_still_has_its_policies(restored: Engine) -> None:
    """Sem as policies, a RLS é decoração — e nada na tela denuncia isso."""
    original = get_engine(DbRole.system)
    query = text(
        "SELECT tablename || ':' || policyname FROM pg_policies "
        "WHERE schemaname = 'portal' ORDER BY 1"
    )
    with original.connect() as before, restored.connect() as after:
        assert set(after.execute(query).scalars()) == set(before.execute(query).scalars())


def test_the_column_grants_survive_as_column_grants(restored: Engine) -> None:
    """Uma policy decide *linhas*; só o GRANT de coluna decide *colunas*.

    Perdê-lo no restore transformaria "marcar como lida" em "reescrever o aviso"
    e o polegar do feedback em "reescrever a resposta e as citações"
    (ADR 0012, ADR 0015), sem que nada estourasse.
    """
    query = text(
        "SELECT table_name || ' ' || string_agg(column_name, ',' ORDER BY column_name) "
        "FROM information_schema.column_privileges "
        "WHERE table_schema = 'portal' AND grantee = 'portal_app' "
        "  AND privilege_type = 'UPDATE' GROUP BY table_name ORDER BY 1"
    )
    with restored.connect() as connection:
        grants = dict(row.split(" ", 1) for row in connection.execute(query).scalars())

    assert grants["notification"] == "read_at,updated_at"
    assert grants["conversation_message"] == (
        "feedback,feedback_at,feedback_comment,updated_at"
    )
    assert "id" not in grants.get("user", "")


def test_the_restored_database_still_isolates_one_tenant_from_another(
    restored: Engine, two_tenants: dict[str, uuid.UUID]
) -> None:
    """A afirmação de aceite do roadmap, do outro lado do restore.

    Conectado como ``portal_app`` — a credencial da API, sujeita às policies —
    com o contexto de uma organização publicado nas GUCs, o que se vê é ela. Um
    restore que trouxesse as linhas e perdesse essa fronteira devolveria um
    portal onde todo cliente vê todo projeto.
    """
    # A policy de `organization` não lê a GUC de organização: ela exige uma
    # `membership` do usuário publicado em `portal.user_id`. É o desenho da
    # ADR 0010 — pertencer é o que dá acesso, e não afirmar a que se pertence.
    me = two_tenants["acme_user"]
    mine, theirs = two_tenants["acme_org"], two_tenants["globex_org"]

    with restored.connect() as connection:
        connection.execute(
            text("SELECT set_config('portal.user_id', :who, true)"), {"who": str(me)}
        )
        visible = set(
            connection.execute(text("SELECT id FROM portal.organization")).scalars()
        )

    assert mine in visible
    assert theirs not in visible
    # E sem contexto nenhum a resposta é vazio, nunca "tudo".
    with restored.connect() as connection:
        assert not set(
            connection.execute(text("SELECT id FROM portal.organization")).scalars()
        )


def test_a_tampered_backup_is_refused_before_any_database_is_touched(
    script_env: dict[str, str], tmp_path: Path
) -> None:
    """O digest do manifesto é conferido antes do primeiro CREATE DATABASE."""
    if not script_env.get("POSTGRES_PASSWORD"):
        pytest.skip("POSTGRES_USER/POSTGRES_PASSWORD não definidos")

    out = tmp_path / "snapshot"
    env = {**script_env, "TMPDIR": str(tmp_path)}
    made = subprocess.run(
        [str(SCRIPTS / "backup.sh"), "--out", str(out), "--allow-plaintext"],
        capture_output=True, text=True, env=env, cwd=REPO_ROOT,
    )
    assert made.returncode == 0, made.stderr

    (out / "dump.pgc").write_bytes((out / "dump.pgc").read_bytes() + b"lixo")

    refused = subprocess.run(
        [str(SCRIPTS / "restore.sh"), str(out), "--database", "portal_never_created"],
        capture_output=True, text=True, env=env, cwd=REPO_ROOT,
    )
    assert refused.returncode != 0
    assert "digest" in refused.stderr


def test_a_backup_without_a_key_refuses_to_run(
    script_env: dict[str, str], tmp_path: Path
) -> None:
    """Um backup em claro pode ser escolha; nunca efeito de variável esquecida.

    É a regra que a ADR 0017 impôs ao scanner ("``skipped`` não é ``clean``")
    aplicada à cifra: a ausência da chave não vira uma versão pior do backup, ela
    vira a recusa de fazê-lo.
    """
    env = {**script_env, "TMPDIR": str(tmp_path)}
    env.pop("BACKUP_AGE_RECIPIENT", None)
    out = tmp_path / "snapshot"

    refused = subprocess.run(
        [str(SCRIPTS / "backup.sh"), "--out", str(out)],
        capture_output=True, text=True, env=env, cwd=REPO_ROOT,
    )

    assert refused.returncode != 0
    assert "BACKUP_AGE_RECIPIENT" in refused.stderr
    assert not (out / "dump.pgc").exists()


def test_the_census_is_taken_with_a_different_credential_than_the_dump() -> None:
    """A afirmação que faz o manifesto valer alguma coisa.

    Se o censo saísse sob a mesma credencial do dump, os dois errariam na mesma
    direção — a credencial errada devolveria zero linhas nos dois, e o manifesto
    confirmaria com entusiasmo que zero virou zero.
    """
    script = (SCRIPTS / "backup.sh").read_text()

    census_line = next(l for l in script.splitlines() if "census.sql" in l)
    dump_line = next(l for l in script.splitlines() if "$PG_DUMP" in l and "--format" in l)

    assert "SYSTEM_URL" in census_line
    assert "MIGRATION_URL" in dump_line


def test_no_http_route_can_reach_the_backup() -> None:
    """Mesma regra da ADR 0017 para o expurgo, pelo mesmo motivo.

    Uma rota que devolvesse o bucket inteiro seria um caminho de requisição capaz
    de ler dado de todo tenant de uma vez — o avesso da regra 1 do ``AGENTS.md``.
    """
    from portal_api import admin, main

    for module in (admin, main):
        assert "backup" not in Path(module.__file__).read_text().lower()
