"""HCS Celery Tasks."""
from app.tasks.scan_tasks import run_scan

__all__ = ["run_scan"]
