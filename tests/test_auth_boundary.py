import uuid

from app.models import ConfigSnapshot, Device


def _login(client, username, password):
    return client.post(
        "/login", data={"username": username, "password": password}, follow_redirects=True
    )


def test_anonymous_access(client):
    """Anonymous access is redirected to login for web, 401 for API."""
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 302
    assert "/login" in res.location

    res = client.get("/api/devices", follow_redirects=False)
    assert res.status_code == 401

    res = client.get("/health")
    assert res.status_code == 200
    assert res.json == {"status": "ok"}


def test_viewer_role_access(client, viewer_user):
    """Viewer role is read-only for general resources, forbidden from admin sections."""
    _login(client, "viewer", "viewer_pass")

    res = client.get("/api/devices")
    assert res.status_code == 200

    res = client.post("/api/scans")
    assert res.status_code == 403

    res = client.get("/admin", follow_redirects=False)
    assert res.status_code == 302

    res = client.get("/api/admin/settings")
    assert res.status_code == 403


def test_operator_role_access(client, operator_user):
    """Operator role can execute actions but cannot access admin sections."""
    _login(client, "operator", "operator_pass")

    res = client.get("/api/devices")
    assert res.status_code == 200

    from unittest.mock import patch

    with patch("app.tasks.scan_tasks.run_scan") as mock_run_scan:
        mock_run_scan.delay.return_value = None
        res = client.post("/api/scans", json={})
        assert res.status_code != 403

    res = client.get("/api/admin/settings")
    assert res.status_code == 403


def test_admin_role_access(client, admin_user):
    """Admin role has unrestricted access."""
    _login(client, "admin", "admin_pass")

    res = client.get("/api/admin/settings")
    assert res.status_code == 200

    res = client.get("/admin")
    assert res.status_code == 200


def test_configs_blueprint_rbac(client, session, admin_user, operator_user, viewer_user):
    """Verify configs blueprint endpoints register and enforce role limits."""

    d = Device(id=uuid.uuid4(), hostname="test-router", vendor_code="cisco_ios", is_active=True)
    session.add(d)
    session.commit()

    snap = ConfigSnapshot(
        id=uuid.uuid4(),
        device_id=d.id,
        config_text="secret password plain",
        config_hash="h123",
        config_size=21,
        vendor_code="cisco_ios",
        is_changed=True,
    )
    session.add(snap)
    session.commit()

    _login(client, "viewer", "viewer_pass")
    res = client.get(f"/api/configs/{snap.id}/raw")
    assert res.status_code == 403

    _login(client, "operator", "operator_pass")
    res = client.get(f"/api/configs/{snap.id}/raw")
    assert res.status_code == 403

    _login(client, "admin", "admin_pass")
    res = client.get(f"/api/configs/{snap.id}/raw")
    assert res.status_code == 200
    assert "secret password plain" in res.text


def test_get_ldap_setting_helper(session):
    """Test _get_ldap_setting helper with db overrides and env fallbacks."""
    from app.auth import _get_ldap_setting
    from app.models.system_setting import SystemSetting

    # Ensure clean slate / verify defaults
    assert _get_ldap_setting("ldap_enabled") is False
    assert _get_ldap_setting("ldap_port") == 389

    # Add DB setting
    session.add(SystemSetting(key="ldap_enabled", value="true"))
    session.add(SystemSetting(key="ldap_port", value="636"))
    session.add(SystemSetting(key="ldap_server", value="ldaps://ldap.example.com"))
    session.commit()

    # Now verify it reads from database
    assert _get_ldap_setting("ldap_enabled") is True
    assert _get_ldap_setting("ldap_port") == 636
    assert _get_ldap_setting("ldap_server") == "ldaps://ldap.example.com"

    # Cleanup settings
    SystemSetting.query.filter(
        SystemSetting.key.in_(["ldap_enabled", "ldap_port", "ldap_server"])
    ).delete()
    session.commit()


def test_ldap_test_connection_masked_password(client, admin_user, session):
    """Test that LDAP connection test replaces masked password with DB stored value."""
    from unittest.mock import patch

    from app.models.system_setting import SystemSetting

    _login(client, "admin", "admin_pass")

    # Store real password in DB
    session.add(SystemSetting(key="ldap_bind_password", value="real_secret_password"))
    session.commit()

    # Send request with masked password
    with patch("app.api.auth_api.test_ldap_connection") as mock_test_conn:
        mock_test_conn.return_value = {"success": True, "message": "Success"}

        payload = {
            "server": "ldap.example.com",
            "port": 389,
            "bind_dn": "cn=admin",
            "bind_password": "••••••••",
            "use_ssl": False,
        }
        res = client.post("/api/admin/ldap/test", json=payload)
        assert res.status_code == 200

        # Verify mock received the resolved password from DB
        mock_test_conn.assert_called_once()
        called_config = mock_test_conn.call_args[0][0]
        assert called_config["bind_password"] == "real_secret_password"

    # Cleanup
    SystemSetting.query.filter_by(key="ldap_bind_password").delete()
    session.commit()
