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
    
    class Config:
        env_file = ".env"
        case_sensitive = True


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
