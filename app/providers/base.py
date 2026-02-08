"""Base class for configuration source providers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FetchResult:
    """Result of fetching a configuration."""
    success: bool
    config: str | dict | None = None
    error: str | None = None
    metadata: dict | None = None
    format: str = "text"  # text, json, xml


class ConfigSourceProvider(ABC):
    """Abstract base class for configuration source providers."""
    
    @abstractmethod
    def fetch_config(self, device_id: str) -> FetchResult:
        """
        Fetch configuration for a specific device.
        
        Args:
            device_id: Device identifier (hostname, IP, etc.)
            
        Returns:
            FetchResult with config text/dict or error
        """
        pass
    
    @abstractmethod
    def list_devices(self) -> list[str]:
        """
        List all available devices from this source.
        
        Returns:
            List of device identifiers
        """
        pass
    
    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """
        Test connectivity to the data source.
        
        Returns:
            Tuple of (success, message)
        """
        pass
    
    def close(self):
        """Clean up resources (optional)."""
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
