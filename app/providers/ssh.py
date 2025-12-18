"""SSH Provider - fetch configs directly from devices via SSH."""
import logging
from typing import Optional

from app.providers.base import ConfigSourceProvider, FetchResult

logger = logging.getLogger(__name__)


class SSHProvider(ConfigSourceProvider):
    """
    Provider for fetching configurations via SSH (using Netmiko).
    
    Connection params:
    {
        "device_type": "cisco_ios",  # Netmiko device type
        "username": "admin",
        "password": "...",  # or use key_file
        "key_file": "/path/to/key",
        "port": 22,
        "command": "show running-config",
        "timeout": 30
    }
    """
    
    DEVICE_TYPE_MAP = {
        "cisco_ios": "cisco_ios",
        "cisco_xe": "cisco_xe",
        "cisco_nxos": "cisco_nxos",
        "eltex_esr": "eltex",
        "huawei": "huawei",
        "juniper": "juniper_junos",
    }
    
    def __init__(
        self,
        device_type: str,
        username: str,
        password: Optional[str] = None,
        key_file: Optional[str] = None,
        port: int = 22,
        command: str = "show running-config",
        timeout: int = 30,
        devices: list[str] = None,
        ssh_config_file: Optional[str] = None
    ):
        self.device_type = self.DEVICE_TYPE_MAP.get(device_type, device_type)
        self.username = username
        self.password = password
        self.key_file = key_file
        self.port = port
        self.command = command
        self.timeout = timeout
        self.devices = devices or []
        self.ssh_config_file = ssh_config_file
    
    def test_connection(self) -> tuple[bool, str]:
        """Test SSH connection to first device."""
        if not self.devices:
            return False, "No devices configured"
        
        result = self.fetch_config(self.devices[0])
        if result.success:
            return True, f"Successfully connected to {self.devices[0]}"
        return False, f"Connection failed: {result.error}"
    
    def fetch_config(self, device_id: str) -> FetchResult:
        """Fetch running config from device via SSH."""
        try:
            from netmiko import ConnectHandler
        except ImportError:
            return FetchResult(
                success=False,
                config=None,
                error="netmiko is not installed"
            )
        
        device_params = {
            "device_type": self.device_type,
            "host": device_id,
            "username": self.username,
            "port": self.port,
            "timeout": self.timeout,
        }
        
        if self.password:
            device_params["password"] = self.password
        if self.key_file:
            device_params["key_file"] = self.key_file
        
        # Proxy / Bastion support
        if self.ssh_config_file:
            device_params["ssh_config_file"] = self.ssh_config_file
        
        # Advanced: Allow passing an existing socket/proxy command if configured in subclass/externally
        if hasattr(self, "sock") and self.sock:
            device_params["sock"] = self.sock
            
        try:
            with ConnectHandler(**device_params) as conn:
                output = conn.send_command(self.command)
                
                return FetchResult(
                    success=True,
                    config=output,
                    metadata={
                        "device": device_id,
                        "command": self.command,
                        "device_type": self.device_type
                    }
                )
                
        except Exception as e:
            logger.error(f"SSH error for {device_id}: {e}")
            return FetchResult(
                success=False,
                config=None,
                error=str(e)
            )
    
    def list_available_devices(self) -> list[str]:
        """Return configured list of devices."""
        return self.devices.copy()
    
    def add_device(self, device_id: str):
        """Add device to the list."""
        if device_id not in self.devices:
            self.devices.append(device_id)
    
    def remove_device(self, device_id: str):
        """Remove device from the list."""
        if device_id in self.devices:
            self.devices.remove(device_id)
