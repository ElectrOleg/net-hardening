"""Structure Checker - JSON/JMESPath checking for API-based vendors."""
import jmespath
from app.engine.base import RuleChecker, CheckResult


class StructureChecker(RuleChecker):
    """
    Checker for structured (JSON) configurations.
    Uses JMESPath for querying nested structures.
    
    Payload format:
    {
        "path": "network.interfaces[?type=='external'].security_profile",
        "operator": "eq",  // eq, neq, contains, not_contains, gt, lt, gte, lte, exists, not_exists
        "value": "strict-profile",  // expected value (not needed for exists/not_exists)
        "all_must_match": true  // if path returns array, all items must match
    }
    """
    
    OPERATORS = {
        "eq": lambda a, b: a == b,
        "neq": lambda a, b: a != b,
        "contains": lambda a, b: b in a if isinstance(a, (str, list)) else False,
        "not_contains": lambda a, b: b not in a if isinstance(a, (str, list)) else True,
        "gt": lambda a, b: a > b,
        "lt": lambda a, b: a < b,
        "gte": lambda a, b: a >= b,
        "lte": lambda a, b: a <= b,
        "exists": lambda a, b: a is not None,
        "not_exists": lambda a, b: a is None,
        "in": lambda a, b: a in b if isinstance(b, list) else False,
        "not_in": lambda a, b: a not in b if isinstance(b, list) else True,
    }
    
    def validate_payload(self, payload: dict) -> list[str]:
        errors = []
        if "path" not in payload:
            errors.append("'path' is required")
        operator = payload.get("operator", "eq")
        if operator not in self.OPERATORS:
            errors.append(f"'operator' must be one of: {list(self.OPERATORS.keys())}")
        if operator not in ("exists", "not_exists") and "value" not in payload:
            errors.append("'value' is required for this operator")
        return errors
    
    def check(self, config: dict, payload: dict) -> CheckResult:
        if not isinstance(config, dict):
            return CheckResult.error("Configuration must be a dictionary for structure checks")
        
        path = payload["path"]
        operator = payload.get("operator", "eq")
        expected_value = payload.get("value")
        all_must_match = payload.get("all_must_match", True)
        
        try:
            # Query the configuration
            result = jmespath.search(path, config)
        except jmespath.exceptions.JMESPathError as e:
            return CheckResult.error(f"Invalid JMESPath: {e}")
        
        op_func = self.OPERATORS[operator]
        
        # Handle array results
        if isinstance(result, list):
            if not result:
                if operator in ("exists", "not_exists"):
                    passed = op_func(None, expected_value)
                else:
                    return CheckResult.failure(
                        message=f"Path '{path}' returned empty array",
                        raw_value=result
                    )
            else:
                results = [op_func(item, expected_value) for item in result]
                passed = all(results) if all_must_match else any(results)
        else:
            passed = op_func(result, expected_value)
        
        if passed:
            return CheckResult.success(
                message=f"Check passed: {path} {operator} {expected_value}",
                raw_value=result
            )
        else:
            return CheckResult.failure(
                message=f"Check failed: expected {path} {operator} {expected_value}",
                diff_data=f"Actual value: {result}",
                raw_value=result
            )
