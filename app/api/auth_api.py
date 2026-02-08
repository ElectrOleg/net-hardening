"""Authentication API — login, logout, user management, LDAP settings."""
from flask import jsonify, request, session
from app.api import api_bp
from app.extensions import db
from app.auth import require_auth, require_role, authenticate, test_ldap_connection


# ─── Login / Logout ───────────────────────────────────────────────

@api_bp.route("/auth/login", methods=["POST"])
def api_login():
    """Authenticate user and create session.

    Body: {"username": "...", "password": "..."}
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    user = authenticate(username, password)
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    # Set session
    session["user_id"] = str(user.id)
    session["username"] = user.username
    session["role"] = user.role
    session.permanent = True

    return jsonify({
        "message": "Login successful",
        "user": user.to_dict(),
    })


@api_bp.route("/auth/logout", methods=["POST"])
def api_logout():
    """Clear session."""
    session.clear()
    return jsonify({"message": "Logged out"})


@api_bp.route("/auth/me", methods=["GET"])
@require_auth
def api_me():
    """Get current user info."""
    from flask import g
    return jsonify(g.current_user)


# ─── User Management (admin only) ─────────────────────────────────

@api_bp.route("/admin/users", methods=["GET"])
@require_auth
@require_role("admin")
def list_users():
    """List all users."""
    from app.models.user import User
    users = User.query.order_by(User.username).all()
    return jsonify([u.to_dict() for u in users])


@api_bp.route("/admin/users", methods=["POST"])
@require_auth
@require_role("admin")
def create_user():
    """Create a local user.

    Body: {"username": "...", "password": "...", "display_name": "...",
           "email": "...", "role": "viewer|operator|admin"}
    """
    from app.models.user import User

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""

    if not username:
        return jsonify({"error": "Username is required"}), 400
    if not password or len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"error": f"User '{username}' already exists"}), 409

    role = data.get("role", "viewer")
    if role not in ("admin", "operator", "viewer"):
        return jsonify({"error": "Invalid role. Must be: admin, operator, viewer"}), 400

    user = User(
        username=username,
        display_name=data.get("display_name", username),
        email=data.get("email", ""),
        auth_source="local",
        role=role,
        is_active=True,
    )
    user.set_password(password)

    db.session.add(user)
    db.session.commit()

    return jsonify(user.to_dict()), 201


@api_bp.route("/admin/users/<uuid:user_id>", methods=["PUT"])
@require_auth
@require_role("admin")
def update_user(user_id):
    """Update user properties (role, active, display_name, email, password)."""
    from app.models.user import User

    user = User.query.get_or_404(user_id)
    data = request.get_json()

    if "display_name" in data:
        user.display_name = data["display_name"]
    if "email" in data:
        user.email = data["email"]
    if "role" in data:
        if data["role"] not in ("admin", "operator", "viewer"):
            return jsonify({"error": "Invalid role"}), 400
        user.role = data["role"]
    if "is_active" in data:
        user.is_active = data["is_active"]
    if "password" in data and data["password"]:
        if len(data["password"]) < 6:
            return jsonify({"error": "Password must be at least 6 characters"}), 400
        user.set_password(data["password"])

    db.session.commit()
    return jsonify(user.to_dict())


@api_bp.route("/admin/users/<uuid:user_id>", methods=["DELETE"])
@require_auth
@require_role("admin")
def delete_user(user_id):
    """Deactivate a user (soft delete)."""
    from app.models.user import User
    from flask import g

    user = User.query.get_or_404(user_id)

    # Prevent self-deletion
    current = g.current_user
    if str(user.id) == current.get("id"):
        return jsonify({"error": "Cannot delete yourself"}), 400

    user.is_active = False
    db.session.commit()

    return jsonify({"message": f"User '{user.username}' deactivated"})


# ─── LDAP Settings ─────────────────────────────────────────────────

@api_bp.route("/admin/ldap/settings", methods=["GET"])
@require_auth
@require_role("admin")
def get_ldap_settings():
    """Get current LDAP settings from SystemSetting."""
    from app.models.system_setting import SystemSetting

    ldap_keys = [
        "ldap_enabled", "ldap_server", "ldap_port", "ldap_use_ssl",
        "ldap_starttls", "ldap_bind_dn", "ldap_bind_password",
        "ldap_base_dn", "ldap_user_filter", "ldap_attr_username",
        "ldap_attr_email", "ldap_attr_display_name",
        "ldap_admin_group", "ldap_operator_group",
        "ldap_cert_validation",
    ]

    settings = {}
    for key in ldap_keys:
        setting = SystemSetting.query.filter_by(key=key).first()
        if setting:
            settings[key] = setting.value
        else:
            settings[key] = _ldap_defaults().get(key, "")

    # Never expose bind password in full
    if settings.get("ldap_bind_password"):
        settings["ldap_bind_password"] = "••••••••"

    return jsonify(settings)


@api_bp.route("/admin/ldap/settings", methods=["PUT"])
@require_auth
@require_role("admin")
def update_ldap_settings():
    """Save LDAP settings to SystemSetting."""
    from app.models.system_setting import SystemSetting

    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({"error": "JSON object required"}), 400

    allowed_keys = {
        "ldap_enabled", "ldap_server", "ldap_port", "ldap_use_ssl",
        "ldap_starttls", "ldap_bind_dn", "ldap_bind_password",
        "ldap_base_dn", "ldap_user_filter", "ldap_attr_username",
        "ldap_attr_email", "ldap_attr_display_name",
        "ldap_admin_group", "ldap_operator_group",
        "ldap_cert_validation",
    }

    updated = []
    for key, value in data.items():
        if key not in allowed_keys:
            continue
        # Skip masked password placeholder
        if key == "ldap_bind_password" and value == "••••••••":
            continue
        SystemSetting.set(key, str(value))
        updated.append(key)

    db.session.commit()

    return jsonify({"updated": updated})


@api_bp.route("/admin/ldap/test", methods=["POST"])
@require_auth
@require_role("admin")
def test_ldap():
    """Test LDAP connection with provided settings.

    Body: full LDAP config dict or empty (uses saved settings).
    """
    data = request.get_json() or {}

    # Build config from request or saved settings
    if data.get("server"):
        config = {
            "server": data.get("server", ""),
            "port": data.get("port", 389),
            "use_ssl": data.get("use_ssl", False),
            "starttls": data.get("starttls", False),
            "bind_dn": data.get("bind_dn", ""),
            "bind_password": data.get("bind_password", ""),
            "base_dn": data.get("base_dn", ""),
            "cert_validation": data.get("cert_validation", "REQUIRED"),
        }
    else:
        config = _load_ldap_config_from_db()

    result = test_ldap_connection(config)
    status_code = 200 if result["success"] else 400
    return jsonify(result), status_code


def _ldap_defaults():
    return {
        "ldap_enabled": "false",
        "ldap_server": "",
        "ldap_port": "389",
        "ldap_use_ssl": "false",
        "ldap_starttls": "false",
        "ldap_bind_dn": "",
        "ldap_bind_password": "",
        "ldap_base_dn": "",
        "ldap_user_filter": "(sAMAccountName={username})",
        "ldap_attr_username": "sAMAccountName",
        "ldap_attr_email": "mail",
        "ldap_attr_display_name": "displayName",
        "ldap_admin_group": "",
        "ldap_operator_group": "",
        "ldap_cert_validation": "REQUIRED",
    }


def _load_ldap_config_from_db():
    """Load LDAP settings from SystemSetting for connection test."""
    from app.models.system_setting import SystemSetting

    def _get(key, default=""):
        s = SystemSetting.query.filter_by(key=key).first()
        return s.value if s else default

    return {
        "server": _get("ldap_server"),
        "port": int(_get("ldap_port", "389")),
        "use_ssl": _get("ldap_use_ssl") == "true",
        "starttls": _get("ldap_starttls") == "true",
        "bind_dn": _get("ldap_bind_dn"),
        "bind_password": _get("ldap_bind_password"),
        "base_dn": _get("ldap_base_dn"),
        "cert_validation": _get("ldap_cert_validation", "REQUIRED"),
    }
