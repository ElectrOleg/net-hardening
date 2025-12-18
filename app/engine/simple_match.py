"""Simple Match Checker - regex and text pattern matching."""
import re
from app.engine.base import RuleChecker, CheckResult


class SimpleMatchChecker(RuleChecker):
    """
    Checker for simple text/regex pattern matching.
    
    Payload format:
    {
        "pattern": "^service password-encryption",
        "match_mode": "must_exist",  // or "must_not_exist"
        "is_regex": true,
        "case_insensitive": false  // optional
    }
    """
    
    def validate_payload(self, payload: dict) -> list[str]:
        errors = []
        if "pattern" not in payload:
            errors.append("'pattern' is required")
        if payload.get("match_mode") not in ("must_exist", "must_not_exist", None):
            errors.append("'match_mode' must be 'must_exist' or 'must_not_exist'")
        return errors
    
    def check(self, config: str, payload: dict) -> CheckResult:
        pattern = payload["pattern"]
        match_mode = payload.get("match_mode", "must_exist")
        is_regex = payload.get("is_regex", False)
        case_insensitive = payload.get("case_insensitive", False)
        
        try:
            if is_regex:
                flags = re.MULTILINE
                if case_insensitive:
                    flags |= re.IGNORECASE
                match = re.search(pattern, config, flags)
                found = match is not None
                raw_value = match.group(0) if match else None
            else:
                search_config = config.lower() if case_insensitive else config
                search_pattern = pattern.lower() if case_insensitive else pattern
                found = search_pattern in search_config
                raw_value = pattern if found else None
                
        except re.error as e:
            return CheckResult.error(f"Invalid regex pattern: {e}")
        
        if match_mode == "must_exist":
            if found:
                return CheckResult.success(
                    message=f"Pattern '{pattern}' found",
                    raw_value=raw_value
                )
            else:
                return CheckResult.failure(
                    message=f"Pattern '{pattern}' not found (required)",
                    diff_data=f"Expected to find: {pattern}"
                )
        else:  # must_not_exist
            if not found:
                return CheckResult.success(
                    message=f"Pattern '{pattern}' not found (as expected)"
                )
            else:
                return CheckResult.failure(
                    message=f"Pattern '{pattern}' found (should not exist)",
                    diff_data=f"Found forbidden pattern: {raw_value}",
                    raw_value=raw_value
                )
