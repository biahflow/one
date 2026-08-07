"""O teto de frequência de contato, por pessoa (FDD 021, FDD 022, ADR 0042).

A poda e o apagamento ficam em ``test_retention.py``, e a ausência de acesso pelo
papel de requisição em ``test_rls_isolation.py`` — cada um ao lado dos outros da
mesma forma, que é a organização que estes arquivos já tinham.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from conftest import captured
from portal_api import contact_budget, retention
from portal_api.config import Settings
from portal_api.models import ContactEvent, ContactKind, Organization, User

pytestmark = pytest.mark.integration


@pytest.fixture
def world(migrated_engine: Engine) -> Iterator[dict[str, uuid.UUID]]:
    """Uma organização e **duas** pessoas.

    Duas porque a afirmação central do módulo é que o orçamento é de uma pessoa: com
    uma só, um teto compartilhado por engano entre todo mundo passaria verde.
    """
    tag = uuid.uuid4().hex[:8]
    ids: dict[str, uuid.UUID] = {}
    with Session(migrated_engine) as session:
        organization = Organization(name="Contato Ltda", slug=f"contato-{tag}")
        session.add(organization)
        session.flush()
        ids["org"] = organization.id
        for label in ("ana", "bruno"):
            person = User(
                email=f"{label}-{tag}@exemplo.test",
                full_name=label.title(),
                external_subject=f"sub-contato-{label}-{tag}",
            )
            session.add(person)
            session.flush()
            ids[label] = person.id
        session.commit()
    yield ids
    with Session(migrated_engine) as session:
        session.execute(
            delete(ContactEvent).where(ContactEvent.organization_id == ids["org"])
        )
        session.execute(
            delete(User).where(User.id.in_([ids["ana"], ids["bruno"]]))
        )
        session.execute(delete(Organization).where(Organization.id == ids["org"]))
        session.commit()


def _claim(
    session: Session,
    ids: dict[str, uuid.UUID],
    who: str,
    key: str,
    settings: Settings,
) -> bool:
    return contact_budget.claim(
        session,
        user_id=ids[who],
        organization_id=ids["org"],
        kind=ContactKind.whatsapp_notice,
        dedupe_key=key,
        settings=settings,
    )


def _spent(session: Session, user_id: uuid.UUID) -> int:
    return int(
        session.execute(
            select(func.count(ContactEvent.id)).where(ContactEvent.user_id == user_id)
        ).scalar_one()
    )


def test_the_contact_within_the_cap_goes_out_and_leaves_a_row(
    migrated_engine: Engine, world: dict[str, uuid.UUID]
) -> None:
    settings = Settings()
    with Session(migrated_engine) as session:
        assert _claim(session, world, "ana", "aviso:1", settings) is True
        session.commit()

    with Session(migrated_engine) as session:
        assert _spent(session, world["ana"]) == 1


def test_the_contact_past_the_cap_is_suppressed(
    migrated_engine: Engine, world: dict[str, uuid.UUID]
) -> None:
    """E o evento sai **sem** a pessoa.

    Comportamento de pessoa identificada é dado sensível e o log não é o lugar dele —
    a mesma regra que ``onboarding.stamp`` segue ao registrar só o tenant e o nome do
    degrau. A asserção olha o ``extra`` inteiro justamente para pegar um ``user_id``
    acrescentado por conveniência num conserto futuro.
    """
    settings = Settings(contact_cap_per_window=2)
    with Session(migrated_engine) as session:
        assert _claim(session, world, "ana", "aviso:1", settings) is True
        assert _claim(session, world, "ana", "aviso:2", settings) is True
        with captured("portal_api.contact_budget") as records:
            assert _claim(session, world, "ana", "aviso:3", settings) is False
        session.commit()

    assert [r.msg for r in records] == ["contact.suppressed"]
    assert records[0].kind == ContactKind.whatsapp_notice.value
    assert records[0].reason == "window_cap"
    assert records[0].cap == 2
    assert not hasattr(records[0], "user_id")

    with Session(migrated_engine) as session:
        assert _spent(session, world["ana"]) == 2


def test_a_redelivery_of_the_same_contact_does_not_spend_a_second_unit(
    migrated_engine: Engine, world: dict[str, uuid.UUID]
) -> None:
    """O caso que salva o aviso quando o provedor cai.

    A task de envio retenta sobre ``whatsapp_sent_at IS NULL``, então o **mesmo**
    aviso volta a pedir orçamento. Sem a chave, ele encontraria a cota gasta por ele
    mesmo e sumiria do canal para sempre — uma falha temporária do fornecedor virando
    silêncio permanente.
    """
    settings = Settings(contact_cap_per_window=1)
    with Session(migrated_engine) as session:
        assert _claim(session, world, "ana", "aviso:1", settings) is True
        assert _claim(session, world, "ana", "aviso:1", settings) is True
        assert _claim(session, world, "ana", "aviso:1", settings) is True
        session.commit()

    with Session(migrated_engine) as session:
        assert _spent(session, world["ana"]) == 1
        # E a cota continua valendo para um contato **diferente**: a reentrega passar
        # não pode ter virado "esta pessoa tem crédito infinito".
        assert _claim(session, world, "ana", "aviso:2", settings) is False


def test_a_contact_older_than_the_window_no_longer_counts(
    migrated_engine: Engine, world: dict[str, uuid.UUID]
) -> None:
    settings = Settings(contact_cap_per_window=1)
    with Session(migrated_engine) as session:
        session.add(
            ContactEvent(
                organization_id=world["org"],
                user_id=world["ana"],
                kind=ContactKind.whatsapp_notice,
                dedupe_key="aviso:antigo",
                created_at=retention.now()
                - timedelta(days=settings.contact_window_days + 1),
            )
        )
        session.commit()

    with Session(migrated_engine) as session:
        assert _claim(session, world, "ana", "aviso:novo", settings) is True
        session.commit()


def test_the_budget_is_one_persons_and_not_the_organizations(
    migrated_engine: Engine, world: dict[str, uuid.UUID]
) -> None:
    """Gastar o orçamento da Ana não pode calar o Bruno.

    É a afirmação que separa este teto de um limite por tenant — e o modo de falha
    seria silencioso na direção pior: quanto maior o cliente, menos cada pessoa dele
    receberia.
    """
    settings = Settings(contact_cap_per_window=1)
    with Session(migrated_engine) as session:
        assert _claim(session, world, "ana", "aviso:1", settings) is True
        assert _claim(session, world, "ana", "aviso:2", settings) is False
        assert _claim(session, world, "bruno", "aviso:3", settings) is True
        session.commit()
