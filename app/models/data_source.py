"""DataSource model - источники конфигураций."""
import uuid
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.extensions import db


class DataSource(db.Model):
    """Источники конфигураций (GitLab, SSH, API)."""
    
    __tablename__ = "hcs_data_sources"
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # gitlab, ssh_direct, api_rest
    credentials_ref = db.Column(db.String(200))  # Vault path or env var name
    connection_params = db.Column(JSONB)  # url, branch, path_template, etc.
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    def __repr__(self):
        return f"<DataSource {self.name} ({self.type})>"
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "type": self.type,
            "credentials_ref": self.credentials_ref,
            "connection_params": self.connection_params,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
