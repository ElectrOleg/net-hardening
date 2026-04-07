"""HCS Celery Tasks."""
from app import create_app
from app.extensions import celery  # noqa: F401 — required for `celery -A app.tasks`

# Create Flask app so that init_celery() is called,
# which sets up ContextTask (app_context wrapping) and config.
# Without this, Celery workers get "Working outside of application context".
_flask_app = create_app()

from app.tasks.scan_tasks import run_scan  # noqa: F401, E402
from app.tasks import sync_tasks  # noqa: F401, E402
from app.tasks import maintenance_tasks  # noqa: F401, E402

__all__ = ["celery", "run_scan"]
