"""Authentication service — local DB + AD LDAP/LDAPS.

Flow:
  1. Try local DB authentication (if user exists with auth_source='local')
  2. If LDAP_ENABLED, try AD bind
  3. On first successful LDAP login, auto-create User record

Decorators:
  - require_auth  — enforces login (session or Bearer token)
  - require_role  — enforces minimum role level
"""

import functools
import logging
from typing import Optional

from flask import g, jsonify, redirect, request, session, url_for

from app.extensions import db
from app.utils import utc_now

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   Decorators
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ROLE_HIERARCHY = {"admin": 3, "operator": 2, "viewer": 1}


def require_auth(f):
    """Decorator: require authenticated session or Bearer token."""

    @functools.wraps(f)
    def decorated(*args, **kwargs):
        from app.config import settings

        # Kill-switch for development
        if not getattr(settings, "AUTH_ENABLED", False):
            g.current_user = {"username": "anonymous", "role": "admin"}
            return f(*args, **kwargs)

        user = _get_current_user()
        if not user:
            # API requests get JSON 401; browser requests → redirect
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("web.login_page"))

        g.current_user = user.to_dict()
        return f(*args, **kwargs)

    return decorated


def require_role(*roles):
    """Decorator: require specific role(s). Must be placed after @require_auth."""

    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            user = getattr(g, "current_user", {})
            user_role = user.get("role", "viewer")
            if user_role not in roles and user_role != "admin":
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Insufficient permissions"}), 403
                return redirect(url_for("web.dashboard"))
            return f(*args, **kwargs)

        return decorated

    return decorator


def _get_current_user():
    """Resolve current user from session or Bearer token."""
    from app.models.user import User

    # 1. Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        return _validate_api_token(token)

    # 2. Session
    user_id = session.get("user_id")
    if user_id:
        import uuid

        try:
            user = db.session.get(User, uuid.UUID(str(user_id)))
        except (ValueError, TypeError, AttributeError):
            user = None
        if user and user.is_active:
            return user

    return None


def _validate_api_token(token: str):
    """Validate Bearer token. Returns User or None."""
    from app.config import settings
    from app.models.user import User

    expected = getattr(settings, "API_TOKEN", "")
    if expected and token == expected:
        # Return a virtual admin user for API token auth
        admin = User.query.filter_by(role="admin", is_active=True).first()
        return admin
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   Authentication Logic
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _get_ldap_setting(key: str, default=None):
    """Retrieve an LDAP setting from the database SystemSetting table,
    falling back to settings from the config/env if not found or empty.
    """
    from app.config import settings
    from app.models.system_setting import SystemSetting

    db_key = key.lower()
    config_key = key.upper()
    if not config_key.startswith("LDAP_"):
        config_key = f"LDAP_{config_key}"

    env_default = getattr(settings, config_key, default)

    setting = SystemSetting.query.filter_by(key=db_key).first()
    if setting is not None:
        val = setting.value
        if isinstance(env_default, bool):
            return val.lower() in ("true", "1", "yes", "on")
        elif isinstance(env_default, int):
            try:
                return int(val)
            except (ValueError, TypeError):
                return env_default
        else:
            return val
    return env_default


def authenticate(username: str, password: str) -> Optional["User"]:
    """Authenticate user via local DB or LDAP.

    Returns User on success, None on failure.
    """
    from app.models.user import User

    if not username or not password:
        return None

    username = username.strip().lower()

    # 1. Try local authentication
    user = User.query.filter_by(username=username, auth_source="local").first()
    if user and user.is_active and user.check_password(password):
        user.last_login_at = utc_now()
        from app.extensions import db

        db.session.commit()
        return user

    # 2. Try LDAP if enabled
    if _get_ldap_setting("ldap_enabled"):
        ldap_result = ldap_authenticate(username, password)
        if ldap_result:
            return ldap_result

    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   LDAP / Active Directory
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def ldap_authenticate(username: str, password: str) -> Optional["User"]:
    """Authenticate against AD via LDAP/LDAPS.

    On first successful bind, creates a local User record with
    auth_source='ldap' and syncs display_name + email from AD.
    """
    try:
        import ldap3
        from ldap3 import SUBTREE, Connection, Server, Tls
    except ImportError:
        logger.error("ldap3 package not installed — pip install ldap3")
        return None

    try:
        # Build server config
        tls_config = None
        use_ssl = _get_ldap_setting("ldap_use_ssl")
        starttls = _get_ldap_setting("ldap_starttls")
        cert_validation = _get_ldap_setting("ldap_cert_validation")
        server_url = _get_ldap_setting("ldap_server")
        port = _get_ldap_setting("ldap_port")
        bind_dn = _get_ldap_setting("ldap_bind_dn")
        bind_password = _get_ldap_setting("ldap_bind_password")
        user_filter_tpl = _get_ldap_setting("ldap_user_filter")
        attr_username = _get_ldap_setting("ldap_attr_username")
        attr_email = _get_ldap_setting("ldap_attr_email")
        attr_display_name = _get_ldap_setting("ldap_attr_display_name")
        base_dn = _get_ldap_setting("ldap_base_dn")

        if use_ssl or starttls:
            import ssl

            validate_map = {
                "NONE": ssl.CERT_NONE,
                "OPTIONAL": ssl.CERT_OPTIONAL,
                "REQUIRED": ssl.CERT_REQUIRED,
            }
            tls_config = Tls(
                validate=validate_map.get(cert_validation, ssl.CERT_REQUIRED),
            )

        server = Server(
            server_url,
            port=port,
            use_ssl=use_ssl,
            tls=tls_config,
            get_info=ldap3.ALL,
        )

        # Step 1: Bind with service account to find user DN
        service_conn = Connection(
            server,
            user=bind_dn,
            password=bind_password,
            auto_bind=True,
            raise_exceptions=True,
        )

        if starttls and not use_ssl:
            service_conn.start_tls()

        # Search for user
        user_filter = user_filter_tpl.replace("{username}", username)
        attrs = [
            attr_username,
            attr_email,
            attr_display_name,
            "memberOf",
        ]

        service_conn.search(
            search_base=base_dn,
            search_filter=user_filter,
            search_scope=SUBTREE,
            attributes=attrs,
        )

        if not service_conn.entries:
            logger.info(f"LDAP: user '{username}' not found")
            service_conn.unbind()
            return None

        entry = service_conn.entries[0]
        user_dn = entry.entry_dn
        service_conn.unbind()

        # Step 2: Bind as user to verify password
        user_conn = Connection(
            server,
            user=user_dn,
            password=password,
            auto_bind=True,
            raise_exceptions=True,
        )

        if starttls and not use_ssl:
            user_conn.start_tls()

        # If we reach here, auth succeeded
        user_conn.unbind()

        # Extract attributes
        display_name = str(getattr(entry, attr_display_name, username))
        email = str(getattr(entry, attr_email, ""))
        member_of = [str(g) for g in getattr(entry, "memberOf", [])]

        # Determine role from AD group membership
        role = _resolve_ldap_role(member_of)

        # Create or update local User record
        return _upsert_ldap_user(username, display_name, email, role)

    except Exception as e:
        logger.error(f"LDAP authentication failed for '{username}': {e}")
        return None


def _resolve_ldap_role(member_of: list[str]) -> str:
    """Map AD group membership to HCS role."""
    admin_group = _get_ldap_setting("ldap_admin_group", "")
    operator_group = _get_ldap_setting("ldap_operator_group", "")

    member_of_lower = [g.lower() for g in member_of]

    if admin_group and admin_group.lower() in member_of_lower:
        return "admin"
    if operator_group and operator_group.lower() in member_of_lower:
        return "operator"
    return "viewer"


def _upsert_ldap_user(username: str, display_name: str, email: str, role: str):
    """Create or update User record for LDAP user."""
    from app.extensions import db
    from app.models.user import User

    user = User.query.filter_by(username=username).first()

    if user:
        # Update attributes from AD
        user.display_name = display_name
        user.email = email
        user.role = role
        user.auth_source = "ldap"
        user.last_login_at = utc_now()
    else:
        user = User(
            username=username,
            display_name=display_name,
            email=email,
            auth_source="ldap",
            role=role,
            is_active=True,
            last_login_at=utc_now(),
        )
        db.session.add(user)

    db.session.commit()
    logger.info(f"LDAP user '{username}' authenticated (role={role})")
    return user


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   LDAP Connection Test
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_ldap_connection(config: dict) -> dict:
    """Test LDAP connection with provided or saved settings.

    Returns dict with 'success', 'message', and optional 'details'.
    """
    try:
        import ldap3
        from ldap3 import Connection, Server, Tls
    except ImportError:
        return {"success": False, "message": "ldap3 package not installed (pip install ldap3)"}

    server_url = config.get("server", "")
    port = int(config.get("port", 389))
    use_ssl = config.get("use_ssl", False)
    starttls = config.get("starttls", False)
    bind_dn = config.get("bind_dn", "")
    bind_password = config.get("bind_password", "")
    base_dn = config.get("base_dn", "")
    cert_validation = config.get("cert_validation", "REQUIRED")

    if not server_url:
        return {"success": False, "message": "LDAP server URL is required"}

    try:
        # Build TLS config
        tls_config = None
        if use_ssl or starttls:
            import ssl

            validate_map = {
                "NONE": ssl.CERT_NONE,
                "OPTIONAL": ssl.CERT_OPTIONAL,
                "REQUIRED": ssl.CERT_REQUIRED,
            }
            tls_config = Tls(
                validate=validate_map.get(cert_validation, ssl.CERT_REQUIRED),
            )

        server = Server(
            server_url,
            port=port,
            use_ssl=use_ssl,
            tls=tls_config,
            get_info=ldap3.ALL,
        )

        conn = Connection(
            server,
            user=bind_dn,
            password=bind_password,
            auto_bind=True,
            raise_exceptions=True,
        )

        if starttls and not use_ssl:
            conn.start_tls()

        # Try a base-level search to verify base_dn
        details = {
            "server_info": str(server.info.naming_contexts) if server.info else "N/A",
            "who_am_i": "",
        }

        try:
            details["who_am_i"] = conn.extend.standard.who_am_i() or bind_dn
        except Exception:
            details["who_am_i"] = bind_dn

        if base_dn:
            conn.search(
                search_base=base_dn,
                search_filter="(objectClass=*)",
                search_scope=ldap3.BASE,
            )
            details["base_dn_accessible"] = len(conn.entries) > 0

        conn.unbind()

        return {
            "success": True,
            "message": f"Successfully connected to {server_url}:{port}",
            "details": details,
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Connection failed: {str(e)}",
        }
