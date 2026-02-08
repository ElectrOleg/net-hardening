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
        "password": "...",  // or use key_file
        "key_file": "/path/to/key",
        "port": 22,
        "command": "show running-config",
        "commands": ["show run", "show ip access-lists", "show version"],
        "timeout": 30,
        "devices": ["10.0.0.1", "10.0.0.2"],
        "ssh_config_file": "/path/to/ssh_config",
        "enable_password": "...",  // for enable mode
        "global_delay_factor": 2,  // for slow devices
        
        // Jump/hop server (optional):
        "jump_host": "10.0.0.100",
        "jump_user": "admin",
        "jump_port": 22,
        "jump_password": "...",
        "jump_key_file": "/path/to/jump_key"
    }
    """
    
    # Expanded device type map covering major network vendors
    DEVICE_TYPE_MAP = {
        # Cisco
        "cisco_ios": "cisco_ios",
        "cisco_xe": "cisco_xe",
        "cisco_xr": "cisco_xr",
        "cisco_nxos": "cisco_nxos",
        "cisco_asa": "cisco_asa",
        "cisco_ftd": "cisco_ftd",
        "cisco_wlc": "cisco_wlc_ssh",
        # Juniper
        "juniper": "juniper_junos",
        "juniper_junos": "juniper_junos",
        # Arista
        "arista": "arista_eos",
        "arista_eos": "arista_eos",
        # Huawei
        "huawei": "huawei",
        "huawei_vrp": "huawei_vrpv8",
        # FortiGate
        "fortigate": "fortinet",
        "fortinet": "fortinet",
        "fortios": "fortinet",
        # Palo Alto
        "paloalto": "paloalto_panos",
        "panos": "paloalto_panos",
        # CheckPoint
        "checkpoint": "checkpoint_gaia",
        "checkpoint_gaia": "checkpoint_gaia",
        # UserGate  
        "usergate": "linux",  # UserGate CLI is Linux-like
        # Nokia
        "nokia_sros": "nokia_sros",
        # MikroTik
        "mikrotik": "mikrotik_routeros",
        "routeros": "mikrotik_routeros",
        # Eltex
        "eltex_esr": "eltex",
        "eltex": "eltex",
        # F5
        "f5_ltm": "f5_ltm",
        "f5_tmsh": "f5_tmsh",
        # Linux/generic
        "linux": "linux",
        "generic": "generic",
        # HP / Comware
        "hp_comware": "hp_comware",
        "hp_procurve": "hp_procurve",
        # Dell
        "dell_force10": "dell_force10",
        "dell_os10": "dell_os10",
        # Extreme
        "extreme": "extreme",
        "extreme_exos": "extreme_exos",
        # A10
        "a10": "a10",
        # Ubiquiti
        "ubiquiti_edge": "ubiquiti_edgeswitch",
        "vyos": "vyos",
    }
    
    # Предустановленные команды по типу устройства
    DEFAULT_COMMANDS = {
        "cisco_ios": ["show running-config"],
        "cisco_xe": ["show running-config"],
        "cisco_xr": ["show running-config"],
        "cisco_nxos": ["show running-config"],
        "cisco_asa": ["show running-config"],
        "juniper_junos": ["show configuration | display set"],
        "arista_eos": ["show running-config"],
        "huawei": ["display current-configuration"],
        "fortinet": ["show full-configuration"],
        "paloalto_panos": ["show config running"],
        "checkpoint_gaia": ["clish -c 'show configuration'"],
        "mikrotik_routeros": ["/export"],
        "nokia_sros": ["admin display-config"],
        "linux": ["cat /etc/network/interfaces"],
        "vyos": ["show configuration commands"],
    }
    
    def __init__(self, config: dict):
        device_type = config.get("device_type", "cisco_ios")
        self.device_type = self.DEVICE_TYPE_MAP.get(device_type, device_type)
        self.username = config.get("username", "")
        self.password = config.get("password")
        self.key_file = config.get("key_file")
        self.port = config.get("port", 22)
        self.timeout = config.get("timeout", 30)
        self.devices = config.get("devices", [])
        self.ssh_config_file = config.get("ssh_config_file")
        self.enable_password = config.get("enable_password")
        self.global_delay_factor = config.get("global_delay_factor", 1)
        
        # Multi-command support
        # "commands" takes priority; falls back to "command" → default for device_type
        self.commands = config.get("commands")
        if not self.commands:
            single = config.get("command")
            if single:
                self.commands = [single]
            else:
                self.commands = self.DEFAULT_COMMANDS.get(
                    self.device_type, ["show running-config"]
                )
        
        # Jump/hop server config
        self.jump_host = config.get("jump_host")
        self.jump_user = config.get("jump_user", self.username)
        self.jump_port = config.get("jump_port", 22)
        self.jump_password = config.get("jump_password")
        self.jump_key_file = config.get("jump_key_file", self.key_file)
        
        # Active jump transport (reused across fetch_config calls)
        self._jump_client = None
    
    def _get_jump_channel(self, target_host: str, target_port: int):
        """Create an SSH channel through the jump host to the target device.
        
        Returns a Paramiko channel that can be used as Netmiko's `sock` parameter.
        """
        import paramiko
        
        if self._jump_client is None:
            self._jump_client = paramiko.SSHClient()
            self._jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            connect_kwargs = {
                "hostname": self.jump_host,
                "port": self.jump_port,
                "username": self.jump_user,
                "timeout": self.timeout,
            }
            if self.jump_password:
                connect_kwargs["password"] = self.jump_password
            if self.jump_key_file:
                connect_kwargs["key_filename"] = self.jump_key_file
            
            logger.info(f"Connecting to jump host {self.jump_host}:{self.jump_port}")
            self._jump_client.connect(**connect_kwargs)
        
        # Open a direct-tcpip channel through the jump host to the target
        transport = self._jump_client.get_transport()
        dest_addr = (target_host, target_port)
        local_addr = ("127.0.0.1", 0)
        channel = transport.open_channel("direct-tcpip", dest_addr, local_addr)
        
        return channel
    
    def test_connection(self) -> tuple[bool, str]:
        """Test SSH connection to first device."""
        if not self.devices:
            return False, "No devices configured"
        
        result = self.fetch_config(self.devices[0])
        if result.success:
            return True, f"Successfully connected to {self.devices[0]}"
        return False, f"Connection failed: {result.error}"
    
    def fetch_config(self, device_id: str) -> FetchResult:
        """Fetch config from device via SSH (supports multiple commands).
        
        When multiple commands are configured, each command's output is returned
        as a separate section with a header:
        
            === show running-config ===
            <output>
            === show ip access-lists ===
            <output>
        """
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
            "global_delay_factor": self.global_delay_factor,
        }
        
        if self.password:
            device_params["password"] = self.password
        if self.key_file:
            device_params["key_file"] = self.key_file
        if self.enable_password:
            device_params["secret"] = self.enable_password
        
        # Jump host → create tunnel channel
        if self.jump_host:
            try:
                channel = self._get_jump_channel(device_id, self.port)
                device_params["sock"] = channel
            except Exception as e:
                logger.error(f"Jump host tunnel failed for {device_id}: {e}")
                return FetchResult(
                    success=False,
                    config=None,
                    error=f"Jump host tunnel failed: {e}"
                )
        elif self.ssh_config_file:
            device_params["ssh_config_file"] = self.ssh_config_file
            
        try:
            with ConnectHandler(**device_params) as conn:
                # Enter enable mode if secret is provided
                if self.enable_password:
                    conn.enable()
                
                if len(self.commands) == 1:
                    # Single command → return raw output
                    output = conn.send_command(self.commands[0])
                else:
                    # Multiple commands → sectioned output
                    sections = []
                    for cmd in self.commands:
                        cmd_output = conn.send_command(cmd)
                        sections.append(f"=== {cmd} ===\n{cmd_output}")
                    output = "\n\n".join(sections)
                
                return FetchResult(
                    success=True,
                    config=output,
                    metadata={
                        "device": device_id,
                        "commands": self.commands,
                        "device_type": self.device_type,
                        "via_jump_host": bool(self.jump_host),
                    }
                )
                
        except Exception as e:
            logger.error(f"SSH error for {device_id}: {e}")
            return FetchResult(
                success=False,
                config=None,
                error=str(e)
            )
    
    def list_devices(self) -> list[str]:
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
    
    def close(self):
        """Clean up jump host connection."""
        if self._jump_client:
            try:
                self._jump_client.close()
            except Exception:
                pass
            self._jump_client = None
