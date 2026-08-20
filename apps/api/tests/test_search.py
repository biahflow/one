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
    MemberRole,
    Meeting,
    Membership,
    Milestone,
    Organization,
    PendingItem,
    Project,
    ProjectStatus,
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


def test_the_excerpt_shows_the_neighbourhood_with_its_accents(world: World) -> None:
    """Recorte em Python e não por ``ts_headline``: o casamento é sobre o texto
    dobrado e o recorte é sobre o original, que é o que vai para a tela."""
    long_text = ("palavra " * 60) + "cláusula de rescisão antecipada " + ("fim " * 60)

    excerpt = search._excerpt(long_text, "rescisao")

    assert "rescisão" in excerpt
    assert excerpt.startswith("…") and excerpt.endswith("…")
    assert len(excerpt) < len(long_text)
