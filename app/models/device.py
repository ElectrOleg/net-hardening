"""Device model - internal device inventory."""
import uuid
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.extensions import db


class Device(db.Model):
    """Device - internal representation of network devices."""
    
    __tablename__ = "hcs_devices"
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id = db.Column(db.String(200))  # ID from external system
    hostname = db.Column(db.String(200), nullable=False)
    ip_address = db.Column(db.String(50))
    
    # Vendor relationship
    vendor_code = db.Column(db.String(50), db.ForeignKey("hcs_vendors.code"), nullable=True)
    vendor = db.relationship("Vendor", backref="devices")
    
    # Grouping
    group_id = db.Column(UUID(as_uuid=True), db.ForeignKey("hcs_device_groups.id"), nullable=True)
    group = db.relationship("DeviceGroup", back_populates="devices")
    
    # Additional info
    location = db.Column(db.String(200))
    os_version = db.Column(db.String(100))
    hardware = db.Column(db.String(200))
    extra_data = db.Column(JSONB, default=dict)
    
    # Sync tracking
    source_id = db.Column(UUID(as_uuid=True), db.ForeignKey("hcs_inventory_sources.id"), nullable=True)
    source = db.relationship("InventorySource", backref="devices")
    last_sync_at = db.Column(db.DateTime)
    last_scan_at = db.Column(db.DateTime)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    # M2M with Policies (device-specific policies)
    policies = db.relationship(
        "Policy",
        secondary="hcs_device_policies",
        backref=db.backref("devices", lazy="dynamic")
    )
    
    def __repr__(self):
        return f"<Device {self.hostname}>"
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "external_id": self.external_id,
            "hostname": self.hostname,
            "ip_address": self.ip_address,
            "vendor_code": self.vendor_code,
            "group_id": str(self.group_id) if self.group_id else None,
            "group_name": self.group.name if self.group else None,
            "location": self.location,
            "os_version": self.os_version,
            "hardware": self.hardware,
            "extra_data": self.extra_data,
            "source_id": str(self.source_id) if self.source_id else None,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "last_scan_at": self.last_scan_at.isoformat() if self.last_scan_at else None,
            "is_active": self.is_active,
            "policies": [str(p.id) for p in self.policies],
        }


# M2M table for Device <-> Policy
device_policies = db.Table(
    "hcs_device_policies",
    db.Column("device_id", UUID(as_uuid=True), db.ForeignKey("hcs_devices.id"), primary_key=True),
    db.Column("policy_id", UUID(as_uuid=True), db.ForeignKey("hcs_policies.id"), primary_key=True),
    db.Column("assigned_at", db.DateTime, server_default=db.func.now()),
)
