"""API Provider - fetch configs from REST APIs (UserGate, CheckPoint, etc.)."""
import logging
from typing import Optional

import requests

from app.providers.base import ConfigSourceProvider, FetchResult

logger = logging.getLogger(__name__)


class APIProvider(ConfigSourceProvider):
    """
    Provider for fetching configurations from REST APIs.
    Returns JSON data suitable for StructureChecker.
    
    Connection params:
    {
        "base_url": "https://api.example.com",
        "auth_type": "bearer",  // bearer, basic, api_key
        "auth_value": "token_or_credentials",
        "api_key_header": "X-API-Key",
        "endpoint_template": "/devices/{device_id}/config",
        "devices_endpoint": "/devices",
        "method": "GET",
        "headers": {},
        "timeout": 30,
        "verify_ssl": true
    }
    """
    
    def __init__(self, config: dict):
        self.base_url = config.get("base_url", "").rstrip("/")
        self.auth_type = config.get("auth_type", "bearer")
        self.auth_value = config.get("auth_value") or config.get("token", "")
        self.api_key_header = config.get("api_key_header", "X-API-Key")
        self.endpoint_template = config.get("endpoint_template", "/devices/{device_id}/config")
        self.devices_endpoint = config.get("devices_endpoint", "/devices")
        self.method = config.get("method", "GET")
        self.headers = config.get("headers", {})
        self.timeout = config.get("timeout", 30)
        self.verify_ssl = config.get("verify_ssl", True)
        
        self._session: Optional[requests.Session] = None
    
    @property
    def session(self) -> requests.Session:
        """Lazy initialization of requests session."""
        if self._session is None:
            self._session = requests.Session()
            self._session.verify = self.verify_ssl
            
            # Set up authentication
            if self.auth_type == "bearer":
                self._session.headers["Authorization"] = f"Bearer {self.auth_value}"
            elif self.auth_type == "basic":
                # auth_value should be "username:password"
                import base64
                encoded = base64.b64encode(self.auth_value.encode()).decode()
                self._session.headers["Authorization"] = f"Basic {encoded}"
            elif self.auth_type == "api_key":
                self._session.headers[self.api_key_header] = self.auth_value
            
            # Add custom headers
            self._session.headers.update(self.headers)
        
        return self._session
    
    def test_connection(self) -> tuple[bool, str]:
        """Test API connection."""
        try:
            response = self.session.get(
                f"{self.base_url}{self.devices_endpoint}",
                timeout=self.timeout
            )
            response.raise_for_status()
            return True, f"Connected successfully (status {response.status_code})"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"
    
    def fetch_config(self, device_id: str) -> FetchResult:
        """Fetch configuration from API."""
        endpoint = self.endpoint_template.format(
            device_id=device_id,
            hostname=device_id
        )
        url = f"{self.base_url}{endpoint}"
        
        try:
            if self.method.upper() == "GET":
                response = self.session.get(url, timeout=self.timeout)
            elif self.method.upper() == "POST":
                response = self.session.post(url, timeout=self.timeout)
            else:
                return FetchResult(
                    success=False,
                    config=None,
                    error=f"Unsupported method: {self.method}"
                )
            
            response.raise_for_status()
            
            # Try to parse as JSON
            try:
                config = response.json()
                fmt = "json"
            except ValueError:
                # Return as text if not JSON
                config = response.text
                fmt = "text"
            
            return FetchResult(
                success=True,
                config=config,
                format=fmt,
                metadata={
                    "url": url,
                    "status_code": response.status_code,
                    "content_type": response.headers.get("Content-Type")
                }
            )
            
        except requests.RequestException as e:
            logger.error(f"API error for {device_id}: {e}")
            return FetchResult(
                success=False,
                config=None,
                error=str(e)
            )
    
    def list_devices(self) -> list[str]:
        """List devices from API."""
        try:
            response = self.session.get(
                f"{self.base_url}{self.devices_endpoint}",
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            
            # Try common response formats
            if isinstance(data, list):
                # Direct list of devices
                if all(isinstance(d, str) for d in data):
                    return data
                # List of objects with id/name
                return [
                    d.get("id") or d.get("name") or d.get("hostname")
                    for d in data
                    if isinstance(d, dict)
                ]
            elif isinstance(data, dict):
                # Wrapped response
                devices = data.get("devices") or data.get("items") or data.get("data") or []
                if isinstance(devices, list):
                    return [
                        d.get("id") or d.get("name") or d.get("hostname") or str(d)
                        for d in devices
                    ]
            
            return []
            
        except Exception as e:
            logger.error(f"Failed to list devices: {e}")
            return []
    
    def close(self):
        """Close the session."""
        if self._session:
            self._session.close()
            self._session = None
