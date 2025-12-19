"""HCS Flask Application Configuration."""
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Flask
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    DEBUG: bool = True
    
    # Database
    DATABASE_URL: str = "postgresql://hcs:hcs@localhost:5432/hcs"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    
    # GitLab
    GITLAB_URL: str = ""
    GITLAB_TOKEN: str = ""
    GITLAB_PROJECT_ID: str = ""

    # SMTP / Notifications
    SMTP_PORT: int = 587
    SMTP_TO: str = "admin@example.com"
    ALERT_SCORE_THRESHOLD: int = 80

    # Ansible / AWX
    ANSIBLE_EXECUTOR_TYPE: str = "local"
    ANSIBLE_USER: str = "ansible"
    ANSIBLE_PLAYBOOK_DIR: str = "/tmp/hcs_playbooks"
    ANSIBLE_INVENTORY: str = "/etc/ansible/hosts"
    AWX_URL: str = ""
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Allow extra env vars like FLASK_APP without error


settings = Settings()


class FlaskConfig:
    """Flask configuration class."""
    
    SECRET_KEY = settings.SECRET_KEY
    
    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI = settings.DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    
    # Celery
    CELERY = {
        "broker_url": settings.CELERY_BROKER_URL,
        "result_backend": settings.CELERY_RESULT_BACKEND,
        "task_serializer": "json",
        "result_serializer": "json",
        "accept_content": ["json"],
        "timezone": "UTC",
        "enable_utc": True,
    }
