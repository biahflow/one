"""Emissão de notificações a partir do sync (Fase 2, ADR 0012).

O que estes testes protegem, em ordem de importância:

1. **o mesmo webhook reenviado não duplica.** O snapshot do Biahflow é uma
   reconciliação completa, não um delta, então ele chega repetido por desenho;
2. **o primeiro sync não notifica.** Um projeto que acabou de chegar tem marcos
   concluídos e documentos que o cliente nunca "viu acontecer";
3. **a audiência é dado, não convenção** — o cliente recebe o andamento, o time
   interno só o que exige ação dele.

Todos precisam de Postgres de verdade (enum, JSONB, ``ON CONFLICT``) e se
auto-pulam quando não há, como o resto da camada de dados.
"""

from __future__ import annotations

import uuid
from contextlib import nullcontext
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal_api import notifications, worker
from portal_api.integrations import biahflow
from portal_api.models import (
    DeliverableState,
    MemberRole,
    Membership,
    MilestoneState,
    Notification,
    NotificationKind,
    PendingItem,
    PendingItemComment,
    PendingState,
    PhaseState,
    User,
)

pytestmark = pytest.mark.integration


def _snapshot(*, biahflow_project_id: int, client_id: int) -> dict[str, Any]:
    """Snapshot mínimo, com um de cada fato que vira aviso."""
    return {
        "project": {
            "id": biahflow_project_id,
            "name": "Automação Financeira",
            "status": "active",
            "client": {"id": client_id, "name": "Acme Brasil"},
        },
        "completion": 40,
        "milestones": [
            {"id": 1, "title": "Validação", "status": "todo", "party": "provider",
             "due_date": None, "completed_at": None},
        ],
        "journey": {
            "current_phase": "Welcome",
            "phases": [
                {"name": "Welcome", "description": "", "position": 0, "status": "active",
                 "target_date": None, "deliverables": [
                     {"name": "Acesso ao portal", "status": "pending", "link": None}]},
                {"name": "Prove", "description": "", "position": 1, "status": "locked",
                 "target_date": None, "deliverables": []},
            ],
        },
        "health": {"label": "No prazo", "level": "green"},
        "documents": [
            {"id": 41, "name": "Plano de implantação.pdf", "type": "PDF", "author": "Ana",
             "link": "https://drive.example/doc-41", "created_at": "2026-08-01T12:00:00+00:00"},
        ],
        "meetings": [
            {"id": 5, "title": "Kickoff", "date": "2026-08-07", "recording_url": "",
             "has_transcript": False, "status": "held"},
        ],
        "pendencias": [
            {"id": 71, "title": "Aprovar fluxo", "status": "open", "party": "client",
             "created_at": "2026-08-02T10:00:00+00:00", "resolved_at": None},
        ],
    }


def _with_members(session: Session, project, tag: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Um cliente e um interno no projeto. Devolve (client_id, internal_id)."""
    created: list[uuid.UUID] = []
    for name, role in (("cliente", MemberRole.client_member), ("interno", MemberRole.internal_admin)):
        user = User(
            email=f"{name}-{tag}@example.com",
            full_name=name.title(),
            external_subject=f"sub-{name}-{tag}",
            is_internal=role is not MemberRole.client_member,
        )
        session.add(user)
        session.flush()
        session.add(
            Membership(
                organization_id=project.organization_id,
                project_id=project.id,
                user_id=user.id,
                role=role,
            )
        )
        created.append(user.id)
    session.flush()
    return created[0], created[1]


def _notifications(session: Session, project_id: uuid.UUID) -> list[Notification]:
    return list(
        session.execute(
            select(Notification).where(Notification.project_id == project_id)
        ).scalars()
    )


def test_first_sync_notifies_nobody(db_session: Session) -> None:
    """Um projeto novo chega inteiro; nada nele "aconteceu" para o cliente."""
    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=101, client_id=51)
    )
    assert _notifications(db_session, project.id) == []


def test_milestone_reaching_done_notifies_the_client(db_session: Session) -> None:
    snapshot = _snapshot(biahflow_project_id=102, client_id=52)
    project = biahflow.sync_snapshot(db_session, snapshot)
    client_id, internal_id = _with_members(db_session, project, "m102")

    snapshot["milestones"][0]["status"] = "done"
    biahflow.sync_snapshot(db_session, snapshot)

    emitted = _notifications(db_session, project.id)
    assert [item.kind for item in emitted] == [NotificationKind.milestone_done]
    assert emitted[0].detail == "Validação"
    # Andamento é assunto do cliente: o time interno acabou de digitar isso no
    # Biahflow e não precisa do próprio eco.
    assert emitted[0].user_id == client_id
    assert internal_id not in {item.user_id for item in emitted}


def test_the_same_webhook_replayed_does_not_duplicate(db_session: Session) -> None:
    """A garantia central: o snapshot é reconciliação completa, não delta."""
    snapshot = _snapshot(biahflow_project_id=103, client_id=53)
    project = biahflow.sync_snapshot(db_session, snapshot)
    _with_members(db_session, project, "m103")

    snapshot["milestones"][0]["status"] = "done"
    biahflow.sync_snapshot(db_session, snapshot)
    first = _notifications(db_session, project.id)

    biahflow.sync_snapshot(db_session, snapshot)
    biahflow.sync_snapshot(db_session, snapshot)

    assert len(first) == 1
    assert [item.id for item in _notifications(db_session, project.id)] == [first[0].id]


def test_a_new_pending_reaches_the_client_and_the_internal_team(db_session: Session) -> None:
    snapshot = _snapshot(biahflow_project_id=104, client_id=54)
    project = biahflow.sync_snapshot(db_session, snapshot)
    client_id, internal_id = _with_members(db_session, project, "m104")

    snapshot["pendencias"].append(
        {"id": 72, "title": "Definir alçada", "status": "open", "party": "provider",
         "created_at": "2026-08-03T10:00:00+00:00", "resolved_at": None}
    )
    biahflow.sync_snapshot(db_session, snapshot)

    emitted = _notifications(db_session, project.id)
    assert {item.kind for item in emitted} == {NotificationKind.pending_opened}
    assert {item.user_id for item in emitted} == {client_id, internal_id}


def test_documents_meetings_transcripts_and_phases_each_notify(db_session: Session) -> None:
    snapshot = _snapshot(biahflow_project_id=105, client_id=55)
    project = biahflow.sync_snapshot(db_session, snapshot)
    _with_members(db_session, project, "m105")

    snapshot["documents"].append(
        {"id": 42, "name": "Mapa de integrações", "type": "", "author": "Rafael",
         "link": "", "created_at": "2026-08-03T09:30:00+00:00"}
    )
    snapshot["meetings"][0]["has_transcript"] = True
    snapshot["meetings"].append(
        {"id": 6, "title": "Comitê", "date": "2026-08-20", "recording_url": "",
         "has_transcript": False, "status": "scheduled"}
    )
    snapshot["journey"]["phases"][1]["status"] = "active"
    snapshot["journey"]["phases"][0]["deliverables"][0]["status"] = "delivered"
    biahflow.sync_snapshot(db_session, snapshot)

    kinds = {item.kind for item in _notifications(db_session, project.id)}
    assert kinds == {
        NotificationKind.document_added,
        NotificationKind.transcript_ready,
        NotificationKind.meeting_scheduled,
        NotificationKind.phase_advanced,
        NotificationKind.deliverable_delivered,
    }


def test_a_resolved_pending_notifies_and_a_status_change_too(db_session: Session) -> None:
    snapshot = _snapshot(biahflow_project_id=106, client_id=56)
    project = biahflow.sync_snapshot(db_session, snapshot)
    _with_members(db_session, project, "m106")

    snapshot["pendencias"][0]["status"] = "resolved"
    snapshot["pendencias"][0]["resolved_at"] = "2026-08-04T10:00:00+00:00"
    snapshot["project"]["status"] = "completed"
    biahflow.sync_snapshot(db_session, snapshot)

    kinds = {item.kind for item in _notifications(db_session, project.id)}
    assert kinds == {
        NotificationKind.pending_resolved,
        NotificationKind.project_status_changed,
    }


def test_a_member_of_another_project_receives_nothing(db_session: Session) -> None:
    """Fan-out segue a membership: quem não está no projeto não é destinatário."""
    snapshot = _snapshot(biahflow_project_id=107, client_id=57)
    project = biahflow.sync_snapshot(db_session, snapshot)
    _with_members(db_session, project, "m107")

    other = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=108, client_id=58)
    )
    outsider, _ = _with_members(db_session, other, "m108")

    snapshot["milestones"][0]["status"] = "done"
    biahflow.sync_snapshot(db_session, snapshot)

    assert outsider not in {item.user_id for item in _notifications(db_session, project.id)}


def test_every_notification_kind_declares_its_audience() -> None:
    """O `.get(kind, _CLIENT_ONLY)` de `recipients` faz o esquecimento **enviar ao cliente**.

    Três linhas contra o defeito mais caro que a ADR 0040 podia introduzir: o aviso de
    cliente travado é o primeiro cuja audiência é só o time, e sem a entrada no `AUDIENCE`
    ele contaria ao próprio cliente que ele está sendo medido — que é o que a FDD 020 proíbe
    na seção de jornada.

    A guarda é sobre **completude** e não sobre o valor de cada linha: quem escrever a
    próxima espécie escolhe a audiência, e o que não pode é escolher por omissão.
    """
    faltando = [
        kind.value for kind in NotificationKind if kind not in notifications.AUDIENCE
    ]

    assert faltando == []


def test_dedupe_key_survives_a_title_longer_than_the_column() -> None:
    """Marco vai a 200 caracteres e a coluna a 255: a chave não pode estourar."""
    key = notifications._key("milestone", "x" * 300, "done")
    assert len(key) <= 255
    assert key.startswith("milestone:")
    assert key == notifications._key("milestone", "x" * 300, "done")  # determinística


@pytest.mark.integration
def test_a_comment_notifies_the_other_side_and_not_its_author(db_session: Session) -> None:
    """Avisar alguém do que ele mesmo escreveu é o ruído que ensina a ignorar o sino.

    `fan_out` derivava destinatários só de `AUDIENCE`, que é do **tipo** do aviso;
    `exclude_user_id` é deste **evento** (ADR 0032), e é por isso que ele fica no
    `fan_out` e não em `recipients` — juntá-los faria o `AUDIENCE` deixar de ser
    uma tabela legível.
    """
    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=131, client_id=81)
    )
    client_id, internal_id = _with_members(db_session, project, "m131")

    created = notifications.fan_out(
        db_session,
        project,
        [
            notifications.Change(
                kind=notifications.NotificationKind.pending_commented,
                title="Cliente comentou numa pendência",
                detail="Enviar a planilha",
                dedupe_key=f"comment:{uuid.uuid4()}",
            )
        ],
        exclude_user_id=client_id,
    )

    recipients = set(
        db_session.execute(
            select(Notification.user_id).where(Notification.id.in_(created))
        ).scalars()
    )
    assert recipients == {internal_id}


def test_the_diff_names_the_row_of_every_change() -> None:
    """Toda ramificação do ``diff`` diz **qual linha** mudou (ADR 0056).

    Unitário sobre os dois estados, e não sobre o sync: o que se prova aqui é que
    nenhuma das dez ramificações esqueceu o ``item=``, e é o valor que importa —
    uma âncora com o rótulo errado leva o cliente a uma linha que não é a do aviso,
    e é indistinguível de uma certa até alguém abrir a tela.

    O ``project_status_changed`` aparece duas vezes com ``None``: status e saúde são
    fatos do projeto inteiro, e é a única espécie de cliente legitimamente sem
    âncora (``notifications.ANCHORLESS``).
    """
    before = notifications.ProjectState(
        status="active",
        health_label="No prazo",
        milestones={"Validação de integrações": MilestoneState.in_progress},
        phases={"Welcome": PhaseState.active, "Prove": PhaseState.locked},
        deliverables={("Welcome", "Acesso ao portal"): DeliverableState.pending},
        documents={},
        meetings={"Kickoff": False},
        pendings={"71": ("Aprovar fluxo", PendingState.open)},
    )
    after = notifications.ProjectState(
        status="completed",
        health_label="Em atenção",
        milestones={"Validação de integrações": MilestoneState.done},
        phases={"Welcome": PhaseState.active, "Prove": PhaseState.active},
        deliverables={("Welcome", "Acesso ao portal"): DeliverableState.delivered},
        documents={"41": "Plano de implantação.pdf"},
        meetings={"Kickoff": True, "Comitê": False},
        pendings={
            "71": ("Aprovar fluxo", PendingState.resolved),
            "72": ("Enviar lista de usuários", PendingState.open),
        },
    )

    assert {(change.kind, change.item) for change in notifications.diff(before, after)} == {
        (NotificationKind.project_status_changed, None),
        (NotificationKind.phase_advanced, "Prove"),
        (NotificationKind.milestone_done, "Validação de integrações"),
        # O nome do entregável e **não** "Acesso ao portal (Welcome)": a fase sai da
        # âncora quando a jornada escolhe qual delas abrir.
        (NotificationKind.deliverable_delivered, "Acesso ao portal"),
        # O título, e não o `external_id` que compõe a chave de dedupe — aquele não
        # aparece em lugar nenhum da tela.
        (NotificationKind.document_added, "Plano de implantação.pdf"),
        (NotificationKind.meeting_scheduled, "Comitê"),
        (NotificationKind.transcript_ready, "Kickoff"),
        (NotificationKind.pending_opened, "Enviar lista de usuários"),
        (NotificationKind.pending_resolved, "Aprovar fluxo"),
    }


def test_the_link_of_a_milestone_points_at_the_milestone() -> None:
    """A URL literal, encoding incluído — é o que pega um ``quote`` esquecido."""
    project_id = uuid.UUID("11111111-2222-4333-8444-555555555555")

    assert notifications.deep_link(
        project_id, NotificationKind.milestone_done, "Validação de integrações"
    ) == (
        "/?project=11111111-2222-4333-8444-555555555555&tab=Cronograma"
        "&item=milestone%3AValida%C3%A7%C3%A3o%20de%20integra%C3%A7%C3%B5es"
    )


def test_a_title_with_ampersand_survives_the_link() -> None:
    """O rótulo é texto do cliente, e ``&`` em título de documento é comum.

    Sem ``safe=""`` no ``quote`` o ``&`` viraria separador de parâmetro: a tela
    receberia um ``item`` truncado e um parâmetro extra, e a âncora deixaria de
    casar sem nada ficar vermelho. Vale igual para ``#``, ``?`` e ``+``.
    """
    project_id = uuid.UUID("11111111-2222-4333-8444-555555555555")

    link = notifications.deep_link(
        project_id, NotificationKind.document_added, "Contrato P&D + anexo?"
    )

    assert link is not None
    assert link.endswith("&item=document%3AContrato%20P%26D%20%2B%20anexo%3F")
    # Um parâmetro a mais seria exatamente o sintoma do escape faltando.
    assert link.count("&") == 2


def _system_session(monkeypatch: pytest.MonkeyPatch, session: Session) -> None:
    """Faz as tasks do worker rodarem sobre a sessão do teste.

    As duas tasks abrem a **própria** sessão de sistema, e a fixture desta suíte é
    revertida no fim: sem este desvio a task não enxergaria a linha que o teste
    acabou de escrever. O que continua sendo exercitado é o corpo real da task —
    inclusive a construção do ``Change`` e o ``fan_out`` —, que é onde mora o
    ``item=`` desta fatia; e o papel é o mesmo (``portal_system``), então nem a
    credencial muda.
    """
    monkeypatch.setattr(worker, "get_session", lambda **_: nullcontext(session))


def test_the_ai_pending_notice_carries_the_anchor(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pendência que a IA abriu é uma linha da aba, e o link cai nela.

    Origem de ``Change`` que o ``diff`` não cobre: são quatro, e uma guarda dirigida
    pela fixture do sync só veria uma. Foi o mesmo ponto cego que deixou dez
    ramificações sem ``link`` até a ADR 0043.
    """
    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=141, client_id=91)
    )
    _with_members(db_session, project, "m141")
    pending = db_session.execute(
        select(PendingItem).where(PendingItem.project_id == project.id)
    ).scalars().one()

    _system_session(monkeypatch, db_session)
    worker.notify_pending_created(str(project.id), str(pending.id))

    links = {item.link for item in _notifications(db_session, project.id)}
    assert links == {
        f"/?project={project.id}&tab=Pend%C3%AAncias&item=pending%3AAprovar%20fluxo"
    }


def test_the_comment_notice_carries_the_anchor_of_its_pending(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E o comentário aponta para a pendência comentada, não para a aba."""
    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=142, client_id=92)
    )
    client_id, _ = _with_members(db_session, project, "m142")
    pending = db_session.execute(
        select(PendingItem).where(PendingItem.project_id == project.id)
    ).scalars().one()
    comment = PendingItemComment(
        organization_id=project.organization_id,
        project_id=project.id,
        pending_item_id=pending.id,
        author_user_id=client_id,
        author_label="Cliente",
        body="Segue a planilha.",
    )
    db_session.add(comment)
    db_session.flush()

    _system_session(monkeypatch, db_session)
    worker.notify_pending_comment(str(project.id), str(comment.id))

    links = {item.link for item in _notifications(db_session, project.id)}
    assert links == {
        f"/?project={project.id}&tab=Pend%C3%AAncias&item=pending%3AAprovar%20fluxo"
    }


def test_the_comment_notice_falls_back_to_the_tab_when_the_pending_is_gone(
    db_session: Session
) -> None:
    """Sem rótulo, o link do comentário é o da aba — a degradação de sempre.

    O ramo é o ``item.title if item is not None else None`` da task: entre o
    comentário e a passagem dela, o sync pode ter apagado e recriado a pendência.

    **Provado pelo ``fan_out`` e não pela task**, e a razão é medida: o FK do
    comentário é ``ON DELETE CASCADE``, então uma pendência que some leva o
    comentário junto e a task para antes, no ``comment is None``. Encenar o
    contrário no banco exigiria desligar a integridade referencial para provar uma
    linha — e é justamente essa a saída que ``AGENTS.md`` não deixa tomar.
    """
    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=143, client_id=93)
    )
    _with_members(db_session, project, "m143")

    notifications.fan_out(
        db_session,
        project,
        [
            notifications.Change(
                kind=NotificationKind.pending_commented,
                title="Cliente comentou numa pendência",
                dedupe_key=f"comment:{uuid.uuid4()}",
                item=None,
            )
        ],
    )

    links = {item.link for item in _notifications(db_session, project.id)}
    assert links == {f"/?project={project.id}&tab=Pend%C3%AAncias"}


# --- o aceite do entregável (Fase 7, FDD 027, ADR 0077) ----------------------


def _acceptance(session: Session, project, *, actor_id, action) -> uuid.UUID:
    from portal_api.models import DeliverableAcceptance

    decision = DeliverableAcceptance(
        organization_id=project.organization_id,
        project_id=project.id,
        deliverable_external_ref="91",
        phase_name="Prove",
        deliverable_name="Funcionário Digital",
        action=action,
        actor_user_id=actor_id,
        actor_label="Cliente",
        actor_is_internal=False,
        comment="Pode seguir.",
    )
    session.add(decision)
    session.flush()
    return decision.id


def test_o_aviso_de_aceite_vai_para_o_time_e_nao_para_o_cliente(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A audiência é ``_INTERNAL_ONLY``, e é o risco central desta fatia.

    O ``.get(kind, _CLIENT_ONLY)`` de :func:`notifications.recipients` tem o
    cliente como padrão: esquecer a linha em ``AUDIENCE`` mandaria ao cliente o
    aviso da **própria** decisão. O terceiro aviso só do time, depois do funil e
    da resposta pelo canal.
    """
    from portal_api.models import DeliverableAcceptanceAction

    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=171, client_id=121)
    )
    client_id, internal_id = _with_members(db_session, project, "m171")
    decision_id = _acceptance(
        db_session,
        project,
        actor_id=client_id,
        action=DeliverableAcceptanceAction.accepted,
    )

    _system_session(monkeypatch, db_session)
    worker.notify_deliverable_acceptance(str(project.id), str(decision_id))

    emitted = _notifications(db_session, project.id)
    assert [item.kind for item in emitted] == [NotificationKind.deliverable_reviewed]
    assert {item.user_id for item in emitted} == {internal_id}
    assert client_id not in {item.user_id for item in emitted}
    assert emitted[0].title == "Cliente aprovou um entregável"
    assert emitted[0].detail == "Funcionário Digital (Prove)"
    # Interno não abre aba de cliente: sem entrada no `LINK_TAB`, `deep_link`
    # devolve `None` antes de olhar a âncora (ADR 0056).
    assert emitted[0].link is None


def test_o_aviso_de_aceite_nao_avisa_quem_decidiu(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quando é alguém do time que registra a decisão, ele não recebe o eco.

    É o único caso em que ``exclude_user_id`` morde numa audiência interna — e é
    exatamente o caso que existe, porque o time interno alcança a tela do cliente
    pelo vínculo org-wide que já tem.
    """
    from portal_api.models import DeliverableAcceptanceAction

    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=172, client_id=122)
    )
    _, internal_id = _with_members(db_session, project, "m172")
    decision_id = _acceptance(
        db_session,
        project,
        actor_id=internal_id,
        action=DeliverableAcceptanceAction.changes_requested,
    )

    _system_session(monkeypatch, db_session)
    worker.notify_deliverable_acceptance(str(project.id), str(decision_id))

    assert _notifications(db_session, project.id) == []


def test_pedir_ajuste_depois_de_aprovar_avisa_de_novo(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O ``dedupe_key`` é ``(external_ref, action)``, e o preço está declarado.

    Repetir a **mesma** decisão não avisa duas vezes — a segunda aprovação não é
    informação nova para quem lê a fila, e a decisão em si nunca se perde porque
    ela está gravada em ``deliverable_acceptance``. Mudar de decisão avisa, que é
    o caso em que algo mudou.
    """
    from portal_api.models import DeliverableAcceptanceAction

    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=173, client_id=123)
    )
    client_id, internal_id = _with_members(db_session, project, "m173")

    _system_session(monkeypatch, db_session)
    for action in (
        DeliverableAcceptanceAction.accepted,
        DeliverableAcceptanceAction.accepted,
        DeliverableAcceptanceAction.changes_requested,
    ):
        decision_id = _acceptance(
            db_session, project, actor_id=client_id, action=action
        )
        worker.notify_deliverable_acceptance(str(project.id), str(decision_id))

    titles = [item.title for item in _notifications(db_session, project.id)]
    assert sorted(titles) == [
        "Cliente aprovou um entregável",
        "Cliente pediu ajuste num entregável",
    ]
    assert {item.user_id for item in _notifications(db_session, project.id)} == {
        internal_id
    }


def test_toda_especie_de_aviso_declara_a_audiencia() -> None:
    """Nenhuma espécie cai no padrão do ``.get``, que é o cliente.

    A guarda de completude que a ADR 0040 abriu, cobrada de todo o enum: uma
    espécie nova sem linha em ``AUDIENCE`` não fica sem destinatário — ela vai
    para o **cliente**, em silêncio. Foi por isso que o funil precisou dela, e é
    por isso que o aceite precisa dela agora.
    """
    faltando = sorted(
        kind.value for kind in NotificationKind if kind not in notifications.AUDIENCE
    )
    assert faltando == [], (
        "estas espécies não declaram audiência e cairiam no padrão `_CLIENT_ONLY`: "
        + ", ".join(faltando)
        + ". Acrescente a linha em `notifications.AUDIENCE` — o padrão do `.get`"
        " manda o aviso ao cliente."
    )
