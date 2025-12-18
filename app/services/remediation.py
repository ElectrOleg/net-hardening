"""Remediation Service - Ansible playbook generation."""
import logging
from typing import Optional
from dataclasses import dataclass
import json
import yaml

from app.models import Rule, Result

logger = logging.getLogger(__name__)


@dataclass
class RemediationTask:
    """Single remediation task."""
    device_id: str
    rule_id: str
    rule_title: str
    vendor_code: str
    commands: list[str]
    description: str


class RemediationService:
    """Service for generating remediation playbooks."""
    
    # Vendor to Ansible connection mapping
    VENDOR_CONNECTION_MAP = {
        "cisco_ios": {"network_os": "cisco.ios.ios", "module": "cisco.ios.ios_config"},
        "cisco_nxos": {"network_os": "cisco.nxos.nxos", "module": "cisco.nxos.nxos_config"},
        "cisco_asa": {"network_os": "cisco.asa.asa", "module": "cisco.asa.asa_config"},
        "eltex_esr": {"network_os": "community.network.eltex_esr", "module": "community.network.eltex_command"},
        "eltex_mes": {"network_os": "community.network.eltex", "module": "community.network.cli_config"},
        "juniper_junos": {"network_os": "junipernetworks.junos.junos", "module": "junipernetworks.junos.junos_config"},
        "arista_eos": {"network_os": "arista.eos.eos", "module": "arista.eos.eos_config"},
        "huawei_vrp": {"network_os": "community.network.ce", "module": "community.network.ce_config"},
        # API-based (non-network)
        "usergate": {"type": "api"},
        "checkpoint": {"type": "api"},
        "paloalto": {"type": "api"},
        "fortigate": {"type": "api"},
    }
    
    def generate_playbook_for_scan(
        self, 
        scan_id: str, 
        device_id: Optional[str] = None
    ) -> tuple[str, list[RemediationTask]]:
        """
        Generate Ansible playbook for failed checks in a scan.
        
        Returns:
            Tuple of (playbook_yaml, list_of_tasks)
        """
        results = Result.query.filter_by(scan_id=scan_id, status="FAIL")
        
        if device_id:
            results = results.filter_by(device_id=device_id)
        
        results = results.all()
        
        if not results:
            return "", []
        
        tasks = []
        for result in results:
            if not result.rule or not result.rule.remediation:
                continue
            
            # Parse remediation commands
            commands = self._parse_remediation(result.rule.remediation)
            if not commands:
                continue
            
            tasks.append(RemediationTask(
                device_id=result.device_id,
                rule_id=str(result.rule_id),
                rule_title=result.rule.title,
                vendor_code=result.rule.vendor_code,
                commands=commands,
                description=result.rule.description or ""
            ))
        
        playbook = self._build_playbook(tasks)
        return playbook, tasks
    
    def generate_playbook_for_rule(
        self, 
        rule_id: str, 
        device_ids: list[str]
    ) -> str:
        """Generate playbook for applying single rule to devices."""
        rule = Rule.query.get(rule_id)
        if not rule or not rule.remediation:
            return ""
        
        commands = self._parse_remediation(rule.remediation)
        if not commands:
            return ""
        
        tasks = [
            RemediationTask(
                device_id=device_id,
                rule_id=rule_id,
                rule_title=rule.title,
                vendor_code=rule.vendor_code,
                commands=commands,
                description=rule.description or ""
            )
            for device_id in device_ids
        ]
        
        return self._build_playbook(tasks)
    
    def _parse_remediation(self, remediation: str) -> list[str]:
        """Parse remediation field into list of commands."""
        if not remediation:
            return []
        
        # Try JSON array first
        remediation = remediation.strip()
        if remediation.startswith("["):
            try:
                return json.loads(remediation)
            except json.JSONDecodeError:
                pass
        
        # Split by newlines, filter empty
        lines = [line.strip() for line in remediation.split("\n")]
        return [line for line in lines if line and not line.startswith("#")]
    
    def _build_playbook(self, tasks: list[RemediationTask]) -> str:
        """Build Ansible playbook YAML from tasks."""
        if not tasks:
            return ""
        
        # Group by vendor and device
        vendor_device_tasks = {}
        for task in tasks:
            key = (task.vendor_code, task.device_id)
            if key not in vendor_device_tasks:
                vendor_device_tasks[key] = []
            vendor_device_tasks[key].append(task)
        
        playbook = []
        
        for (vendor_code, device_id), device_tasks in vendor_device_tasks.items():
            vendor_info = self.VENDOR_CONNECTION_MAP.get(vendor_code, {})
            
            if vendor_info.get("type") == "api":
                # API-based device - use uri module
                play = self._build_api_play(device_id, vendor_code, device_tasks)
            else:
                # Network device - use network modules
                play = self._build_network_play(device_id, vendor_code, vendor_info, device_tasks)
            
            playbook.append(play)
        
        return yaml.dump(playbook, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    def _build_network_play(
        self, 
        device_id: str, 
        vendor_code: str,
        vendor_info: dict,
        tasks: list[RemediationTask]
    ) -> dict:
        """Build play for network device."""
        network_os = vendor_info.get("network_os", "")
        module = vendor_info.get("module", "cli_config")
        
        ansible_tasks = []
        
        for task in tasks:
            ansible_tasks.append({
                "name": f"Apply: {task.rule_title}",
                module: {
                    "lines": task.commands
                },
                "tags": [task.rule_id[:8], vendor_code]
            })
        
        # Save config after changes
        if vendor_code.startswith("cisco"):
            ansible_tasks.append({
                "name": "Save configuration",
                module: {
                    "save_when": "modified"
                }
            })
        
        return {
            "name": f"Remediation for {device_id}",
            "hosts": device_id,
            "gather_facts": False,
            "connection": "ansible.netcommon.network_cli",
            "vars": {
                "ansible_network_os": network_os,
                "ansible_become": True,
                "ansible_become_method": "enable"
            },
            "tasks": ansible_tasks
        }
    
    def _build_api_play(
        self, 
        device_id: str, 
        vendor_code: str,
        tasks: list[RemediationTask]
    ) -> dict:
        """Build play for API-based device."""
        ansible_tasks = []
        
        for task in tasks:
            # For API devices, remediation might be JSON
            if task.commands and task.commands[0].startswith("{"):
                # JSON payload for API
                ansible_tasks.append({
                    "name": f"Apply: {task.rule_title}",
                    "ansible.builtin.uri": {
                        "url": f"{{{{ api_base_url }}}}/{{ api_endpoint }}",
                        "method": "POST",
                        "body": task.commands[0],
                        "body_format": "json",
                        "headers": {
                            "Authorization": "Bearer {{ api_token }}"
                        },
                        "validate_certs": False
                    },
                    "tags": [task.rule_id[:8], vendor_code]
                })
            else:
                # CLI-style commands - document them
                ansible_tasks.append({
                    "name": f"TODO: {task.rule_title}",
                    "ansible.builtin.debug": {
                        "msg": f"Manual remediation needed: {'; '.join(task.commands)}"
                    }
                })
        
        return {
            "name": f"API Remediation for {device_id}",
            "hosts": "localhost",
            "gather_facts": False,
            "vars": {
                "target_device": device_id,
                "api_base_url": f"https://{device_id}",
                "api_token": "{{ lookup('env', 'API_TOKEN') }}"
            },
            "tasks": ansible_tasks
        }
    
    def preview_remediation(self, rule_id: str) -> dict:
        """Preview remediation for a rule."""
        rule = Rule.query.get(rule_id)
        if not rule:
            return {"error": "Rule not found"}
        
        commands = self._parse_remediation(rule.remediation) if rule.remediation else []
        vendor_info = self.VENDOR_CONNECTION_MAP.get(rule.vendor_code, {})
        
        return {
            "rule_id": rule_id,
            "rule_title": rule.title,
            "vendor_code": rule.vendor_code,
            "remediation_type": "api" if vendor_info.get("type") == "api" else "network",
            "commands": commands,
            "ansible_module": vendor_info.get("module", "unknown"),
            "sample_task": self._build_sample_task(rule, commands, vendor_info)
        }
    
    def _build_sample_task(self, rule: Rule, commands: list[str], vendor_info: dict) -> dict:
        """Build sample Ansible task for preview."""
        if vendor_info.get("type") == "api":
            return {
                "name": f"Apply: {rule.title}",
                "uri": {
                    "url": "{{ api_url }}",
                    "method": "POST",
                    "body": commands[0] if commands else "{}"
                }
            }
        else:
            module = vendor_info.get("module", "cli_config")
            return {
                "name": f"Apply: {rule.title}",
                module: {
                    "lines": commands
                }
            }


# Singleton
remediation_service = RemediationService()
