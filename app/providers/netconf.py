"""NETCONF Provider - Fetch configurations via NETCONF/YANG.

Supports modern network devices with NETCONF interface:
- Juniper (JUNOS)
- Cisco (IOS-XE, IOS-XR, NX-OS)
- Arista (EOS)
- Huawei (VRP)
- Nokia
"""
import logging
from typing import Optional
from xml.etree import ElementTree as ET

from app.providers.base import ConfigSourceProvider, FetchResult

logger = logging.getLogger(__name__)


class NetconfProvider(ConfigSourceProvider):
    """
    NETCONF provider for modern network devices.
    
    Uses ncclient library for NETCONF communication.
    
    Config parameters:
        host: Device hostname/IP
        port: NETCONF port (default: 830)
        username: SSH username
        password: SSH password (or use key_filename)
        key_filename: Path to SSH private key
        device_params: Device-specific parameters (e.g., {"name": "junos"})
        hostkey_verify: Verify host key (default: False)
        timeout: Connection timeout in seconds
    """
    
    SOURCE_TYPE = "netconf"
    
    # Device params for different vendors
    DEVICE_PARAMS = {
        "juniper": {"name": "junos"},
        "cisco_xe": {"name": "csr"},
        "cisco_xr": {"name": "iosxr"},
        "cisco_nxos": {"name": "nexus"},
        "arista": {"name": "default"},
        "huawei": {"name": "huawei"},
        "nokia": {"name": "sros"},
    }
    
    def __init__(self, config: dict):
        self.host = config.get("host")
        self.port = config.get("port", 830)
        self.username = config.get("username")
        self.password = config.get("password")
        self.key_filename = config.get("key_filename")
        self.timeout = config.get("timeout", 30)
        self.hostkey_verify = config.get("hostkey_verify", False)
        
        # Device-specific params
        vendor = config.get("vendor", "default")
        self.device_params = config.get("device_params") or self.DEVICE_PARAMS.get(vendor, {})
        
        # Filter for get-config (optional)
        self.filter_xml = config.get("filter")
        self.datastore = config.get("datastore", "running")
        
        self._manager = None
    
    def _connect(self):
        """Establish NETCONF connection."""
        try:
            from ncclient import manager
        except ImportError:
            raise ImportError("ncclient not installed. pip install ncclient")
        
        connect_params = {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": self.timeout,
            "hostkey_verify": self.hostkey_verify,
        }
        
        if self.password:
            connect_params["password"] = self.password
        if self.key_filename:
            connect_params["key_filename"] = self.key_filename
        if self.device_params:
            connect_params["device_params"] = self.device_params
        
        self._manager = manager.connect(**connect_params)
        return self._manager
    
    def fetch_config(self, device_id: str) -> FetchResult:
        """
        Fetch running configuration via NETCONF.
        
        Returns XML configuration as string.
        """
        try:
            mgr = self._connect()
            
            if self.filter_xml:
                # Use subtree filter
                config = mgr.get_config(
                    source=self.datastore, 
                    filter=("subtree", self.filter_xml)
                )
            else:
                # Get full config
                config = mgr.get_config(source=self.datastore)
            
            # Convert to string
            config_xml = config.data_xml if hasattr(config, 'data_xml') else str(config)
            
            return FetchResult(
                success=True,
                config=config_xml,
                format="xml"
            )
            
        except Exception as e:
            logger.exception(f"NETCONF fetch failed for {device_id}: {e}")
            return FetchResult(
                success=False,
                error=str(e)
            )
        finally:
            self._disconnect()
    
    def get_operational_data(self, filter_xml: str) -> FetchResult:
        """
        Get operational data (state) via NETCONF get.
        
        Args:
            filter_xml: XML filter for subtree filtering
        """
        try:
            mgr = self._connect()
            
            result = mgr.get(filter=("subtree", filter_xml))
            data_xml = result.data_xml if hasattr(result, 'data_xml') else str(result)
            
            return FetchResult(
                success=True,
                config=data_xml,
                format="xml"
            )
            
        except Exception as e:
            logger.exception(f"NETCONF get failed: {e}")
            return FetchResult(success=False, error=str(e))
        finally:
            self._disconnect()
    
    def rpc(self, rpc_xml: str) -> FetchResult:
        """
        Execute raw RPC command.
        
        Args:
            rpc_xml: RPC XML to execute
        """
        try:
            mgr = self._connect()
            
            result = mgr.dispatch(ET.fromstring(rpc_xml))
            result_xml = result.xml if hasattr(result, 'xml') else str(result)
            
            return FetchResult(
                success=True,
                config=result_xml,
                format="xml"
            )
            
        except Exception as e:
            logger.exception(f"NETCONF RPC failed: {e}")
            return FetchResult(success=False, error=str(e))
        finally:
            self._disconnect()
    
    def list_devices(self) -> list[str]:
        """NETCONF provider connects to single device."""
        return [self.host] if self.host else []
    
    def test_connection(self) -> tuple[bool, str]:
        """Test NETCONF connection."""
        try:
            mgr = self._connect()
            # Get server capabilities
            caps = list(mgr.server_capabilities)
            self._disconnect()
            return True, f"Connected. Server has {len(caps)} capabilities."
        except Exception as e:
            return False, str(e)
    
    def _disconnect(self):
        """Close NETCONF connection."""
        if self._manager:
            try:
                self._manager.close_session()
            except Exception:
                pass
            self._manager = None
    
    def cleanup(self):
        """Cleanup resources."""
        self._disconnect()
