"""Conversas persistidas, pelo stack HTTP real (ADR 0015).

Só o ``bearer_principal`` é dublado. Daí para baixo é tudo de verdade: a sessão
abre sob ``portal_app``, o turno é gravado pelas policies da migração 0012 e o
histórico volta pela mesma credencial que o gravou. Um 404 aqui significa que a
negação sobreviveu à cadeia inteira.

O que estes testes existem para fixar é a diferença entre *registrar* e *poder
reescrever*: o feedback muda, a resposta e as citações não. A prova de que o
banco recusa a reescrita mora em ``test_rls_isolation.py``, onde a tentativa é
feita em SQL cru — aqui prova-se que a API nem oferece o caminho.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from portal_api.auth import bearer_principal
from portal_api.main import app
from portal_api.models import (
    Conversation,
    MemberRole,
    Membership,
    Organization,
    PendingItem,
    Project,
    ProjectStatus,
    User,
)
from portal_api.principal import Principal

pytestmark = pytest.mark.integration

client = TestClient(app)

#: Bate no ramo de status do respondedor offline, que cita "Status do projeto" —
#: uma resposta fundamentada, com citação, sem depender de documento indexado.
GROUNDED_QUESTION = "Qual é o status do projeto?"
#: Nenhum ramo temático e nenhum termo em comum com a evidência: lacuna, e com
#: ela a pendência que a mensagem do assistente passa a referenciar.
GAP_QUESTION = "Qual foi a cotação do níquel na bolsa de Xangai?"


@dataclass(frozen=True)
class Actor:
    subject: str
    email: str
    full_name: str
    realm_roles: tuple[str, ...] = ("client_member",)


@dataclass(frozen=True)
class Talkers:
    organization_id: uuid.UUID
    project_id: uuid.UUID
    owner: Actor
    colleague: Actor


@pytest.fixture
def talkers(migrated_engine: Engine) -> Iterator[Talkers]:
    """Duas pessoas, um projeto — o par mínimo para "a conversa tem dono" ter sentido.

    Comitado de verdade: a API responde em outra conexão e não enxergaria a
    transação aberta de um fixture rolled-back.
    """
    tag = uuid.uuid4().hex[:8]
    with Session(migrated_engine) as session:
        organization = Organization(name="Conversas", slug=f"conversas-{tag}")
        session.add(organization)
        session.flush()
        project = Project(
            organization_id=organization.id,
            name="Automação de conversas",
            slug=f"conversas-project-{tag}",
            status=ProjectStatus.in_implementation,
            completion_percent=42,
        )
        session.add(project)
        session.flush()

        actors: list[Actor] = []
        for role in ("dono", "colega"):
            person = User(
                email=f"{role}-{tag}@example.com",
                full_name=role.title(),
                external_subject=f"sub-{role}-{tag}",
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
            actors.append(Actor(person.external_subject or "", person.email, person.full_name))
        session.commit()
        built = Talkers(organization.id, project.id, actors[0], actors[1])

    yield built

    # O chat comita — é uma requisição HTTP de verdade — então o que ele deixou
    # para trás sai aqui. A conversa cai por CASCADE do projeto; a pendência e a
    # auditoria também.
    with Session(migrated_engine) as session:
        session.execute(delete(Organization).where(Organization.id == built.organization_id))
        session.execute(delete(User).where(User.email.like(f"%-{tag}@example.com")))
        session.commit()


@pytest.fixture
def authenticated() -> Iterator[Callable[[Actor], None]]:
    def _as(actor: Actor) -> None:
        app.dependency_overrides[bearer_principal] = lambda: Principal(
            subject=actor.subject,
            email=actor.email,
            full_name=actor.full_name,
            realm_roles=frozenset(actor.realm_roles),
        )

    yield _as
    app.dependency_overrides.clear()


def _ask(question: str, conversation_id: str | None = None) -> dict:
    body: dict = {"question": question}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    response = client.post("/api/v1/chat", json=body)
    assert response.status_code == 200, response.text
    return response.json()


# --- o turno vira histórico ------------------------------------------------


def test_a_turn_is_persisted_with_the_citations_it_showed(
    talkers: Talkers, authenticated
) -> None:
    authenticated(talkers.owner)

    answered = _ask(GROUNDED_QUESTION)
    assert answered["confidence"] == "grounded"
    assert answered["sources"]

    history = client.get("/api/v1/me/conversations/latest")
    assert history.status_code == 200
    body = history.json()

    assert body["conversation_id"] == answered["conversation_id"]
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["text"] == GROUNDED_QUESTION
    # A citação do histórico é a mesma que a resposta mostrou na hora: é o que
    # faz disto um registro, e não uma segunda opinião sobre o mesmo turno.
    assert body["messages"][1]["sources"] == answered["sources"]
    assert body["messages"][1]["confidence"] == "grounded"


def test_the_gap_turn_records_the_pendencia_it_opened(
    talkers: Talkers, authenticated, migrated_engine: Engine
) -> None:
    """Sem evidência, a resposta é a lacuna — e o histórico guarda o vínculo.

    "Por que a IA não respondeu isso?" passa a ter, na mesma linha, a resposta
    dada e a pendência que ela abriu.
    """
    authenticated(talkers.owner)

    answered = _ask(GAP_QUESTION)
    assert answered["pending_created"] is True

    body = client.get("/api/v1/me/conversations/latest").json()
    assistant = body["messages"][1]
    assert assistant["confidence"] == "insufficient_context"
    assert assistant["sources"] == []
    assert assistant["pending_created"] is True

    with Session(migrated_engine) as check:
        pendings = check.execute(
            delete(PendingItem)
            .where(PendingItem.project_id == talkers.project_id)
            .returning(PendingItem.id)
        ).all()
        check.commit()
    assert len(pendings) == 1


def test_the_second_turn_continues_the_same_conversation(
    talkers: Talkers, authenticated
) -> None:
    authenticated(talkers.owner)

    first = _ask(GROUNDED_QUESTION)
    second = _ask("E o andamento das entregas?", first["conversation_id"])

    assert second["conversation_id"] == first["conversation_id"]

    body = client.get("/api/v1/me/conversations/latest").json()
    assert [message["role"] for message in body["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_omitting_the_conversation_id_opens_a_new_thread(
    talkers: Talkers, authenticated
) -> None:
    """É assim que "nova conversa" funciona — sem endpoint próprio para isso."""
    authenticated(talkers.owner)

    first = _ask(GROUNDED_QUESTION)
    second = _ask(GROUNDED_QUESTION)

    assert second["conversation_id"] != first["conversation_id"]
    # A corrente é a que recebeu mensagem por último, e ela começa do zero.
    body = client.get("/api/v1/me/conversations/latest").json()
    assert body["conversation_id"] == second["conversation_id"]
    assert len(body["messages"]) == 2


def test_an_unknown_conversation_id_opens_a_thread_instead_of_failing(
    talkers: Talkers, authenticated
) -> None:
    """O turno já foi respondido quando a gravação acontece.

    Derrubar a requisição por causa de um id velho no cliente perderia a resposta
    para punir o cliente por um estado obsoleto — degradar é a escolha certa, a
    mesma do broker morto em ``queue_*``.
    """
    authenticated(talkers.owner)

    answered = _ask(GROUNDED_QUESTION, str(uuid.uuid4()))

    assert answered["conversation_id"] is not None
    assert client.get("/api/v1/me/conversations/latest").json()["conversation_id"] == (
        answered["conversation_id"]
    )


def test_a_conversation_id_from_a_colleague_does_not_hijack_their_thread(
    talkers: Talkers, authenticated
) -> None:
    """O id de outra pessoa vale tanto quanto um id inventado: abre thread nova.

    Se valesse, bastaria adivinhar um UUID para escrever dentro da conversa
    alheia — e a policy de INSERT recusaria, mas só depois de o desenho já ter
    prometido o contrário.
    """
    authenticated(talkers.colleague)
    theirs = _ask(GROUNDED_QUESTION)

    authenticated(talkers.owner)
    mine = _ask(GROUNDED_QUESTION, theirs["conversation_id"])

    assert mine["conversation_id"] != theirs["conversation_id"]


def test_a_colleague_in_the_same_project_does_not_see_your_conversation(
    talkers: Talkers, authenticated
) -> None:
    authenticated(talkers.owner)
    _ask(GROUNDED_QUESTION)

    authenticated(talkers.colleague)
    body = client.get("/api/v1/me/conversations/latest").json()

    assert body == {"conversation_id": None, "messages": []}


def test_no_conversation_yet_is_an_empty_thread_and_not_a_404(
    talkers: Talkers, authenticated
) -> None:
    """"Ainda não perguntei nada" não é ausência de recurso."""
    authenticated(talkers.owner)

    response = client.get("/api/v1/me/conversations/latest")

    assert response.status_code == 200
    assert response.json() == {"conversation_id": None, "messages": []}


# --- feedback --------------------------------------------------------------


def test_feedback_is_recorded_and_the_resend_overwrites_the_vote(
    talkers: Talkers, authenticated
) -> None:
    """O polegar é o estado atual da opinião, não um evento — nada a deduplicar."""
    authenticated(talkers.owner)
    answered = _ask(GROUNDED_QUESTION)
    message_id = answered["message_id"]

    down = client.post(
        f"/api/v1/me/conversations/messages/{message_id}/feedback",
        json={"helpful": False, "comment": "citou o marco errado"},
    )
    assert down.status_code == 200
    assert down.json()["feedback"] == "not_helpful"

    up = client.post(
        f"/api/v1/me/conversations/messages/{message_id}/feedback",
        json={"helpful": True},
    )
    assert up.json()["feedback"] == "helpful"

    body = client.get("/api/v1/me/conversations/latest").json()
    assert body["messages"][1]["feedback"] == "helpful"
    # E o que ele avalia continua intacto: o feedback não é uma edição.
    assert body["messages"][1]["text"] == answered["answer"]
    assert body["messages"][1]["sources"] == answered["sources"]


def test_rating_your_own_question_is_not_an_opinion_about_anything(
    talkers: Talkers, authenticated
) -> None:
    authenticated(talkers.owner)
    _ask(GROUNDED_QUESTION)
    body = client.get("/api/v1/me/conversations/latest").json()
    my_question_id = body["messages"][0]["id"]

    response = client.post(
        f"/api/v1/me/conversations/messages/{my_question_id}/feedback",
        json={"helpful": True},
    )

    assert response.status_code == 404


def test_rating_a_colleagues_answer_is_404(talkers: Talkers, authenticated) -> None:
    authenticated(talkers.colleague)
    theirs = _ask(GROUNDED_QUESTION)

    authenticated(talkers.owner)
    response = client.post(
        f"/api/v1/me/conversations/messages/{theirs['message_id']}/feedback",
        json={"helpful": True},
    )

    assert response.status_code == 404


def test_rating_a_message_that_does_not_exist_is_the_same_404(
    talkers: Talkers, authenticated
) -> None:
    """A resposta é indistinguível da anterior: quem chama não descobre a diferença."""
    authenticated(talkers.owner)

    response = client.post(
        f"/api/v1/me/conversations/messages/{uuid.uuid4()}/feedback",
        json={"helpful": True},
    )

    assert response.status_code == 404


def test_the_history_returns_the_end_of_a_long_conversation(
    talkers: Talkers, authenticated, migrated_engine: Engine
) -> None:
    """Uma conversa longa perde o começo, não o que acabou de ser dito."""
    from portal_api import conversations as conversations_module

    authenticated(talkers.owner)
    first = _ask("Pergunta número 1: qual é o status?")
    conversation_id = first["conversation_id"]
    for number in range(2, 2 + conversations_module.HISTORY_LIMIT // 2):
        _ask(f"Pergunta número {number}: qual é o status?", conversation_id)

    body = client.get("/api/v1/me/conversations/latest").json()

    assert len(body["messages"]) == conversations_module.HISTORY_LIMIT
    assert body["messages"][0]["role"] == "user"
    assert "Pergunta número 1:" not in body["messages"][0]["text"]

    with Session(migrated_engine) as cleanup:
        cleanup.execute(
            delete(Conversation).where(Conversation.project_id == talkers.project_id)
        )
        cleanup.commit()
