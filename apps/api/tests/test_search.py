"""A busca do projeto, pelo stack HTTP real (Fase 6, ADR 0024).

Só o ``bearer_principal`` é dublado, como em ``test_conversations.py``: daí para
baixo a sessão abre sob ``portal_app`` e as policies da migração 0007 valem. Um
resultado vazio aqui é uma negação que atravessou a cadeia inteira.

O teste que dá sentido a todos os outros é
``test_a_term_only_the_other_project_uses_finds_nothing``: o critério de aceite
da Fase 1 exige que acesso cruzado falhe "na API, no banco **e na busca**", e
até esta fatia a terceira não existia para falhar.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from portal_api import search
from portal_api.auth import bearer_principal
from portal_api.main import app
from portal_api.models import (
    Document,
    DocumentChunk,
    DocumentIngestState,
    DocumentSource,
    EpistemicStatus,
    Finding,
    ImprovementOpportunity,
    MemberRole,
    Meeting,
    Membership,
    Milestone,
    Organization,
    PainPoint,
    PendingItem,
    Process,
    ProcessStep,
    Project,
    ProjectStatus,
    SolutionHypothesis,
    User,
)
from portal_api.principal import Principal
from portal_api.repositories import TenantContext
from portal_api.scanner import ScanState

pytestmark = pytest.mark.integration

client = TestClient(app)

#: O termo que só o documento do **outro** projeto usa. Inventado justamente
#: para não casar com nada do read model semeado — se ele aparecer para o
#: cliente errado, é vazamento e não coincidência.
FOREIGN_TERM = "zanzibar"

#: O irmão do anterior para o **Discovery**, e ele é uma constante própria em vez
#: de um segundo uso do de cima: o Discovery é escopado pela **conta** e não pelo
#: projeto (ADR 0086), então o que ele prova é outra coisa — e as asserções que já
#: afirmam ``[hit["kind"] …] == ["chunk"]`` para o ``FOREIGN_TERM`` continuariam
#: certas por acidente se as duas espécies casassem com o mesmo termo.
FOREIGN_DISCOVERY_TERM = "tombuctu"

#: Os ids **da origem** que a fixture semeia no Discovery. São eles que a tela
#: publica como identidade e que a âncora carrega (ADR 0087) — daí estarem
#: nomeados aqui em vez de espalhados pelas asserções.
PROCESS_ID = 301
STEP_ID = 3101
FINDING_ID = 401
OPEN_FINDING_ID = 402
PAIN_POINT_ID = 501
IMPROVEMENT_OPPORTUNITY_ID = 601
SOLUTION_HYPOTHESIS_ID = 701


@dataclass(frozen=True)
class Actor:
    subject: str
    email: str
    full_name: str


@dataclass(frozen=True)
class Side:
    organization_id: uuid.UUID
    project_id: uuid.UUID
    document_id: uuid.UUID
    actor: Actor


@dataclass(frozen=True)
class World:
    mine: Side
    theirs: Side


def _populate(session: Session, tag: str, *, name: str, foreign: bool) -> Side:
    organization = Organization(name=f"Busca {name}", slug=f"busca-{name}-{tag}")
    session.add(organization)
    session.flush()

    project = Project(
        organization_id=organization.id,
        name=f"Projeto {name}",
        slug=f"busca-projeto-{name}-{tag}",
        status=ProjectStatus.in_implementation,
        completion_percent=40,
    )
    session.add(project)
    session.flush()

    person = User(
        email=f"busca-{name}-{tag}@example.com",
        full_name=f"Pessoa {name}",
        external_subject=f"sub-busca-{name}-{tag}",
    )
    session.add(person)
    session.flush()
    session.add(
        Membership(
            organization_id=organization.id,
            project_id=project.id,
            user_id=person.id,
            role=MemberRole.client_member,
        )
    )

    document = Document(
        organization_id=organization.id,
        project_id=project.id,
        title="Contrato de Manutenção" if not foreign else "Contrato Reservado",
        source=DocumentSource.upload,
        storage_key=f"org/{organization.id}/doc-{tag}-{name}.pdf",
        author_label="Jurídico",
        ingest_state=DocumentIngestState.indexed,
        scan_state=ScanState.clean,
    )
    session.add(document)
    session.flush()

    body = (
        f"A cláusula de salvaguarda {FOREIGN_TERM} vale por doze meses."
        if foreign
        else "A cláusula de rescisão antecipada exige aviso de trinta dias."
    )
    session.add(
        DocumentChunk(
            organization_id=organization.id,
            project_id=project.id,
            document_id=document.id,
            ordinal=0,
            text=body,
            location="página 2",
            char_count=len(body),
            content_hash=uuid.uuid4().hex,
        )
    )

    _populate_discovery(session, organization.id, foreign=foreign)

    if not foreign:
        session.add(
            Meeting(
                organization_id=organization.id,
                project_id=project.id,
                title="Reunião de Kickoff",
                status="held",
            )
        )
        session.add(
            PendingItem(
                organization_id=organization.id,
                project_id=project.id,
                title="Revisar a integração de faturamento",
                owner_label="Equipe Labs",
            )
        )
        session.add(
            Milestone(
                organization_id=organization.id,
                project_id=project.id,
                title="Migração do faturamento",
                position=1,
            )
        )

    session.flush()
    return Side(
        organization_id=organization.id,
        project_id=project.id,
        document_id=document.id,
        actor=Actor(person.external_subject or "", person.email, person.full_name),
    )


def _populate_discovery(
    session: Session, organization_id: uuid.UUID, *, foreign: bool
) -> None:
    """As quatro listas do Discovery da **conta**, na mesma fixture (ADR 0087).

    Aqui e não num mundo paralelo: o que a busca do Discovery precisa provar é
    isolamento, e isolamento se prova com **dois** tenants semeados pelo mesmo
    caminho. Um segundo fixture teria de recriar organização, projeto, pessoa e
    membership para chegar ao mesmo lugar — e a divergência entre os dois mundos
    seria a primeira coisa a passar despercebida.

    O lado alheio recebe um achado com o ``FOREIGN_DISCOVERY_TERM`` e nada mais: é
    o bastante para o par "o vizinho não acha / o dono acha", e o Discovery é da
    conta, então o vazamento que interessa é o de organização.
    """
    if foreign:
        session.add(
            Finding(
                organization_id=organization_id,
                external_id=FINDING_ID,
                statement=f"O fechamento de {FOREIGN_DISCOVERY_TERM} trava na alfândega.",
                epistemic_status=EpistemicStatus.fact,
            )
        )
        session.flush()
        return

    process = Process(
        organization_id=organization_id,
        external_id=PROCESS_ID,
        name="Fechamento contábil",
        position=0,
    )
    session.add(process)
    session.flush()
    session.add(
        ProcessStep(
            organization_id=organization_id,
            process_id=process.id,
            external_id=STEP_ID,
            position=0,
            name="Conferir os lançamentos",
            pessoas="Time do financeiro",
            sistema="ERP",
            # Casa com o **nome do processo** de propósito: é o par que prova o
            # dedupe — pai e filho casando produzem uma linha, não duas.
            dados="Razão contábil",
            # A coluna pela qual o teste procura o processo a partir do filho: é
            # onde mora a frase que alguém realmente digita.
            erro="Duplicidade de nota",
        )
    )
    session.add(
        Finding(
            organization_id=organization_id,
            external_id=FINDING_ID,
            statement="A conferência é feita duas vezes pelo mesmo analista.",
            epistemic_status=EpistemicStatus.hypothesis,
        )
    )
    session.add(
        Finding(
            organization_id=organization_id,
            external_id=OPEN_FINDING_ID,
            statement="Não se sabe quantos analistas revisam o mesmo lote.",
            epistemic_status=EpistemicStatus.unknown,
        )
    )
    session.add(
        PainPoint(
            organization_id=organization_id,
            external_id=PAIN_POINT_ID,
            title="Retrabalho na conferência",
            description="Gargalo no encerramento do mês.",
            status="confirmed",
        )
    )
    opportunity = ImprovementOpportunity(
        organization_id=organization_id,
        external_id=IMPROVEMENT_OPPORTUNITY_ID,
        title="Automatizar a conciliação",
        desired_change="Conferir por regra, com exceção para uma pessoa.",
        status="backlog",
    )
    session.add(opportunity)
    session.flush()
    session.add(
        SolutionHypothesis(
            organization_id=organization_id,
            improvement_opportunity_id=opportunity.id,
            external_id=SOLUTION_HYPOTHESIS_ID,
            statement="Um Funcionário Digital concilia por regra.",
            intervention="Fila de excedente no ERP",
            status="proposed",
        )
    )
    session.flush()


@pytest.fixture
def world(migrated_engine: Engine) -> Iterator[World]:
    """Dois projetos em duas organizações, com um termo exclusivo de cada.

    Comitado de verdade: a API responde em outra conexão e não enxergaria a
    transação aberta de um fixture com rollback — mesma razão do ``world`` de
    ``test_authorization.py``.
    """
    tag = uuid.uuid4().hex[:8]
    with Session(migrated_engine) as session:
        mine = _populate(session, tag, name="minha", foreign=False)
        theirs = _populate(session, tag, name="alheia", foreign=True)
        session.commit()
        built = World(mine, theirs)

    yield built

    with Session(migrated_engine) as session:
        session.execute(
            delete(Organization).where(
                Organization.id.in_(
                    [built.mine.organization_id, built.theirs.organization_id]
                )
            )
        )
        session.execute(delete(User).where(User.email.like(f"busca-%-{tag}@example.com")))
        session.commit()


@pytest.fixture
def authenticated() -> Iterator[Callable[[Actor], None]]:
    def _as(actor: Actor) -> None:
        app.dependency_overrides[bearer_principal] = lambda: Principal(
            subject=actor.subject,
            email=actor.email,
            full_name=actor.full_name,
            realm_roles=frozenset({"client_member"}),
        )

    yield _as
    app.dependency_overrides.clear()


def _response(term: str, project: uuid.UUID | str | None = None):
    params: dict[str, str] = {"q": term}
    # Ausente é ausente: um ``?project=`` vazio não é "sem parâmetro" — ele
    # chegaria à rota como string vazia e viraria 422 (ADR 0059).
    if project is not None:
        params["project"] = str(project)
    return client.get("/api/v1/me/search", params=params)


def _search(term: str, project: uuid.UUID | str | None = None) -> list[dict]:
    response = _response(term, project)
    assert response.status_code == 200, response.text
    return response.json()["results"]


def _kinds(results: list[dict]) -> set[str]:
    return {hit["kind"] for hit in results}


# --- o que a busca acha -----------------------------------------------------


def test_each_kind_the_tabs_show_is_reachable(world: World, authenticated) -> None:
    """As quatro espécies de linha, uma por aba — a promessa do placeholder."""
    authenticated(world.mine.actor)

    assert _kinds(_search("contrato")) >= {"document"}
    assert _kinds(_search("kickoff")) >= {"meeting"}
    assert _kinds(_search("faturamento")) >= {"pending", "milestone"}


def test_the_hit_carries_the_tab_it_belongs_to(world: World, authenticated) -> None:
    """O rótulo da aba vem pronto da API: a tela navega por rótulo, e um segundo
    mapa no navegador envelheceria sozinho."""
    authenticated(world.mine.actor)

    tabs = {hit["kind"]: hit["tab"] for hit in _search("faturamento")}
    assert tabs["pending"] == "Pendências"
    assert tabs["milestone"] == "Cronograma"
    assert _search("kickoff")[0]["tab"] == "Reuniões"


def test_the_meeting_hit_says_realizada_and_not_held(
    world: World, authenticated
) -> None:
    """O defeito anterior que a ADR 0087 achou: o mesmo valor com dois nomes.

    A busca mandava o ``status`` cru da origem — ``held`` — e a aba Reuniões desenha
    "Realizada", traduzida pelo BFF. O cliente lia um código em inglês ou uma palavra
    em português conforme a **porta** por onde chegasse na mesma reunião, e nada
    ficava vermelho: o campo tem escritor dos dois lados, e os dois discordavam.
    """
    authenticated(world.mine.actor)

    reunião = _search("kickoff")[0]
    assert reunião["kind"] == "meeting"
    assert reunião["detail"] == "Realizada"


def test_the_search_folds_accents_and_case(world: World, authenticated) -> None:
    """"reuniao" acha "Reunião", e "MIGRAÇÃO" acha "Migração".

    É o par ``fold``/``folded`` de ``textfold.py``: a coluna é dobrada pelo
    Postgres, o termo pelo Python. Um sem o outro faria a busca acertar num
    sentido e errar no outro.
    """
    authenticated(world.mine.actor)

    assert [hit["title"] for hit in _search("reuniao")] == ["Reunião de Kickoff"]
    assert [hit["title"] for hit in _search("MIGRAÇÃO")] == ["Migração do faturamento"]
    assert [hit["title"] for hit in _search("manutencao")] == ["Contrato de Manutenção"]


def test_a_term_inside_a_document_is_found_with_the_page(
    world: World, authenticated
) -> None:
    """O que faz "buscar no contexto do projeto" valer para o conteúdo.

    "rescisão" não aparece em título nenhum — só dentro do texto do trecho. E o
    hit volta com a página e com o id do documento, que é o que permite abrir a
    fonte pela rota assinada em vez de pedir confiança no rótulo.
    """
    authenticated(world.mine.actor)

    chunks = [hit for hit in _search("rescisão") if hit["kind"] == "chunk"]
    assert len(chunks) == 1
    assert chunks[0]["title"] == "Contrato de Manutenção"
    assert chunks[0]["location"] == "página 2"
    assert chunks[0]["document_id"] == str(world.mine.document_id)
    assert "rescisão" in chunks[0]["detail"]


def test_the_document_text_is_found_without_its_accents_too(
    world: World, authenticated
) -> None:
    """O índice GIN é sobre a expressão dobrada, e a consulta repete a mesma
    expressão — é a única coisa que faz o índice ser usado."""
    authenticated(world.mine.actor)

    assert [hit["kind"] for hit in _search("rescisao")] == ["chunk"]


# --- o Discovery, que a aba mostra e a busca não alcançava (ADR 0087) --------


def test_each_discovery_list_is_reachable_by_a_term_only_it_uses(
    world: World, authenticated
) -> None:
    """As quatro listas da aba, uma a uma.

    A regra da ADR 0024 §5 é que entra na busca o que alguma aba mostra, e a ADR
    0086 acrescentou quatro listas à tela sem que a busca as alcançasse. Cada termo
    aqui existe numa lista só, então o hit não pode vir por acaso de outra.
    """
    authenticated(world.mine.actor)

    assert _kinds(_search("contábil")) == {"process"}
    assert _kinds(_search("gargalo")) == {"pain_point"}
    assert _kinds(_search("conciliação")) == {"improvement_opportunity"}

    achados = _search("analista")
    assert _kinds(achados) == {"finding"}
    assert len(achados) == 2, "a hipótese e a pergunta em aberto, as duas"


def test_the_process_is_found_by_a_column_of_its_step_and_the_hit_is_the_process(
    world: World, authenticated
) -> None:
    """Casa no filho, o hit é do pai — *"a âncora é do objeto, não do fato"*.

    "Duplicidade de nota" está numa coluna de ``ProcessStep`` e em lugar nenhum
    além dela. O hit é do **processo**, porque é a linha que a aba desenha; a etapa
    é uma linha da tabela dentro dele, e o ``detail`` diz qual foi — sem isso o
    cliente veria um processo na lista sem ter como saber por que ele apareceu.
    """
    authenticated(world.mine.actor)

    hits = _search("duplicidade")
    assert [hit["kind"] for hit in hits] == ["process"]
    assert hits[0]["title"] == "Fechamento contábil"
    assert hits[0]["detail"] == "Conferir os lançamentos"
    assert hits[0]["tab"] == "Discovery"


def test_a_process_whose_name_and_step_both_match_is_a_single_row(
    world: World, authenticated
) -> None:
    """Um casamento no pai **e** no filho não vira duas linhas iguais.

    "contábil" está no nome do processo e na coluna ``dados`` da etapa. Sem o
    dedupe, a lista mostraria o mesmo processo duas vezes com âncoras idênticas — e
    o teto por espécie passaria a ser gasto por duplicata.

    O nome ganha, e o ``detail`` fica vazio: quando o casamento é do próprio
    processo não há etapa a nomear.
    """
    authenticated(world.mine.actor)

    hits = _search("contábil")
    assert len(hits) == 1
    assert hits[0]["detail"] == ""


def test_the_improvement_opportunity_is_found_by_its_solution_hypothesis(
    world: World, authenticated
) -> None:
    """O irmão do processo, um nível abaixo: a hipótese vem aninhada no pai.

    "excedente" só existe na ``intervention`` de uma ``SolutionHypothesis``, que a
    aba desenha debaixo da oportunidade — e é a oportunidade que tem linha.
    """
    authenticated(world.mine.actor)

    hits = _search("excedente")
    assert [hit["kind"] for hit in hits] == ["improvement_opportunity"]
    assert hits[0]["title"] == "Automatizar a conciliação"


def test_no_finding_reaches_the_client_without_its_epistemic_label(
    world: World, authenticated
) -> None:
    """A regra 1 da §3 do Language Map, na porta que a ADR 0086 não olhou.

    Um ``hypothesis`` aparece **rotulado** como hipótese ou não aparece, nunca como
    fato — e um resultado de busca com o ``statement`` cru é uma afirmação sem
    rótulo, que é a leitura de fato por omissão. O rótulo viaja no ``detail``, que é
    o que a tela renderiza abaixo do título.

    A lacuna entra junto e rotulada: um levantamento que só mostrasse o que ficou
    sabido esconderia do cliente o que ainda não se sabe.
    """
    authenticated(world.mine.actor)

    rotulos = {hit["title"]: hit["detail"] for hit in _search("analista")}
    assert rotulos == {
        "A conferência é feita duas vezes pelo mesmo analista.": "Hipótese",
        "Não se sabe quantos analistas revisam o mesmo lote.": "Pergunta em aberto",
    }


def test_the_search_never_shows_more_of_a_row_than_the_tab_does(
    world: World, authenticated
) -> None:
    """A dor e a oportunidade saem **sem** ``detail``, e isso é decisão medida.

    O candidato óbvio era o ``status``, e ele não serve por duas razões que se
    somam: ele guarda o código cru da origem (``confirmed``, ``backlog``), e **nenhum
    bloco da aba o desenha** — a dor mostra título, impacto, descrição e achados; a
    oportunidade mostra título e Opportunity Score. Publicá-lo aqui faria a busca
    mostrar *mais* do que a aba, que é a ADR 0024 §5 ao contrário, e mostrá-lo em
    inglês numa tela cujo texto visível é PT-BR.

    O par que dá sentido a esta asserção é o ``detail`` do processo logo acima: lá
    ele existe porque a etapa que casou tem **nome** e a aba a desenha. A regra não é
    "não mande detalhe", é "não mande o que a aba não mostra".
    """
    authenticated(world.mine.actor)

    assert _search("gargalo")[0]["detail"] == ""
    assert _search("conciliação")[0]["detail"] == ""
    assert "confirmed" not in str(_search("gargalo"))
    assert "backlog" not in str(_search("conciliação"))


def test_the_discovery_hit_anchors_by_the_source_id_and_not_by_the_label(
    world: World, authenticated
) -> None:
    """A bifurcação da âncora, afirmada inteira (ADR 0087).

    As outras cinco espécies ancoram por ``<namespace>:<título>`` e continuam
    assim; as quatro do Discovery ancoram pelo **id da origem**, que é o que a tela
    publica como identidade e usa como chave de lista. Ancorar o ``Finding`` por
    texto seria ancorar por um parágrafo — ele não tem título.
    """
    authenticated(world.mine.actor)

    assert _search("contábil")[0]["item_anchor"] == f"process:{PROCESS_ID}"
    assert _search("gargalo")[0]["item_anchor"] == f"pain_point:{PAIN_POINT_ID}"
    assert (
        _search("conciliação")[0]["item_anchor"]
        == f"improvement_opportunity:{IMPROVEMENT_OPPORTUNITY_ID}"
    )

    achados = {hit["title"]: hit["item_anchor"] for hit in _search("analista")}
    assert achados["A conferência é feita duas vezes pelo mesmo analista."] == (
        f"finding:{FINDING_ID}"
    )

    # E o rótulo continua sendo a metade da direita nas espécies de sempre.
    assert _search("kickoff")[0]["item_anchor"] == "meeting:Reunião de Kickoff"


def test_a_discovery_term_only_the_other_account_uses_finds_nothing(
    world: World, authenticated
) -> None:
    """O critério de aceite da Fase 1 aplicado ao escopo de **conta**.

    O Discovery não é escopado por projeto: a lista inteira da conta chega em
    fan-out no snapshot de todo projeto dela (ADR 0086). O que impede o hit é o par
    de barreiras — filtro do repositório e RLS —, e o mesmo termo achado pelo dono é
    o que torna o vazio significativo em vez de acidental.
    """
    authenticated(world.mine.actor)
    assert _search(FOREIGN_DISCOVERY_TERM) == []

    authenticated(world.theirs.actor)
    assert [hit["kind"] for hit in _search(FOREIGN_DISCOVERY_TERM)] == ["finding"]


# --- o projeto que a tela está mostrando (ADR 0059) ----------------------


@pytest.fixture
def two_projects(world: World, migrated_engine: Engine) -> World:
    """O ator que faltava neste arquivo: **uma pessoa com duas memberships**.

    O ``world`` dá um projeto por pessoa, e é por isso que o defeito F1 podia
    existir sem nenhum teste ficar vermelho: com um projeto só, "o mais recente"
    e "o que está na tela" são sempre o mesmo projeto, e a diferença entre
    ``default_project`` e ``chosen_project`` não tem como aparecer.

    O vínculo novo nasce **depois** do do ``world``, em transação própria, então
    é ele o mais recente — que é o que ``access.default_project`` responderia sem
    o parâmetro.
    """
    with Session(migrated_engine) as session:
        person = session.execute(
            select(User).where(User.external_subject == world.mine.actor.subject)
        ).scalar_one()
        session.add(
            Membership(
                organization_id=world.theirs.organization_id,
                project_id=world.theirs.project_id,
                user_id=person.id,
                role=MemberRole.client_member,
            )
        )
        session.commit()
    return world


def test_the_search_answers_for_the_project_the_screen_names(
    two_projects: World, authenticated
) -> None:
    """O parâmetro escolhe o projeto, e o cliente com dois projetos deixa de ver o outro.

    Até a ADR 0057 a rota resolvia ``access.default_project`` — a membership mais
    recente —, enquanto o dashboard ao lado vinha de
    ``/projects/{project_id}/dashboard`` com o ``?project=`` da URL. Um cliente
    vendo B recebia a busca de A, e os dois documentos que afirmavam o contrário
    (a FDD 018 e o docstring da rota) não podiam estar certos ao mesmo tempo.
    """
    authenticated(two_projects.mine.actor)

    meu = _search("rescisão", two_projects.mine.project_id)
    assert [hit["title"] for hit in meu] == ["Contrato de Manutenção"]
    assert _search(FOREIGN_TERM, two_projects.mine.project_id) == []

    outro = _search(FOREIGN_TERM, two_projects.theirs.project_id)
    assert [hit["kind"] for hit in outro] == ["chunk"]
    assert _search("rescisão", two_projects.theirs.project_id) == []


def test_without_the_parameter_the_search_still_answers_for_the_default(
    two_projects: World, authenticated
) -> None:
    """Ausente é o comportamento de sempre: quem não nomeia projeto cai no padrão.

    Compatível para trás de propósito — as onze rotas de ``/me/`` respondiam
    assim desde a Fase 1, e o parâmetro é um acréscimo, não uma troca. O padrão é
    a membership mais recente, que aqui é a do ``two_projects``.
    """
    authenticated(two_projects.mine.actor)

    assert [hit["kind"] for hit in _search(FOREIGN_TERM)] == ["chunk"]
    assert _search("rescisão") == []


def test_a_project_the_caller_does_not_reach_is_404_and_never_the_default(
    world: World, authenticated
) -> None:
    """Projeto alheio recusa; não cai no padrão em silêncio.

    Cair no padrão seria o ``.get(kind, _CLIENT_ONLY)`` da ADR 0040 outra vez: o
    esquecimento entrega ao cliente a coisa **errada** em vez de recusar. E é 404
    e nunca 403, como toda negação deste contrato (regra 6 do `AGENTS.md`).
    """
    authenticated(world.mine.actor)

    assert _response("contrato", world.theirs.project_id).status_code == 404
    assert _response("contrato", uuid.uuid4()).status_code == 404


# --- o que a busca não acha -------------------------------------------------


def test_a_term_only_the_other_project_uses_finds_nothing(
    world: World, authenticated
) -> None:
    """O critério de aceite da Fase 1, na terceira das três camadas.

    O documento do outro projeto existe, está indexado e limpo. O que impede o
    hit é o par de barreiras — filtro do repositório e RLS —, e o mesmo termo
    achado pelo dono é o que torna o vazio significativo em vez de acidental.
    """
    authenticated(world.mine.actor)
    assert _search(FOREIGN_TERM) == []
    assert _search("reservado") == []

    authenticated(world.theirs.actor)
    assert [hit["kind"] for hit in _search(FOREIGN_TERM)] == ["chunk"]


def test_the_database_refuses_even_when_the_app_filter_points_elsewhere(
    world: World, rls_session: Session, bind_context
) -> None:
    """A segunda barreira, sozinha.

    Com o contexto de tenant fixado no projeto A e um ``TenantContext`` forjado
    apontando para o B, o filtro da aplicação está do lado errado de propósito —
    e as policies devolvem zero linhas assim mesmo. É o que garante que a busca
    não é uma superfície onde a RLS deixou de ser a rede embaixo.
    """
    bind_context(
        subject=world.mine.actor.subject,
        email=world.mine.actor.email,
        organization_id=world.mine.organization_id,
        project_id=world.mine.project_id,
    )
    forged = TenantContext(
        organization_id=world.theirs.organization_id,
        project_id=world.theirs.project_id,
    )

    assert search.search_project(rls_session, forged, FOREIGN_TERM) == []


def test_the_database_refuses_the_discovery_of_another_account(
    world: World, rls_session: Session, bind_context
) -> None:
    """A segunda barreira, sozinha, sobre as tabelas que a fatia acrescentou.

    Vale por si e não é cópia da de cima: lá o que a RLS protege é escopado por
    **projeto**, e aqui por **conta** — as seis tabelas do Discovery não têm
    ``project_id``, e as duas de ligação não têm chave de tenant nenhuma (a policy
    as alcança pelo pai). Com o contexto fixado numa conta e um ``TenantContext``
    forjado apontando para a outra, o filtro da aplicação está do lado errado de
    propósito e as policies devolvem zero linhas assim mesmo.
    """
    bind_context(
        subject=world.mine.actor.subject,
        email=world.mine.actor.email,
        organization_id=world.mine.organization_id,
        project_id=world.mine.project_id,
    )
    forged = TenantContext(
        organization_id=world.theirs.organization_id,
        project_id=world.theirs.project_id,
    )

    assert search.search_project(rls_session, forged, FOREIGN_DISCOVERY_TERM) == []


def test_a_term_too_short_finds_nothing_and_is_not_an_error(
    world: World, authenticated
) -> None:
    """A busca não erra, ela não acha: 200 com lista vazia, nunca 422."""
    authenticated(world.mine.actor)

    assert _search("c") == []
    assert _search("   ") == []
    assert _search("") == []


def test_the_wildcards_of_like_are_not_a_query_language(
    world: World, authenticated
) -> None:
    """``%`` e ``_`` são texto, não sintaxe.

    Sem o escape, ``%%`` casaria com o projeto inteiro — a busca passaria a
    responder a uma linguagem que ninguém documentou e que o cliente não sabe
    que está usando.
    """
    authenticated(world.mine.actor)

    assert _search("%%") == []
    assert _search("__") == []


def test_a_document_barred_by_the_scanner_offers_nothing_to_open(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    """Varredura é portão separado do isolamento, e vale aqui também.

    O título continua achável — ele já está na aba Documentos, e some da busca
    seria mentir sobre o que o projeto tem. O que não sai é o **conteúdo**, e o
    hit não oferece ``document_id``: sem id não há URL assinada, que é a mesma
    regra de ``document_download``.
    """
    authenticated(world.mine.actor)
    with Session(migrated_engine) as session:
        document = session.get(Document, world.mine.document_id)
        assert document is not None
        document.scan_state = ScanState.infected
        session.commit()

    results = _search("rescisão")
    assert [hit["kind"] for hit in results] == []

    titles = _search("contrato")
    assert [hit["kind"] for hit in titles] == ["document"]
    assert titles[0]["document_id"] == ""


def test_a_decision_is_reachable_now_that_a_tab_shows_one(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    """A exceção que a regra 1 carregava por três fases, fechada (ADR 0049).

    Este teste afirmava o contrário: que decisão **não** entra na busca, porque nenhuma
    aba a mostrava e um hit dela levaria a lugar nenhum. O docstring do módulo dizia
    "quando existir aba de decisões, entra aqui junto", e a ADR 0024 nomeava este caso
    como o que muda junto. É o que está acontecendo aqui.
    """
    from portal_api.models import Decision

    authenticated(world.mine.actor)
    with Session(migrated_engine) as session:
        session.add(
            Decision(
                organization_id=world.mine.organization_id,
                project_id=world.mine.project_id,
                title="Decisão sobre o faturamento",
                rationale="O cliente prefere nota mensal por centro de custo.",
            )
        )
        session.commit()

    hits = _search("faturamento")
    assert "decision" in _kinds(hits)
    decision = next(hit for hit in hits if hit["kind"] == "decision")
    assert decision["tab"] == "Decisões"


def test_the_hit_carries_the_row_it_points_at_and_not_only_the_tab(
    world: World, authenticated
) -> None:
    """A âncora vem pronta da rota, no mesmo formato do ``?item=`` do aviso (ADR 0057).

    O par do ``test_the_hit_carries_the_tab_it_belongs_to`` um degrau abaixo: até
    a ADR 0056 a resolução do clique era a **aba**, dos dois lados; o link do
    WhatsApp passou a cair na linha e a navegação de dentro do portal ficou
    para trás. Aqui é a rota que fecha a diferença.

    O formato é afirmado **inteiro** e não por prefixo, de propósito: é
    ``<namespace>:<rótulo>``, o rótulo é o ``title`` que a tela usa como chave de
    lista, e trocar ``title`` por ``detail`` na derivação produziria uma âncora bem
    formada que não casa com linha nenhuma — o defeito silencioso desta família.
    """
    authenticated(world.mine.actor)

    anchors = {hit["kind"]: hit["item_anchor"] for hit in _search("faturamento")}
    assert anchors["pending"] == "pending:Revisar a integração de faturamento"
    assert anchors["milestone"] == "milestone:Migração do faturamento"

    assert _search("kickoff")[0]["item_anchor"] == "meeting:Reunião de Kickoff"

    por_espécie = {hit["kind"]: hit["item_anchor"] for hit in _search("rescisão")}
    # O trecho ancora no **documento**: "a âncora é do objeto, não do fato"
    # (ADR 0056), e a aba de Documentos desenha a linha do documento, não a do
    # trecho — que não tem linha nenhuma lá.
    assert por_espécie["chunk"] == "document:Contrato de Manutenção"


def test_the_decision_says_it_has_no_row_instead_of_inventing_one(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    """A isenção assinada em ``ANCHORLESS_HITS``, do lado da resposta.

    Vazio é "não há o que ancorar", nunca "ancore por sua conta" — a mesma
    convenção do ``document_id`` ao lado. A aba de Decisões **não** desenha
    ``data-item``, e isso é decisão da ADR 0056: publicar um namespace que só
    existe de um lado é construir o atributo antes do escritor.
    """
    from portal_api.models import Decision

    authenticated(world.mine.actor)
    with Session(migrated_engine) as session:
        session.add(
            Decision(
                organization_id=world.mine.organization_id,
                project_id=world.mine.project_id,
                title="Decisão sobre o faturamento",
                rationale="O cliente prefere nota mensal por centro de custo.",
            )
        )
        session.commit()

    decision = next(hit for hit in _search("faturamento") if hit["kind"] == "decision")
    assert decision["item_anchor"] == ""
    assert decision["tab"] == "Decisões"


def test_a_decision_is_found_by_its_rationale_not_only_its_title(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    """Quem procura uma decisão raramente lembra o título dela.

    Lembra do assunto que a motivou — que está no porquê. Sem o `rationale` no
    casamento, a busca acharia a decisão só por um texto que ninguém memoriza.
    """
    from portal_api.models import Decision

    authenticated(world.mine.actor)
    with Session(migrated_engine) as session:
        session.add(
            Decision(
                organization_id=world.mine.organization_id,
                project_id=world.mine.project_id,
                title="Adotar fila gerenciada",
                rationale="O volume previsto não paga o Memorystore.",
            )
        )
        session.commit()

    assert "decision" in _kinds(_search("Memorystore"))


# --- forma do resultado -----------------------------------------------------


def test_the_result_is_capped_per_kind(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    """Um projeto com muitos documentos não pode esconder a única reunião que
    casou — daí o teto ser por espécie antes de ser geral."""
    authenticated(world.mine.actor)
    with Session(migrated_engine) as session:
        for index in range(search.PER_KIND_LIMIT + 3):
            session.add(
                Document(
                    organization_id=world.mine.organization_id,
                    project_id=world.mine.project_id,
                    title=f"Contrato anexo {index}",
                    source=DocumentSource.upload,
                    scan_state=ScanState.clean,
                )
            )
        session.commit()

    results = _search("contrato")
    documents = [hit for hit in results if hit["kind"] == "document"]
    assert len(documents) == search.PER_KIND_LIMIT
    assert len(results) <= search.TOTAL_LIMIT


def test_the_document_excerpt_survives_a_screenful_of_read_model_rows(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    """O defeito que a fatia agravaria, virado asserção (ADR 0087).

    Vinte linhas de read model casando **já** enchiam as vinte vagas antes desta
    fatia, e os trechos entram por último: o corte por ordem de inserção os
    derrubava inteiros. Com nove espécies o silêncio deles seria o caso comum — e os
    trechos são o que a ADR 0024 §4 diz fazer a promessa valer, porque a pergunta
    que alguém faz de verdade é onde está a cláusula de rescisão.

    O termo casa nas quatro espécies de linha **e** dentro do documento, que é a
    única forma de a disputa acontecer numa busca só.
    """
    authenticated(world.mine.actor)
    with Session(migrated_engine) as session:
        for index in range(search.PER_KIND_LIMIT):
            session.add(
                Document(
                    organization_id=world.mine.organization_id,
                    project_id=world.mine.project_id,
                    title=f"Rescisão anexo {index}",
                    source=DocumentSource.upload,
                    scan_state=ScanState.clean,
                )
            )
            session.add(
                Meeting(
                    organization_id=world.mine.organization_id,
                    project_id=world.mine.project_id,
                    title=f"Rescisão em pauta {index}",
                    status="held",
                )
            )
            session.add(
                PendingItem(
                    organization_id=world.mine.organization_id,
                    project_id=world.mine.project_id,
                    title=f"Revisar a rescisão {index}",
                )
            )
            session.add(
                Milestone(
                    organization_id=world.mine.organization_id,
                    project_id=world.mine.project_id,
                    title=f"Rescisão assinada {index}",
                    position=index,
                )
            )
        session.commit()

    results = _search("rescisão")
    assert len(results) <= search.TOTAL_LIMIT
    kinds = [hit["kind"] for hit in results]

    assert "chunk" in kinds, (
        "vinte linhas de read model derrubaram os trechos: o corte voltou a ser por"
        " ordem de inserção, e a busca virou uma lista de títulos"
    )
    # E nenhuma das outras foi zerada para isso acontecer: o rodízio reparte, não
    # troca uma espécie por outra.
    assert {"document", "meeting", "pending", "milestone"} <= set(kinds)


def test_the_excerpt_shows_the_neighbourhood_with_its_accents(world: World) -> None:
    """Recorte em Python e não por ``ts_headline``: o casamento é sobre o texto
    dobrado e o recorte é sobre o original, que é o que vai para a tela."""
    long_text = ("palavra " * 60) + "cláusula de rescisão antecipada " + ("fim " * 60)

    excerpt = search._excerpt(long_text, "rescisao")

    assert "rescisão" in excerpt
    assert excerpt.startswith("…") and excerpt.endswith("…")
    assert len(excerpt) < len(long_text)
