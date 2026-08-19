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
import threading
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from portal_api import notifications, retention, worker
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
    item: str | None = None,
) -> uuid.UUID:
    """Um aviso já comitado, na forma que o ``fan_out`` grava — com link inclusive."""
    record = Notification(
        organization_id=ids["org"],
        project_id=ids["project"],
        user_id=ids["user"],
        kind=kind,
        title=title,
        detail=detail,
        link=notifications.deep_link(ids["project"], kind, item),
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


def test_the_message_url_points_at_the_row_and_not_at_the_tab(
    migrated_engine: Engine,
    world: dict,
    sent: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E, desde a ADR 0056, na **linha** — que é o que o critério (4) pede.

    Afirmado sobre o `url` que o `build_payload` mandou, e não sobre o `link` da
    linha do banco: o pedido enviado é o único lugar onde se prova o que **sai**,
    a mesma forma da asserção de que trecho de documento não viaja no template.
    """
    with Session(migrated_engine) as session:
        _notify(
            session,
            world,
            kind=NotificationKind.milestone_done,
            dedupe_key="m:1",
            title="Marco concluído",
            detail="Validação de integrações",
            item="Validação de integrações",
        )
        session.commit()

    _run(monkeypatch, world, _settings())

    url = sent.bodies[0]["template"]["components"][0]["parameters"][1]["text"]
    assert url == (
        f"https://portal.test/?project={world['project']}&tab=Cronograma"
        "&item=milestone%3AValida%C3%A7%C3%A3o%20de%20integra%C3%A7%C3%B5es"
    )


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


# --------------------------------------------------------------------------- #
# O teto de horário, e quem volta buscar o que ele adiou (FDD 021)
# --------------------------------------------------------------------------- #
#
# As duas metades são uma fatia só de propósito. Uma guarda que adia sem
# varredura seria descarte com outro nome: até aqui a task de envio só rodava no
# fim de um sync do Biahflow, e num projeto quieto o "depois" não chegava.

#: 23h30 em São Paulo. Escolhido em **UTC** porque é o que o worker passa, e a
#: conversão é justamente o que está sob teste.
_QUIET = datetime(2026, 8, 19, 2, 30, tzinfo=timezone.utc)
#: 08h30 em São Paulo, o primeiro horário fora da janela padrão.
_AWAKE = datetime(2026, 8, 19, 11, 30, tzinfo=timezone.utc)


def _freeze(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    """Congela o relógio da passagem, na forma do ``retention.now`` (ADR 0017).

    Uma indireção só: a task e o ``contact_budget`` leem o mesmo relógio, então
    congelar um congela os dois — que é a razão de o worker ter deixado de chamar
    ``datetime.now`` direto nesta fatia.
    """
    monkeypatch.setattr(retention, "now", lambda: moment)


def test_inside_the_quiet_window_nothing_is_sent_and_nothing_is_stamped(
    migrated_engine: Engine,
    world: dict,
    sent: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """É a asserção que distingue **adiar** de descartar.

    As outras três guardas do laço carimbam ``whatsapp_sent_at`` e seguem, porque
    o que as motiva é definitivo. O relógio não é: ele não foi gasto, só ainda não
    chegou — e um aviso carimbado aqui nunca mais sairia pelo canal.
    """
    with Session(migrated_engine) as session:
        notification_id = _notify(session, world)
        session.commit()

    _freeze(monkeypatch, _QUIET)
    result = _run(monkeypatch, world, _settings())

    assert result["sent"] == 0
    assert result["deferred"] == 1
    assert sent.requests == []
    with Session(migrated_engine) as session:
        assert session.get(Notification, notification_id).whatsapp_sent_at is None


def test_inside_the_quiet_window_the_contact_budget_is_not_spent(
    migrated_engine: Engine,
    world: dict,
    sent: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A guarda vem **antes** do ``claim``, e é isso que este teste fixa.

    Reservar orçamento para uma mensagem que não vai sair agora gastaria a unidade
    na hora errada — e é a unidade que conta a janela de sete dias, de modo que o
    aviso adiado voltaria de manhã já suprimido pelo teto que ele mesmo consumiu.
    """
    with Session(migrated_engine) as session:
        _notify(session, world)
        session.commit()

    _freeze(monkeypatch, _QUIET)
    _run(monkeypatch, world, _settings())

    with Session(migrated_engine) as session:
        spent = session.execute(
            select(ContactEvent).where(ContactEvent.user_id == world["user"])
        ).scalars().all()
    assert spent == []


def test_after_the_quiet_window_the_same_notice_goes_out(
    migrated_engine: Engine,
    world: dict,
    sent: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O adiamento tem fim, e o aviso é o mesmo — não um segundo aviso."""
    with Session(migrated_engine) as session:
        notification_id = _notify(session, world)
        session.commit()

    _freeze(monkeypatch, _QUIET)
    assert _run(monkeypatch, world, _settings())["sent"] == 0

    _freeze(monkeypatch, _AWAKE)
    assert _run(monkeypatch, world, _settings())["sent"] == 1

    assert len(sent.requests) == 1
    with Session(migrated_engine) as session:
        assert session.get(Notification, notification_id).whatsapp_sent_at is not None


def test_the_window_is_read_in_the_product_timezone_and_not_in_utc() -> None:
    """Os dois horários que **invertem** entre São Paulo e UTC.

    Sem eles o teste passaria por acidente sobre uma implementação que ignorasse o
    fuso: 23h30 e 08h30 em São Paulo caem do mesmo lado da janela em UTC. 06h00 e
    18h30 não caem — e são os que provam que a conversão acontece.
    """
    current = _settings()

    # 06h00 em São Paulo (09h00 UTC): silêncio. Em UTC seria dia claro.
    assert whatsapp.within_quiet_hours(
        current, datetime(2026, 8, 19, 9, 0, tzinfo=timezone.utc)
    )
    # 18h30 em São Paulo (21h30 UTC): não é silêncio. Em UTC já seria.
    assert not whatsapp.within_quiet_hours(
        current, datetime(2026, 8, 19, 21, 30, tzinfo=timezone.utc)
    )

    # E os dois lados da virada, que é o caso normal da janela e não a exceção.
    assert whatsapp.within_quiet_hours(current, _QUIET)
    assert not whatsapp.within_quiet_hours(current, _AWAKE)


def test_a_window_that_does_not_cross_midnight_is_read_correctly_too() -> None:
    """A outra forma da janela, que um ``start <= hour < end`` ingênuo acertaria e
    a de cima quebraria. As duas precisam estar certas ao mesmo tempo."""
    current = _settings(contact_quiet_hours_start=2, contact_quiet_hours_end=6)

    # 03h00 em São Paulo (06h00 UTC).
    assert whatsapp.within_quiet_hours(
        current, datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc)
    )
    # 07h00 em São Paulo (10h00 UTC).
    assert not whatsapp.within_quiet_hours(
        current, datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)
    )
    # E 23h30, que a janela padrão silencia e esta não.
    assert not whatsapp.within_quiet_hours(current, _QUIET)


def test_a_start_equal_to_the_end_silences_nothing(
    migrated_engine: Engine,
    world: dict,
    sent: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """É como um ambiente desliga a janela sem uma terceira setting booleana.

    E o teste é pela task, não pela função pura: desligar a janela tem de sair
    pelo caminho que envia, senão prova só que a aritmética aceita o caso.
    """
    with Session(migrated_engine) as session:
        _notify(session, world)
        session.commit()

    _freeze(monkeypatch, _QUIET)
    result = _run(
        monkeypatch,
        world,
        _settings(contact_quiet_hours_start=21, contact_quiet_hours_end=21),
    )

    assert result["sent"] == 1
    assert result["deferred"] == 0
    assert len(sent.requests) == 1


def test_the_sweep_sends_a_pending_notice_without_a_new_sync(
    migrated_engine: Engine,
    world: dict,
    sent: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A metade sem a qual a guarda de horário seria um descarte.

    Ninguém chama ``send_whatsapp_notices`` aqui: a varredura descobre sozinha o
    projeto que tem aviso pendente. Era o que faltava — não havia entrada de
    ``beat_schedule`` para o canal, e a task só rodava no fim de um sync.
    """
    with Session(migrated_engine) as session:
        notification_id = _notify(session, world)
        session.commit()

    _freeze(monkeypatch, _AWAKE)
    settings = _settings()
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    result = worker.send_due_whatsapp_notices()

    assert result["projects"] >= 1
    # As asserções são sobre **este** aviso e não sobre um total: a varredura é
    # global por desenho — ela procura em todo projeto com pendência —, e um total
    # aqui mediria também o que outro teste deixou no banco compartilhado.
    ours = [
        body
        for body in sent.bodies
        if str(world["project"]) in body["template"]["components"][0]["parameters"][1]["text"]
    ]
    assert len(ours) == 1
    with Session(migrated_engine) as session:
        assert session.get(Notification, notification_id).whatsapp_sent_at is not None


def test_the_sweep_asks_the_clock_once_instead_of_waking_every_project(
    migrated_engine: Engine,
    world: dict,
    sent: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A janela é a mesma para todos, e o tick pergunta por todos de uma vez.

    A guarda de dentro sozinha daria a resposta certa e cara: uma transação e um
    ``FOR UPDATE`` por projeto, de quinze em quinze minutos, para descobrir em
    cada um que ainda é madrugada — e a mesma linha de log repetida a noite
    inteira. O que este teste fixa é que **nada é carimbado e nada sai**, e que a
    contagem devolvida é de projetos, não de avisos.
    """
    with Session(migrated_engine) as session:
        notification_id = _notify(session, world)
        session.commit()

    _freeze(monkeypatch, _QUIET)
    settings = _settings()
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    result = worker.send_due_whatsapp_notices()

    assert result["sent"] == 0
    assert result["deferred"] == result["projects"] >= 1
    assert sent.requests == []
    with Session(migrated_engine) as session:
        assert session.get(Notification, notification_id).whatsapp_sent_at is None


def test_a_notice_already_claimed_by_another_pass_is_skipped(
    migrated_engine: Engine,
    world: dict,
    sent: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Com dois produtores, duas passagens podem pegar o mesmo aviso.

    **O que este teste afirma é o mecanismo, não uma corrida de verdade**: ele
    segura a linha com um ``FOR UPDATE`` noutra conexão — que é exatamente o
    estado em que uma passagem concorrente deixa a linha — e verifica que a task
    **pula** em vez de esperar ou de enviar. Provar a corrida real exigiria duas
    passagens disputando o mesmo instante, e o que se ganharia é a mesma
    afirmação com um escalonador no meio.

    O ``join`` com prazo é parte da asserção e não impaciência. Sem
    ``skip_locked`` a task não envia duas vezes: ela **bloqueia** na linha até a
    outra soltar — e uma regressão que trava é o pior sinal que este repositório
    conhece (foi o que segurou o ``web-quality`` por seis horas). Aqui ela vira
    vermelho com o motivo escrito.

    O ``claim`` do orçamento não cobre isto: ele é idempotente pela chave do aviso
    e responde ``True`` para as duas passagens — de propósito, para a retentativa
    não custar uma segunda unidade do teto.
    """
    with Session(migrated_engine) as session:
        notification_id = _notify(session, world)
        session.commit()

    _freeze(monkeypatch, _AWAKE)
    settings = _settings()
    monkeypatch.setattr(worker, "get_settings", lambda: settings)

    outcome: dict = {}

    def second_pass() -> None:
        outcome["result"] = worker.send_whatsapp_notices(str(world["project"]))

    passage = threading.Thread(target=second_pass, daemon=True)
    holder = Session(migrated_engine)
    try:
        holder.execute(
            select(Notification)
            .where(Notification.id == notification_id)
            .with_for_update()
        ).scalars().all()

        passage.start()
        passage.join(timeout=20)
        skipped = not passage.is_alive()
    finally:
        # Soltar a linha antes de afirmar: se a task tiver ficado bloqueada, é
        # aqui que ela destrava e termina, em vez de sobrar uma thread presa.
        holder.rollback()
        holder.close()
        passage.join(timeout=20)

    assert skipped, (
        "a passagem esperou pela linha em vez de pulá-la: o `select` perdeu o "
        "`skip_locked` e duas passagens agora se enfileiram sobre o mesmo aviso."
    )
    assert outcome["result"]["sent"] == 0
    assert outcome["result"]["notifications"] == 0
    assert sent.requests == []

    # E o aviso continua pendente: a passagem que o tinha é que vai enviá-lo.
    with Session(migrated_engine) as session:
        assert session.get(Notification, notification_id).whatsapp_sent_at is None
