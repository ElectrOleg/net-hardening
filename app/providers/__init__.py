"""HCS Data Source Providers."""
from app.providers.base import ConfigSourceProvider, FetchResult
from app.providers.gitlab import GitLabProvider
from app.providers.ssh import SSHProvider
from app.providers.api import APIProvider
from app.providers.netconf import NetconfProvider
from app.providers.snmp import SNMPProvider
from app.providers.local import LocalFileProvider, SingleFileProvider
from app.providers.firewall import (
    CheckPointProvider,
    FortiGateProvider,
    UserGateProvider,
    PaloAltoProvider,
)

__all__ = [
    "ConfigSourceProvider",
    "FetchResult",
    "GitLabProvider",
    "SSHProvider",
    "APIProvider",
    "NetconfProvider",
    "SNMPProvider",
    "LocalFileProvider",
    "SingleFileProvider",
    "CheckPointProvider",
    "FortiGateProvider",
    "UserGateProvider",
    "PaloAltoProvider",
]
