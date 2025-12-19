"""HCS Flask Application Factory."""
from flask import Flask

from app.config import FlaskConfig
from app.extensions import db, migrate, init_celery


def create_app(config_class=FlaskConfig):
    """Create and configure the Flask application."""
    app = Flask(__name__, static_folder='static', static_url_path='/static')
    app.config.from_object(config_class)
    
    # Configure ProxyFix for Nginx/Reverse Proxy
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
    )
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    init_celery(app)
    
    # Register API blueprint
    from app.api import api_bp
    app.register_blueprint(api_bp, url_prefix="/api")
    
    # Register Web blueprint
    from app.views import web_bp
    app.register_blueprint(web_bp)
    
    # Health check endpoint
    @app.route("/health")
    def health():
        return {"status": "ok"}
    
    # Register commands
    from app.commands import seed_command
    app.cli.add_command(seed_command)

    return app
