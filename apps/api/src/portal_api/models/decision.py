"""Decision domain — decisions recorded per project.

A decision may be extracted from a meeting (``meeting_id``); the link is
optional so decisions can also be logged directly. Uses ``SET NULL`` so
removing a meeting keeps the decision but drops the provenance link.

``project_phase_id`` says **which phase this decision unlocked**, and it has the
same shape and the same reason: nullable, ``SET NULL``, resolved on ingestion
against the phase ids of the very envelope that recreated both tables.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TimestampMixin
from portal_api.models.project import _ProjectChildMixin


class Decision(Base, _ProjectChildMixin, TimestampMixin):
    __tablename__ = "decision"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("meeting.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: A fase que esta decisão destravou (ADR 0088), espelhando ``meeting_id``
    #: linha a linha — e pela mesma razão, que aqui vale duas vezes.
    #:
    #: **Nullable, e a nulidade é significativa.** O Pulse carimba ``phase_ref``
    #: em toda decisão publicada desde a ADR 0057 de lá, e manda ``null`` no
    #: legado: "a lacuna é declarada em vez de mascarada por heurística". Deste
    #: lado a leitura é a mesma — ausência é ausência de afirmação, nunca uma
    #: fase adivinhada por ``decided_on`` × janela da fase. Essa inferência foi
    #: **recusada em dois gates humanos independentes** (o nosso em 27/08/2026,
    #: o deles na ADR 0057), e não é fallback: é a falsa precisão que
    #: ``results.py`` recusa por princípio.
    #:
    #: ``SET NULL`` porque a fase é apagada e recriada a cada webhook e porque,
    #: no dia em que a origem remover a fase, o fato da decisão sobrevive e
    #: **volta a declarar a lacuna** — que é o que o outro lado decidiu fazer
    #: com o mesmo FK.
    project_phase_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project_phase.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
