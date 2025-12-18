"""Inventory Source model - configuration for device inventory sources."""
import uuid
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.extensions import db


class InventorySource(db.Model):
    """Configuration for external device inventory sources."""
    
    __tablename__ = "hcs_inventory_sources"
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(30), nullable=False)  # postgres, api, static
    description = db.Column(db.Text)
    
    # Connection settings (type-specific)
    connection_params = db.Column(JSONB)
    
    # Credentials reference (env var name or Vault path)
    credentials_ref = db.Column(db.String(200))
    
    # Scheduling
    sync_enabled = db.Column(db.Boolean, default=True)
    sync_interval_minutes = db.Column(db.Integer, default=60)
    last_sync_at = db.Column(db.DateTime)
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    def __repr__(self):
        return f"<InventorySource {self.name} ({self.type})>"
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "connection_params": self.connection_params,
            "sync_enabled": self.sync_enabled,
            "sync_interval_minutes": self.sync_interval_minutes,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "is_active": self.is_active,
        }
