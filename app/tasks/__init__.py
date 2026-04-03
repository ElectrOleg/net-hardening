"""HCS Celery Tasks."""
from app.extensions import celery  # noqa: F401 — required for `celery -A app.tasks`
from app.tasks.scan_tasks import run_scan  # noqa: F401
from app.tasks import sync_tasks  # noqa: F401
from app.tasks import maintenance_tasks  # noqa: F401

__all__ = ["celery", "run_scan"]

