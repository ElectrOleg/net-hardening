"""Version Checker - Compare software versions.

Useful for:
- Checking minimum firmware/OS versions
- Ensuring devices are updated
- Compliance with security patches
"""
import logging
import re
from typing import Optional

from app.engine.base import RuleChecker, CheckResult, CheckStatus

logger = logging.getLogger(__name__)


class VersionChecker(RuleChecker):
    """
    Version comparison checker.
    
    Extracts version from config and compares against required version.
    
    Payload structure:
    {
        "pattern": "regex pattern with version group",
        "version_group": 1,  # Regex group containing version (default: 1)
        "operator": "eq|ne|gt|lt|ge|le|in_range",
        "value": "15.2",  # Required version
        "min_version": "15.0",  # For in_range
        "max_version": "16.0",  # For in_range
        "version_format": "semver|numeric|cisco"  # How to parse versions
    }
    
    Example:
    {
        "pattern": "version (\\d+\\.\\d+\\.\\d+)",
        "operator": "ge",
        "value": "15.2.4",
        "version_format": "semver"
    }
    """
    
    LOGIC_TYPE = "version_check"
    
    @classmethod
    def validate_payload(cls, payload: dict) -> tuple[bool, str]:
        """Validate checker payload."""
        if not payload.get("pattern"):
            return False, "'pattern' is required"
        
        operator = payload.get("operator", "ge")
        valid_ops = ["eq", "ne", "gt", "lt", "ge", "le", "in_range"]
        if operator not in valid_ops:
            return False, f"Invalid operator. Must be one of: {valid_ops}"
        
        if operator == "in_range":
            if not payload.get("min_version") or not payload.get("max_version"):
                return False, "'min_version' and 'max_version' required for in_range"
        elif not payload.get("value"):
            return False, "'value' is required"
        
        return True, ""
    
    @classmethod
    def get_payload_schema(cls) -> dict:
        return {
            "type": "object",
            "required": ["pattern"],
            "properties": {
                "pattern": {"type": "string", "description": "Regex with version capture group"},
                "version_group": {"type": "integer", "default": 1},
                "operator": {"type": "string", "enum": ["eq", "ne", "gt", "lt", "ge", "le", "in_range"]},
                "value": {"type": "string", "description": "Required version"},
                "min_version": {"type": "string"},
                "max_version": {"type": "string"},
                "version_format": {"type": "string", "enum": ["semver", "numeric", "cisco", "auto"]}
            }
        }
    
    def check(self, config_text: str, payload: dict) -> CheckResult:
        """Extract version and compare."""
        pattern = payload.get("pattern")
        version_group = payload.get("version_group", 1)
        operator = payload.get("operator", "ge")
        expected = payload.get("value")
        version_format = payload.get("version_format", "auto")
        
        # Extract version
        try:
            match = re.search(pattern, config_text, re.MULTILINE | re.IGNORECASE)
            if not match:
                return CheckResult(
                    status=CheckStatus.FAIL,
                    passed=False,
                    message=f"Version pattern not found"
                )
            
            actual_version = match.group(version_group)
        except Exception as e:
            return CheckResult(
                status=CheckStatus.ERROR,
                passed=False,
                message=f"Version extraction failed: {e}"
            )
        
        # Parse versions
        actual_parsed = self._parse_version(actual_version, version_format)
        
        # Compare
        if operator == "in_range":
            min_ver = self._parse_version(payload.get("min_version"), version_format)
            max_ver = self._parse_version(payload.get("max_version"), version_format)
            
            if min_ver <= actual_parsed <= max_ver:
                return CheckResult(
                    status=CheckStatus.PASS,
                    passed=True,
                    message=f"Version {actual_version} is in range [{payload['min_version']}, {payload['max_version']}]"
                )
            else:
                return CheckResult(
                    status=CheckStatus.FAIL,
                    passed=False,
                    message=f"Version {actual_version} is not in range [{payload['min_version']}, {payload['max_version']}]"
                )
        
        expected_parsed = self._parse_version(expected, version_format)
        
        comparisons = {
            "eq": actual_parsed == expected_parsed,
            "ne": actual_parsed != expected_parsed,
            "gt": actual_parsed > expected_parsed,
            "lt": actual_parsed < expected_parsed,
            "ge": actual_parsed >= expected_parsed,
            "le": actual_parsed <= expected_parsed,
        }
        
        passed = comparisons.get(operator, False)
        
        if passed:
            return CheckResult(
                status=CheckStatus.PASS,
                passed=True,
                message=f"Version {actual_version} {operator} {expected}"
            )
        else:
            return CheckResult(
                status=CheckStatus.FAIL,
                passed=False,
                message=f"Version {actual_version} does not satisfy {operator} {expected}"
            )
    
    def _parse_version(self, version: str, format_type: str = "auto") -> tuple:
        """Parse version string into comparable tuple."""
        if not version:
            return (0,)
        
        # Remove common prefixes
        version = re.sub(r'^[vV]', '', version.strip())
        
        # Split by common separators
        parts = re.split(r'[.\-_]', version)
        
        # Convert to integers where possible
        result = []
        for part in parts:
            # Extract leading number
            match = re.match(r'(\d+)', part)
            if match:
                result.append(int(match.group(1)))
            else:
                result.append(0)
        
        return tuple(result) if result else (0,)
