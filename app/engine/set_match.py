"""Set Match Checker — collects values from config and compares against an expected set.

Use case: verify that exactly the right set of objects/hosts/interfaces exist,
no more and no less (or subset/superset variants).
"""
import re
import logging
from app.engine.base import RuleChecker, CheckResult

logger = logging.getLogger(__name__)


class SetMatchChecker(RuleChecker):
    """
    Collects all occurrences of a regex pattern in the config,
    extracts captured values, and compares them against an expected set.

    Payload format:
    {
        "collect_pattern": "^\\s*object-group\\s+service\\s+(\\S+)",
        "capture_group": 1,                       // which regex group to extract
        "expected_set": ["ISAKMP_PORT", "SSH"],   // the reference set
        "mode": "exact",                          // exact | subset | superset | contains | disjoint
        "case_insensitive": false                 // optional
    }

    Modes:
    - exact:     found == expected (no more, no less)
    - subset:    found ⊆ expected (all found items must be in expected; extras in expected OK)
    - superset:  found ⊇ expected (all expected must be present; extras in found OK)
    - contains:  alias for superset
    - disjoint:  found ∩ expected == ∅ (none of expected should be found — "forbidden set")
    """

    VALID_MODES = {"exact", "subset", "superset", "contains", "disjoint"}

    def validate_payload(self, payload: dict) -> list[str]:
        errors = []
        if not payload.get("collect_pattern"):
            errors.append("'collect_pattern' is required")
        if "expected_set" not in payload:
            errors.append("'expected_set' is required")
        elif not isinstance(payload["expected_set"], list):
            errors.append("'expected_set' must be a list")
        mode = payload.get("mode", "exact")
        if mode not in self.VALID_MODES:
            errors.append(f"'mode' must be one of {self.VALID_MODES}")
        return errors

    def check(self, config: str, payload: dict) -> CheckResult:
        collect_pattern = payload["collect_pattern"]
        capture_group = payload.get("capture_group", 1)
        expected_set = payload["expected_set"]
        mode = payload.get("mode", "exact")
        case_insensitive = payload.get("case_insensitive", False)

        flags = re.MULTILINE
        if case_insensitive:
            flags |= re.IGNORECASE

        try:
            matches = re.finditer(collect_pattern, config, flags)
        except re.error as e:
            return CheckResult.error(f"Invalid regex: {e}")

        # Collect found values
        found_raw = []
        for m in matches:
            try:
                val = m.group(capture_group)
                if val is not None:
                    found_raw.append(val)
            except IndexError:
                found_raw.append(m.group(0))

        # Normalize for comparison
        if case_insensitive:
            found_set = {v.lower() for v in found_raw}
            expected = {v.lower() for v in expected_set}
        else:
            found_set = set(found_raw)
            expected = set(expected_set)

        # Compare
        missing = expected - found_set
        extra = found_set - expected

        if mode == "exact":
            passed = found_set == expected
        elif mode == "subset":
            # found must be ⊆ expected (no extra items)
            passed = found_set <= expected
        elif mode in ("superset", "contains"):
            # found must be ⊇ expected (all expected present)
            passed = found_set >= expected
        elif mode == "disjoint":
            # none of expected should be in found
            passed = found_set.isdisjoint(expected)
            # For disjoint, "missing" means "correctly absent", invert semantics
            if not passed:
                forbidden_found = found_set & expected
                return CheckResult.failure(
                    message=f"Found {len(forbidden_found)} forbidden item(s)",
                    diff_data=f"Forbidden items found: {sorted(forbidden_found)}",
                    details={
                        "found": sorted(found_raw),
                        "forbidden_found": sorted(forbidden_found),
                    },
                )
            return CheckResult.success(
                f"None of {len(expected)} forbidden items found",
                details={"found": sorted(found_raw)},
            )
        else:
            return CheckResult.error(f"Unknown mode: {mode}")

        if passed:
            return CheckResult.success(
                f"Set match ({mode}): {len(found_set)} items OK",
                details={
                    "found": sorted(found_raw),
                    "expected": sorted(expected_set),
                },
            )

        # Build failure message
        parts = []
        if missing:
            parts.append(f"Missing: {sorted(missing)}")
        if extra and mode in ("exact", "subset"):
            parts.append(f"Extra: {sorted(extra)}")

        return CheckResult.failure(
            message=f"Set mismatch ({mode}): {'; '.join(parts)}",
            diff_data=f"Found:    {sorted(found_set)}\nExpected: {sorted(expected)}\n" + "\n".join(parts),
            details={
                "found": sorted(found_raw),
                "expected": sorted(expected_set),
                "missing": sorted(missing),
                "extra": sorted(extra),
            },
        )
