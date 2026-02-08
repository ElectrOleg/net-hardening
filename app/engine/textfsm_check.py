"""TextFSM Checker - Parse CLI output and check structured data.

Uses TextFSM templates to parse unstructured CLI output
into structured tables for validation.

Ideal for checking output of 'show' commands.
"""
import logging
import re
from typing import Any

from app.engine.base import RuleChecker, CheckResult, CheckStatus

logger = logging.getLogger(__name__)


class TextFSMChecker(RuleChecker):
    """
    TextFSM-based checker for CLI output parsing.
    
    Parses CLI output using TextFSM templates, then validates
    the resulting structured data.
    
    Payload structure:
    {
        "template": "TextFSM template content or path",
        "template_name": "ntc-templates template name (optional)",
        "checks": [
            {
                "field": "FIELD_NAME",
                "operator": "eq|ne|contains|regex|gt|lt|ge|le|in",
                "value": "expected_value",
                "on_all": true  # Check all rows, not just first
            }
        ],
        "row_filter": {
            "field": "FIELD_NAME",
            "pattern": "filter_regex"
        },
        "min_rows": 1,  # Minimum number of parsed rows
        "max_rows": null  # Maximum number of parsed rows
    }
    """
    
    LOGIC_TYPE = "textfsm_check"
    
    OPERATORS = {
        "eq": lambda a, b: str(a) == str(b),
        "ne": lambda a, b: str(a) != str(b),
        "contains": lambda a, b: str(b) in str(a),
        "not_contains": lambda a, b: str(b) not in str(a),
        "regex": lambda a, b: bool(re.search(b, str(a))),
        "gt": lambda a, b: float(a) > float(b),
        "lt": lambda a, b: float(a) < float(b),
        "ge": lambda a, b: float(a) >= float(b),
        "le": lambda a, b: float(a) <= float(b),
        "in": lambda a, b: str(a) in b,
        "not_in": lambda a, b: str(a) not in b,
        "empty": lambda a, b: not a or a == "",
        "not_empty": lambda a, b: a and a != "",
    }
    
    def validate_payload(self, payload: dict) -> list[str]:
        """Validate checker payload."""
        errors = []
        if not payload.get("template") and not payload.get("template_name"):
            errors.append("Either 'template' or 'template_name' is required")
        
        checks = payload.get("checks", [])
        if not checks:
            errors.append("'checks' array is required")
        
        for i, check in enumerate(checks):
            if "field" not in check:
                errors.append(f"Check {i}: 'field' is required")
            if "operator" not in check:
                errors.append(f"Check {i}: 'operator' is required")
            elif check["operator"] not in self.OPERATORS:
                errors.append(f"Check {i}: unknown operator '{check['operator']}'")
        
        return errors
    
    @classmethod
    def get_payload_schema(cls) -> dict:
        """Return JSON schema for payload."""
        return {
            "type": "object",
            "required": ["checks"],
            "properties": {
                "template": {"type": "string", "description": "TextFSM template content"},
                "template_name": {"type": "string", "description": "NTC-templates name (e.g., 'cisco_ios_show_interfaces')"},
                "checks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["field", "operator"],
                        "properties": {
                            "field": {"type": "string"},
                            "operator": {"type": "string", "enum": list(cls.OPERATORS.keys())},
                            "value": {},
                            "on_all": {"type": "boolean", "default": False}
                        }
                    }
                },
                "row_filter": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "pattern": {"type": "string"}
                    }
                },
                "min_rows": {"type": "integer"},
                "max_rows": {"type": "integer"}
            }
        }
    
    def check(self, config_text: str, payload: dict) -> CheckResult:
        """
        Parse CLI output with TextFSM and validate.
        """
        try:
            import textfsm
        except ImportError:
            return CheckResult.error(
                message="textfsm not installed. pip install textfsm"
            )
        
        template_content = payload.get("template")
        template_name = payload.get("template_name")
        
        # Get template
        if template_name:
            # Try ntc-templates
            try:
                from ntc_templates import parse
                parsed = parse.parse_output(platform=template_name.rsplit("_", 1)[0], 
                                           command=template_name.split("_")[-1], 
                                           data=config_text)
                if parsed:
                    return self._validate_parsed_data(parsed, payload)
            except Exception as e:
                logger.warning(f"NTC-templates failed: {e}")
                return CheckResult.error(
                    message=f"Failed to use template '{template_name}': {e}"
                )
        
        if not template_content:
            return CheckResult.error(
                message="No template content provided"
            )
        
        # Parse with TextFSM
        try:
            import io
            template_file = io.StringIO(template_content)
            fsm = textfsm.TextFSM(template_file)
            parsed = fsm.ParseText(config_text)
            
            # Convert to list of dicts
            headers = fsm.header
            data = [dict(zip(headers, row)) for row in parsed]
            
            return self._validate_parsed_data(data, payload)
            
        except Exception as e:
            return CheckResult.error(
                message=f"TextFSM parsing failed: {e}"
            )
    
    def _validate_parsed_data(self, data: list[dict], payload: dict) -> CheckResult:
        """Validate parsed data against checks."""
        # Apply row filter
        row_filter = payload.get("row_filter")
        if row_filter:
            field = row_filter.get("field")
            pattern = row_filter.get("pattern", "")
            data = [row for row in data if re.search(pattern, str(row.get(field, "")))]
        
        # Check row count
        min_rows = payload.get("min_rows")
        max_rows = payload.get("max_rows")
        
        if min_rows and len(data) < min_rows:
            return CheckResult.failure(
                message=f"Expected at least {min_rows} rows, got {len(data)}"
            )
        
        if max_rows and len(data) > max_rows:
            return CheckResult.failure(
                message=f"Expected at most {max_rows} rows, got {len(data)}"
            )
        
        # Run checks
        failures = []
        checks = payload.get("checks", [])
        
        for check in checks:
            field = check.get("field")
            operator = check.get("operator")
            expected = check.get("value")
            on_all = check.get("on_all", False)
            
            op_func = self.OPERATORS.get(operator)
            if not op_func:
                continue
            
            if on_all:
                # Check all rows
                for i, row in enumerate(data):
                    actual = row.get(field, "")
                    try:
                        if not op_func(actual, expected):
                            failures.append(f"Row {i}: {field}='{actual}' failed {operator} '{expected}'")
                    except Exception as e:
                        failures.append(f"Row {i}: check error - {e}")
            else:
                # Check first matching row
                if data:
                    actual = data[0].get(field, "")
                    try:
                        if not op_func(actual, expected):
                            failures.append(f"{field}='{actual}' failed {operator} '{expected}'")
                    except Exception as e:
                        failures.append(f"Check error: {e}")
                else:
                    failures.append(f"No data rows to check")
        
        if failures:
            return CheckResult.failure(
                message="; ".join(failures[:5]),  # Limit messages
                diff_data="\n".join(failures)
            )
        
        return CheckResult.success(
            message=f"All {len(checks)} checks passed on {len(data)} rows"
        )
