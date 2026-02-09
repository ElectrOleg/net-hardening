"""VendorMapping model - configurable vendor detection rules."""
import uuid
from sqlalchemy.dialects.postgresql import UUID
from app.extensions import db


class VendorMapping(db.Model):
    """Configurable rules for detecting device vendor from config content.
    
    Replaces hardcoded if/elif chains in ScannerService with
    database-driven, user-manageable patterns.
    """
    
    __tablename__ = "hcs_vendor_mappings"
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_code = db.Column(db.String(50), db.ForeignKey("hcs_vendors.code"), nullable=False)
    vendor = db.relationship("Vendor")
    
    # Detection pattern (regex)
    pattern = db.Column(db.String(500), nullable=False)
    
    # Where to look: "config_content", "sysDescr", "hostname", "banner"
    match_field = db.Column(db.String(50), nullable=False, default="config_content")
    
    # Priority: lower = checked first
    priority = db.Column(db.Integer, nullable=False, default=100)
    
    # Description for admin UI
    description = db.Column(db.String(200))
    
    is_active = db.Column(db.Boolean, default=True)
    
    def __repr__(self):
        return f"<VendorMapping {self.vendor_code}: {self.pattern[:30]}>"
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "vendor_code": self.vendor_code,
            "pattern": self.pattern,
            "match_field": self.match_field,
            "priority": self.priority,
            "description": self.description,
            "is_active": self.is_active,
        }


# Default vendor detection rules (seeded via migration or startup)
DEFAULT_VENDOR_MAPPINGS = [
    # Cisco
    {"vendor_code": "cisco_ios", "pattern": r"(?i)! Vendor: cisco_ios", "match_field": "config_content", "priority": 10, "description": "Explicit cisco_ios marker"},
    {"vendor_code": "cisco_nxos", "pattern": r"(?i)(NX-OS|nx-os)", "match_field": "config_content", "priority": 20, "description": "NX-OS detection"},
    {"vendor_code": "cisco_iosxr", "pattern": r"(?i)(IOS-XR|ios-xr)", "match_field": "config_content", "priority": 20, "description": "IOS-XR detection"},
    {"vendor_code": "cisco_iosxe", "pattern": r"(?i)(IOS-XE|ios-xe)", "match_field": "config_content", "priority": 20, "description": "IOS-XE detection"},
    {"vendor_code": "cisco_ios", "pattern": r"(?i)version.*cisco", "match_field": "config_content", "priority": 50, "description": "Generic Cisco IOS"},
    
    # Juniper
    {"vendor_code": "juniper_junos", "pattern": r"(?i)# Vendor: juniper_junos", "match_field": "config_content", "priority": 10, "description": "Explicit juniper marker"},
    {"vendor_code": "juniper_junos", "pattern": r"system\s*\{[\s\S]*host-name", "match_field": "config_content", "priority": 40, "description": "JUNOS curly-brace config"},
    
    # Arista
    {"vendor_code": "arista_eos", "pattern": r"(?i)!\s*Command:.*Arista", "match_field": "config_content", "priority": 30, "description": "Arista EOS header"},
    
    # Huawei
    {"vendor_code": "huawei", "pattern": r"(?i)sysname.*huawei", "match_field": "config_content", "priority": 30, "description": "Huawei VRP sysname"},
    
    # Fortinet
    {"vendor_code": "fortinet_fortios", "pattern": r"config system global", "match_field": "config_content", "priority": 30, "description": "FortiOS config block"},
    
    # Palo Alto
    {"vendor_code": "paloalto_panos", "pattern": r"set deviceconfig system", "match_field": "config_content", "priority": 30, "description": "PAN-OS set commands"},
    
    # MikroTik
    {"vendor_code": "mikrotik_routeros", "pattern": r"/system identity|/interface bridge", "match_field": "config_content", "priority": 30, "description": "RouterOS commands"},
    
    # Linux
    {"vendor_code": "linux", "pattern": r"(?i)(iptables|nftables)", "match_field": "config_content", "priority": 50, "description": "Linux firewall"},
]
