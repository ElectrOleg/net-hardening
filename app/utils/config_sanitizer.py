"""Config sanitizer — masks sensitive data in device configurations.

Applies regex-based pattern masking to prevent exposure of:
- Passwords and secrets (clear-text and hashed)
- SNMP community strings
- Pre-shared keys (IKE/IPSec)
- API tokens and certificates
- TACACS/RADIUS shared secrets

Patterns are vendor-agnostic where possible, with specific patterns
for Cisco IOS/NXOS, Eltex ESR, Juniper, and common network vendors.
"""

import logging
import re
from typing import Callable

logger = logging.getLogger(__name__)

# Mask placeholder
MASK = "********"

# Compiled regex patterns: list of (pattern, replacement)
# Order matters — more specific patterns first
_SANITIZE_PATTERNS: list[tuple[re.Pattern, str]] = []


def _p(pattern: str, replacement: str = None, flags: int = re.IGNORECASE | re.MULTILINE):
    """Helper to compile and register a sanitize pattern."""
    if replacement is None:
        replacement = rf"\g<1>{MASK}"
    _SANITIZE_PATTERNS.append((re.compile(pattern, flags), replacement))


# ── Cisco IOS / IOS-XE / NXOS ──────────────────────────────────────
_p(r"((?:enable|username\s+\S+)\s+(?:secret|password)\s+\d?\s*)(\S+)", rf"\g<1>{MASK}")
_p(r"(snmp-server\s+community\s+)(\S+)", rf"\g<1>{MASK}")
_p(
    r"(snmp-server\s+(?:user|host)\s+\S+\s+\S+\s+auth\s+\S+\s+)(\S+)(\s+priv\s+\S+\s+)(\S+)",
    rf"\g<1>{MASK}\g<3>{MASK}",
)
_p(r"(tacacs-server\s+key\s+\d?\s*)(\S+)", rf"\g<1>{MASK}")
_p(r"(radius-server\s+key\s+\d?\s*)(\S+)", rf"\g<1>{MASK}")
_p(r"(ip\s+ospf\s+authentication-key\s+)(\S+)", rf"\g<1>{MASK}")
_p(r"(ip\s+ospf\s+message-digest-key\s+\d+\s+md5\s+\d?\s*)(\S+)", rf"\g<1>{MASK}")
_p(r"(standby\s+\d+\s+authentication\s+)(\S+)", rf"\g<1>{MASK}")
_p(r"(key-string\s+)(.+)", rf"\g<1>{MASK}")
_p(r"(crypto\s+isakmp\s+key\s+\d?\s*)(\S+)", rf"\g<1>{MASK}")
_p(r"(pre-shared-key\s+(?:local|remote)?\s*)(\S+)", rf"\g<1>{MASK}")
_p(r"(ntp\s+authentication-key\s+\d+\s+md5\s+)(\S+)", rf"\g<1>{MASK}")

# ── Eltex ESR ──────────────────────────────────────────────────────
_p(r"(password\s+encrypted\s+)(\S+)", rf"\g<1>{MASK}")
_p(r"(snmp-server\s+community\s+)(\S+)", rf"\g<1>{MASK}")
_p(r"(authentication\s+key-chain\s+\S+\s+key\s+\d+\s+key-string\s+)(.+)", rf"\g<1>{MASK}")

# ── Juniper JunOS ──────────────────────────────────────────────────
_p(r'(encrypted-password\s+")([^"]+)(")', rf"\g<1>{MASK}\g<3>")
_p(r'(secret\s+"\$\d\$)([^"]+)(")', rf"\g<1>{MASK}\g<3>")
_p(r"(community\s+)(\S+)(\s+\{)", rf"\g<1>{MASK}\g<3>")
_p(r'(pre-shared-key\s+(?:ascii-text|hexadecimal)\s+")([^"]+)(")', rf"\g<1>{MASK}\g<3>")

# ── Generic / multi-vendor ─────────────────────────────────────────
_p(r"((?:password|passwd|secret|key|token|psk)\s*[:=]\s*)(\S+)", rf"\g<1>{MASK}")
_p(
    r"(-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----).+?(-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----)",
    rf"\g<1>\n{MASK}\n\g<2>",
    re.DOTALL | re.IGNORECASE,
)
_p(
    r"(-----BEGIN\s+CERTIFICATE-----).+?(-----END\s+CERTIFICATE-----)",
    rf"\g<1>\n{MASK}\n\g<2>",
    re.DOTALL | re.IGNORECASE,
)


def sanitize_config(config_text: str) -> str:
    """Mask all sensitive data in a device configuration string.

    Args:
        config_text: Raw configuration text

    Returns:
        Sanitized config with passwords/keys replaced by '********'
    """
    if not config_text:
        return config_text

    result = config_text
    for pattern, replacement in _SANITIZE_PATTERNS:
        result = pattern.sub(replacement, result)

    return result


def get_sanitizer() -> Callable[[str], str]:
    """Return the sanitizer function (for use as callback)."""
    return sanitize_config
