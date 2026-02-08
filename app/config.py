"""HCS Flask Application Configuration."""
import os
import secrets
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Flask
    SECRET_KEY: str = ""  # Will be auto-generated if not set
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
    
    # Authentication
    AUTH_ENABLED: bool = False  # Set to True in production
    API_TOKEN: str = ""  # Static API token for automation
    
    # LDAP / Active Directory
    LDAP_ENABLED: bool = False
    LDAP_SERVER: str = ""          # ldap://dc.example.com or ldaps://dc.example.com
    LDAP_PORT: int = 389           # 636 for LDAPS
    LDAP_USE_SSL: bool = False     # True for LDAPS
    LDAP_STARTTLS: bool = False
    LDAP_BIND_DN: str = ""
    LDAP_BIND_PASSWORD: str = ""
    LDAP_BASE_DN: str = ""
    LDAP_USER_FILTER: str = "(sAMAccountName={username})"
    LDAP_ATTR_USERNAME: str = "sAMAccountName"
    LDAP_ATTR_EMAIL: str = "mail"
    LDAP_ATTR_DISPLAY_NAME: str = "displayName"
    LDAP_ADMIN_GROUP: str = ""
    LDAP_OPERATOR_GROUP: str = ""
    LDAP_CERT_VALIDATION: str = "REQUIRED"  # NONE | OPTIONAL | REQUIRED
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Allow extra env vars like FLASK_APP without error


settings = Settings()

# Auto-generate SECRET_KEY if not provided
if not settings.SECRET_KEY:
    import warnings
    settings.SECRET_KEY = secrets.token_hex(32)
    warnings.warn(
        "SECRET_KEY not set in environment — using auto-generated ephemeral key. "
        "Sessions will not persist across restarts. Set SECRET_KEY in .env for production.",
        RuntimeWarning,
        stacklevel=1,
    )


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
