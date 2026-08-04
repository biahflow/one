"""From a verified token to a ``user`` row (ADR 0010).

Three steps, in order, and each one is a policy branch on the ``user`` table —
this whole module runs under the unprivileged ``portal_app`` credential:

1. by ``external_subject``: the durable identity, and the common case;
2. by e-mail, but only on a row that has **no** subject yet — the meeting point
   between the realm and the versioned seed. Claiming it writes the ``sub``;
3. provisioning: first login of someone the seed never knew about.

Authentication is not authorization. A user provisioned here with no membership
authenticates fine and then sees 404 everywhere — which is the correct answer,
and the reason the invitation flow is separate work.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from portal_api.db.session import bind_user
from portal_api.models import User
from portal_api.principal import Principal

logger = logging.getLogger(__name__)


def _by_subject(session: Session, subject: str) -> User | None:
    return session.execute(
        select(User).where(User.external_subject == subject)
    ).scalar_one_or_none()


def _claim_seeded_row(session: Session, principal: Principal) -> User | None:
    """A row seeded with the e-mail but no subject yet — link it, once.

    ``lower(email)`` rather than a plain comparison because that is exactly what
    the RLS predicate uses; comparing differently here would find rows the policy
    then hides, or the reverse.
    """
    user = session.execute(
        select(User).where(
            func.lower(User.email) == principal.email,
            User.external_subject.is_(None),
        )
    ).scalar_one_or_none()
    if user is None:
        return None

    user.external_subject = principal.subject
    session.flush()
    # Not audit_log: that table requires an organization_id and at this point we
    # have not resolved one yet (ADR 0010).
    logger.info(
        "identity.linked", extra={"user_id": str(user.id), "subject": principal.subject}
    )
    return user


def _provision(session: Session, principal: Principal) -> User:
    user = User(
        email=principal.email,
        full_name=principal.full_name,
        external_subject=principal.subject,
        # Hint from the realm role, used only to mark staff. It cannot say *which
        # project* — that stays with membership.
        is_internal=principal.is_internal,
    )
    session.add(user)
    session.flush()
    logger.info(
        "identity.provisioned",
        extra={"user_id": str(user.id), "subject": principal.subject},
    )
    return user


def resolve_user(session: Session, principal: Principal) -> User:
    """The caller's ``user`` row, creating or linking it on first login.

    Side effect: publishes ``portal.user_id``, which is what unlocks
    ``membership`` — and through it ``organization`` and ``project`` — for the
    rest of the transaction. Without it every later read comes back empty.
    """
    user = _by_subject(session, principal.subject) or _claim_seeded_row(
        session, principal
    )
    if user is None:
        user = _provision(session, principal)

    bind_user(session, user.id)
    return user
