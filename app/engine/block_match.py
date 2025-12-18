"""Block Match Checker - hierarchical config checking with ciscoconfparse2."""
import re
from app.engine.base import RuleChecker, CheckResult


class BlockMatchChecker(RuleChecker):
    """
    Checker for hierarchical block-based configurations (Cisco, Eltex, etc.)
    Uses ciscoconfparse2 for parsing IOS-style configs.
    
    Payload format:
    {
        "parent_block_start": "^interface (GigabitEthernet|TenGig)",
        "parent_block_end": "^!",  // optional, defaults to same-or-less indentation
        "exclude_filter": "description .*UPLINK.*",  // optional, skip blocks matching this
        "child_rules": [
            {"pattern": "no ip redirects", "mode": "must_exist"},
            {"pattern": "ip proxy-arp", "mode": "must_not_exist"}
        ],
        "logic": "ALL"  // ALL = all rules must pass, ANY = at least one must pass
    }
    """
    
    def validate_payload(self, payload: dict) -> list[str]:
        errors = []
        if "parent_block_start" not in payload:
            errors.append("'parent_block_start' is required")
        if "child_rules" not in payload or not payload["child_rules"]:
            errors.append("'child_rules' is required and must not be empty")
        if payload.get("logic") not in ("ALL", "ANY", None):
            errors.append("'logic' must be 'ALL' or 'ANY'")
        return errors
    
    def check(self, config: str, payload: dict) -> CheckResult:
        try:
            from ciscoconfparse2 import CiscoConfParse
        except ImportError:
            return CheckResult.error("ciscoconfparse2 is not installed")
        
        parent_pattern = payload["parent_block_start"]
        exclude_filter = payload.get("exclude_filter")
        child_rules = payload["child_rules"]
        logic = payload.get("logic", "ALL")
        
        try:
            # Parse configuration
            parse = CiscoConfParse(config.splitlines())
            
            # Find all parent blocks
            parent_objs = parse.find_parent_objects(parent_pattern)
            
            if not parent_objs:
                return CheckResult.success(
                    message=f"No blocks matching '{parent_pattern}' found",
                    details={"blocks_checked": 0}
                )
            
            all_failures = []
            blocks_checked = 0
            blocks_skipped = 0
            
            for parent in parent_objs:
                parent_text = parent.text.strip()
                
                # Check exclude filter
                if exclude_filter:
                    children_text = "\n".join(c.text for c in parent.children)
                    if re.search(exclude_filter, f"{parent_text}\n{children_text}", re.MULTILINE):
                        blocks_skipped += 1
                        continue
                
                blocks_checked += 1
                block_failures = self._check_block(parent, child_rules, logic)
                
                if block_failures:
                    all_failures.append({
                        "block": parent_text,
                        "failures": block_failures
                    })
            
            if all_failures:
                diff_lines = []
                for f in all_failures:
                    diff_lines.append(f"Block: {f['block']}")
                    for fail in f["failures"]:
                        diff_lines.append(f"  - {fail}")
                
                return CheckResult.failure(
                    message=f"Failed in {len(all_failures)} of {blocks_checked} blocks",
                    diff_data="\n".join(diff_lines),
                    details={
                        "blocks_checked": blocks_checked,
                        "blocks_skipped": blocks_skipped,
                        "blocks_failed": len(all_failures)
                    }
                )
            
            return CheckResult.success(
                message=f"All {blocks_checked} blocks passed",
                details={
                    "blocks_checked": blocks_checked,
                    "blocks_skipped": blocks_skipped
                }
            )
            
        except Exception as e:
            return CheckResult.error(f"Parse error: {str(e)}")
    
    def _check_block(self, parent, child_rules: list[dict], logic: str) -> list[str]:
        """Check a single block against child rules."""
        failures = []
        passes = 0
        
        # Get all children text for searching
        children_text = [c.text.strip() for c in parent.children]
        children_combined = "\n".join(children_text)
        
        for rule in child_rules:
            pattern = rule["pattern"]
            mode = rule.get("mode", "must_exist")
            is_regex = rule.get("is_regex", True)  # Default to regex for flexibility
            
            # Search in children
            if is_regex:
                found = bool(re.search(pattern, children_combined, re.MULTILINE))
            else:
                found = any(pattern in child for child in children_text)
            
            if mode == "must_exist" and not found:
                failures.append(f"Missing: {pattern}")
            elif mode == "must_not_exist" and found:
                failures.append(f"Found forbidden: {pattern}")
            else:
                passes += 1
        
        # Apply logic
        if logic == "ANY" and passes > 0:
            return []  # At least one passed, so block passes
        
        return failures
