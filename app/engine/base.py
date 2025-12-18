"""Base classes for Rule Engine - Strategy Pattern implementation."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from enum import Enum


class CheckStatus(str, Enum):
    """Possible check result statuses."""
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


@dataclass
class CheckResult:
    """Result of a single rule check."""
    
    status: CheckStatus
    message: str
    diff_data: str | None = None
    raw_value: Any = None
    details: dict = field(default_factory=dict)
    
    @property
    def passed(self) -> bool:
        return self.status == CheckStatus.PASS
    
    @classmethod
    def success(cls, message: str = "Check passed", **kwargs) -> "CheckResult":
        return cls(status=CheckStatus.PASS, message=message, **kwargs)
    
    @classmethod
    def failure(cls, message: str, diff_data: str | None = None, **kwargs) -> "CheckResult":
        return cls(status=CheckStatus.FAIL, message=message, diff_data=diff_data, **kwargs)
    
    @classmethod
    def error(cls, message: str, **kwargs) -> "CheckResult":
        return cls(status=CheckStatus.ERROR, message=message, **kwargs)
    
    @classmethod
    def skipped(cls, message: str = "Check skipped", **kwargs) -> "CheckResult":
        return cls(status=CheckStatus.SKIPPED, message=message, **kwargs)


class RuleChecker(ABC):
    """Abstract base class for rule checkers (Strategy Pattern)."""
    
    @abstractmethod
    def check(self, config: str | dict, payload: dict) -> CheckResult:
        """
        Execute check against configuration.
        
        Args:
            config: Configuration text (for text-based checks) or dict (for structured)
            payload: Rule logic_payload with check-specific parameters
            
        Returns:
            CheckResult with status and details
        """
        pass
    
    def validate_payload(self, payload: dict) -> list[str]:
        """
        Validate that payload has required fields.
        
        Returns:
            List of validation error messages (empty if valid)
        """
        return []
