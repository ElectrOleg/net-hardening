"""GitLab Provider - fetch configs from GitLab repository."""
import fnmatch
import logging
from typing import Optional

from app.providers.base import ConfigSourceProvider, FetchResult

logger = logging.getLogger(__name__)


class GitLabProvider(ConfigSourceProvider):
    """
    Provider for fetching configurations from GitLab repository.
    
    Connection params:
    {
        "url": "https://gitlab.example.com",
        "token": "glpat-xxx",
        "project_id": "123",
        "branch": "main",
        "path_template": "configs/{hostname}.cfg",
        "file_pattern": "*.cfg",
        "base_path": "configs"
    }
    """
    
    def __init__(self, config: dict):
        self.url = config.get("url", "")
        self.token = config.get("token", "")
        self.project_id = config.get("project_id", "")
        self.branch = config.get("branch", "main")
        self.path_template = config.get("path_template", "{hostname}.cfg")
        self.file_pattern = config.get("file_pattern", "*.cfg")
        self.base_path = config.get("base_path", "").rstrip("/")
        
        self._gl = None
        self._project = None
        self._file_cache: dict[str, str] = {}
    
    @property
    def gl(self):
        """Lazy initialization of GitLab client."""
        if self._gl is None:
            import gitlab
            self._gl = gitlab.Gitlab(self.url, private_token=self.token)
        return self._gl
    
    @property
    def project(self):
        """Lazy initialization of project."""
        if self._project is None:
            self._project = self.gl.projects.get(self.project_id)
        return self._project
    
    def test_connection(self) -> tuple[bool, str]:
        """Test connection to GitLab."""
        try:
            project = self.project
            return True, f"Connected to project: {project.name}"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"
    
    def fetch_config(self, device_id: str) -> FetchResult:
        """Fetch configuration file for device."""
        # Build file path from template
        file_path = self.path_template.format(
            hostname=device_id,
            device_id=device_id,
            ip=device_id
        )
        
        if self.base_path:
            file_path = f"{self.base_path}/{file_path}"
        
        # Check cache first
        if file_path in self._file_cache:
            return FetchResult(
                success=True,
                config=self._file_cache[file_path],
                metadata={"cached": True, "path": file_path}
            )
        
        try:
            file = self.project.files.get(file_path=file_path, ref=self.branch)
            content = file.decode().decode("utf-8")
            
            # Cache the result
            self._file_cache[file_path] = content
            
            return FetchResult(
                success=True,
                config=content,
                metadata={
                    "path": file_path,
                    "ref": self.branch,
                    "commit_id": file.commit_id,
                    "last_commit_id": file.last_commit_id
                }
            )
        except Exception as e:
            logger.error(f"Failed to fetch config for {device_id}: {e}")
            return FetchResult(
                success=False,
                config=None,
                error=str(e)
            )
    
    def list_devices(self) -> list[str]:
        """List devices by scanning repository files."""
        devices = []
        
        try:
            # Get repository tree
            tree = self.project.repository_tree(
                path=self.base_path or "",
                ref=self.branch,
                recursive=True,
                all=True
            )
            
            for item in tree:
                if item["type"] != "blob":
                    continue
                
                name = item["name"]
                
                # Match against file pattern
                if fnmatch.fnmatch(name, self.file_pattern):
                    # Extract device ID from filename
                    device_id = self._extract_device_id(name)
                    if device_id:
                        devices.append(device_id)
            
            return sorted(devices)
            
        except Exception as e:
            logger.error(f"Failed to list devices: {e}")
            return []
    
    def _extract_device_id(self, filename: str) -> Optional[str]:
        """Extract device ID from filename based on path_template."""
        # Simple extraction: remove known extensions
        for ext in [".cfg", ".conf", ".txt", ".config"]:
            if filename.endswith(ext):
                return filename[:-len(ext)]
        return filename
    
    def prefetch_all(self) -> int:
        """Prefetch all configs into cache. Returns count of loaded files."""
        devices = self.list_devices()
        count = 0
        
        for device_id in devices:
            result = self.fetch_config(device_id)
            if result.success:
                count += 1
        
        return count
    
    def clear_cache(self):
        """Clear the file cache."""
        self._file_cache.clear()
    
    def close(self):
        """Clean up GitLab connection."""
        self._file_cache.clear()
        self._project = None
        self._gl = None
