"""Provider Registry - Universal provider management.

This module provides a registry pattern for dynamic provider loading,
making it easy to add new data sources without modifying core code.
"""
from typing import Type, Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """
    Central registry for all provider types.
    
    Supports:
    - Config Providers (GitLab, SSH, API, etc.)
    - Inventory Providers (PostgreSQL, API, Static, etc.)
    - Rule Checkers (SimpleMatch, BlockMatch, Structure, etc.)
    
    Usage:
        # Register a provider
        registry.register("config", "netconf", NetconfProvider)
        
        # Get provider instance
        provider = registry.get("config", "netconf", config_dict)
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._providers: Dict[str, Dict[str, Type]] = {
                "config": {},
                "inventory": {},
                "checker": {},
            }
            cls._instance._initialized = False
        return cls._instance
    
    def register(self, category: str, name: str, provider_class: Type):
        """Register a provider class."""
        if category not in self._providers:
            self._providers[category] = {}
        
        self._providers[category][name] = provider_class
        logger.debug(f"Registered {category} provider: {name}")
    
    def get(self, category: str, name: str, config: Optional[dict] = None) -> Any:
        """Get a provider instance."""
        if category not in self._providers:
            raise ValueError(f"Unknown category: {category}")
        
        if name not in self._providers[category]:
            raise ValueError(f"Unknown {category} provider: {name}")
        
        provider_class = self._providers[category][name]
        
        if config is not None:
            return provider_class(config)
        return provider_class()
    
    def list_providers(self, category: str) -> list[str]:
        """List all registered providers in a category."""
        return list(self._providers.get(category, {}).keys())
    
    def has_provider(self, category: str, name: str) -> bool:
        """Check if a provider is registered."""
        return name in self._providers.get(category, {})
    
    def initialize_defaults(self):
        """Register all built-in providers."""
        if self._initialized:
            return
        
        # Config providers
        from app.providers.gitlab import GitLabProvider
        from app.providers.ssh import SSHProvider
        from app.providers.api import APIProvider
        from app.providers.netconf import NetconfProvider
        from app.providers.local import LocalFileProvider, SingleFileProvider
        from app.providers.snmp import SNMPProvider
        
        self.register("config", "gitlab", GitLabProvider)
        self.register("config", "ssh", SSHProvider)
        self.register("config", "api", APIProvider)
        self.register("config", "netconf", NetconfProvider)
        self.register("config", "local", LocalFileProvider)
        self.register("config", "file", SingleFileProvider)
        self.register("config", "snmp", SNMPProvider)
        
        # Firewall-specific providers
        from app.providers.firewall import (
            CheckPointProvider, FortiGateProvider, UserGateProvider, PaloAltoProvider
        )
        self.register("config", "checkpoint", CheckPointProvider)
        self.register("config", "fortigate", FortiGateProvider)
        self.register("config", "usergate", UserGateProvider)
        self.register("config", "paloalto", PaloAltoProvider)
        
        # Inventory providers
        from app.inventory import PostgresInventoryProvider
        from app.inventory import APIInventoryProvider
        from app.inventory import StaticInventoryProvider
        
        self.register("inventory", "postgres", PostgresInventoryProvider)
        self.register("inventory", "api", APIInventoryProvider)
        self.register("inventory", "static", StaticInventoryProvider)
        
        # Rule checkers
        from app.engine.simple_match import SimpleMatchChecker
        from app.engine.block_match import BlockMatchChecker
        from app.engine.structure_check import StructureChecker
        from app.engine.textfsm_check import TextFSMChecker
        from app.engine.xml_check import XMLChecker
        from app.engine.version_check import VersionChecker
        from app.engine.advanced_block import AdvancedBlockChecker
        
        self.register("checker", "simple_match", SimpleMatchChecker)
        self.register("checker", "regex_match", SimpleMatchChecker)  # Alias
        self.register("checker", "block_match", BlockMatchChecker)
        self.register("checker", "block_context_match", BlockMatchChecker)  # Alias
        self.register("checker", "structure_check", StructureChecker)
        self.register("checker", "textfsm_check", TextFSMChecker)
        self.register("checker", "xml_check", XMLChecker)
        self.register("checker", "xpath_check", XMLChecker)  # Alias
        self.register("checker", "version_check", VersionChecker)
        self.register("checker", "advanced_block_check", AdvancedBlockChecker)
        self.register("checker", "nested_block_check", AdvancedBlockChecker)  # Alias
        
        from app.engine.composite_check import CompositeChecker
        self.register("checker", "composite_check", CompositeChecker)
        self.register("checker", "multi_section_check", CompositeChecker)  # Alias
        
        self._initialized = True
        logger.info("Provider registry initialized with defaults")


# Singleton instance
registry = ProviderRegistry()


def get_config_provider(source_type: str, config: dict):
    """Get a config provider by type."""
    registry.initialize_defaults()
    return registry.get("config", source_type, config)


def get_inventory_provider(source_type: str, config: dict):
    """Get an inventory provider by type."""
    registry.initialize_defaults()
    return registry.get("inventory", source_type, config)


def get_checker(logic_type: str):
    """Get a rule checker by logic type."""
    registry.initialize_defaults()
    return registry.get("checker", logic_type)
