"""Device Inventory Providers - Flexible external device sources."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class Device:
    """Device information from inventory."""
    id: str  # Unique identifier (hostname or IP)
    hostname: str
    ip_address: Optional[str] = None
    vendor_code: Optional[str] = None
    group: Optional[str] = None
    location: Optional[str] = None
    is_active: bool = True
    metadata: Optional[dict] = None
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "hostname": self.hostname,
            "ip_address": self.ip_address,
            "vendor_code": self.vendor_code,
            "group": self.group,
            "location": self.location,
            "is_active": self.is_active,
            "metadata": self.metadata
        }


class DeviceInventoryProvider(ABC):
    """Abstract base class for device inventory sources."""
    
    @abstractmethod
    def list_devices(self, filters: Optional[dict] = None) -> list[Device]:
        """Get list of devices, optionally filtered."""
        pass
    
    @abstractmethod
    def get_device(self, device_id: str) -> Optional[Device]:
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
            "group": "device_group",
            "location": "site",
            "is_active": "is_active"
        },
        "filter_sql": "is_active = true"
    }
    """
    
    def __init__(
        self,
        host: str,
        port: int = 5432,
        database: str = "inventory",
        user: str = "postgres",
        password: str = "",
        table: str = "devices",
        columns: Optional[dict] = None,
        filter_sql: Optional[str] = None
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.table = table
        self.columns = columns or {
            "id": "hostname",
            "hostname": "hostname",
            "ip_address": "ip",
            "vendor_code": "vendor",
            "group": "device_group",
            "location": "location",
            "is_active": "is_active"
        }
        self.filter_sql = filter_sql
        self._connection = None
    
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
    
    def list_devices(self, filters: Optional[dict] = None) -> list[Device]:
        devices = []
        
        # Build SELECT with column mapping
        cols = self.columns
        select_cols = ", ".join([
            f"{v} AS {k}" for k, v in cols.items()
        ])
        
        sql = f"SELECT {select_cols} FROM {self.table}"
        
        where_clauses = []
        if self.filter_sql:
            where_clauses.append(f"({self.filter_sql})")
        
        if filters:
            for key, value in filters.items():
                if key in cols:
                    where_clauses.append(f"{cols[key]} = %s")
        
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
        
        params = list(filters.values()) if filters else []
        
        try:
            cursor = self.connection.cursor()
            cursor.execute(sql, params)
            
            for row in cursor.fetchall():
                desc = cursor.description
                row_dict = {desc[i][0]: value for i, value in enumerate(row)}
                
                devices.append(Device(
                    id=row_dict.get("id", ""),
                    hostname=row_dict.get("hostname", ""),
                    ip_address=row_dict.get("ip_address"),
                    vendor_code=row_dict.get("vendor_code"),
                    group=row_dict.get("group"),
                    location=row_dict.get("location"),
                    is_active=row_dict.get("is_active", True)
                ))
            
            cursor.close()
            
        except Exception as e:
            logger.error(f"Failed to list devices: {e}")
        
        return devices
    
    def get_device(self, device_id: str) -> Optional[Device]:
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
            "vendor_code": "platform"
        }
    }
    """
    
    def __init__(
        self,
        base_url: str,
        endpoint: str = "/devices",
        auth_type: str = "bearer",
        auth_value: str = "",
        response_path: Optional[str] = None,
        field_mapping: Optional[dict] = None,
        timeout: int = 30
    ):
        import requests
        self.base_url = base_url.rstrip("/")
        self.endpoint = endpoint
        self.auth_type = auth_type
        self.auth_value = auth_value
        self.response_path = response_path
        self.field_mapping = field_mapping or {}
        self.timeout = timeout
        
        self._session = requests.Session()
        
        # Set up auth
        if auth_type == "bearer":
            self._session.headers["Authorization"] = f"Bearer {auth_value}"
        elif auth_type == "api_key":
            self._session.headers["X-API-Key"] = auth_value
    
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
        """Extract devices list from response using path."""
        if not self.response_path:
            return response_data if isinstance(response_data, list) else []
        
        data = response_data
        for key in self.response_path.split("."):
            if isinstance(data, dict):
                data = data.get(key, [])
            else:
                return []
        
        return data if isinstance(data, list) else []
    
    def _map_device(self, raw: dict) -> Device:
        """Map API response to Device object."""
        mapping = self.field_mapping
        
        def get_field(name: str):
            if name in mapping:
                return raw.get(mapping[name])
            return raw.get(name)
        
        return Device(
            id=str(get_field("id") or get_field("hostname") or ""),
            hostname=str(get_field("hostname") or ""),
            ip_address=get_field("ip_address"),
            vendor_code=get_field("vendor_code"),
            group=get_field("group"),
            location=get_field("location"),
            is_active=get_field("is_active") or True
        )
    
    def list_devices(self, filters: Optional[dict] = None) -> list[Device]:
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
    
    def get_device(self, device_id: str) -> Optional[Device]:
        devices = self.list_devices({"id": device_id})
        return devices[0] if devices else None
    
    def close(self):
        self._session.close()


class StaticInventoryProvider(DeviceInventoryProvider):
    """
    Simple static provider for testing or small deployments.
    Devices are defined in configuration.
    """
    
    def __init__(self, devices: list[dict]):
        self.devices = [
            Device(
                id=d.get("id") or d.get("hostname"),
                hostname=d.get("hostname", ""),
                ip_address=d.get("ip_address"),
                vendor_code=d.get("vendor_code"),
                group=d.get("group"),
                location=d.get("location"),
                is_active=d.get("is_active", True)
            )
            for d in devices
        ]
    
    def test_connection(self) -> tuple[bool, str]:
        return True, f"Static inventory with {len(self.devices)} devices"
    
    def list_devices(self, filters: Optional[dict] = None) -> list[Device]:
        if not filters:
            return self.devices.copy()
        
        return [
            d for d in self.devices
            if all(getattr(d, k, None) == v for k, v in filters.items())
        ]
    
    def get_device(self, device_id: str) -> Optional[Device]:
        for d in self.devices:
            if d.id == device_id:
                return d
        return None
