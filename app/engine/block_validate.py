"""Block Validate Checker — validates that ALL lines in a block match an allowlist.

Use case: ensure no unauthorized/unexpected config lines exist inside a block,
e.g. object-group network entries must be valid ip prefix / address-range only.
"""
import re
import logging
from app.engine.base import RuleChecker, CheckResult

logger = logging.getLogger(__name__)


class BlockValidateChecker(RuleChecker):
    """
    Validates that every non-skipped line inside matching blocks
    conforms to at least one of the allowed patterns.

    Payload format:
    {
        "block_start": "^\\s*object-group\\s+network\\s+\\S+",
        "block_end": "^\\s*exit\\s*$",           // optional, default: exit
        "skip_lines": ["^\\s*$", "^\\s*!"],       // optional, skip blanks/comments
        "allowed_patterns": [
            "^\\s*ip\\s+prefix\\s+.+$",
            "^\\s*ip\\s+address-range\\s+.+$",
            "^\\s*description\\s+.+$"
        ],
        "case_insensitive": false,                // optional
        "fail_on_no_blocks": false                // optional
    }

    Result:
    - PASS if every line in every block matches at least one allowed_patterns
    - FAIL if any line doesn't match (reports offending lines)
    - PASS/configurable if no blocks found
    """

    def validate_payload(self, payload: dict) -> list[str]:
        errors = []
        if not payload.get("block_start"):
            errors.append("'block_start' is required")
        if not payload.get("allowed_patterns"):
            errors.append("'allowed_patterns' must be a non-empty list")
        elif not isinstance(payload["allowed_patterns"], list):
            errors.append("'allowed_patterns' must be a list")
        return errors

    def check(self, config: str, payload: dict) -> CheckResult:
        block_start = payload["block_start"]
        block_end_pat = payload.get("block_end", r"^\s*exit\s*$")
        skip_patterns = payload.get("skip_lines", [r"^\s*$"])
        allowed_patterns = payload["allowed_patterns"]
        case_flag = re.IGNORECASE if payload.get("case_insensitive") else 0
        fail_on_no_blocks = payload.get("fail_on_no_blocks", False)

        # Pre-compile patterns
        try:
            re_start = re.compile(block_start, case_flag)
            re_end = re.compile(block_end_pat, case_flag)
            re_skips = [re.compile(p, case_flag) for p in skip_patterns]
            re_allowed = [re.compile(p, case_flag) for p in allowed_patterns]
        except re.error as e:
            return CheckResult.error(f"Invalid regex: {e}")

        lines = config.splitlines() if isinstance(config, str) else []

        # Parse blocks
        blocks_found = 0
        all_violations = []

        in_block = False
        block_header = ""
        block_violations = []

        for line_raw in lines:
            line = line_raw.rstrip("\n")

            if not in_block:
                if re_start.search(line):
                    in_block = True
                    block_header = line.strip()
                    block_violations = []
                continue

            # Inside block
            if re_end.search(line):
                # Block ended
                blocks_found += 1
                if block_violations:
                    all_violations.append({
                        "block": block_header,
                        "violations": block_violations,
                    })
                in_block = False
                continue

            # Skip header-like lines (the block_start line itself is already skipped)
            stripped = line.strip()

            # Skip empty/comment lines
            if any(r.search(stripped) for r in re_skips):
                continue

            # Validate: must match at least one allowed pattern
            if not any(r.search(stripped) for r in re_allowed):
                block_violations.append(stripped)

        # Handle unterminated block
        if in_block:
            blocks_found += 1
            if block_violations:
                all_violations.append({
                    "block": block_header,
                    "violations": block_violations,
                })

        if blocks_found == 0:
            if fail_on_no_blocks:
                return CheckResult.failure(
                    f"No blocks matching '{block_start}' found"
                )
            return CheckResult.success("No blocks to validate")

        if all_violations:
            diff_lines = []
            for v in all_violations[:10]:
                diff_lines.append(f"Block: {v['block']}")
                for vl in v["violations"][:5]:
                    diff_lines.append(f"  ✗ Unexpected: {vl}")

            total_bad = sum(len(v["violations"]) for v in all_violations)
            return CheckResult.failure(
                message=f"{total_bad} unauthorized line(s) in {len(all_violations)} block(s)",
                diff_data="\n".join(diff_lines),
                details={
                    "blocks_checked": blocks_found,
                    "blocks_with_violations": len(all_violations),
                    "total_violations": total_bad,
                },
            )

        return CheckResult.success(
            f"All lines valid in {blocks_found} block(s)",
            details={"blocks_checked": blocks_found},
        )
