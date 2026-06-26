"""HCS Flask Application Factory."""

from flask import Flask

from app.config import FlaskConfig
from app.extensions import db, init_celery, init_csrf, migrate


def create_app(config_class=FlaskConfig):
    """Create and configure the Flask application."""
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.from_object(config_class)

    # Configure ProxyFix for Nginx/Reverse Proxy
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    init_celery(app)
    init_csrf(app)

    # Register API blueprint
    from app.api import api_bp, metrics_bp

    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(metrics_bp)  # /metrics at root level

    # Register Web blueprint
    from app.views import web_bp

    app.register_blueprint(web_bp)

    # Health check endpoint
    @app.route("/health")
    def health():
        return {"status": "ok"}

    # Global Authentication & RBAC Boundary Enforcement
    @app.before_request
    def enforce_auth():
        from flask import flash, g, jsonify, redirect, request, url_for

        from app.auth import _get_current_user
        from app.config import settings

        # 1. Dev/test kill switch
        if not getattr(settings, "AUTH_ENABLED", False):
            g.current_user = {"username": "anonymous", "role": "admin"}
            return

        # 2. Whitelist of public endpoints / paths
        endpoint = request.endpoint or ""
        path = request.path or ""

        if (
            endpoint in ("web.login_page", "web.login_submit", "web.logout", "api.api_login")
            or endpoint == "static"
            or path.startswith("/static/")
            or path == "/health"
        ):
            return

        # 3. Whitelist metrics if METRICS_TOKEN matches
        if path == "/metrics":
            expected_token = getattr(settings, "METRICS_TOKEN", "")
            if not expected_token:
                return  # Public if not configured

            # Check Bearer token or query parameter
            auth_header = request.headers.get("Authorization", "")
            token = ""
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
            else:
                token = request.args.get("token", "")

            if token != expected_token:
                return jsonify({"error": "Unauthorized metrics access"}), 401
            return

        # 4. Resolve current user
        user = _get_current_user()
        if not user:
            # API requests get JSON 401; browser requests → redirect
            if path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("web.login_page", next=request.path))

        g.current_user = user.to_dict()
        user_role = g.current_user.get("role", "viewer")

        # 5. Enforce RBAC
        # Admin-only Web views
        is_admin_web = endpoint == "web.admin" or endpoint.startswith("web.settings")
        if is_admin_web and user_role != "admin":
            flash("У вас нет прав для доступа к этому разделу.", "error")
            return redirect(url_for("web.dashboard"))

        # Operator/Admin Web views (rule creation/editing)
        is_operator_web = endpoint in ("web.rule_builder", "web.rule_edit")
        if is_operator_web and user_role not in ("operator", "admin"):
            flash("У вас нет прав для изменения правил.", "error")
            return redirect(url_for("web.dashboard"))

        # Admin-only APIs/Blueprints
        is_admin_api = (
            endpoint.startswith("api.admin_")
            or endpoint
            in (
                "api.get_system_settings",
                "api.update_system_settings",
                "api.list_scan_schedules",
                "api.create_scan_schedule",
                "api.update_scan_schedule",
                "api.delete_scan_schedule",
                "api.list_sync_logs",
                "api.list_users",
                "api.create_user",
                "api.update_user",
                "api.delete_user",
                "api.get_ldap_settings",
                "api.update_ldap_settings",
                "api.test_ldap",
            )
            or "data_sources" in endpoint
            or "inventory_sources" in endpoint
            or "vendors" in endpoint
        )
        if is_admin_api and user_role != "admin":
            return jsonify({"error": "Insufficient permissions (admin required)"}), 403

        # Operator-only modifying APIs (POST/PUT/DELETE/PATCH)
        if path.startswith("/api/") and request.method in ("POST", "PUT", "DELETE", "PATCH"):
            if endpoint not in ("api.api_logout", "api.api_me"):
                if user_role not in ("operator", "admin"):
                    return jsonify(
                        {"error": "Insufficient permissions (operator/admin required)"}
                    ), 403

    # Register commands
    from app.commands import seed_admin_command, seed_command

    app.cli.add_command(seed_command)
    app.cli.add_command(seed_admin_command)

    # Ensure all tables exist in development (safe: only creates missing ones).
    # In production, use Flask-Migrate: flask db upgrade
    with app.app_context():
        from app import models as _models  # noqa: F401 — ensure all models are imported

        if app.debug:
            try:
                db.create_all()
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "db.create_all() skipped — database not reachable"
                )

    return app
