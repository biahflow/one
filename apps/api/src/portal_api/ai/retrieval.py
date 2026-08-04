"""Evidence retrieval from the project read model, strictly tenant-scoped.

Per docs/ai/context-contract.md the retriever receives the tenant/project context and only
returns evidence matching it. The scoped repositories enforce that filter, so a caller can
never retrieve another project's rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from portal_api.models import (
    MilestoneState,
    PendingState,
    Project,
    ProjectStatus,
)
from portal_api.repositories import (
    MilestoneRepository,
    PendingItemRepository,
    TenantContext,
)

PROJECT_STATUS_LABELS: dict[ProjectStatus, str] = {
    ProjectStatus.discovery: "em descoberta",
    ProjectStatus.in_implementation: "em implementação",
    ProjectStatus.live: "em produção",
    ProjectStatus.paused: "pausado",
}
MILESTONE_STATE_LABELS: dict[MilestoneState, str] = {
    MilestoneState.planned: "planejado",
    MilestoneState.in_progress: "em andamento",
    MilestoneState.next: "próxima entrega",
    MilestoneState.done: "concluído",
}
_MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _short_date(value: date | None) -> str:
    return f"{value.day:02d} {_MONTHS[value.month - 1]}" if value else ""


@dataclass(frozen=True)
class Evidence:
    """A single citable fact from the read model."""

    id: str
    source: str
    location: str
    text: str

    @property
    def citation(self) -> str:
        return f"{self.source} — {self.location}" if self.location else self.source


def collect_evidence(session: Session, ctx: TenantContext, project: Project) -> list[Evidence]:
    """Gather the project's citable facts (project, milestones, open pendings) for ``ctx``."""
    status_label = PROJECT_STATUS_LABELS.get(project.status, project.status.value)
    evidence: list[Evidence] = [
        Evidence(
            id="project",
            source="Status do projeto",
            location=f"{project.completion_percent}% concluído",
            text=(
                f"O projeto '{project.name}' está {status_label} e "
                f"{project.completion_percent}% concluído."
            ),
        )
    ]

    milestones = sorted(
        MilestoneRepository(session, ctx).list(), key=lambda item: item.position
    )
    for milestone in milestones:
        state_label = MILESTONE_STATE_LABELS.get(milestone.state, milestone.state.value)
        due = _short_date(milestone.due_date)
        text = f"O marco '{milestone.title}' está {state_label}"
        text += f", previsto para {due}." if due else "."
        evidence.append(
            Evidence(
                id=f"milestone-{milestone.id}",
                source=f"Marco: {milestone.title}",
                location=due,
                text=text,
            )
        )

    for pending in PendingItemRepository(session, ctx).list():
        if pending.state == PendingState.resolved:
            continue
        owner = f" (responsável: {pending.owner_label})" if pending.owner_label else ""
        evidence.append(
            Evidence(
                id=f"pending-{pending.id}",
                source=f"Pendência: {pending.title}",
                location="",
                text=f"Há uma pendência aberta: '{pending.title}'{owner}.",
            )
        )

    return evidence
