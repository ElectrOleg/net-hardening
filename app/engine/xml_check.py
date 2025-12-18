"""XML/XPath Checker - Validate XML configurations.

Supports:
- XPath queries for element selection
- Namespace handling
- Multiple validation operators
- NETCONF response validation
"""
import logging
import re
from typing import Any, Optional

from app.engine.base import RuleChecker, CheckResult, CheckStatus

logger = logging.getLogger(__name__)


class XMLChecker(RuleChecker):
    """
    XML/XPath-based checker for XML configurations.
    
    Ideal for:
    - NETCONF responses
    - XML-based configs (Juniper, Palo Alto)
    - API responses in XML format
    
    Payload structure:
    {
        "xpath": "XPath expression to select elements",
        "namespaces": {"prefix": "namespace_uri"},  # Optional
        "operator": "exists|not_exists|eq|ne|contains|regex|count_eq|count_gt|count_lt",
        "value": "expected_value",
        "attribute": "attribute_name",  # Check attribute instead of text
        "check_all": true  # All matching elements must pass
    }
    
    Multiple checks:
    {
        "checks": [
            {"xpath": "...", "operator": "...", "value": "..."},
            ...
        ]
    }
    """
    
    LOGIC_TYPE = "xml_check"
    
    OPERATORS = {
        "exists": lambda elements, value: len(elements) > 0,
        "not_exists": lambda elements, value: len(elements) == 0,
        "count_eq": lambda elements, value: len(elements) == int(value),
        "count_gt": lambda elements, value: len(elements) > int(value),
        "count_lt": lambda elements, value: len(elements) < int(value),
        "count_ge": lambda elements, value: len(elements) >= int(value),
        "count_le": lambda elements, value: len(elements) <= int(value),
    }
    
    VALUE_OPERATORS = {
        "eq": lambda actual, expected: str(actual) == str(expected),
        "ne": lambda actual, expected: str(actual) != str(expected),
        "contains": lambda actual, expected: str(expected) in str(actual),
        "not_contains": lambda actual, expected: str(expected) not in str(actual),
        "regex": lambda actual, expected: bool(re.search(expected, str(actual))),
        "starts_with": lambda actual, expected: str(actual).startswith(str(expected)),
        "ends_with": lambda actual, expected: str(actual).endswith(str(expected)),
        "gt": lambda actual, expected: float(actual) > float(expected),
        "lt": lambda actual, expected: float(actual) < float(expected),
        "ge": lambda actual, expected: float(actual) >= float(expected),
        "le": lambda actual, expected: float(actual) <= float(expected),
    }
    
    @classmethod
    def validate_payload(cls, payload: dict) -> tuple[bool, str]:
        """Validate checker payload."""
        checks = payload.get("checks", [])
        
        # Single check mode
        if not checks and payload.get("xpath"):
            checks = [payload]
        
        if not checks:
            return False, "'xpath' or 'checks' array is required"
        
        for i, check in enumerate(checks):
            if not check.get("xpath"):
                return False, f"Check {i}: 'xpath' is required"
            
            operator = check.get("operator", "exists")
            all_ops = set(cls.OPERATORS.keys()) | set(cls.VALUE_OPERATORS.keys())
            if operator not in all_ops:
                return False, f"Check {i}: unknown operator '{operator}'"
        
        return True, ""
    
    @classmethod
    def get_payload_schema(cls) -> dict:
        """Return JSON schema for payload."""
        all_ops = list(cls.OPERATORS.keys()) + list(cls.VALUE_OPERATORS.keys())
        return {
            "type": "object",
            "properties": {
                "xpath": {"type": "string", "description": "XPath expression"},
                "namespaces": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Namespace prefix mappings"
                },
                "operator": {"type": "string", "enum": all_ops},
                "value": {"description": "Expected value for comparison"},
                "attribute": {"type": "string", "description": "Check attribute instead of text"},
                "check_all": {"type": "boolean", "default": False},
                "checks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["xpath"],
                        "properties": {
                            "xpath": {"type": "string"},
                            "operator": {"type": "string"},
                            "value": {},
                            "attribute": {"type": "string"}
                        }
                    }
                }
            }
        }
    
    def check(self, config_text: str, payload: dict) -> CheckResult:
        """
        Parse XML and validate with XPath.
        """
        try:
            from lxml import etree
        except ImportError:
            # Fallback to stdlib
            from xml.etree import ElementTree as etree
            logger.warning("lxml not installed, using stdlib (limited XPath)")
        
        # Parse XML
        try:
            # Remove XML declaration if present (common issue)
            config_clean = re.sub(r'<\?xml[^?]*\?>', '', config_text).strip()
            
            if hasattr(etree, 'fromstring'):
                root = etree.fromstring(config_clean.encode('utf-8'))
            else:
                root = etree.XML(config_clean)
                
        except Exception as e:
            return CheckResult(
                status=CheckStatus.ERROR,
                passed=False,
                message=f"XML parse error: {e}"
            )
        
        # Get namespaces
        namespaces = payload.get("namespaces", {})
        
        # Get checks
        checks = payload.get("checks", [])
        if not checks and payload.get("xpath"):
            checks = [payload]
        
        failures = []
        
        for check in checks:
            result = self._run_check(root, check, namespaces)
            if not result.passed:
                failures.append(result.message)
        
        if failures:
            return CheckResult(
                status=CheckStatus.FAIL,
                passed=False,
                message="; ".join(failures[:3]),
                diff_data="\n".join(failures)
            )
        
        return CheckResult(
            status=CheckStatus.PASS,
            passed=True,
            message=f"All {len(checks)} XPath checks passed"
        )
    
    def _run_check(self, root, check: dict, namespaces: dict) -> CheckResult:
        """Run a single XPath check."""
        xpath = check.get("xpath")
        operator = check.get("operator", "exists")
        expected = check.get("value")
        attribute = check.get("attribute")
        check_all = check.get("check_all", False)
        
        try:
            # Execute XPath
            if hasattr(root, 'xpath'):
                # lxml
                elements = root.xpath(xpath, namespaces=namespaces)
            else:
                # stdlib - limited XPath support
                elements = root.findall(xpath, namespaces)
        except Exception as e:
            return CheckResult(
                status=CheckStatus.ERROR,
                passed=False,
                message=f"XPath error '{xpath}': {e}"
            )
        
        # Count-based operators
        if operator in self.OPERATORS:
            op_func = self.OPERATORS[operator]
            if op_func(elements, expected):
                return CheckResult(status=CheckStatus.PASS, passed=True, message="OK")
            else:
                return CheckResult(
                    status=CheckStatus.FAIL,
                    passed=False,
                    message=f"XPath '{xpath}': {operator} failed (found {len(elements)} elements)"
                )
        
        # Value-based operators
        if operator in self.VALUE_OPERATORS:
            if not elements:
                return CheckResult(
                    status=CheckStatus.FAIL,
                    passed=False,
                    message=f"XPath '{xpath}': no elements found"
                )
            
            op_func = self.VALUE_OPERATORS[operator]
            
            failed_elements = []
            for elem in elements:
                # Get value
                if attribute:
                    actual = elem.get(attribute, "") if hasattr(elem, 'get') else elem.attrib.get(attribute, "")
                else:
                    actual = elem.text if hasattr(elem, 'text') else str(elem)
                
                try:
                    if not op_func(actual, expected):
                        failed_elements.append(f"'{actual}' {operator} '{expected}'")
                        if not check_all:
                            break
                except Exception as e:
                    failed_elements.append(f"comparison error: {e}")
            
            if failed_elements:
                return CheckResult(
                    status=CheckStatus.FAIL,
                    passed=False,
                    message=f"XPath '{xpath}': " + "; ".join(failed_elements[:3])
                )
            
            return CheckResult(status=CheckStatus.PASS, passed=True, message="OK")
        
        return CheckResult(
            status=CheckStatus.ERROR,
            passed=False,
            message=f"Unknown operator: {operator}"
        )
