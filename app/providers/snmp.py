"""SNMP Provider - Fetch data via SNMP.

Supports:
- SNMPv2c and SNMPv3
- GET, GET-NEXT, WALK operations
- Common OIDs for network devices
"""
import logging
from typing import Optional

from app.providers.base import ConfigSourceProvider, FetchResult

logger = logging.getLogger(__name__)


class SNMPProvider(ConfigSourceProvider):
    """
    SNMP provider for monitoring and configuration data.
    
    Uses pysnmp library for SNMP communication.
    
    Config parameters:
        host: Device hostname/IP
        port: SNMP port (default: 161)
        version: SNMP version ("2c" or "3")
        
        # For SNMPv2c:
        community: Community string
        
        # For SNMPv3:
        username: Security name
        auth_protocol: "MD5" or "SHA"
        auth_password: Authentication password
        priv_protocol: "DES" or "AES"
        priv_password: Privacy password
        
        # What to fetch:
        oids: List of OIDs to get
        walk_oid: OID subtree to walk
        timeout: Request timeout (default: 5)
        retries: Number of retries (default: 3)
    """
    
    SOURCE_TYPE = "snmp"
    
    # Common OIDs
    COMMON_OIDS = {
        "sysDescr": "1.3.6.1.2.1.1.1.0",
        "sysName": "1.3.6.1.2.1.1.5.0",
        "sysLocation": "1.3.6.1.2.1.1.6.0",
        "sysUpTime": "1.3.6.1.2.1.1.3.0",
        "ifTable": "1.3.6.1.2.1.2.2",
        "ipAddrTable": "1.3.6.1.2.1.4.20",
    }
    
    def __init__(self, config: dict):
        self.host = config.get("host")
        self.port = config.get("port", 161)
        self.version = config.get("version", "2c")
        self.timeout = config.get("timeout", 5)
        self.retries = config.get("retries", 3)
        
        # SNMPv2c
        self.community = config.get("community", "public")
        
        # SNMPv3
        self.username = config.get("username")
        self.auth_protocol = config.get("auth_protocol", "SHA")
        self.auth_password = config.get("auth_password")
        self.priv_protocol = config.get("priv_protocol", "AES")
        self.priv_password = config.get("priv_password")
        
        # What to fetch
        self.oids = config.get("oids", ["sysDescr", "sysName"])
        self.walk_oid = config.get("walk_oid")
    
    def fetch_config(self, device_id: str) -> FetchResult:
        """
        Fetch SNMP data and return as JSON structure.
        """
        try:
            from pysnmp.hlapi import (
                SnmpEngine, CommunityData, UsmUserData,
                UdpTransportTarget, ContextData, ObjectType, ObjectIdentity,
                getCmd, nextCmd,
                usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol,
                usmDESPrivProtocol, usmAesCfb128Protocol
            )
        except ImportError:
            return FetchResult(
                success=False,
                error="pysnmp not installed. pip install pysnmp"
            )
        
        # Build auth data
        if self.version == "3":
            auth_proto = usmHMACSHAAuthProtocol if self.auth_protocol == "SHA" else usmHMACMD5AuthProtocol
            priv_proto = usmAesCfb128Protocol if self.priv_protocol == "AES" else usmDESPrivProtocol
            
            auth_data = UsmUserData(
                self.username,
                self.auth_password,
                self.priv_password,
                authProtocol=auth_proto,
                privProtocol=priv_proto
            )
        else:
            auth_data = CommunityData(self.community)
        
        transport = UdpTransportTarget(
            (self.host, self.port),
            timeout=self.timeout,
            retries=self.retries
        )
        
        results = {}
        
        # Resolve OID names to values
        oid_objects = []
        for oid in self.oids:
            if oid in self.COMMON_OIDS:
                oid_objects.append(ObjectType(ObjectIdentity(self.COMMON_OIDS[oid])))
            else:
                oid_objects.append(ObjectType(ObjectIdentity(oid)))
        
        # Execute GET
        try:
            errorIndication, errorStatus, errorIndex, varBinds = next(
                getCmd(
                    SnmpEngine(),
                    auth_data,
                    transport,
                    ContextData(),
                    *oid_objects
                )
            )
            
            if errorIndication:
                return FetchResult(success=False, error=str(errorIndication))
            
            if errorStatus:
                return FetchResult(
                    success=False,
                    error=f"SNMP error: {errorStatus.prettyPrint()}"
                )
            
            for varBind in varBinds:
                oid, value = varBind
                results[str(oid)] = str(value)
            
        except Exception as e:
            return FetchResult(success=False, error=str(e))
        
        # Walk if requested
        if self.walk_oid:
            walk_results = self._walk(auth_data, transport, self.walk_oid)
            results["walk"] = walk_results
        
        import json
        return FetchResult(
            success=True,
            config=json.dumps(results, indent=2),
            format="json"
        )
    
    def _walk(self, auth_data, transport, oid: str) -> dict:
        """Perform SNMP walk."""
        from pysnmp.hlapi import (
            SnmpEngine, ContextData, ObjectType, ObjectIdentity, nextCmd
        )
        
        results = {}
        
        for errorIndication, errorStatus, errorIndex, varBinds in nextCmd(
            SnmpEngine(),
            auth_data,
            transport,
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False
        ):
            if errorIndication or errorStatus:
                break
            
            for varBind in varBinds:
                oid_str, value = varBind
                results[str(oid_str)] = str(value)
        
        return results
    
    def list_devices(self) -> list[str]:
        return [self.host] if self.host else []
    
    # Alias for backward compat
    list_available_devices = list_devices
    
    def test_connection(self) -> tuple[bool, str]:
        """Test SNMP connectivity."""
        result = self.fetch_config(self.host)
        if result.success:
            return True, "SNMP connection successful"
        return False, result.error or "Connection failed"
    
    def close(self):
        """Clean up resources."""
        pass
