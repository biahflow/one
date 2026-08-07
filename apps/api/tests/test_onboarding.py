"""O funil de onboarding: carimbo imutável, escrito pelas rotas de verdade (RFC 001, ADR 0039).

Os degraus são exercitados **pela rota**, e não chamando ``onboarding.stamp`` direto. A
diferença foi medida na ADR 0035: uma ligação frouxa entre o teste e o caminho real deu
`POST /chat` como coberto por um 404 que era de outra rota. Aqui vale o mesmo — provar que a
função carimba não prova que alguém a chama.

O isolamento e a ausência de GRANT para o papel de requisição ficam em
``test_rls_isolation.py``, ao lado dos outros da mesma forma.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session

from conftest import captured
from portal_api import onboarding
from portal_api.config import Settings
from portal_api.models import OnboardingStep, OnboardingStepName

pytestmark = pytest.mark.integration


@pytest.fixture
def organization_id(migrated_engine: Engine) -> uuid.UUID:
    """Uma organização qualquer, criada e limpa por este arquivo.

    Não reusa a do ``World`` de ``test_authorization.py`` de propósito: o funil é uma linha
    por organização e por degrau, então um teste que carimbasse na organização compartilhada
    envenenaria o seguinte — e o defeito apareceria como "o segundo carimbo não criou linha",
    que é exatamente o que outro teste aqui **espera** ver.
    """
    from portal_api.models import Organization

    with Session(migrated_engine) as session:
        organization = Organization(
            name="Funil Ltda", slug=f"funil-{uuid.uuid4().hex[:8]}"
        )
        session.add(organization)
        session.commit()
        oid = organization.id
    yield oid
    with Session(migrated_engine) as session:
        session.execute(delete(OnboardingStep).where(OnboardingStep.organization_id == oid))
        session.execute(delete(Organization).where(Organization.id == oid))
        session.commit()


def _steps(migrated_engine: Engine, organization_id: uuid.UUID) -> list[OnboardingStep]:
    with Session(migrated_engine) as session:
        return list(
            session.execute(
                select(OnboardingStep)
                .where(OnboardingStep.organization_id == organization_id)
                .order_by(OnboardingStep.step)
            ).scalars()
        )


def test_the_stamp_is_immutable(migrated_engine: Engine, organization_id: uuid.UUID) -> None:
    """Primeira vez é primeira vez — o segundo carimbo não tem efeito nenhum.

    É a única métrica que interessa (o *time-to-first-value*), e reescrevê-la a destruiria.
    A garantia é a ``UniqueConstraint`` mais ``ON CONFLICT DO NOTHING``, e não a boa vontade
    de quem chama: nenhum papel tem GRANT de ``UPDATE`` nesta tabela.
    """
    primeiro = datetime.now(timezone.utc) - timedelta(days=3)

    assert onboarding.stamp(
        organization_id, OnboardingStepName.first_login, reached_at=primeiro
    ) is True
    # O retorno é o que distingue "aconteceu agora" de "acontece toda vez" — e é ele que
    # impede o evento de virar uma linha de log por download.
    assert onboarding.stamp(organization_id, OnboardingStepName.first_login) is False

    linhas = _steps(migrated_engine, organization_id)
    assert len(linhas) == 1
    assert linhas[0].reached_at == primeiro


def test_a_failure_to_stamp_never_breaks_the_caller() -> None:
    """A decisão declarada na ADR 0039: medir engajamento não derruba o que o cliente veio fazer.

    Um degrau perdido é um dado a menos numa métrica de tendência; uma exceção propagada
    seria um download que não acontece ou um dashboard que não abre.

    A falha é de banco de verdade — organização inexistente viola a chave estrangeira —, e
    não um erro de tipo: o que precisa ser provado é o caminho que a produção percorreria.
    """
    assert (
        onboarding.stamp(uuid.uuid4(), OnboardingStepName.first_login) is False
    )


def test_the_dashboard_route_stamps_the_first_login(migrated_engine: Engine) -> None:
    """O degrau pela **rota** que o cliente de fato abre, e não chamando ``stamp`` direto.

    A diferença foi medida na ADR 0035: uma ligação frouxa entre teste e caminho real deu
    ``POST /chat`` como coberto por um 404 que era de outra rota. Provar que a função
    carimba não prova que alguém a chama.

    O login é carimbado nesta rota e não em ``identity.resolve_user``, e a razão está escrita
    naquele módulo: quando o ``external_subject`` deixa de ser nulo ainda não há organização
    resolvida. Aqui há — e o degrau fica melhor definido, porque "aceitou o convite" passa a
    significar que a pessoa **entrou e viu o projeto**.
    """
    from fastapi.testclient import TestClient

    from portal_api.auth import Principal, bearer_principal
    from portal_api.integrations import biahflow
    from portal_api.main import app

    # Sessão própria e **comitada**, e não a `db_session` transacional: a rota abre conexão
    # própria e o carimbo abre uma terceira, sob `portal_system`. Montar o cenário numa
    # transação aberta faz as três disputarem lock — medido, e o teste trava sem falhar.
    with Session(migrated_engine) as setup:
        project = biahflow.sync_snapshot(setup, _snapshot(biahflow_project_id=91, client_id=87))
        biahflow.ensure_demo_client(setup, project, "funil@acme.test", "Cliente Funil")
        setup.commit()
        organization_id = project.organization_id
        project_id = project.id

    app.dependency_overrides[bearer_principal] = lambda: Principal(
        subject="sub-funil",
        email="funil@acme.test",
        full_name="Cliente Funil",
        realm_roles=frozenset({"client_member"}),
    )
    try:
        assert TestClient(app).get("/api/v1/me/dashboard").status_code == 200
    finally:
        app.dependency_overrides.clear()

    carimbados = {row.step for row in _steps(migrated_engine, organization_id)}
    assert OnboardingStepName.first_login in carimbados

    with Session(migrated_engine) as cleanup:
        from portal_api.models import Membership, Organization, Project

        cleanup.execute(
            delete(OnboardingStep).where(OnboardingStep.organization_id == organization_id)
        )
        cleanup.execute(delete(Membership).where(Membership.organization_id == organization_id))
        cleanup.execute(delete(Project).where(Project.id == project_id))
        cleanup.execute(delete(Organization).where(Organization.id == organization_id))
        cleanup.commit()


# --------------------------------------------------------------------------------------
# A leitura, o alerta e o tick (RFC 001 passo 3, ADR 0040).
# --------------------------------------------------------------------------------------


@dataclass
class Cenario:
    organization_id: uuid.UUID
    project_id: uuid.UUID
    internal_user_id: uuid.UUID
    client_user_id: uuid.UUID | None


@pytest.fixture
def cenario(migrated_engine: Engine):
    """Uma organização com projeto vivo, um interno e um cliente convidado.

    Fixture própria pela razão que a do ``organization_id`` acima já dá, e uma a mais: a
    leitura do funil consulta documento, pendência, ROI e teto de IA da organização, então
    um cenário compartilhado faria o rótulo de um teste depender do que outro semeou.
    """
    from portal_api.models import MemberRole, Membership, Organization, Project, User

    with Session(migrated_engine) as session:
        organization = Organization(
            name="Funil Alerta Ltda", slug=f"alerta-{uuid.uuid4().hex[:8]}"
        )
        session.add(organization)
        session.flush()
        project = Project(
            organization_id=organization.id,
            name="Automação",
            slug=f"automacao-{uuid.uuid4().hex[:8]}",
        )
        interno = User(
            email=f"interno-{uuid.uuid4().hex[:8]}@labs.test",
            full_name="Pessoa Interna",
            is_internal=True,
        )
        cliente = User(
            email=f"cliente-{uuid.uuid4().hex[:8]}@acme.test", full_name="Pessoa Cliente"
        )
        session.add_all([project, interno, cliente])
        session.flush()
        session.add_all(
            [
                # Vínculo **organizacional** (`project_id IS NULL`), que é a forma do
                # bootstrap da ADR 0025 — e o ramo de `recipients` que faz o time interno
                # ser alcançado sem vínculo direto com o projeto.
                Membership(
                    organization_id=organization.id,
                    project_id=None,
                    user_id=interno.id,
                    role=MemberRole.internal_admin,
                ),
                Membership(
                    organization_id=organization.id,
                    project_id=project.id,
                    user_id=cliente.id,
                    role=MemberRole.client_member,
                ),
            ]
        )
        session.commit()
        built = Cenario(
            organization_id=organization.id,
            project_id=project.id,
            internal_user_id=interno.id,
            client_user_id=cliente.id,
        )

    yield built

    with Session(migrated_engine) as cleanup:
        from portal_api.models import Notification

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
        cleanup.execute(delete(Organization).where(Organization.id == built.organization_id))
        cleanup.execute(
            delete(User).where(User.id.in_([built.internal_user_id, built.client_user_id]))
        )
        cleanup.commit()


def _invited_days_ago(engine: Engine, organization_id: uuid.UUID, days: int) -> None:
    """Recua o convite do cliente. É a âncora quando não há carimbo nenhum."""
    from portal_api.models import MemberRole, Membership

    with Session(engine) as session:
        session.execute(
            update(Membership)
            .where(
                Membership.organization_id == organization_id,
                Membership.role == MemberRole.client_member,
            )
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=days))
        )
        session.commit()


def _read(engine: Engine, organization_id: uuid.UUID):
    with Session(engine) as session:
        return onboarding.read_funnel(session, organization_id, Settings())


def test_the_current_step_is_the_lowest_rung_without_a_stamp(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """O degrau atual é o mais baixo em aberto — e **não** o mais alto alcançado mais um.

    O caso que força a regra existe de verdade: ``stamp`` aceita ``reached_at`` justamente
    para o degrau do Biahflow, que chega pelo sync com a data do fato. Um cliente pode então
    ter ``first_deliverable_delivered`` carimbado com data anterior a um ``first_login`` que
    nunca aconteceu. "Mais alto alcançado" diria que ele completou o funil; a verdade é que
    entregamos alguma coisa que ele nunca viu.
    """
    _invited_days_ago(migrated_engine, cenario.organization_id, 20)
    onboarding.stamp(
        cenario.organization_id,
        OnboardingStepName.first_deliverable_delivered,
        reached_at=datetime.now(timezone.utc) - timedelta(days=15),
    )

    leitura = _read(migrated_engine, cenario.organization_id)

    assert leitura is not None
    assert leitura.current_step is OnboardingStepName.first_login


def test_the_days_are_counted_from_the_last_rung_reached(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """"Há quantos dias este cliente não recebe nada" — e não desde o degrau abaixo.

    Um cliente que conversou com o assistente anteontem mas está travado em
    ``first_pending_answered`` desde o mês passado **não** está parado há um mês.
    """
    _invited_days_ago(migrated_engine, cenario.organization_id, 60)
    onboarding.stamp(
        cenario.organization_id,
        OnboardingStepName.first_login,
        reached_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    onboarding.stamp(
        cenario.organization_id,
        OnboardingStepName.first_document_opened,
        reached_at=datetime.now(timezone.utc) - timedelta(days=2),
    )

    leitura = _read(migrated_engine, cenario.organization_id)

    assert leitura is not None
    assert leitura.current_step is OnboardingStepName.first_pending_answered
    assert leitura.days_stuck == 2
    assert leitura.anchor_source == "step"


def test_a_client_invited_and_never_seen_shows_up_with_the_right_day_count(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """O critério de aceite (1) da FDD 020, e o caso que justifica a fatia inteira.

    "Ganho há nove dias, convite enviado, nunca logou": hoje invisível, e aos nove dias
    ainda recuperável com um telefonema. A âncora é o convite e não a criação da
    organização, que o sync cria quando o projeto chega do Biahflow — possivelmente dias
    antes de alguém ter porta.
    """
    _invited_days_ago(migrated_engine, cenario.organization_id, 9)

    leitura = _read(migrated_engine, cenario.organization_id)

    assert leitura is not None
    assert leitura.current_step is OnboardingStepName.first_login
    assert leitura.days_stuck == 9
    assert leitura.anchor_source == "membership"
    assert leitura.blame is onboarding.Blame.client
    # Nove dias contra um limiar de sete: travado, e é este booleano que a tela e o alerta
    # leem — nunca `days_stuck > threshold_days` reimplementado do outro lado.
    assert leitura.threshold_days == 7
    assert leitura.stuck is True


def test_a_client_who_was_never_invited_is_stuck_on_us(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """Sem ninguém do cliente com porta, a espera é **nossa** — e a lacuna é declarada.

    A âncora cai para a criação da organização, e o número passa a dizer "há quantos dias o
    tenant existe e ninguém foi convidado", que é uma frase sobre a equipe.
    """
    from portal_api.models import MemberRole, Membership

    with Session(migrated_engine) as session:
        session.execute(
            delete(Membership).where(
                Membership.organization_id == cenario.organization_id,
                Membership.role == MemberRole.client_member,
            )
        )
        session.commit()

    leitura = _read(migrated_engine, cenario.organization_id)

    assert leitura is not None
    assert leitura.current_step is OnboardingStepName.first_login
    assert leitura.blame is onboarding.Blame.us
    assert leitura.anchor_source == "organization"
    assert "no_client_member" in leitura.gaps


def test_a_deliverable_that_never_left_pending_is_stuck_on_us(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """O critério de aceite (4) da FDD 020: o degrau que depende de entrega não realizada.

    ``first_deliverable_delivered`` é afirmação do Biahflow, e o portal não origina status
    (ADR 0006/0008). Não há nada que o cliente possa fazer, então este degrau é **sempre**
    nosso — e com o limiar mais longo dos três, para o radar de engajamento não virar um
    relatório de execução.
    """
    _invited_days_ago(migrated_engine, cenario.organization_id, 40)
    for step in onboarding.LADDER[:-1]:
        onboarding.stamp(
            cenario.organization_id,
            step,
            reached_at=datetime.now(timezone.utc) - timedelta(days=40),
        )

    leitura = _read(migrated_engine, cenario.organization_id)

    assert leitura is not None
    assert leitura.current_step is OnboardingStepName.first_deliverable_delivered
    assert leitura.blame is onboarding.Blame.us
    assert leitura.threshold_days == 30
    assert leitura.stuck is True


def test_a_missing_rung_before_the_instrumentation_declares_the_gap_instead_of_zero(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """Degrau ausente **não** é degrau zerado (FDD 020).

    Numa organização anterior a 07/08/2026, um degrau sem carimbo pode não ter sido
    alcançado **ou** ter sido alcançado antes de existir medição — e as duas coisas não
    podem sair iguais. A lacuna é declarada e a linha **não** conta como travada: ninguém
    deve ser chamado por um degrau que talvez já esteja cumprido.

    O que a contagem nunca faz é fabricar um zero, e é isso que a FDD proíbe: a âncora é
    sempre uma data real — o último carimbo, o convite ou a criação da organização —, nunca
    a data da instrumentação.
    """
    from portal_api.models import Organization

    idade = (datetime.now(timezone.utc) - onboarding.INSTRUMENTED_SINCE).days + 30
    _invited_days_ago(migrated_engine, cenario.organization_id, idade)
    with Session(migrated_engine) as session:
        session.execute(
            update(Organization)
            .where(Organization.id == cenario.organization_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=idade))
        )
        session.commit()
    # Com o login já carimbado, o degrau atual passa a ser um dos que **não** têm
    # corroboração fora do funil — que é onde a incerteza mora.
    onboarding.stamp(
        cenario.organization_id,
        OnboardingStepName.first_login,
        reached_at=datetime.now(timezone.utc) - timedelta(days=idade),
    )

    leitura = _read(migrated_engine, cenario.organization_id)

    assert leitura is not None
    assert leitura.current_step is OnboardingStepName.first_document_opened
    assert "before_instrumentation" in leitura.gaps
    assert leitura.stuck is False
    # E a contagem que aparece é de uma data real, não um zero fabricado.
    assert leitura.days_stuck == idade


def test_a_login_that_predates_the_instrumentation_is_not_reported_as_never_logged_in(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """A medição não nasce cega, e este é o defeito que a primeira execução revelou.

    Sem consultar ``user.external_subject`` — que deixa de ser nulo no primeiro login e não
    depende do funil —, no primeiro dia da instrumentação **toda** organização existente
    apareceria travada em "nunca entrou no portal". Seria o alerta mais caro possível: manda
    ligar justamente para o cliente que está usando o produto.
    """
    from portal_api.models import Organization, User

    idade = (datetime.now(timezone.utc) - onboarding.INSTRUMENTED_SINCE).days + 30
    _invited_days_ago(migrated_engine, cenario.organization_id, idade)
    with Session(migrated_engine) as session:
        session.execute(
            update(Organization)
            .where(Organization.id == cenario.organization_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=idade))
        )
        session.execute(
            update(User)
            .where(User.id == cenario.client_user_id)
            .values(external_subject=f"sub-{uuid.uuid4().hex[:8]}")
        )
        session.commit()

    leitura = _read(migrated_engine, cenario.organization_id)

    assert leitura is not None
    assert leitura.current_step is not OnboardingStepName.first_login
    assert "login_before_instrumentation" in leitura.gaps


def test_a_document_that_cannot_be_downloaded_does_not_count_as_ours_being_done(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """A prova é a condição da rota que **carimba** o degrau, e ela é o download.

    Um documento indexado sem ``storage_key`` é a linha espelhada do Biahflow — metadado e
    link — e não é baixável. Usar ``ingest_state`` produziria "travou no cliente" sobre um
    cliente que não tinha o que abrir.
    """
    from portal_api.models import Document, DocumentIngestState, DocumentSource

    _invited_days_ago(migrated_engine, cenario.organization_id, 30)
    onboarding.stamp(
        cenario.organization_id,
        OnboardingStepName.first_login,
        reached_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    with Session(migrated_engine) as session:
        session.add(
            Document(
                organization_id=cenario.organization_id,
                project_id=cenario.project_id,
                title="Contrato espelhado",
                source=DocumentSource.upload,
                ingest_state=DocumentIngestState.indexed,
                storage_key=None,
            )
        )
        session.commit()

    leitura = _read(migrated_engine, cenario.organization_id)

    assert leitura is not None
    assert leitura.current_step is OnboardingStepName.first_document_opened
    assert leitura.blame is onboarding.Blame.us


def test_the_roi_gap_comes_from_the_snapshot_and_not_from_the_assumption(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """"ROI visto" depende de ``project.roi_net``, que é o que o dashboard projeta.

    A premissa financeira e os eventos dos agentes alimentam a **apuração**, que é outro
    número e não porteia degrau nenhum: o carimbo é condicionado ao `roi` de
    ``build_dashboard``, e esse sai da coluna do snapshot.
    """
    from portal_api.models import Project

    _invited_days_ago(migrated_engine, cenario.organization_id, 30)
    # Nomeados, e **não** `LADDER[:n]`: a fatia por índice se desloca inteira quando a escada
    # ganha um degrau na frente, e foi exatamente o que a ADR 0041 fez — o teste passou a
    # afirmar sobre outro degrau sem que uma linha dele mudasse.
    for step in (
        OnboardingStepName.artifact_accepted,
        OnboardingStepName.first_login,
        OnboardingStepName.first_document_opened,
        OnboardingStepName.first_pending_answered,
        OnboardingStepName.first_chat_turn,
    ):
        onboarding.stamp(
            cenario.organization_id,
            step,
            reached_at=datetime.now(timezone.utc) - timedelta(days=30),
        )

    sem_roi = _read(migrated_engine, cenario.organization_id)
    assert sem_roi is not None
    assert sem_roi.current_step is OnboardingStepName.first_roi_seen
    assert sem_roi.blame is onboarding.Blame.us

    with Session(migrated_engine) as session:
        session.execute(
            update(Project)
            .where(Project.id == cenario.project_id)
            .values(roi_net=Decimal("1234.00"))
        )
        session.commit()

    com_roi = _read(migrated_engine, cenario.organization_id)
    assert com_roi is not None
    assert com_roi.blame is onboarding.Blame.client


def test_the_alert_rings_once_for_the_same_rung(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """O sino toca **uma vez** por organização e degrau, e o evento sai junto dele.

    A memória de "já avisei" não é tabela nova: é o ``dedupe_key`` da notificação, com
    ``ON CONFLICT DO NOTHING``. ``fan_out`` devolve só os ids que nasceram, e lista vazia
    significa que o sino já tem — que é como a segunda passagem fica muda sem precisar de um
    ``UPDATE`` que nenhum papel desta tabela tem.
    """
    _invited_days_ago(migrated_engine, cenario.organization_id, 9)

    with captured("portal_api.onboarding") as linhas:
        with Session(migrated_engine) as session:
            primeiro = onboarding.raise_alert(
                session, cenario.organization_id, Settings()
            )
            session.commit()
        with Session(migrated_engine) as session:
            segundo = onboarding.raise_alert(
                session, cenario.organization_id, Settings()
            )
            session.commit()

    assert primeiro is not None and primeiro.notified == 1
    assert segundo is not None and segundo.notified == 0

    eventos = [linha.getMessage() for linha in linhas]
    assert eventos.count("onboarding.client_stuck") == 1

    aviso = next(linha for linha in linhas if linha.getMessage() == "onboarding.client_stuck")
    assert aviso.step == OnboardingStepName.first_login.value
    assert aviso.blocked_by == "client"
    assert aviso.days_stuck == 9


def test_the_alert_reaches_only_the_internal_team(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """O cliente **não** é avisado de que está sendo medido (FDD 020).

    É o primeiro aviso do repositório cuja audiência é ``_INTERNAL_ONLY`` — a constante que
    a ADR 0012 definiu e nunca usou. E o destinatário aqui chega pelo vínculo
    **organizacional**, que é a forma do bootstrap da ADR 0025.
    """
    from portal_api.models import Notification

    _invited_days_ago(migrated_engine, cenario.organization_id, 9)
    with Session(migrated_engine) as session:
        onboarding.raise_alert(session, cenario.organization_id, Settings())
        session.commit()

    with Session(migrated_engine) as session:
        destinatarios = set(
            session.execute(
                select(Notification.user_id).where(
                    Notification.organization_id == cenario.organization_id
                )
            ).scalars()
        )

    assert destinatarios == {cenario.internal_user_id}


def test_an_organization_with_nobody_internal_says_the_alert_had_nowhere_to_go(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """Sem ninguém a quem avisar, o alerta **diz isso** em vez de sumir.

    Sem esta linha o desenho teria um ponto cego real: ``fan_out`` devolveria vazio, o
    evento não sairia por ser "repetido", e um tenant sem administrador ficaria travado em
    silêncio absoluto — o único desfecho pior que o alerta não existir.
    """
    from portal_api.models import MemberRole, Membership

    _invited_days_ago(migrated_engine, cenario.organization_id, 9)
    with Session(migrated_engine) as session:
        session.execute(
            delete(Membership).where(
                Membership.organization_id == cenario.organization_id,
                Membership.role == MemberRole.internal_admin,
            )
        )
        session.commit()

    with captured("portal_api.onboarding") as linhas:
        with Session(migrated_engine) as session:
            resultado = onboarding.raise_alert(
                session, cenario.organization_id, Settings()
            )
            session.commit()

    assert resultado is not None and resultado.notified == 0
    eventos = [linha.getMessage() for linha in linhas]
    assert "onboarding.alert_undeliverable" in eventos
    assert "onboarding.client_stuck" not in eventos


def test_an_organization_with_no_live_project_is_not_watched(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """O fantasma pós-expurgo, e o projeto que o Biahflow apagou.

    ``run_erasure`` apaga os projetos e a ``membership`` e **mantém** a linha
    ``organization``, de propósito: é assim que "o que aconteceu com aquele tenant" continua
    tendo resposta (ADR 0017). Sem este filtro, todo tenant apagado viraria uma linha
    perpétua "ninguém foi convidado" com um alerta diário atrás.
    """
    from portal_api.models import Project

    with Session(migrated_engine) as session:
        vigiadas = onboarding.organizations_to_watch(session)
        assert cenario.organization_id in vigiadas

        session.execute(
            update(Project)
            .where(Project.id == cenario.project_id)
            .values(source_deleted_at=datetime.now(timezone.utc))
        )
        session.commit()

    with Session(migrated_engine) as session:
        assert cenario.organization_id not in onboarding.organizations_to_watch(session)


def test_the_tick_keeps_going_when_one_organization_blows_up(
    migrated_engine: Engine, cenario: Cenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uma organização que estoura não impede as outras, e a falha vira evento nomeado.

    É a forma de ``purge_expired_data``, e o limiar em ``alerts.md`` conta com ela: um erro
    isolado é recuperado no tick seguinte por construção, e o que merece alerta é a taxa.
    """
    from portal_api import worker

    explodiu: list[uuid.UUID] = []
    original = onboarding.raise_alert

    def falha_na_primeira(session, organization_id, settings):
        if organization_id != cenario.organization_id:
            explodiu.append(organization_id)
            raise RuntimeError("banco fora do ar")
        return original(session, organization_id, settings)

    _invited_days_ago(migrated_engine, cenario.organization_id, 9)
    monkeypatch.setattr(worker.onboarding, "raise_alert", falha_na_primeira)
    enfileirados: list[str] = []
    monkeypatch.setattr(worker, "queue_project_digests", enfileirados.append)

    with captured("portal_api.worker") as linhas:
        resultado = worker.alert_stuck_onboarding()

    assert resultado["alerted"] == 1
    assert enfileirados == [str(cenario.project_id)]
    if explodiu:
        assert "onboarding.stuck_scan_failed" in [
            linha.getMessage() for linha in linhas
        ]


# --------------------------------------------------------------------------------------
# O sétimo degrau (ADR 0041) — a aprovação que o Biahflow passou a afirmar.
# --------------------------------------------------------------------------------------


def test_the_snapshot_stamps_the_approval_with_the_date_of_the_decision(
    migrated_engine: Engine,
) -> None:
    """O critério (3) da FDD 020, que ficou "adiado e não esquecido" por falta de produtor.

    A data carimbada é a da **decisão** no Biahflow, não a da passagem do sync — é para isso
    que ``reached_at`` existe separado do ``created_at`` (ADR 0039). Se fosse a do sync, todo
    cliente pareceria ter fechado hoje e a régua nasceria zerada.
    """
    from portal_api.integrations import biahflow
    from portal_api.models import Membership, Organization, Project

    decidido = datetime(2026, 6, 12, 14, 30, tzinfo=timezone.utc)
    with Session(migrated_engine) as setup:
        project = biahflow.sync_snapshot(
            setup,
            _snapshot(
                biahflow_project_id=713,
                client_id=713,
                artifact_accepted_at=decidido.isoformat(),
            ),
        )
        setup.commit()
        organization_id = project.organization_id
        project_id = project.id

    carimbos = {row.step: row.reached_at for row in _steps(migrated_engine, organization_id)}
    assert OnboardingStepName.artifact_accepted in carimbos
    assert carimbos[OnboardingStepName.artifact_accepted] == decidido

    with Session(migrated_engine) as cleanup:
        cleanup.execute(
            delete(OnboardingStep).where(OnboardingStep.organization_id == organization_id)
        )
        cleanup.execute(delete(Membership).where(Membership.organization_id == organization_id))
        cleanup.execute(delete(Project).where(Project.id == project_id))
        cleanup.execute(delete(Organization).where(Organization.id == organization_id))
        cleanup.commit()


def test_the_first_snapshot_of_a_brand_new_client_already_stamps(
    migrated_engine: Engine,
) -> None:
    """O defeito da ADR 0039 que só apareceu ao construir o sétimo degrau.

    ``sync_snapshot`` **cria** a organização, e chamava um ``stamp`` que abre sessão própria:
    no primeiro snapshot de um cliente novo a linha ``organization`` ainda não estava
    comitada, o ``INSERT`` batia na chave estrangeira e o carimbo se perdia em silêncio,
    saindo como ``onboarding.stamp_failed`` — que o ``alerts.md`` diagnostica como
    indisponibilidade do banco.

    Era raro com o entregável, e vira o caso **central** com a aprovação: aceitar o artefato
    é justamente o fato que chega no primeiro snapshot. Este teste cobre os dois degraus de
    uma vez, e reprova se alguém voltar a `stamp` aqui dentro.
    """
    from portal_api.integrations import biahflow
    from portal_api.models import (
        Membership,
        Organization,
        PhaseDeliverable,
        Project,
        ProjectPhase,
    )

    snapshot = _snapshot(
        biahflow_project_id=715,
        client_id=715,
        artifact_accepted_at="2026-06-01T09:00:00+00:00",
    )
    snapshot["journey"] = {
        "phases": [
            {
                "name": "Welcome",
                "status": "active",
                "position": 0,
                "deliverables": [{"name": "Diagnóstico", "status": "delivered"}],
            }
        ]
    }
    with Session(migrated_engine) as setup:
        project = biahflow.sync_snapshot(setup, snapshot)
        setup.commit()
        organization_id = project.organization_id
        project_id = project.id

    carimbados = {row.step for row in _steps(migrated_engine, organization_id)}
    assert OnboardingStepName.artifact_accepted in carimbados
    assert OnboardingStepName.first_deliverable_delivered in carimbados

    with Session(migrated_engine) as cleanup:
        cleanup.execute(
            delete(OnboardingStep).where(OnboardingStep.organization_id == organization_id)
        )
        cleanup.execute(
            delete(PhaseDeliverable).where(PhaseDeliverable.project_id == project_id)
        )
        cleanup.execute(delete(ProjectPhase).where(ProjectPhase.project_id == project_id))
        cleanup.execute(delete(Membership).where(Membership.organization_id == organization_id))
        cleanup.execute(delete(Project).where(Project.id == project_id))
        cleanup.execute(delete(Organization).where(Organization.id == organization_id))
        cleanup.commit()


def test_a_failed_stamp_inside_the_sync_does_not_take_the_transaction_down(
    migrated_engine: Engine,
) -> None:
    """O ``SAVEPOINT`` é o que faz "falha em silêncio" continuar verdade dentro do sync.

    Um ``IntegrityError`` deixa a transação do Postgres em estado **abortado**: engolir a
    exceção sem savepoint só adiaria a queda para o ``COMMIT``, trocando um degrau perdido
    por um snapshot perdido — o inverso exato do que a ADR 0039 decidiu, e o desfecho que
    "medir engajamento não pode derrubar o que o cliente veio fazer" existe para impedir.

    O degrau impossível é uma organização que não existe, que é a mesma falha de chave
    estrangeira do defeito medido acima.
    """
    from portal_api.models import Organization

    with Session(migrated_engine) as session:
        assert (
            onboarding.stamp_within(
                session, uuid.uuid4(), OnboardingStepName.artifact_accepted
            )
            is False
        )
        # A prova: a mesma transação segue utilizável depois da falha e comita.
        organization = Organization(
            name="Savepoint Ltda", slug=f"savepoint-{uuid.uuid4().hex[:8]}"
        )
        session.add(organization)
        session.commit()
        organization_id = organization.id

    with Session(migrated_engine) as cleanup:
        cleanup.execute(delete(Organization).where(Organization.id == organization_id))
        cleanup.commit()


def test_a_snapshot_without_the_field_stamps_nothing(migrated_engine: Engine) -> None:
    """Um Biahflow anterior à FDD 031 manda um corpo sem a chave, e isso é **ausência**.

    Ausência de afirmação não é negação nem confirmação (FDD 020) — o que não pode acontecer
    é o sync inventar uma data para não deixar o campo vazio.
    """
    from portal_api.integrations import biahflow
    from portal_api.models import Membership, Organization, Project

    with Session(migrated_engine) as setup:
        project = biahflow.sync_snapshot(
            setup, _snapshot(biahflow_project_id=714, client_id=714)
        )
        setup.commit()
        organization_id = project.organization_id
        project_id = project.id

    carimbados = {row.step for row in _steps(migrated_engine, organization_id)}
    assert OnboardingStepName.artifact_accepted not in carimbados

    with Session(migrated_engine) as cleanup:
        cleanup.execute(delete(Membership).where(Membership.organization_id == organization_id))
        cleanup.execute(delete(Project).where(Project.id == project_id))
        cleanup.execute(delete(Organization).where(Organization.id == organization_id))
        cleanup.commit()


def test_the_approval_anchors_the_ruler_on_the_win_and_not_on_the_invite(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """O que a fatia inteira destrava, e não é um item a mais numa lista.

    A régua da RFC 001 é o *time-to-first-value*: "quanto o cliente demora **do ganho** até a
    primeira aprovação e até o primeiro ROI visto". Sem este degrau a âncora caía no convite,
    que é quando **o portal** conheceu o cliente — de modo que um convite atrasado, que é
    demora nossa, encurtava o número em vez de aparecer nele.

    Aqui o cliente foi ganho há 20 dias e convidado há 9. O funil diz 20, e é a verdade.
    """
    _invited_days_ago(migrated_engine, cenario.organization_id, 9)
    onboarding.stamp(
        cenario.organization_id,
        OnboardingStepName.artifact_accepted,
        reached_at=datetime.now(timezone.utc) - timedelta(days=20),
    )

    leitura = _read(migrated_engine, cenario.organization_id)

    assert leitura is not None
    assert leitura.anchor_source == "step"
    assert leitura.days_stuck == 20
    assert leitura.current_step is OnboardingStepName.first_login
    assert "artifact_not_reported" not in leitura.gaps


def test_a_live_project_corroborates_the_approval_instead_of_calling_everyone(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """A corroboração que impede a medição de nascer cega — de novo, um degrau abaixo.

    ``artifact_accepted`` só passou a ser reportado pela FDD 031 do Biahflow, então toda
    organização anterior a ela chega sem carimbo. Sendo o primeiro da escada, ele seria o
    degrau atual de **todas**, e a tela mandaria registrar o contrato de clientes que estão em
    produção há meses — a repetição exata do susto que a ADR 0040 mediu com o ``first_login``.

    A evidência é estrutural: projeto vivo no Biahflow significa negócio fechado. A lacuna é
    declarada, e nenhuma data é fabricada — por isso a âncora continua saindo do convite.
    """
    _invited_days_ago(migrated_engine, cenario.organization_id, 9)

    leitura = _read(migrated_engine, cenario.organization_id)

    assert leitura is not None
    assert leitura.current_step is OnboardingStepName.first_login
    assert "artifact_not_reported" in leitura.gaps
    assert leitura.anchor_source == "membership"
    assert leitura.days_stuck == 9
    # O carimbo **não** nasceu: a corroboração reconhece o degrau, não o inventa na tabela.
    carimbados = {row.step for row in _steps(migrated_engine, cenario.organization_id)}
    assert OnboardingStepName.artifact_accepted not in carimbados


def test_without_a_live_project_the_approval_stays_open_and_is_ours(
    migrated_engine: Engine, cenario: Cenario
) -> None:
    """Sem projeto vivo não há corroboração, e o degrau em aberto é a verdade.

    E ele é **sempre nosso**, como o do entregável: a aprovação acontece do outro lado, o
    portal não a hospeda e não tem como coletá-la — nada que o cliente faça nesta tela move o
    degrau.
    """
    from portal_api.models import Project

    _invited_days_ago(migrated_engine, cenario.organization_id, 40)
    with Session(migrated_engine) as session:
        session.execute(
            update(Project)
            .where(Project.id == cenario.project_id)
            .values(archived_at=datetime.now(timezone.utc))
        )
        session.commit()

    leitura = _read(migrated_engine, cenario.organization_id)

    assert leitura is not None
    assert leitura.current_step is OnboardingStepName.artifact_accepted
    assert leitura.blame is onboarding.Blame.us
    assert leitura.threshold_days == 30
    assert "artifact_not_reported" not in leitura.gaps


def _snapshot(
    *, biahflow_project_id: int, client_id: int, artifact_accepted_at: str | None = None
) -> dict:
    snapshot: dict = {
        "project": {
            "id": biahflow_project_id, "name": "Automação", "description": "",
            "status": "active", "start_date": "2026-08-01", "due_date": "2026-09-30",
            "is_overdue": False, "client": {"id": client_id, "name": "Funil Ltda"},
        },
        "completion": 50,
        "milestones": [],
        "documents": [],
    }
    # Só entra quando o teste o pede: a **ausência** da chave é o caso de um Biahflow
    # anterior à FDD 031, e é um dos casos que precisam continuar cobertos.
    if artifact_accepted_at is not None:
        snapshot["artifact_accepted_at"] = artifact_accepted_at
    return snapshot
