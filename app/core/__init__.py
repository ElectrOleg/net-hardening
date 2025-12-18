"""Core module initialization."""
from app.core.registry import (
    ProviderRegistry,
    registry,
    get_config_provider,
    get_inventory_provider,
    get_checker,
)

__all__ = [
    "ProviderRegistry",
    "registry",
    "get_config_provider",
    "get_inventory_provider", 
    "get_checker",
]
