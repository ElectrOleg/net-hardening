"""SystemSetting model — DB-backed global configuration."""
import uuid
from sqlalchemy.dialects.postgresql import UUID
from app.extensions import db


# Default settings with types and descriptions
SETTING_DEFAULTS = {
    "retention.scan_days": {
        "value": "90",
        "description": "Хранить результаты сканов (дней)",
        "type": "int",
        "group": "retention",
    },
    "retention.min_scans": {
        "value": "10",
        "description": "Минимум сохраняемых сканов",
        "type": "int",
        "group": "retention",
    },
    "retention.inactive_device_days": {
        "value": "180",
        "description": "Удалять неактивные устройства через (дней)",
        "type": "int",
        "group": "retention",
    },
    "scan.auto_enabled": {
        "value": "false",
        "description": "Автозапуск сканов по расписанию",
        "type": "bool",
        "group": "scan",
    },
    "sync.default_interval_minutes": {
        "value": "60",
        "description": "Интервал синхронизации по умолчанию (мин)",
        "type": "int",
        "group": "sync",
    },
}


class SystemSetting(db.Model):
    """Key-value store for global HCS settings."""
    
    __tablename__ = "hcs_system_settings"
    
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")
    description = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    def __repr__(self):
        return f"<SystemSetting {self.key}={self.value}>"
    
    def to_dict(self):
        meta = SETTING_DEFAULTS.get(self.key, {})
        return {
            "key": self.key,
            "value": self.value,
            "description": self.description or meta.get("description", ""),
            "type": meta.get("type", "str"),
            "group": meta.get("group", "other"),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
    
    @classmethod
    def get(cls, key: str, default: str = "") -> str:
        """Get a setting value by key, with fallback to SETTING_DEFAULTS then default."""
        setting = cls.query.get(key)
        if setting:
            return setting.value
        meta = SETTING_DEFAULTS.get(key)
        if meta:
            return meta["value"]
        return default
    
    @classmethod
    def get_int(cls, key: str, default: int = 0) -> int:
        """Get setting as integer."""
        try:
            return int(cls.get(key, str(default)))
        except (ValueError, TypeError):
            return default
    
    @classmethod
    def get_bool(cls, key: str, default: bool = False) -> bool:
        """Get setting as boolean."""
        val = cls.get(key, str(default)).lower()
        return val in ("true", "1", "yes", "on")
    
    @classmethod
    def set(cls, key: str, value: str) -> "SystemSetting":
        """Set a setting value (upsert)."""
        setting = cls.query.get(key)
        if setting:
            setting.value = str(value)
        else:
            meta = SETTING_DEFAULTS.get(key, {})
            setting = cls(
                key=key,
                value=str(value),
                description=meta.get("description", ""),
            )
            db.session.add(setting)
        return setting
    
    @classmethod
    def get_all(cls) -> dict:
        """Get all settings as dict, filling defaults for missing keys."""
        stored = {s.key: s for s in cls.query.all()}
        result = {}
        
        # Start with defaults
        for key, meta in SETTING_DEFAULTS.items():
            if key in stored:
                result[key] = stored[key].to_dict()
            else:
                result[key] = {
                    "key": key,
                    "value": meta["value"],
                    "description": meta.get("description", ""),
                    "type": meta.get("type", "str"),
                    "group": meta.get("group", "other"),
                    "updated_at": None,
                }
        
        # Add any custom keys not in defaults
        for key, setting in stored.items():
            if key not in result:
                result[key] = setting.to_dict()
        
        return result
