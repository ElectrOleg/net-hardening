"""Device Inventory Providers - Flexible external device sources."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any
import logging

logger = logging.getLogger(__name__)


# ── Standard fields that map to InventoryDevice attributes ──────────────
STANDARD_FIELDS = {
    "id", "hostname", "ip_address", "vendor_code",
    "group", "location", "os_version", "hardware", "is_active"
}


@dataclass
class InventoryDevice:
    """Device information from external inventory source.
    
    NOTE: This is distinct from the ORM `Device` model in app.models.device.
    This dataclass represents raw device data fetched from external sources
    before it is persisted into the database.
    
    Standard fields are mapped directly to Device ORM columns.
    The `metadata` dict carries extra columns/fields that will be
    stored in Device.extra_data JSONB.
    """
    id: str  # Unique identifier (hostname or IP)
    hostname: str
    ip_address: Optional[str] = None
    vendor_code: Optional[str] = None
    group: Optional[str] = None
    location: Optional[str] = None
    os_version: Optional[str] = None
    hardware: Optional[str] = None
    is_active: bool = True
    metadata: Optional[dict] = None
    
    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "hostname": self.hostname,
            "ip_address": self.ip_address,
            "vendor_code": self.vendor_code,
            "group": self.group,
            "location": self.location,
            "os_version": self.os_version,
            "hardware": self.hardware,
            "is_active": self.is_active,
        }
        if self.metadata:
            d["metadata"] = self.metadata
        return d


# Backward compat alias
Device = InventoryDevice


class DeviceInventoryProvider(ABC):
    """Abstract base class for device inventory sources."""
    
    @abstractmethod
    def list_devices(self, filters: Optional[dict] = None) -> list[InventoryDevice]:
        """Get list of devices, optionally filtered."""
        pass
    
    @abstractmethod
    def get_device(self, device_id: str) -> Optional[InventoryDevice]:
        """Get single device by ID."""
        pass
    
    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """Test connectivity to the inventory source."""
        pass
    
    def close(self):
        """Clean up resources."""
        pass


class PostgresInventoryProvider(DeviceInventoryProvider):
    """
    Provider for device inventory stored in external PostgreSQL database.
    
    Config:
    {
        "host": "db.example.com",
        "port": 5432,
        "database": "network_inventory",
        "user": "readonly",
        "password": "...",
        "table": "devices",
        "columns": {
            "id": "hostname",
            "hostname": "hostname",
            "ip_address": "ip",
            "vendor_code": "vendor",
            "os_version": "software_version",
            "hardware": "hw_model",
            "group": "device_group",
            "location": "site",
            "is_active": "is_active"
        },
        "extra_columns": {
            "department": "dept_name",
            "rack": "rack_location",
            "serial": "serial_number",
            "firmware": "fw_version",
            "contact": "admin_contact"
        },
        "filter_sql": "is_active = true"
    }
    
    Standard `columns` keys map to InventoryDevice attributes.
    `extra_columns` keys become entries in InventoryDevice.metadata dict,
    which flows into Device.extra_data JSONB during sync.
    """
    
    def __init__(self, config: dict):
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 5432)
        self.database = config.get("database", "inventory")
        self.user = config.get("user", "postgres")
        self.password = config.get("password", "")
        self.table = config.get("table", "devices")
        self.columns = config.get("columns", {
            "id": "hostname",
            "hostname": "hostname",
            "ip_address": "ip",
            "vendor_code": "vendor",
            "group": "device_group",
            "location": "location",
            "os_version": "os_version",
            "hardware": "hardware",
            "is_active": "is_active"
        })
        self.extra_columns = config.get("extra_columns", {})
        self._raw_filter_sql = config.get("filter_sql")
        self.filter_sql = self._sanitize_filter_sql(self._raw_filter_sql)
        self._connection = None
    
    @staticmethod
    def _sanitize_filter_sql(filter_sql: Optional[str]) -> Optional[str]:
        """Basic validation of filter_sql to prevent SQL injection."""
        if not filter_sql:
            return None
        
        dangerous = [";", "--", "/*", "*/", "drop ", "delete ", "update ", 
                     "insert ", "alter ", "create ", "exec ", "xp_"]
        lower = filter_sql.lower().strip()
        for pattern in dangerous:
            if pattern in lower:
                logger.warning(f"Rejected dangerous filter_sql: {filter_sql}")
                return None
        
        return filter_sql
    
    @property
    def connection(self):
        """Lazy connection initialization."""
        if self._connection is None:
            import psycopg2
            self._connection = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password
            )
        return self._connection
    
    def test_connection(self) -> tuple[bool, str]:
        try:
            conn = self.connection
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return True, "Connection successful"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"
    
    def list_devices(self, filters: Optional[dict] = None) -> list[InventoryDevice]:
        devices = []
        
        # Build SELECT: standard columns + extra columns
        cols = self.columns
        select_parts = [f"{v} AS {k}" for k, v in cols.items()]
        
        # Extra columns: prefixed with _extra_ to distinguish in result
        for extra_key, extra_col in self.extra_columns.items():
            select_parts.append(f"{extra_col} AS _extra_{extra_key}")
        
        select_cols = ", ".join(select_parts)
        sql = f"SELECT {select_cols} FROM {self.table}"
        
        where_clauses = []
        params = []
        
        if self.filter_sql:
            where_clauses.append(f"({self.filter_sql})")
        
        if filters:
            for key, value in filters.items():
                if key in cols:
                    where_clauses.append(f"{cols[key]} = %s")
                    params.append(value)
        
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
        
        try:
            cursor = self.connection.cursor()
            cursor.execute(sql, params)
            
            for row in cursor.fetchall():
                desc = cursor.description
                row_dict = {desc[i][0]: value for i, value in enumerate(row)}
                
                # Split standard fields from extra fields
                extra_data = {}
                for key in list(row_dict.keys()):
                    if key.startswith("_extra_"):
                        real_key = key[7:]  # strip "_extra_" prefix
                        val = row_dict.pop(key)
                        if val is not None:
                            extra_data[real_key] = str(val) if not isinstance(val, str) else val
                
                devices.append(InventoryDevice(
                    id=str(row_dict.get("id", "")),
                    hostname=str(row_dict.get("hostname", "")),
                    ip_address=row_dict.get("ip_address"),
                    vendor_code=row_dict.get("vendor_code"),
                    group=row_dict.get("group"),
                    location=row_dict.get("location"),
                    os_version=row_dict.get("os_version"),
                    hardware=row_dict.get("hardware"),
                    is_active=bool(row_dict.get("is_active", True)),
                    metadata=extra_data or None
                ))
            
            cursor.close()
            
        except Exception as e:
            logger.error(f"Failed to list devices: {e}")
        
        return devices
    
    def get_device(self, device_id: str) -> Optional[InventoryDevice]:
        devices = self.list_devices({"id": device_id})
        return devices[0] if devices else None
    
    def close(self):
        if self._connection:
            self._connection.close()
            self._connection = None


class APIInventoryProvider(DeviceInventoryProvider):
    """
    Provider for device inventory from REST API.
    
    Config:
    {
        "base_url": "https://cmdb.example.com/api",
        "endpoint": "/devices",
        "auth_type": "bearer",
        "auth_value": "token",
        "response_path": "data.items",
        "field_mapping": {
            "id": "hostname",
            "hostname": "hostname",
            "ip_address": "primary_ip",
            "vendor_code": "platform",
            "os_version": "sw_version",
            "hardware": "model"
        },
        "extra_fields": ["serial_number", "department", "rack", "firmware"]
    }
    
    `field_mapping` maps standard InventoryDevice fields to API response keys.
    `extra_fields` lists additional API response keys to pull into metadata.
    Any key NOT in field_mapping and NOT in extra_fields is ignored.
    """
    
    def __init__(self, config: dict):
        import requests
        self.base_url = config.get("base_url", "").rstrip("/")
        self.endpoint = config.get("endpoint", "/devices")
        self.auth_type = config.get("auth_type", "bearer")
        self.auth_value = config.get("auth_value") or config.get("token", "")
        self.response_path = config.get("response_path")
        self.field_mapping = config.get("field_mapping", {})
        self.extra_fields = config.get("extra_fields", [])
        self.timeout = config.get("timeout", 30)
        
        self._session = requests.Session()
        
        # Set up auth
        if self.auth_type == "bearer":
            self._session.headers["Authorization"] = f"Bearer {self.auth_value}"
        elif self.auth_type == "api_key":
            header_name = config.get("api_key_header", "X-API-Key")
            self._session.headers[header_name] = self.auth_value
        elif self.auth_type == "basic":
            import base64
            encoded = base64.b64encode(self.auth_value.encode()).decode()
            self._session.headers["Authorization"] = f"Basic {encoded}"
    
    def test_connection(self) -> tuple[bool, str]:
        try:
            response = self._session.get(
                f"{self.base_url}{self.endpoint}",
                timeout=self.timeout
            )
            response.raise_for_status()
            return True, f"Connected (status {response.status_code})"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"
    
    def _extract_data(self, response_data: Any) -> list[dict]:
        """Extract devices list from response using dot-path."""
        if not self.response_path:
            return response_data if isinstance(response_data, list) else []
        
        data = response_data
        for key in self.response_path.split("."):
            if isinstance(data, dict):
                data = data.get(key, [])
            else:
                return []
        
        return data if isinstance(data, list) else []
    
    def _get_field(self, raw: dict, name: str):
        """Get a field value from raw dict, applying field_mapping if configured."""
        if name in self.field_mapping:
            # Mapping value can be a dot-path for nested access
            path = self.field_mapping[name]
            return self._resolve_path(raw, path)
        return raw.get(name)
    
    @staticmethod
    def _resolve_path(data: dict, path: str):
        """Resolve a dot-separated path in a nested dict."""
        for key in path.split("."):
            if isinstance(data, dict):
                data = data.get(key)
            else:
                return None
        return data
    
    def _map_device(self, raw: dict) -> InventoryDevice:
        """Map API response to InventoryDevice, including extra fields."""
        # Standard fields
        dev_id = self._get_field(raw, "id") or self._get_field(raw, "hostname") or ""
        
        # Extra fields → metadata dict
        extra_data = {}
        for field_name in self.extra_fields:
            val = self._resolve_path(raw, field_name) if "." in field_name else raw.get(field_name)
            if val is not None:
                # Use the leaf key name for nested paths
                key = field_name.split(".")[-1] if "." in field_name else field_name
                extra_data[key] = str(val) if not isinstance(val, (str, int, float, bool)) else val
        
        return InventoryDevice(
            id=str(dev_id),
            hostname=str(self._get_field(raw, "hostname") or ""),
            ip_address=self._get_field(raw, "ip_address"),
            vendor_code=self._get_field(raw, "vendor_code"),
            group=self._get_field(raw, "group"),
            location=self._get_field(raw, "location"),
            os_version=self._get_field(raw, "os_version"),
            hardware=self._get_field(raw, "hardware"),
            is_active=bool(self._get_field(raw, "is_active") or True),
            metadata=extra_data or None
        )
    
    def list_devices(self, filters: Optional[dict] = None) -> list[InventoryDevice]:
        try:
            params = filters or {}
            response = self._session.get(
                f"{self.base_url}{self.endpoint}",
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            raw_devices = self._extract_data(response.json())
            return [self._map_device(d) for d in raw_devices]
            
        except Exception as e:
            logger.error(f"Failed to list devices from API: {e}")
            return []
    
    def get_device(self, device_id: str) -> Optional[InventoryDevice]:
        devices = self.list_devices({"id": device_id})
        return devices[0] if devices else None
    
    def close(self):
        self._session.close()


class StaticInventoryProvider(DeviceInventoryProvider):
    """
    Simple static provider for testing or small deployments.
    Devices are defined in configuration.
    
    Config:
    {
        "devices": [
            {
                "hostname": "sw-core-01",
                "ip_address": "10.0.0.1",
                "vendor_code": "cisco_ios",
                "os_version": "15.2(4)M",
                "hardware": "WS-C3750X",
                "department": "Network",
                "serial": "FOC1234567"
            }
        ]
    }
    
    Standard fields are mapped to InventoryDevice attributes.
    Any extra keys (not in STANDARD_FIELDS) are placed in metadata.
    """
    
    def __init__(self, config: dict):
        devices_list = config.get("devices", []) if isinstance(config, dict) else config
        self.devices = [self._parse_device(d) for d in devices_list]
    
    @staticmethod
    def _parse_device(d: dict) -> InventoryDevice:
        """Parse a device dict, separating standard from extra fields."""
        extra = {}
        for key, val in d.items():
            if key not in STANDARD_FIELDS and key != "metadata" and val is not None:
                extra[key] = val
        
        # Merge with explicit metadata if provided
        if d.get("metadata"):
            extra.update(d["metadata"])
        
        return InventoryDevice(
            id=d.get("id") or d.get("hostname", ""),
            hostname=d.get("hostname", ""),
            ip_address=d.get("ip_address"),
            vendor_code=d.get("vendor_code"),
            group=d.get("group"),
            location=d.get("location"),
            os_version=d.get("os_version"),
            hardware=d.get("hardware"),
            is_active=d.get("is_active", True),
            metadata=extra or None
        )
    
    def test_connection(self) -> tuple[bool, str]:
        return True, f"Static inventory with {len(self.devices)} devices"
    
    def list_devices(self, filters: Optional[dict] = None) -> list[InventoryDevice]:
        if not filters:
            return self.devices.copy()
        
        result = []
        for d in self.devices:
            match = True
            for k, v in filters.items():
                # Check standard fields first
                dev_val = getattr(d, k, None)
                if dev_val is None and d.metadata:
                    # Check extra_data too
                    dev_val = d.metadata.get(k)
                if dev_val != v:
                    match = False
                    break
            if match:
                result.append(d)
        return result
    
    def get_device(self, device_id: str) -> Optional[InventoryDevice]:
        for d in self.devices:
            if d.id == device_id:
                return d
        return None
