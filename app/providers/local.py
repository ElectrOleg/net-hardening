"""Local Files Provider - Load configurations from local filesystem.

Useful for:
- Offline analysis without network access
- Batch processing of exported configs
- CI/CD pipeline integration
- Testing and development
"""
import os
import logging
from pathlib import Path
from typing import Optional

from app.providers.base import ConfigSourceProvider, FetchResult

logger = logging.getLogger(__name__)


class LocalFileProvider(ConfigSourceProvider):
    """
    Provider for loading configs from local filesystem.
    
    Config parameters:
        base_path: Base directory containing config files
        pattern: Glob pattern for finding files (default: "*.conf")
        file_extension: Alternative to pattern - just extension
        encoding: File encoding (default: utf-8)
        device_id_from: How to determine device_id:
            - "filename" (default) - use filename without extension
            - "dirname" - use parent directory name
            - "path" - use relative path
    """
    
    SOURCE_TYPE = "local"
    
    def __init__(self, config: dict):
        self.base_path = Path(config.get("base_path", "."))
        self.pattern = config.get("pattern", "*.conf")
        self.encoding = config.get("encoding", "utf-8")
        self.device_id_from = config.get("device_id_from", "filename")
        
        # Cache of discovered files
        self._file_cache: dict[str, Path] = {}
    
    def _discover_files(self):
        """Discover all config files."""
        if self._file_cache:
            return
        
        if not self.base_path.exists():
            logger.warning(f"Base path does not exist: {self.base_path}")
            return
        
        for file_path in self.base_path.rglob(self.pattern):
            if file_path.is_file():
                device_id = self._get_device_id(file_path)
                self._file_cache[device_id] = file_path
        
        logger.info(f"Discovered {len(self._file_cache)} config files")
    
    def _get_device_id(self, file_path: Path) -> str:
        """Extract device ID from file path."""
        if self.device_id_from == "dirname":
            return file_path.parent.name
        elif self.device_id_from == "path":
            return str(file_path.relative_to(self.base_path))
        else:  # filename
            return file_path.stem
    
    def fetch_config(self, device_id: str) -> FetchResult:
        """
        Load configuration from file.
        
        Args:
            device_id: Device identifier (filename or as configured)
        """
        self._discover_files()
        
        # Try direct lookup
        file_path = self._file_cache.get(device_id)
        
        # Try as direct path
        if not file_path:
            direct_path = self.base_path / device_id
            if direct_path.exists():
                file_path = direct_path
            else:
                # Try with common extensions
                for ext in [".conf", ".cfg", ".txt", ".xml", ".json"]:
                    test_path = self.base_path / f"{device_id}{ext}"
                    if test_path.exists():
                        file_path = test_path
                        break
        
        if not file_path or not file_path.exists():
            return FetchResult(
                success=False,
                error=f"Config file not found for device: {device_id}"
            )
        
        try:
            content = file_path.read_text(encoding=self.encoding)
            
            # Detect format
            format_type = "text"
            if file_path.suffix == ".xml":
                format_type = "xml"
            elif file_path.suffix == ".json":
                format_type = "json"
            
            return FetchResult(
                success=True,
                config=content,
                format=format_type
            )
            
        except Exception as e:
            logger.exception(f"Failed to read config file: {file_path}")
            return FetchResult(success=False, error=str(e))
    
    def list_devices(self) -> list[str]:
        """List all discovered devices."""
        self._discover_files()
        return list(self._file_cache.keys())
    
    # Alias for backward compat
    list_available_devices = list_devices
    
    def test_connection(self) -> tuple[bool, str]:
        """Test that base path exists and is readable."""
        if not self.base_path.exists():
            return False, f"Path does not exist: {self.base_path}"
        
        if not self.base_path.is_dir():
            return False, f"Path is not a directory: {self.base_path}"
        
        self._discover_files()
        return True, f"Found {len(self._file_cache)} config files"
    
    def close(self):
        """Clear file cache."""
        self._file_cache.clear()


class SingleFileProvider(ConfigSourceProvider):
    """
    Provider for a single config file.
    
    Useful when analyzing one specific file.
    """
    
    SOURCE_TYPE = "single_file"
    
    def __init__(self, config: dict):
        self.file_path = Path(config.get("file_path", ""))
        self.encoding = config.get("encoding", "utf-8")
        self.device_id = config.get("device_id", self.file_path.stem)
    
    def fetch_config(self, device_id: str) -> FetchResult:
        """Load the configured file."""
        if not self.file_path.exists():
            return FetchResult(
                success=False,
                error=f"File not found: {self.file_path}"
            )
        
        try:
            content = self.file_path.read_text(encoding=self.encoding)
            return FetchResult(success=True, config=content)
        except Exception as e:
            return FetchResult(success=False, error=str(e))
    
    def list_devices(self) -> list[str]:
        return [self.device_id]
    
    # Alias for backward compat
    list_available_devices = list_devices
    
    def test_connection(self) -> tuple[bool, str]:
        if self.file_path.exists():
            return True, f"File exists: {self.file_path}"
        return False, f"File not found: {self.file_path}"
