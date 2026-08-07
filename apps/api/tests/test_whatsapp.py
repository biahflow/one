"""O canal de WhatsApp: os seis critérios de aceite da FDD 021 (ADR 0043).

Os envios são exercitados **pela task do worker**, e não chamando o adaptador
direto. A diferença foi medida na ADR 0035: uma ligação frouxa entre o teste e o
caminho real deu ``POST /chat`` como coberto por um 404 que era de outra rota.
Aqui vale o mesmo — provar que o adaptador monta o corpo não prova que o portão de
consentimento existe no caminho que envia.

O transporte entra pelo ponto de costura (``whatsapp.session_client``), com
``httpx.MockTransport``, na forma que o conector de Drive estabeleceu: nada aqui
fala com fornecedor nenhum, e o que cada teste afirma é sobre **o pedido enviado**.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from portal_api import notifications, worker
from portal_api.config import Settings
from portal_api.integrations import whatsapp
from portal_api.models import (
    ContactEvent,
    MemberRole,
    Membership,
    Notification,
    NotificationKind,
    Organization,
    Project,
    ProjectStatus,
    User,
)

pytestmark = pytest.mark.integration


def _settings(**overrides) -> Settings:
    base = dict(
        whatsapp_enabled=True,
        whatsapp_api_base="https://provider.test/v1",
        whatsapp_phone_number_id="55500",
        whatsapp_api_token="tok-local-only",
        whatsapp_webhook_secret="whsec-local-only",
        portal_web_url="https://portal.test",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def world(migrated_engine: Engine) -> Iterator[dict]:
    """Uma organização, um projeto e uma pessoa do cliente com telefone e opt-in."""
    tag = uuid.uuid4().hex[:8]
    ids: dict = {}
    with Session(migrated_engine) as session:
        organization = Organization(name="Zap Ltda", slug=f"zap-{tag}")
        session.add(organization)
        session.flush()
        project = Project(
            organization_id=organization.id,
            name="Projeto Zap",
            slug=f"zap-projeto-{tag}",
            status=ProjectStatus.in_implementation,
        )
        session.add(project)
        session.flush()
        person = User(
            email=f"cliente-{tag}@exemplo.test",
            full_name="Ana Cliente",
            external_subject=f"sub-zap-{tag}",
            phone="5511987654321",
            notify_by_whatsapp=True,
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
        session.commit()
        ids = {
            "org": organization.id,
            "project": project.id,
            "user": person.id,
        }
    yield ids
    with Session(migrated_engine) as session:
        session.execute(delete(ContactEvent).where(ContactEvent.organization_id == ids["org"]))
        session.execute(delete(Notification).where(Notification.organization_id == ids["org"]))
        session.execute(delete(Membership).where(Membership.organization_id == ids["org"]))
        session.execute(delete(User).where(User.id == ids["user"]))
        session.execute(delete(Project).where(Project.id == ids["project"]))
        session.execute(delete(Organization).where(Organization.id == ids["org"]))
        session.commit()


def _notify(
    session: Session,
    ids: dict,
    *,
    kind: NotificationKind = NotificationKind.document_added,
    dedupe_key: str = "document:1",
    title: str = "Novo documento no projeto",
    detail: str | None = "Contrato de prestação — cláusula 4, R$ 180.000",
) -> uuid.UUID:
    """Um aviso já comitado, na forma que o ``fan_out`` grava — com link inclusive."""
    record = Notification(
        organization_id=ids["org"],
        project_id=ids["project"],
        user_id=ids["user"],
        kind=kind,
        title=title,
        detail=detail,
        link=notifications.deep_link(ids["project"], kind),
        occurred_at=datetime.now(timezone.utc),
        dedupe_key=dedupe_key,
    )
    session.add(record)
    session.flush()
    return record.id


class _Capture:
    """Um transporte que grava o que foi pedido e responde como o fornecedor."""

    def __init__(self, status_code: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.status_code = status_code

    def client(self) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if self.status_code >= 400:
                return httpx.Response(self.status_code, json={"error": "nope"})
            return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})

        return httpx.Client(transport=httpx.MockTransport(handler))

    @property
    def bodies(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> _Capture:
    capture = _Capture()
    monkeypatch.setattr(whatsapp, "session_client", capture.client)
    return capture


def _run(monkeypatch: pytest.MonkeyPatch, ids: dict, settings: Settings) -> dict:
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    return worker.send_whatsapp_notices(str(ids["project"]))


# (1) Pessoa sem consentimento não recebe mensagem ------------------------------


def test_without_consent_nothing_is_sent_even_with_the_channel_on(
    migrated_engine: Engine,
    world: dict,
    sent: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E o portão é do **envio**, não do formulário.

    Com o canal ligado, o telefone preenchido e o aviso na fila, o que decide é a
    coluna de consentimento — conferida no momento de enviar.
    """
    with Session(migrated_engine) as session:
        _notify(session, world)
        session.get(User, world["user"]).notify_by_whatsapp = False
        session.commit()

    result = _run(monkeypatch, world, _settings())

    assert result["sent"] == 0
    assert sent.requests == []


# (2) Revogar o consentimento cancela um aviso já enfileirado -------------------


def test_revoking_the_consent_cancels_what_is_already_queued(
    migrated_engine: Engine,
    world: dict,
    sent: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O aviso fica na fila entre o sync e o envio; revogar no meio o cancela.

    E o carimbo sai mesmo sem envio, na decisão que o digest já tinha tomado: quem
    religar a preferência amanhã não recebe semanas de avisos de uma vez.
    """
    with Session(migrated_engine) as session:
        notification_id = _notify(session, world)
        session.commit()

    with Session(migrated_engine) as session:
        session.get(User, world["user"]).notify_by_whatsapp = False
        session.commit()

    _run(monkeypatch, world, _settings())

    assert sent.requests == []
    with Session(migrated_engine) as session:
        stamped = session.get(Notification, notification_id)
        assert stamped is not None and stamped.whatsapp_sent_at is not None

    # E religar não faz o aviso velho sair.
    with Session(migrated_engine) as session:
        session.get(User, world["user"]).notify_by_whatsapp = True
        session.commit()
    _run(monkeypatch, world, _settings())
    assert sent.requests == []


# (3) Uma mudança produz uma mensagem; a reentrega não produz a segunda ---------


def test_a_change_sends_once_and_a_redelivery_does_not_send_again(
    migrated_engine: Engine,
    world: dict,
    sent: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(migrated_engine) as session:
        _notify(session, world)
        session.commit()

    first = _run(monkeypatch, world, _settings())
    second = _run(monkeypatch, world, _settings())

    assert first["sent"] == 1
    assert second["sent"] == 0
    assert len(sent.requests) == 1

    # E gastou **uma** unidade do teto, não duas.
    with Session(migrated_engine) as session:
        spent = session.execute(
            select(ContactEvent).where(ContactEvent.user_id == world["user"])
        ).scalars().all()
    assert len(spent) == 1


# (4) O link abre a tela específica do assunto ----------------------------------


def test_the_link_lands_on_the_subject_and_not_on_the_home(
    migrated_engine: Engine,
    world: dict,
    sent: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A aba vai na URL, que é o que essa fatia teve de construir para existir.

    Até aqui a navegação era estado de React e nenhuma URL alcançava uma aba —
    então `Notification.link`, que o sino já renderizava, não tinha para onde
    apontar e era sempre nulo.
    """
    with Session(migrated_engine) as session:
        _notify(session, world, kind=NotificationKind.pending_opened, dedupe_key="p:1")
        session.commit()

    _run(monkeypatch, world, _settings())

    parameters = sent.bodies[0]["template"]["components"][0]["parameters"]
    url = parameters[1]["text"]
    assert url.startswith("https://portal.test/?project=")
    assert str(world["project"]) in url
    assert "tab=Pend%C3%AAncias" in url


# (5) Provedor fora do ar: o aviso continua no sino ----------------------------


def test_a_dead_provider_leaves_the_notice_in_the_bell_and_retries_later(
    migrated_engine: Engine,
    world: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sem carimbo, e sem gastar uma segunda unidade do teto na retentativa.

    É o par que a ADR 0042 desenhou: a reserva é pela chave do aviso, então a
    passagem seguinte a reusa em vez de debitar de novo — o que impede uma queda de
    minutos do fornecedor de virar silêncio permanente naquele canal.
    """
    with Session(migrated_engine) as session:
        notification_id = _notify(session, world)
        session.commit()

    broken = _Capture(status_code=500)
    monkeypatch.setattr(whatsapp, "session_client", broken.client)
    result = _run(monkeypatch, world, _settings())

    assert result["sent"] == 0
    with Session(migrated_engine) as session:
        assert session.get(Notification, notification_id).whatsapp_sent_at is None

    # O fornecedor volta: sai agora, e o teto foi debitado uma vez só.
    healthy = _Capture()
    monkeypatch.setattr(whatsapp, "session_client", healthy.client)
    again = _run(monkeypatch, world, _settings())

    assert again["sent"] == 1
    with Session(migrated_engine) as session:
        spent = session.execute(
            select(ContactEvent).where(ContactEvent.user_id == world["user"])
        ).scalars().all()
    assert len(spent) == 1


# (6) A mensagem não carrega trecho de documento nem valor comercial ------------


def test_the_message_carries_the_fact_and_the_link_and_nothing_else(
    migrated_engine: Engine,
    world: dict,
    sent: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asserção sobre **o que é enviado**, que é a única forma de provar que não sai.

    O ``detail`` do aviso semeado carrega de propósito uma cláusula e um valor: é o
    campo de texto livre do modelo, e o que este teste fixa é que ele **não tem por
    onde viajar** — o corpo tem dois parâmetros, o fato e o link.
    """
    with Session(migrated_engine) as session:
        _notify(session, world)
        session.commit()

    _run(monkeypatch, world, _settings())

    body = sent.bodies[0]
    raw = json.dumps(body, ensure_ascii=False)
    assert "180.000" not in raw
    assert "cláusula" not in raw
    assert body["recipient_type"] == "individual"

    parameters = body["template"]["components"][0]["parameters"]
    assert len(parameters) == 2
    assert parameters[0]["text"] == "Novo documento no projeto"


# O teto compartilhado, do lado do canal ---------------------------------------


def test_the_frequency_cap_suppresses_and_the_notice_stays_in_the_bell(
    migrated_engine: Engine,
    world: dict,
    sent: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passado o teto, o canal se cala — e o aviso continua no portal.

    O carimbo sai mesmo suprimido: deixar sem carimbo faria a mensagem sair dias
    depois, quando a janela rolasse, sobre um fato que o sino já mostrou.
    """
    with Session(migrated_engine) as session:
        for index in range(3):
            _notify(session, world, dedupe_key=f"document:{index}")
        session.commit()

    result = _run(monkeypatch, world, _settings(contact_cap_per_window=2))

    assert result["sent"] == 2
    assert result["suppressed"] == 1
    assert len(sent.requests) == 2
    with Session(migrated_engine) as session:
        remaining = session.execute(
            select(Notification).where(
                Notification.organization_id == world["org"],
                Notification.whatsapp_sent_at.is_(None),
            )
        ).scalars().all()
    assert remaining == []


# O adaptador: o 200 que não aceitou ------------------------------------------


def test_a_200_without_a_message_id_is_a_refusal(
    world: dict,
) -> None:
    """É a classe de defeito que três das quatro rodadas de homologação acharam.

    Linha gravada como se o fornecedor tivesse aceitado, sem ele ter aceitado — e
    aqui o estrago seria específico: o carimbo sairia sobre uma mensagem que não
    existe do outro lado, e o laço, que trabalha sobre o nulo, nunca mais a tentaria.
    """
    empty = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    )
    with pytest.raises(whatsapp.WhatsappError):
        whatsapp.send_notice(
            _settings(), to="5511987654321", title="Oi", url="https://portal.test/", client=empty
        )
