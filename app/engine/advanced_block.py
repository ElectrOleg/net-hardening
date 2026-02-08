"""Advanced Block Checker - Complex hierarchical config validation.

Enhanced features:
- Deep nested block support (multi-level hierarchy)
- Grouped checks (multiple lines must match together)
- Partial matching with variable extraction
- Cross-block validation
- Conditional checks
"""
import re
import logging
from typing import Optional, Any
from dataclasses import dataclass

from app.engine.base import RuleChecker, CheckResult, CheckStatus

logger = logging.getLogger(__name__)


@dataclass
class BlockContext:
    """Context for a matched block."""
    block_text: str
    block_lines: list[str]
    parent_text: Optional[str] = None
    depth: int = 0
    variables: dict = None
    
    def __post_init__(self):
        if self.variables is None:
            self.variables = {}


class AdvancedBlockChecker(RuleChecker):
    """
    Advanced checker for complex hierarchical configurations.
    
    Supports:
    - Multi-level nested blocks (VLAN in interface in router, etc.)
    - Grouped line checks (all lines in group must match)
    - Variable extraction and reuse across checks
    - Conditional checks based on other matches
    - Cross-block validation
    
    Payload structure:
    {
        "block": {
            "start": "^interface (\\S+)",  // Regex, group 1 = variable $1
            "end": "^!",  // Optional end marker
            "depth": 1,  // Nesting level (1 = direct children)
            "filter": {
                "include": "GigabitEthernet|TenGig",  // Only these blocks
                "exclude": "Loopback"  // Skip these
            }
        },
        
        "checks": [
            // Simple must_exist
            {"pattern": "no ip proxy-arp", "mode": "must_exist"},
            
            // Simple must_not_exist
            {"pattern": "ip redirects", "mode": "must_not_exist"},
            
            // Grouped check - ALL lines must exist together
            {
                "group": [
                    "switchport mode access",
                    "switchport access vlan \\d+",
                    "spanning-tree portfast"
                ],
                "mode": "all_must_exist",
                "name": "Access port config"
            },
            
            // Any of group
            {
                "group": [
                    "switchport mode access",
                    "switchport mode trunk"
                ],
                "mode": "any_must_exist",
                "name": "Switchport mode required"
            },
            
            // Variable extraction and reuse
            {
                "pattern": "ip address (\\d+\\.\\d+\\.\\d+\\.\\d+)",
                "capture": "ip_address",  // Store in variable
                "mode": "must_exist"
            },
            
            // Conditional check
            {
                "pattern": "ip helper-address",
                "mode": "must_exist",
                "condition": {
                    "if_match": "switchport mode access"  // Only check if this exists
                }
            },
            
            // Nested block check
            {
                "nested_block": {
                    "start": "service-policy",
                    "checks": [
                        {"pattern": "input", "mode": "must_exist"}
                    ]
                }
            }
        ],
        
        "cross_block": {
            // Check consistency across all matched blocks
            "all_same": ["vlan (\\d+)"],  // All blocks must have same value
            "unique": ["ip address (\\S+)"]  // All blocks must have different values
        },
        
        "logic": "ALL",  // ALL blocks must pass, or "ANY"
        "fail_on_no_blocks": false  // Fail if no blocks found?
    }
    """
    
    LOGIC_TYPE = "advanced_block_check"
    
    def validate_payload(self, payload: dict) -> list[str]:
        """Validate payload structure."""
        errors = []
        if not payload.get("block"):
            errors.append("'block' configuration is required")
        
        block_config = payload.get("block", {})
        if not block_config.get("start"):
            errors.append("'block.start' pattern is required")
        
        checks = payload.get("checks", [])
        if not checks:
            errors.append("'checks' array is required")
        
        return errors
    
    @classmethod
    def get_payload_schema(cls) -> dict:
        return {
            "type": "object",
            "required": ["block", "checks"],
            "properties": {
                "block": {
                    "type": "object",
                    "required": ["start"],
                    "properties": {
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "depth": {"type": "integer", "default": 1},
                        "filter": {
                            "type": "object",
                            "properties": {
                                "include": {"type": "string"},
                                "exclude": {"type": "string"}
                            }
                        }
                    }
                },
                "checks": {"type": "array"},
                "cross_block": {"type": "object"},
                "logic": {"type": "string", "enum": ["ALL", "ANY"]},
                "fail_on_no_blocks": {"type": "boolean", "default": False}
            }
        }
    
    def check(self, config_text: str, payload: dict) -> CheckResult:
        """Perform advanced block checking."""
        try:
            from ciscoconfparse2 import CiscoConfParse
        except ImportError:
            return CheckResult.error(
                message="ciscoconfparse2 not installed"
            )
        
        block_config = payload.get("block", {})
        checks = payload.get("checks", [])
        cross_block = payload.get("cross_block", {})
        logic = payload.get("logic", "ALL")
        fail_on_no_blocks = payload.get("fail_on_no_blocks", False)
        
        try:
            parse = CiscoConfParse(config_text.splitlines())
        except Exception as e:
            return CheckResult.error(
                message=f"Config parse error: {e}"
            )
        
        # Find matching blocks
        blocks = self._find_blocks(parse, block_config)
        
        if not blocks:
            if fail_on_no_blocks:
                return CheckResult.failure(
                    message=f"No blocks matching '{block_config.get('start')}' found"
                )
            return CheckResult.success(
                message="No blocks to check"
            )
        
        # Check each block
        all_failures = []
        passed_blocks = 0
        extracted_values = {}  # For cross-block validation
        
        for block in blocks:
            block_failures = self._check_block(block, checks)
            
            if block_failures:
                all_failures.append({
                    "block": block.block_text,
                    "failures": block_failures
                })
            else:
                passed_blocks += 1
            
            # Collect values for cross-block validation
            if cross_block:
                self._collect_cross_block_values(block, cross_block, extracted_values)
        
        # Cross-block validation
        if cross_block and not all_failures:
            cross_failures = self._validate_cross_block(extracted_values, cross_block)
            if cross_failures:
                all_failures.append({
                    "block": "Cross-block validation",
                    "failures": cross_failures
                })
        
        # Apply logic
        total_blocks = len(blocks)
        
        if logic == "ANY":
            if passed_blocks > 0:
                return CheckResult.success(
                    message=f"{passed_blocks}/{total_blocks} blocks passed (ANY mode)"
                )
        
        if all_failures:
            diff_lines = []
            for f in all_failures[:10]:  # Limit output
                diff_lines.append(f"Block: {f['block']}")
                for fail in f['failures'][:5]:
                    diff_lines.append(f"  ✗ {fail}")
            
            return CheckResult.failure(
                message=f"{len(all_failures)}/{total_blocks} blocks failed",
                diff_data="\n".join(diff_lines)
            )
        
        return CheckResult.success(
            message=f"All {total_blocks} blocks passed"
        )
    
    def _find_blocks(self, parse, config: dict) -> list[BlockContext]:
        """Find all matching blocks."""
        start_pattern = config.get("start")
        include_filter = config.get("filter", {}).get("include")
        exclude_filter = config.get("filter", {}).get("exclude")
        
        blocks = []
        
        try:
            parent_objs = parse.find_parent_objects(start_pattern)
        except Exception as e:
            logger.error(f"Block search failed: {e}")
            return []
        
        for parent in parent_objs:
            block_text = parent.text.strip()
            
            # Apply filters
            if include_filter and not re.search(include_filter, block_text):
                continue
            if exclude_filter and re.search(exclude_filter, block_text):
                continue
            
            # Get all lines including nested children
            block_lines = [c.text.strip() for c in parent.all_children]
            
            # Extract variables from start pattern
            variables = {}
            match = re.search(start_pattern, block_text)
            if match:
                for i, group in enumerate(match.groups(), 1):
                    variables[f"${i}"] = group
            
            blocks.append(BlockContext(
                block_text=block_text,
                block_lines=block_lines,
                variables=variables,
                depth=0
            ))
        
        return blocks
    
    def _check_block(self, block: BlockContext, checks: list[dict]) -> list[str]:
        """Run all checks on a block."""
        failures = []
        block_content = "\n".join(block.block_lines)
        
        for check in checks:
            # Grouped check
            if "group" in check:
                group_result = self._check_group(block_content, check)
                if group_result:
                    failures.append(group_result)
                continue
            
            # Nested block check
            if "nested_block" in check:
                nested_result = self._check_nested(block.block_lines, check["nested_block"])
                if nested_result:
                    failures.extend(nested_result)
                continue
            
            # Simple pattern check
            pattern = check.get("pattern")
            if not pattern:
                continue
            
            mode = check.get("mode", "must_exist")
            condition = check.get("condition")
            
            # Check condition first
            if condition:
                if_match = condition.get("if_match")
                if if_match and not re.search(if_match, block_content, re.MULTILINE):
                    continue  # Condition not met, skip this check
            
            # Perform pattern check
            found = bool(re.search(pattern, block_content, re.MULTILINE))
            
            # Extract capture if specified
            if check.get("capture") and found:
                match = re.search(pattern, block_content, re.MULTILINE)
                if match and match.groups():
                    block.variables[check["capture"]] = match.group(1)
            
            if mode == "must_exist" and not found:
                failures.append(f"Missing: {pattern}")
            elif mode == "must_not_exist" and found:
                failures.append(f"Found forbidden: {pattern}")
        
        return failures
    
    def _check_group(self, content: str, check: dict) -> Optional[str]:
        """Check a group of patterns."""
        group = check.get("group", [])
        mode = check.get("mode", "all_must_exist")
        name = check.get("name", "Group check")
        
        matches = []
        for pattern in group:
            if re.search(pattern, content, re.MULTILINE):
                matches.append(pattern)
        
        if mode == "all_must_exist":
            if len(matches) != len(group):
                missing = [p for p in group if p not in matches]
                return f"{name}: missing {len(missing)} of {len(group)} required lines"
        
        elif mode == "any_must_exist":
            if not matches:
                return f"{name}: none of {len(group)} options found"
        
        elif mode == "none_must_exist":
            if matches:
                return f"{name}: found forbidden patterns"
        
        elif mode == "exactly_one":
            if len(matches) != 1:
                return f"{name}: expected exactly one match, found {len(matches)}"
        
        return None
    
    def _check_nested(self, lines: list[str], nested_config: dict) -> list[str]:
        """Check nested block within current block."""
        failures = []
        start = nested_config.get("start")
        nested_checks = nested_config.get("checks", [])
        
        # Find nested block start
        in_nested = False
        nested_lines = []
        
        for line in lines:
            if re.search(start, line):
                in_nested = True
                nested_lines = []
                continue
            
            if in_nested:
                # Check for end (less indentation or new block)
                if line and not line.startswith(" ") and not line.startswith("\t"):
                    in_nested = False
                else:
                    nested_lines.append(line)
        
        if nested_lines:
            nested_content = "\n".join(nested_lines)
            for check in nested_checks:
                pattern = check.get("pattern")
                mode = check.get("mode", "must_exist")
                
                if not pattern:
                    continue
                
                found = bool(re.search(pattern, nested_content, re.MULTILINE))
                
                if mode == "must_exist" and not found:
                    failures.append(f"Nested [{start}]: missing {pattern}")
                elif mode == "must_not_exist" and found:
                    failures.append(f"Nested [{start}]: found forbidden {pattern}")
        
        return failures
    
    def _collect_cross_block_values(
        self, 
        block: BlockContext, 
        cross_block: dict, 
        values: dict
    ):
        """Collect values for cross-block validation."""
        block_content = "\n".join(block.block_lines)
        
        for check_type in ["all_same", "unique"]:
            patterns = cross_block.get(check_type, [])
            for pattern in patterns:
                if pattern not in values:
                    values[pattern] = []
                
                match = re.search(pattern, block_content, re.MULTILINE)
                if match and match.groups():
                    values[pattern].append({
                        "block": block.block_text,
                        "value": match.group(1)
                    })
    
    def _validate_cross_block(self, values: dict, cross_block: dict) -> list[str]:
        """Validate cross-block consistency."""
        failures = []
        
        # All same check
        for pattern in cross_block.get("all_same", []):
            if pattern in values and len(values[pattern]) > 1:
                unique_values = set(v["value"] for v in values[pattern])
                if len(unique_values) > 1:
                    failures.append(
                        f"Inconsistent values for '{pattern}': {unique_values}"
                    )
        
        # Unique check
        for pattern in cross_block.get("unique", []):
            if pattern in values:
                all_values = [v["value"] for v in values[pattern]]
                if len(all_values) != len(set(all_values)):
                    duplicates = [v for v in all_values if all_values.count(v) > 1]
                    failures.append(
                        f"Duplicate values for '{pattern}': {set(duplicates)}"
                    )
        
        return failures
