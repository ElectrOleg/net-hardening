"""Rule Evaluator - orchestrates rule checking."""
from typing import Type
from app.engine.base import RuleChecker, CheckResult
from app.engine.simple_match import SimpleMatchChecker
from app.engine.block_match import BlockMatchChecker
from app.engine.structure_check import StructureChecker
from app.engine.version_check import VersionChecker
from app.engine.textfsm_check import TextFSMChecker
from app.engine.xml_check import XMLChecker
from app.engine.advanced_block import AdvancedBlockChecker
from app.engine.composite_check import CompositeChecker


class RuleEvaluator:
    """
    Main entry point for rule evaluation.
    Maps logic_type to appropriate checker and executes checks.
    """
    
    # Registry of checker types
    CHECKERS: dict[str, Type[RuleChecker]] = {
        "simple_match": SimpleMatchChecker,
        "regex_match": SimpleMatchChecker,  # Alias
        "block_match": BlockMatchChecker,
        "block_context_match": BlockMatchChecker,  # Alias
        "structure_check": StructureChecker,
        "structured_check": StructureChecker,  # Alias
        "version_check": VersionChecker,
        "textfsm_check": TextFSMChecker,
        "xml_check": XMLChecker,
        "xpath_check": XMLChecker,  # Alias
        "advanced_block_check": AdvancedBlockChecker,
        "advanced_block": AdvancedBlockChecker,  # Alias
        "nested_block_check": AdvancedBlockChecker,  # Alias
        "composite_check": CompositeChecker,
        "multi_section_check": CompositeChecker,  # Alias
    }
    
    def __init__(self):
        # Instantiate checkers (stateless, can be reused)
        self._checker_instances: dict[str, RuleChecker] = {}
    
    def _get_checker(self, logic_type: str) -> RuleChecker:
        """Get or create checker instance for given type."""
        if logic_type not in self._checker_instances:
            checker_class = self.CHECKERS.get(logic_type)
            if checker_class is None:
                raise ValueError(f"Unknown logic_type: {logic_type}")
            self._checker_instances[logic_type] = checker_class()
        return self._checker_instances[logic_type]
    
    def evaluate(self, config: str | dict, logic_type: str, logic_payload: dict) -> CheckResult:
        """
        Evaluate a single rule against configuration.
        
        Args:
            config: Configuration text or dict
            logic_type: Type of check (simple_match, block_match, etc.)
            logic_payload: Check-specific parameters
            
        Returns:
            CheckResult with status and details
        """
        try:
            checker = self._get_checker(logic_type)
        except ValueError as e:
            return CheckResult.error(str(e))
        
        # Validate payload
        errors = checker.validate_payload(logic_payload)
        if errors:
            return CheckResult.error(f"Invalid payload: {'; '.join(errors)}")
        
        # Execute check
        return checker.check(config, logic_payload)
    
    def test_rule(self, config: str | dict, logic_type: str, logic_payload: dict) -> dict:
        """
        Test a rule in sandbox mode (for Rule Builder UI).
        Returns detailed result suitable for display.
        """
        result = self.evaluate(config, logic_type, logic_payload)
        
        return {
            "status": result.status.value,
            "passed": result.passed,
            "message": result.message,
            "diff_data": result.diff_data,
            "raw_value": result.raw_value,
            "details": result.details,
        }
    
    @classmethod
    def get_supported_types(cls) -> list[str]:
        """Return list of unique supported logic types."""
        return list(set(cls.CHECKERS.keys()))
    
    @classmethod
    def register_checker(cls, logic_type: str, checker_class: Type[RuleChecker]):
        """Register a new checker type (for extensibility)."""
        cls.CHECKERS[logic_type] = checker_class


# Singleton instance for convenience
evaluator = RuleEvaluator()
