"""Credential Resolver - resolve credentials from multiple backends.

Supports:
- Environment variables (default): env://VAR_NAME or just VAR_NAME
- File: file:///path/to/secret
- Vault stub: vault://secret/path#key (requires hvac)
"""
import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CredentialResolver:
    """Resolve credentials from various sources.
    
    Usage:
        resolver = CredentialResolver()
        password = resolver.resolve("env://DB_PASSWORD")
        token = resolver.resolve("file:///run/secrets/api_token")
        secret = resolver.resolve("vault://secret/data/gitlab#token")
        
        # Legacy: plain env var name
        password = resolver.resolve("MY_PASSWORD")
    """
    
    def __init__(self, vault_url: Optional[str] = None, vault_token: Optional[str] = None):
        self.vault_url = vault_url or os.environ.get("VAULT_ADDR")
        self.vault_token = vault_token or os.environ.get("VAULT_TOKEN")
        self._vault_client = None
    
    def resolve(self, ref: str) -> str:
        """Resolve a credential reference to its actual value.
        
        Args:
            ref: Credential reference string. Formats:
                - "env://VAR_NAME" - environment variable
                - "file:///path/to/secret" - read from file
                - "vault://secret/path#key" - HashiCorp Vault
                - "VAR_NAME" - plain env var name (legacy/default)
                
        Returns:
            Resolved credential string, or empty string if not found.
        """
        if not ref:
            return ""
        
        ref = ref.strip()
        
        try:
            if ref.startswith("env://"):
                return self._from_env(ref[6:])
            elif ref.startswith("file://"):
                return self._from_file(ref[7:])
            elif ref.startswith("vault://"):
                return self._from_vault(ref[8:])
            else:
                # Legacy: treat as plain env var name
                return self._from_env(ref)
        except Exception as e:
            logger.error(f"Failed to resolve credential '{ref}': {e}")
            return ""
    
    def _from_env(self, var_name: str) -> str:
        """Resolve from environment variable."""
        value = os.environ.get(var_name, "")
        if not value:
            logger.debug(f"Environment variable '{var_name}' not set or empty")
        return value
    
    def _from_file(self, file_path: str) -> str:
        """Resolve from file contents."""
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"Credential file not found: {file_path}")
            return ""
        
        try:
            return path.read_text().strip()
        except Exception as e:
            logger.error(f"Failed to read credential file {file_path}: {e}")
            return ""
    
    def _from_vault(self, vault_path: str) -> str:
        """Resolve from HashiCorp Vault.
        
        Format: secret/path#key
        """
        if not self.vault_url:
            logger.warning("VAULT_ADDR not configured, cannot resolve vault credentials")
            return ""
        
        try:
            import hvac
        except ImportError:
            logger.error("hvac not installed. pip install hvac")
            return ""
        
        # Parse path and key
        if "#" in vault_path:
            path, key = vault_path.rsplit("#", 1)
        else:
            path = vault_path
            key = "value"
        
        try:
            if self._vault_client is None:
                self._vault_client = hvac.Client(
                    url=self.vault_url,
                    token=self.vault_token
                )
            
            secret = self._vault_client.secrets.kv.v2.read_secret_version(
                path=path
            )
            data = secret.get("data", {}).get("data", {})
            return str(data.get(key, ""))
            
        except Exception as e:
            logger.error(f"Failed to read from Vault at '{vault_path}': {e}")
            return ""


# Singleton instance
_resolver: Optional[CredentialResolver] = None


def get_credential_resolver() -> CredentialResolver:
    """Get or create the singleton credential resolver."""
    global _resolver
    if _resolver is None:
        _resolver = CredentialResolver()
    return _resolver


def resolve_credential(ref: str) -> str:
    """Convenience function to resolve a credential reference."""
    return get_credential_resolver().resolve(ref)
