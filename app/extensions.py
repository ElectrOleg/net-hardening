"""Flask extensions initialization."""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from celery import Celery

db = SQLAlchemy()
migrate = Migrate()
celery = Celery()


def init_celery(app):
    """Initialize Celery with Flask app context."""
    celery.conf.update(app.config.get("CELERY", {}))
    
    # Celery Beat schedule for periodic tasks
    celery.conf.beat_schedule = {
        "auto-sync-inventory": {
            "task": "hcs.sync_all_inventory",
            "schedule": 300.0,  # Check every 5 minutes
        },
        "cleanup-old-data": {
            "task": "hcs.cleanup_old_data",
            "schedule": 86400.0,  # Daily (24h)
        },
        "auto-run-scheduled-scans": {
            "task": "hcs.auto_run_scheduled_scans",
            "schedule": 60.0,  # Check every 60 seconds
        },
    }
    celery.conf.timezone = "UTC"
    
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
    
    celery.Task = ContextTask
    return celery


def init_csrf(app):
    """
    CSRF protection via double-submit cookie pattern.
    
    - Sets a `csrf_token` cookie on every response.
    - Mutating requests (POST/PUT/DELETE) to /api/* must include
      X-CSRF-Token header matching the cookie value.
    - Safe methods (GET/HEAD/OPTIONS) are always allowed.
    """
    import secrets
    from flask import request, jsonify

    SAFE_METHODS = frozenset(["GET", "HEAD", "OPTIONS"])

    @app.before_request
    def ensure_csrf_cookie():
        """If no csrf_token cookie exists, generate and inject one.
        
        This ensures the cookie is available for the first request.
        The cookie will be set on the response via after_request.
        """
        if "csrf_token" not in request.cookies:
            # Store token in g so after_request can set the cookie
            from flask import g
            g._new_csrf_token = secrets.token_hex(32)

    @app.after_request
    def set_csrf_cookie(response):
        from flask import g
        new_token = getattr(g, '_new_csrf_token', None)
        if new_token:
            response.set_cookie(
                "csrf_token",
                new_token,
                httponly=False,  # JS needs to read it
                samesite="Strict",
                secure=request.is_secure,
                max_age=86400,
            )
        return response

    @app.before_request
    def check_csrf_token():
        if request.method in SAFE_METHODS:
            return None

        # Only enforce on API endpoints
        if not request.path.startswith("/api/"):
            return None

        # Skip health check
        if request.path == "/health":
            return None

        # If the cookie was just generated in this request,
        # this is the first visit — skip enforcement
        from flask import g
        if getattr(g, '_new_csrf_token', None):
            return None

        cookie_token = request.cookies.get("csrf_token")
        header_token = request.headers.get("X-CSRF-Token")

        if not cookie_token or not header_token:
            return jsonify({"error": "CSRF token missing"}), 403

        if not secrets.compare_digest(cookie_token, header_token):
            return jsonify({"error": "CSRF token mismatch"}), 403

        return None

