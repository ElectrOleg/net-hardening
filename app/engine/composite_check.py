"""Composite Checker - evaluate rules that require multiple data sections.

When a device's config is fetched with multi-command SSH (sectioned output)
or from an API provider (JSON with named sections), this checker can
evaluate conditions across different sections in a single rule.
"""
from app.engine.base import RuleChecker, CheckResult
from app.engine.simple_match import SimpleMatchChecker
from app.engine.block_match import BlockMatchChecker
from app.engine.structure_check import StructureChecker
from app.engine.xml_check import XMLChecker

import re
import json
import logging

logger = logging.getLogger(__name__)


class SectionParser:
    """Parse multi-section config output into named sections.
    
    Handles two formats:
    1. SSH multi-command: sections delimited by '=== command ===' headers
    2. JSON dict: keys are section names
    """
    
    SECTION_RE = re.compile(r"^=== (.+?) ===$", re.MULTILINE)
    
    @classmethod
    def parse(cls, config) -> dict:
        """Parse config into named sections."""
        if isinstance(config, dict):
            return config
        
        if not isinstance(config, str):
            return {"_default": str(config)}
        
        # Try JSON first
        try:
            parsed = json.loads(config)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        
        # Parse sectioned SSH output
        sections = {}
        parts = cls.SECTION_RE.split(config)
        
        if len(parts) == 1:
            # No sections found — treat entire config as single section
            return {"_default": config}
        
        # parts[0] is text before first header (usually empty)
        if parts[0].strip():
            sections["_preamble"] = parts[0].strip()
        
        # pairs: (section_name, section_content)
        for i in range(1, len(parts), 2):
            name = parts[i].strip()
            content = parts[i + 1].strip() if i + 1 < len(parts) else ""
            sections[name] = content
        
        return sections


class CompositeChecker(RuleChecker):
    """
    Checker that evaluates conditions across multiple config sections.
    
    Payload format:
    {
        "conditions": [
            {
                "section": "show running-config",  // or "_default" for unsectioned
                "checker": "simple_match",          // any supported checker type
                "payload": {...}                    // checker-specific payload
            },
            {
                "section": "show ip access-lists",
                "checker": "block_match",
                "payload": {...}
            }
        ],
        "operator": "all"  // "all" (AND) or "any" (OR) — default "all"
    }
    
    For JSON/API configs:
    {
        "conditions": [
            {
                "section": "firewall-policy",
                "checker": "structure_check",
                "payload": {
                    "path": "[?action=='accept'].name",
                    "operator": "exists"
                }
            }
        ]
    }
    """
    
    CHECKER_MAP = {
        "simple_match": SimpleMatchChecker,
        "block_match": BlockMatchChecker,
        "structure_check": StructureChecker,
        "xml_check": XMLChecker,
    }
    
    def __init__(self):
        self._instances = {}
    
    def _get_checker(self, checker_type: str) -> RuleChecker:
        if checker_type not in self._instances:
            cls = self.CHECKER_MAP.get(checker_type)
            if cls is None:
                raise ValueError(f"Unknown sub-checker: {checker_type}")
            self._instances[checker_type] = cls()
        return self._instances[checker_type]
    
    def validate_payload(self, payload: dict) -> list[str]:
        errors = []
        conditions = payload.get("conditions")
        if not conditions or not isinstance(conditions, list):
            errors.append("'conditions' must be a non-empty list")
            return errors
        
        for i, cond in enumerate(conditions):
            if "checker" not in cond:
                errors.append(f"condition[{i}]: 'checker' is required")
            if "payload" not in cond:
                errors.append(f"condition[{i}]: 'payload' is required")
        
        op = payload.get("operator", "all")
        if op not in ("all", "any"):
            errors.append("'operator' must be 'all' or 'any'")
        
        return errors
    
    def check(self, config, payload: dict) -> CheckResult:
        conditions = payload["conditions"]
        operator = payload.get("operator", "all")
        
        # Parse config into sections
        sections = SectionParser.parse(config)
        
        results = []
        details = []
        
        for i, cond in enumerate(conditions):
            section_name = cond.get("section", "_default")
            checker_type = cond["checker"]
            sub_payload = cond["payload"]
            
            # Get section data
            section_data = sections.get(section_name)
            if section_data is None:
                # Try partial match
                for key in sections:
                    if section_name in key:
                        section_data = sections[key]
                        break
            
            if section_data is None:
                details.append(f"[{i}] Section '{section_name}' not found → SKIP")
                results.append(None)  # Skip missing sections
                continue
            
            try:
                checker = self._get_checker(checker_type)
                result = checker.check(section_data, sub_payload)
                results.append(result.passed)
                details.append(
                    f"[{i}] {section_name}/{checker_type}: "
                    f"{'PASS' if result.passed else 'FAIL'} — {result.message}"
                )
            except Exception as e:
                details.append(f"[{i}] {section_name}/{checker_type}: ERROR — {e}")
                results.append(False)
        
        # Filter out None (skipped) and evaluate
        valid_results = [r for r in results if r is not None]
        
        if not valid_results:
            return CheckResult.error(
                "No sections matched any conditions",
                details={"conditions": details}
            )
        
        if operator == "all":
            passed = all(valid_results)
        else:
            passed = any(valid_results)
        
        detail_text = "\n".join(details)
        
        if passed:
            return CheckResult.success(
                f"Composite check passed ({operator}): "
                f"{sum(valid_results)}/{len(valid_results)} conditions met",
                details={"conditions": details}
            )
        else:
            return CheckResult.failure(
                f"Composite check failed ({operator}): "
                f"{sum(valid_results)}/{len(valid_results)} conditions met",
                diff_data=detail_text,
                details={"conditions": details}
            )
