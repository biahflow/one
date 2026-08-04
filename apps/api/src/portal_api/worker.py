from celery import Celery

from portal_api.config import get_settings
from portal_api.db.session import DbRole, get_session
from portal_api.integrations import biahflow

settings = get_settings()
celery_app = Celery("portal_api", broker=settings.redis_url, backend=settings.redis_url)


@celery_app.task(name="portal_api.reindex_project")
def reindex_project(organization_id: str, project_id: str) -> dict[str, str]:
    """Idempotent placeholder for Drive/document ingestion with explicit tenant scope."""
    return {"organization_id": organization_id, "project_id": project_id, "status": "queued"}


@celery_app.task(name="portal_api.sync_biahflow_project")
def sync_biahflow_project(biahflow_project_id: int) -> dict[str, str]:
    """Backfill/reconciliation: pull a project snapshot from Biahflow into the read model (ADR 0006)."""
    current = get_settings()
    snapshot = biahflow.fetch_snapshot(
        current.biahflow_base_url, current.biahflow_read_token, biahflow_project_id
    )
    # The sync *creates* the tenant, so it runs under portal_system (BYPASSRLS):
    # there is no organization/project context to bind yet (ADR 0010).
    with get_session(role=DbRole.system) as session:
        project = biahflow.sync_snapshot(session, snapshot)
        return {"project_id": str(project.id), "status": "synced"}
