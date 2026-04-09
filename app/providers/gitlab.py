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
        "base_path": "configs",
        "ssl_verify": true | false | "/path/to/ca-bundle.crt"
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
        
        # SSL verification: true (default), false (disable), or path to CA bundle
        ssl_val = config.get("ssl_verify", True)
        if isinstance(ssl_val, str) and ssl_val.lower() in ("false", "0", "no"):
            self.ssl_verify = False
        else:
            self.ssl_verify = ssl_val
        
        self._gl = None
        self._project = None
        self._file_cache: dict[str, str] = {}
    
    @property
    def gl(self):
        """Lazy initialization of GitLab client."""
        if self._gl is None:
            import gitlab
            self._gl = gitlab.Gitlab(
                self.url,
                private_token=self.token,
                ssl_verify=self.ssl_verify,
            )
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
    
    def fetch_config(self, device_id: str, context: dict = None) -> FetchResult:
        """Fetch configuration file for device.
        
        Args:
            device_id: hostname or IP of the device
            context: dict with substitution variables for path_template
                     (hostname, ip, dns_name, and any extra_data fields)
        """
        # Build file path from template using context
        fmt_vars = {"hostname": device_id, "device_id": device_id, "ip": device_id}
        if context:
            fmt_vars.update(context)
        
        try:
            file_path = self.path_template.format(**fmt_vars)
        except KeyError as e:
            return FetchResult(
                success=False,
                error=f"path_template references unknown variable: {e}"
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
        
        # Retry on transient SSL/connection errors (common with self-signed certs
        # under concurrent fork workers). Don't retry on 404-type errors.
        import time
        max_retries = 3
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(f"Fetching config: project={self.project_id} path={file_path} ref={self.branch}")
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
                last_error = e
                error_str = str(e).lower()
                # Retry only on SSL / connection / timeout errors
                is_transient = any(k in error_str for k in (
                    "ssl", "connection", "timeout", "max retries", "reset by peer"
                ))
                if is_transient and attempt < max_retries:
                    logger.warning(
                        f"Transient error fetching '{file_path}' (attempt {attempt}/{max_retries}): {e}"
                    )
                    # Reset GitLab client to get a fresh SSL session
                    self._project = None
                    self._gl = None
                    time.sleep(1)
                    continue
                # Not transient or last attempt — give up
                break
        
        logger.warning(f"Failed to fetch '{file_path}' for device {device_id}: {last_error}")
        return FetchResult(
            success=False,
            config=None,
            error=f"File not found: {file_path} ({last_error})"
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
