"""Vendor-specific API adapters for firewall platforms.

Each adapter extends APIProvider with vendor-specific authentication,
session management, and config fetching logic.
"""
import json
import logging
from typing import Optional

import requests

from app.providers.base import ConfigSourceProvider, FetchResult

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CheckPoint SmartConsole Management API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CheckPointProvider(ConfigSourceProvider):
    """
    CheckPoint Management API (SmartConsole / GAIA R80+).
    
    Uses session-based authentication with SID token.
    
    Connection params:
    {
        "base_url": "https://mgmt-server:443/web_api",
        "username": "admin",
        "password": "...",
        "domain": "SMC User",          # optional, for MDS
        "verify_ssl": false,
        "timeout": 30,
        
        // What to fetch:
        "endpoints": [
            {"name": "access-rules", "command": "show-access-rulebase", "params": {"name": "Network", "limit": 500}},
            {"name": "nat-rules", "command": "show-nat-rulebase", "params": {"package": "Standard"}},
            {"name": "threat-profiles", "command": "show-threat-profiles", "params": {}},
            {"name": "gateways", "command": "show-simple-gateways", "params": {}}
        ]
    }
    """
    
    SOURCE_TYPE = "checkpoint"
    
    # Common endpoints to fetch by default
    DEFAULT_ENDPOINTS = [
        {"name": "access-rules", "command": "show-access-rulebase",
         "params": {"name": "Network", "limit": 500, "details-level": "full"}},
        {"name": "nat-rules", "command": "show-nat-rulebase",
         "params": {"package": "Standard", "limit": 500}},
        {"name": "threat-profiles", "command": "show-threat-profiles", "params": {"limit": 50}},
        {"name": "gateways", "command": "show-simple-gateways", "params": {}},
        {"name": "hosts", "command": "show-hosts", "params": {"limit": 500}},
        {"name": "networks", "command": "show-networks", "params": {"limit": 500}},
    ]
    
    def __init__(self, config: dict):
        self.base_url = config.get("base_url", "").rstrip("/")
        self.username = config.get("username", "admin")
        self.password = config.get("password", "")
        self.domain = config.get("domain")
        self.verify_ssl = config.get("verify_ssl", False)
        self.timeout = config.get("timeout", 30)
        self.endpoints = config.get("endpoints", self.DEFAULT_ENDPOINTS)
        
        self._sid: Optional[str] = None
        self._session: Optional[requests.Session] = None
    
    def _login(self):
        """Authenticate and get session SID."""
        self._session = requests.Session()
        self._session.verify = self.verify_ssl
        
        login_payload = {
            "user": self.username,
            "password": self.password,
        }
        if self.domain:
            login_payload["domain"] = self.domain
        
        resp = self._session.post(
            f"{self.base_url}/login",
            json=login_payload,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        
        self._sid = data.get("sid")
        if not self._sid:
            raise RuntimeError("CheckPoint login failed: no SID in response")
        
        self._session.headers["X-chkp-sid"] = self._sid
        logger.info(f"CheckPoint API login successful (SID: {self._sid[:8]}...)")
    
    def _logout(self):
        """Logout from management server."""
        if self._session and self._sid:
            try:
                self._session.post(
                    f"{self.base_url}/logout",
                    json={},
                    timeout=10
                )
            except Exception:
                pass
            self._sid = None
    
    def _api_call(self, command: str, params: dict = None) -> dict:
        """Execute a SmartConsole API command."""
        if not self._sid:
            self._login()
        
        resp = self._session.post(
            f"{self.base_url}/{command}",
            json=params or {},
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()
    
    def _api_call_paged(self, command: str, params: dict = None) -> list:
        """Execute API command with automatic pagination."""
        params = dict(params or {})
        params.setdefault("limit", 500)
        params.setdefault("offset", 0)
        
        all_objects = []
        
        while True:
            data = self._api_call(command, params)
            
            # Different endpoints use different keys
            objects = (
                data.get("rulebase") or
                data.get("objects") or
                data.get("results") or
                []
            )
            all_objects.extend(objects)
            
            total = data.get("total", len(objects))
            fetched = params["offset"] + len(objects)
            
            if fetched >= total or not objects:
                break
            
            params["offset"] = fetched
        
        return all_objects
    
    def fetch_config(self, device_id: str = "") -> FetchResult:
        """Fetch full policy configuration from CheckPoint management."""
        try:
            self._login()
            
            config = {}
            for ep in self.endpoints:
                name = ep["name"]
                command = ep["command"]
                params = ep.get("params", {})
                
                try:
                    if params.get("limit", 0) > 50:
                        config[name] = self._api_call_paged(command, params)
                    else:
                        config[name] = self._api_call(command, params)
                except Exception as e:
                    logger.warning(f"CheckPoint endpoint '{name}' failed: {e}")
                    config[name] = {"error": str(e)}
            
            return FetchResult(
                success=True,
                config=config,
                format="json",
                metadata={"source": "checkpoint", "endpoints": len(self.endpoints)}
            )
            
        except Exception as e:
            logger.error(f"CheckPoint fetch failed: {e}")
            return FetchResult(success=False, error=str(e))
        finally:
            self._logout()
    
    def list_devices(self) -> list[str]:
        """List gateways managed by this management server."""
        try:
            self._login()
            data = self._api_call("show-simple-gateways")
            gateways = data.get("objects", [])
            return [gw.get("name", "") for gw in gateways]
        except Exception as e:
            logger.error(f"CheckPoint list_devices failed: {e}")
            return []
        finally:
            self._logout()
    
    def test_connection(self) -> tuple[bool, str]:
        try:
            self._login()
            data = self._api_call("show-api-versions")
            versions = data.get("supported-versions", [])
            self._logout()
            return True, f"Connected. API versions: {', '.join(versions[:3])}"
        except Exception as e:
            return False, str(e)
    
    def close(self):
        self._logout()
        if self._session:
            self._session.close()
            self._session = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FortiGate REST API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class FortiGateProvider(ConfigSourceProvider):
    """
    FortiGate REST API (FortiOS 6.x / 7.x).
    
    Supports both API key and session-based authentication.
    
    Connection params:
    {
        "base_url": "https://fortigate.local",
        "auth_type": "api_key",  // "api_key" or "session"
        "api_key": "your-api-key",
        "username": "admin",     // for session auth
        "password": "...",       // for session auth
        "vdom": "root",          // VDOM context
        "verify_ssl": false,
        "timeout": 30,
        
        "endpoints": [
            {"name": "firewall-policy", "path": "/api/v2/cmdb/firewall/policy"},
            {"name": "system-interface", "path": "/api/v2/cmdb/system/interface"},
            {"name": "system-admin", "path": "/api/v2/cmdb/system/admin"},
            {"name": "vpn-ipsec", "path": "/api/v2/cmdb/vpn.ipsec/phase1-interface"}
        ]
    }
    """
    
    SOURCE_TYPE = "fortigate"
    
    DEFAULT_ENDPOINTS = [
        {"name": "firewall-policy", "path": "/api/v2/cmdb/firewall/policy"},
        {"name": "firewall-address", "path": "/api/v2/cmdb/firewall/address"},
        {"name": "firewall-service", "path": "/api/v2/cmdb/firewall.service/custom"},
        {"name": "system-interface", "path": "/api/v2/cmdb/system/interface"},
        {"name": "system-admin", "path": "/api/v2/cmdb/system/admin"},
        {"name": "system-global", "path": "/api/v2/cmdb/system/global"},
        {"name": "system-dns", "path": "/api/v2/cmdb/system/dns"},
        {"name": "system-ntp", "path": "/api/v2/cmdb/system/ntp"},
        {"name": "vpn-ipsec-phase1", "path": "/api/v2/cmdb/vpn.ipsec/phase1-interface"},
        {"name": "vpn-ssl-settings", "path": "/api/v2/cmdb/vpn.ssl/settings"},
        {"name": "log-setting", "path": "/api/v2/cmdb/log.syslogd/setting"},
        {"name": "router-static", "path": "/api/v2/cmdb/router/static"},
        {"name": "user-local", "path": "/api/v2/cmdb/user/local"},
        {"name": "antivirus-profile", "path": "/api/v2/cmdb/antivirus/profile"},
        {"name": "ips-sensor", "path": "/api/v2/cmdb/ips/sensor"},
    ]
    
    def __init__(self, config: dict):
        self.base_url = config.get("base_url", "").rstrip("/")
        self.auth_type = config.get("auth_type", "api_key")
        self.api_key = config.get("api_key", "")
        self.username = config.get("username", "admin")
        self.password = config.get("password", "")
        self.vdom = config.get("vdom", "root")
        self.verify_ssl = config.get("verify_ssl", False)
        self.timeout = config.get("timeout", 30)
        self.endpoints = config.get("endpoints", self.DEFAULT_ENDPOINTS)
        
        self._session: Optional[requests.Session] = None
        self._csrf_token: Optional[str] = None
    
    def _get_session(self) -> requests.Session:
        if self._session:
            return self._session
        
        self._session = requests.Session()
        self._session.verify = self.verify_ssl
        
        if self.auth_type == "api_key":
            # API key is passed as query parameter
            pass  # Added per-request
        elif self.auth_type == "session":
            # Session-based login
            resp = self._session.post(
                f"{self.base_url}/logincheck",
                data={"username": self.username, "secretkey": self.password},
                timeout=self.timeout
            )
            # Get CSRF token from cookies
            for cookie in self._session.cookies:
                if cookie.name == "ccsrftoken":
                    self._csrf_token = cookie.value.strip('"')
                    self._session.headers["X-CSRFTOKEN"] = self._csrf_token
                    break
        
        return self._session
    
    def _api_get(self, path: str) -> dict:
        """Execute API GET request."""
        session = self._get_session()
        
        params = {"vdom": self.vdom}
        if self.auth_type == "api_key":
            params["access_token"] = self.api_key
        
        resp = session.get(
            f"{self.base_url}{path}",
            params=params,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()
    
    def fetch_config(self, device_id: str = "") -> FetchResult:
        """Fetch configuration sections from FortiGate."""
        try:
            config = {}
            for ep in self.endpoints:
                name = ep["name"]
                path = ep["path"]
                try:
                    data = self._api_get(path)
                    config[name] = data.get("results", data)
                except Exception as e:
                    logger.warning(f"FortiGate endpoint '{name}' failed: {e}")
                    config[name] = {"error": str(e)}
            
            return FetchResult(
                success=True,
                config=config,
                format="json",
                metadata={"source": "fortigate", "vdom": self.vdom}
            )
        except Exception as e:
            return FetchResult(success=False, error=str(e))
    
    def list_devices(self) -> list[str]:
        """List VDOMs as 'devices'."""
        try:
            data = self._api_get("/api/v2/cmdb/system/vdom")
            vdoms = data.get("results", [])
            return [v.get("name", "") for v in vdoms]
        except Exception:
            return [self.vdom]
    
    def test_connection(self) -> tuple[bool, str]:
        try:
            data = self._api_get("/api/v2/cmdb/system/global")
            results = data.get("results", {})
            # FortiOS may return results as list or dict depending on version
            if isinstance(results, list):
                hostname = results[0].get("hostname", "unknown") if results else "unknown"
            else:
                hostname = results.get("hostname", "unknown")
            return True, f"Connected to FortiGate: {hostname}"
        except Exception as e:
            return False, str(e)
    
    def close(self):
        if self._session:
            if self.auth_type == "session":
                try:
                    self._session.post(f"{self.base_url}/logout", timeout=5)
                except Exception:
                    pass
            self._session.close()
            self._session = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  UserGate UTM REST API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class UserGateProvider(ConfigSourceProvider):
    """
    UserGate UTM REST API (v5/v6/v7).
    
    Token-based authentication via /api/v1/auth.
    
    Connection params:
    {
        "base_url": "https://usergate.local:8001",
        "username": "admin",
        "password": "...",
        "verify_ssl": false,
        "timeout": 30,
        
        "endpoints": [
            {"name": "firewall-rules", "path": "/api/v1/firewall/rules"},
            {"name": "nat-rules", "path": "/api/v1/firewall/nat-rules"},
            {"name": "zones", "path": "/api/v1/network/zones"},
            {"name": "interfaces", "path": "/api/v1/network/interfaces"}
        ]
    }
    """
    
    SOURCE_TYPE = "usergate"
    
    DEFAULT_ENDPOINTS = [
        {"name": "firewall-rules", "path": "/api/v1/firewall/rules"},
        {"name": "nat-rules", "path": "/api/v1/firewall/nat-rules"},
        {"name": "content-filtering", "path": "/api/v1/content-filtering/rules"},
        {"name": "zones", "path": "/api/v1/network/zones"},
        {"name": "interfaces", "path": "/api/v1/network/interfaces"},
        {"name": "gateways", "path": "/api/v1/network/gateways"},
        {"name": "dns-servers", "path": "/api/v1/network/dns"},
        {"name": "users", "path": "/api/v1/users/users"},
        {"name": "user-groups", "path": "/api/v1/users/groups"},
        {"name": "ssl-profiles", "path": "/api/v1/security/ssl-profiles"},
        {"name": "ips-profiles", "path": "/api/v1/security/ips-profiles"},
        {"name": "antivirus", "path": "/api/v1/security/antivirus"},
    ]
    
    def __init__(self, config: dict):
        self.base_url = config.get("base_url", "").rstrip("/")
        self.username = config.get("username", "admin")
        self.password = config.get("password", "")
        self.verify_ssl = config.get("verify_ssl", False)
        self.timeout = config.get("timeout", 30)
        self.endpoints = config.get("endpoints", self.DEFAULT_ENDPOINTS)
        
        self._session: Optional[requests.Session] = None
        self._token: Optional[str] = None
    
    def _login(self):
        """Authenticate and get auth token."""
        self._session = requests.Session()
        self._session.verify = self.verify_ssl
        
        resp = self._session.post(
            f"{self.base_url}/api/v1/auth",
            json={"username": self.username, "password": self.password},
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        
        self._token = data.get("token") or data.get("auth_token") or data.get("access_token")
        if not self._token:
            raise RuntimeError("UserGate login failed: no token in response")
        
        self._session.headers["Authorization"] = f"Bearer {self._token}"
        logger.info("UserGate API login successful")
    
    def _api_get(self, path: str) -> dict:
        if not self._token:
            self._login()
        
        resp = self._session.get(
            f"{self.base_url}{path}",
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()
    
    def fetch_config(self, device_id: str = "") -> FetchResult:
        try:
            self._login()
            
            config = {}
            for ep in self.endpoints:
                name = ep["name"]
                path = ep["path"]
                try:
                    data = self._api_get(path)
                    config[name] = data.get("items", data.get("results", data))
                except Exception as e:
                    logger.warning(f"UserGate endpoint '{name}' failed: {e}")
                    config[name] = {"error": str(e)}
            
            return FetchResult(
                success=True,
                config=config,
                format="json",
                metadata={"source": "usergate"}
            )
        except Exception as e:
            return FetchResult(success=False, error=str(e))
    
    def list_devices(self) -> list[str]:
        return ["self"]
    
    def test_connection(self) -> tuple[bool, str]:
        try:
            self._login()
            return True, "UserGate API connected successfully"
        except Exception as e:
            return False, str(e)
    
    def close(self):
        if self._session:
            try:
                self._session.post(f"{self.base_url}/api/v1/auth/logout", timeout=5)
            except Exception:
                pass
            self._session.close()
            self._session = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Palo Alto PAN-OS XML API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PaloAltoProvider(ConfigSourceProvider):
    """
    Palo Alto PAN-OS XML API.
    
    Connection params:
    {
        "base_url": "https://fw.local",
        "api_key": "your-api-key",
        "verify_ssl": false,
        "timeout": 30,
        "config_format": "xml",  // "xml" or "json" (PAN-OS 9.0+)
        
        // XPath queries to fetch (PAN-OS config tree)
        "xpaths": [
            "/config/devices/entry/vsys/entry/rulebase/security",
            "/config/devices/entry/vsys/entry/rulebase/nat",
            "/config/devices/entry/deviceconfig/system",
            "/config/shared"
        ]
    }
    """
    
    SOURCE_TYPE = "paloalto"
    
    DEFAULT_XPATHS = [
        "/config/devices/entry/vsys/entry/rulebase/security",
        "/config/devices/entry/vsys/entry/rulebase/nat",
        "/config/devices/entry/deviceconfig/system",
        "/config/devices/entry/deviceconfig/setting",
        "/config/devices/entry/vsys/entry/profiles",
        "/config/devices/entry/vsys/entry/address",
        "/config/devices/entry/vsys/entry/service",
        "/config/devices/entry/vsys/entry/zone",
        "/config/shared",
    ]
    
    def __init__(self, config: dict):
        self.base_url = config.get("base_url", "").rstrip("/")
        self.api_key = config.get("api_key", "")
        self.verify_ssl = config.get("verify_ssl", False)
        self.timeout = config.get("timeout", 30)
        self.config_format = config.get("config_format", "xml")
        self.xpaths = config.get("xpaths", self.DEFAULT_XPATHS)
        self.rest_api_version = config.get("rest_api_version", "v10.1")
        
        self._session: Optional[requests.Session] = None
    
    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.verify = self.verify_ssl
        return self._session
    
    def _api_request(self, params: dict) -> requests.Response:
        """Execute PAN-OS API request."""
        params["key"] = self.api_key
        resp = self.session.get(
            f"{self.base_url}/api/",
            params=params,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp
    
    def fetch_config(self, device_id: str = "") -> FetchResult:
        """Fetch configuration sections via XPath queries."""
        try:
            if self.config_format == "json":
                return self._fetch_json()
            else:
                return self._fetch_xml()
        except Exception as e:
            return FetchResult(success=False, error=str(e))
    
    def _fetch_xml(self) -> FetchResult:
        """Fetch as XML (default)."""
        sections = []
        
        for xpath in self.xpaths:
            resp = self._api_request({
                "type": "config",
                "action": "get",
                "xpath": xpath,
            })
            section_name = xpath.rsplit("/", 1)[-1]
            sections.append(f"<!-- {section_name} : {xpath} -->\n{resp.text}")
        
        combined = "\n\n".join(sections)
        
        return FetchResult(
            success=True,
            config=combined,
            format="xml",
            metadata={"source": "paloalto", "xpaths": len(self.xpaths)}
        )
    
    def _fetch_json(self) -> FetchResult:
        """Fetch as JSON (PAN-OS 9.0+ REST API)."""
        config = {}
        
        for xpath in self.xpaths:
            try:
                # REST API URL format
                rest_path = xpath.replace("/config/", "").replace("/entry", "")
                resp = self.session.get(
                    f"{self.base_url}/restapi/{self.rest_api_version}/Objects/{rest_path}",
                    params={"key": self.api_key},
                    timeout=self.timeout
                )
                resp.raise_for_status()
                section_name = xpath.rsplit("/", 1)[-1]
                config[section_name] = resp.json()
            except Exception as e:
                config[xpath] = {"error": str(e)}
        
        return FetchResult(
            success=True,
            config=config,
            format="json",
            metadata={"source": "paloalto"}
        )
    
    def list_devices(self) -> list[str]:
        """List managed devices (Panorama) or return self."""
        try:
            resp = self._api_request({
                "type": "op",
                "cmd": "<show><devices><connected></connected></devices></show>"
            })
            # Parse XML for device list
            from xml.etree import ElementTree as ET
            root = ET.fromstring(resp.text)
            devices = []
            for entry in root.findall(".//entry"):
                name = entry.findtext("hostname", "")
                if name:
                    devices.append(name)
            return devices if devices else ["self"]
        except Exception:
            return ["self"]
    
    def test_connection(self) -> tuple[bool, str]:
        try:
            resp = self._api_request({
                "type": "op",
                "cmd": "<show><system><info></info></system></show>"
            })
            if "<hostname>" in resp.text:
                from xml.etree import ElementTree as ET
                root = ET.fromstring(resp.text)
                hostname = root.findtext(".//hostname", "unknown")
                return True, f"Connected to PAN-OS: {hostname}"
            return True, "Connected successfully"
        except Exception as e:
            return False, str(e)
    
    def close(self):
        if self._session:
            self._session.close()
            self._session = None
