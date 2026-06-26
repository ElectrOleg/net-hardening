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
