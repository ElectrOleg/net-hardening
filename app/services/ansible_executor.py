"""Remote Ansible Executor - Execute playbooks on remote servers.

Supports:
1. AWX/Ansible Tower API
2. Direct SSH execution on Ansible control node
3. Ansible Runner API (if available)
"""
import logging
import json
from typing import Optional
from dataclasses import dataclass
from enum import Enum

import requests

logger = logging.getLogger(__name__)


class ExecutorType(str, Enum):
    AWX = "awx"
    SSH = "ssh"
    LOCAL = "local"


@dataclass
class ExecutionResult:
    """Result of playbook execution."""
    success: bool
    job_id: Optional[str] = None
    status: str = "unknown"
    output: Optional[str] = None
    error: Optional[str] = None
    url: Optional[str] = None  # Link to job in AWX/Tower


class AWXExecutor:
    """
    Execute playbooks via AWX/Ansible Tower API.
    
    Requires:
    - AWX_URL: Base URL of AWX/Tower
    - AWX_TOKEN: OAuth2 token or personal access token
    - AWX_PROJECT_ID: ID of the project in AWX
    """
    
    def __init__(self, config: dict):
        self.base_url = config.get("url", "").rstrip("/")
        self.token = config.get("token", "")
        self.project_id = config.get("project_id")
        self.inventory_id = config.get("inventory_id")
        self.verify_ssl = config.get("verify_ssl", True)
    
    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
    
    def launch_job_template(
        self, 
        template_id: int, 
        extra_vars: Optional[dict] = None,
        limit: Optional[str] = None
    ) -> ExecutionResult:
        """Launch an existing job template in AWX."""
        url = f"{self.base_url}/api/v2/job_templates/{template_id}/launch/"
        
        payload = {}
        if extra_vars:
            payload["extra_vars"] = json.dumps(extra_vars)
        if limit:
            payload["limit"] = limit
        
        try:
            response = requests.post(
                url,
                headers=self.headers,
                json=payload,
                verify=self.verify_ssl,
                timeout=30
            )
            
            if response.status_code in (200, 201):
                data = response.json()
                job_id = str(data.get("id", ""))
                return ExecutionResult(
                    success=True,
                    job_id=job_id,
                    status="pending",
                    url=f"{self.base_url}/#/jobs/playbook/{job_id}"
                )
            else:
                return ExecutionResult(
                    success=False,
                    error=f"AWX error: {response.status_code} - {response.text}"
                )
                
        except Exception as e:
            return ExecutionResult(success=False, error=str(e))
    
    def create_and_launch_adhoc(
        self, 
        playbook_content: str,
        inventory_id: Optional[int] = None
    ) -> ExecutionResult:
        """
        Create a temporary project and launch playbook.
        Note: This requires AWX admin permissions.
        For most cases, use pre-created job templates instead.
        """
        # For security, we recommend using pre-created job templates
        # rather than ad-hoc playbook execution
        return ExecutionResult(
            success=False,
            error="Ad-hoc playbook execution not supported. Use job templates."
        )
    
    def get_job_status(self, job_id: str) -> ExecutionResult:
        """Get status of a running job."""
        url = f"{self.base_url}/api/v2/jobs/{job_id}/"
        
        try:
            response = requests.get(
                url,
                headers=self.headers,
                verify=self.verify_ssl,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return ExecutionResult(
                    success=data.get("status") == "successful",
                    job_id=job_id,
                    status=data.get("status", "unknown"),
                    url=f"{self.base_url}/#/jobs/playbook/{job_id}"
                )
            else:
                return ExecutionResult(
                    success=False,
                    job_id=job_id,
                    error=f"Failed to get job status: {response.status_code}"
                )
                
        except Exception as e:
            return ExecutionResult(success=False, job_id=job_id, error=str(e))


class SSHAnsibleExecutor:
    """
    Execute playbooks on a remote Ansible control node via SSH.
    
    The playbook is uploaded to the remote server and executed there.
    """
    
    def __init__(self, config: dict):
        self.host = config.get("host")
        self.username = config.get("username", "ansible")
        self.key_file = config.get("key_file")
        self.password = config.get("password")
        self.playbook_dir = config.get("playbook_dir", "/tmp/hcs_playbooks")
        self.inventory_file = config.get("inventory_file", "/etc/ansible/hosts")
    
    def execute(
        self, 
        playbook_content: str,
        playbook_name: str = "remediation.yml",
        extra_vars: Optional[dict] = None,
        limit: Optional[str] = None,
        check_mode: bool = False
    ) -> ExecutionResult:
        """Execute playbook on remote Ansible server via SSH."""
        try:
            from netmiko import ConnectHandler
        except ImportError:
            return ExecutionResult(
                success=False,
                error="netmiko not installed. pip install netmiko"
            )
        
        device = {
            "device_type": "linux",
            "host": self.host,
            "username": self.username,
        }
        
        if self.key_file:
            device["use_keys"] = True
            device["key_file"] = self.key_file
        elif self.password:
            device["password"] = self.password
        
        try:
            with ConnectHandler(**device) as conn:
                # Create directory
                conn.send_command(f"mkdir -p {self.playbook_dir}")
                
                # Upload playbook (via echo for simplicity)
                # For production, use SCP or SFTP
                playbook_path = f"{self.playbook_dir}/{playbook_name}"
                
                # Escape for shell
                escaped_content = playbook_content.replace("'", "'\\''")
                conn.send_command(f"cat > {playbook_path} << 'HCSEOF'\n{playbook_content}\nHCSEOF")
                
                # Build ansible-playbook command
                cmd = f"ansible-playbook -i {self.inventory_file} {playbook_path}"
                
                if extra_vars:
                    vars_json = json.dumps(extra_vars).replace('"', '\\"')
                    cmd += f" --extra-vars '{vars_json}'"
                
                if limit:
                    cmd += f" --limit '{limit}'"
                
                if check_mode:
                    cmd += " --check"
                
                # Execute
                logger.info(f"Executing on {self.host}: {cmd}")
                output = conn.send_command(cmd, read_timeout=300)
                
                # Check for success (simplified)
                success = "failed=0" in output and "unreachable=0" in output
                
                return ExecutionResult(
                    success=success,
                    status="completed",
                    output=output
                )
                
        except Exception as e:
            logger.exception(f"SSH execution failed: {e}")
            return ExecutionResult(success=False, error=str(e))


class RemoteAnsibleExecutor:
    """
    Unified interface for remote Ansible execution.
    
    Automatically selects the appropriate executor based on configuration.
    """
    
    def __init__(self, config: Optional[dict] = None):
        self.config = config or self._load_from_env()
        self.executor_type = ExecutorType(self.config.get("type", "local"))
        self._executor = self._create_executor()
    
    def _load_from_env(self) -> dict:
        """Load configuration from environment variables."""
        import os
        
        config = {"type": os.environ.get("ANSIBLE_EXECUTOR_TYPE", "local")}
        
        if config["type"] == "awx":
            config.update({
                "url": os.environ.get("AWX_URL", ""),
                "token": os.environ.get("AWX_TOKEN", ""),
                "project_id": os.environ.get("AWX_PROJECT_ID"),
                "inventory_id": os.environ.get("AWX_INVENTORY_ID"),
            })
        elif config["type"] == "ssh":
            config.update({
                "host": os.environ.get("ANSIBLE_HOST", ""),
                "username": os.environ.get("ANSIBLE_USER", "ansible"),
                "key_file": os.environ.get("ANSIBLE_KEY_FILE"),
                "password": os.environ.get("ANSIBLE_PASSWORD"),
                "playbook_dir": os.environ.get("ANSIBLE_PLAYBOOK_DIR", "/tmp/hcs"),
                "inventory_file": os.environ.get("ANSIBLE_INVENTORY", "/etc/ansible/hosts"),
            })
        
        return config
    
    def _create_executor(self):
        """Create the appropriate executor instance."""
        if self.executor_type == ExecutorType.AWX:
            return AWXExecutor(self.config)
        elif self.executor_type == ExecutorType.SSH:
            return SSHAnsibleExecutor(self.config)
        else:
            return None  # Local mode - just return playbook
    
    def execute(
        self,
        playbook_content: str,
        playbook_name: str = "remediation.yml",
        extra_vars: Optional[dict] = None,
        limit: Optional[str] = None,
        check_mode: bool = False
    ) -> ExecutionResult:
        """Execute playbook using configured method."""
        if self.executor_type == ExecutorType.LOCAL:
            return ExecutionResult(
                success=True,
                status="generated",
                output=playbook_content,
                error="Local mode: playbook generated but not executed"
            )
        
        if self.executor_type == ExecutorType.AWX:
            # AWX requires pre-configured job templates
            return ExecutionResult(
                success=False,
                error="AWX execution requires job template ID. Use execute_job_template() instead."
            )
        
        if self.executor_type == ExecutorType.SSH:
            return self._executor.execute(
                playbook_content,
                playbook_name,
                extra_vars,
                limit,
                check_mode
            )
        
        return ExecutionResult(success=False, error="Unknown executor type")
    
    def execute_job_template(
        self,
        template_id: int,
        extra_vars: Optional[dict] = None,
        limit: Optional[str] = None
    ) -> ExecutionResult:
        """Execute AWX job template (AWX mode only)."""
        if self.executor_type != ExecutorType.AWX:
            return ExecutionResult(
                success=False,
                error="Job template execution only available in AWX mode"
            )
        
        return self._executor.launch_job_template(template_id, extra_vars, limit)
    
    def get_job_status(self, job_id: str) -> ExecutionResult:
        """Get job status (AWX mode only)."""
        if self.executor_type == ExecutorType.AWX:
            return self._executor.get_job_status(job_id)
        
        return ExecutionResult(
            success=False,
            error="Job status tracking only available in AWX mode"
        )


# Convenience function
def get_ansible_executor(config: Optional[dict] = None) -> RemoteAnsibleExecutor:
    """Get configured Ansible executor."""
    return RemoteAnsibleExecutor(config)
