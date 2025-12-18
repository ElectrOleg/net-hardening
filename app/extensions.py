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
    
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
    
    celery.Task = ContextTask
    return celery
