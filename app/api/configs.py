"""Config Snapshots API — view and compare device configurations.

RBAC:
- admin:    full access (raw + sanitized configs, diff, delete)
- operator: sanitized configs only (passwords masked), diff
- viewer:   metadata only (hash, size, timestamps), no config text

All config text access is logged for audit purposes.
"""
import logging
import difflib
from flask import request, jsonify, g

from app.api import api_bp
from app.api.pagination import paginate_query
from app.auth import require_auth, require_role
from app.models.config_snapshot import ConfigSnapshot
from app.models.device import Device
from app.utils.config_sanitizer import sanitize_config

logger = logging.getLogger(__name__)

# ── Helpers ──────────────────────────────────────────────────────────

ROLE_HIERARCHY = {"admin": 3, "operator": 2, "viewer": 1}


def _user_role() -> str:
    """Get current user's role."""
    user = getattr(g, "current_user", {})
    return user.get("role", "viewer")


def _user_role_level() -> int:
    """Get numeric role level for comparison."""
    return ROLE_HIERARCHY.get(_user_role(), 1)


def _audit_log(action: str, details: str):
    """Log config access for audit trail."""
    user = getattr(g, "current_user", {})
    username = user.get("username", "unknown")
    logger.info(f"CONFIG_AUDIT | user={username} role={user.get('role')} | {action} | {details}")


def _serialize_snapshot(snap: ConfigSnapshot, include_config: bool = False) -> dict:
    """Serialize a snapshot with RBAC-aware config inclusion.
    
    - admin:    raw config text (unsanitized)
    - operator: sanitized config text (passwords masked)
    - viewer:   no config text, metadata only
    """
    role_level = _user_role_level()
    
    if not include_config or role_level < 2:
        # Viewer: metadata only
        return snap.to_dict(include_config=False)
    
    if role_level >= 3:
        # Admin: raw config
        return snap.to_dict(include_config=True)
    
    # Operator: sanitized config
    return snap.to_dict_safe(sanitizer=sanitize_config)


# ── Device Config List ───────────────────────────────────────────────

@api_bp.route("/devices/<uuid:device_id>/configs", methods=["GET"])
@require_auth
def list_device_configs(device_id):
    """List config snapshots for a device.
    
    All roles can see metadata. Config text access controlled by role.
    Query params: ?include_config=true, ?changed_only=true
    """
    device = Device.query.get_or_404(device_id)
    
    query = ConfigSnapshot.query.filter_by(device_id=device_id).order_by(
        ConfigSnapshot.collected_at.desc()
    )
    
    # Optional filter: only changed snapshots
    if request.args.get("changed_only", "").lower() == "true":
        query = query.filter_by(is_changed=True)
    
    include_config = request.args.get("include_config", "").lower() == "true"
    
    result = paginate_query(query)
    result["items"] = [_serialize_snapshot(s, include_config) for s in result["items"]]
    result["device"] = {"id": str(device.id), "hostname": device.hostname}
    
    if include_config:
        _audit_log("LIST_CONFIGS", f"device={device.hostname} count={len(result['items'])}")
    
    return jsonify(result)


# ── Latest Config ────────────────────────────────────────────────────

@api_bp.route("/devices/<uuid:device_id>/configs/latest", methods=["GET"])
@require_auth
def get_latest_config(device_id):
    """Get the latest config snapshot for a device.
    
    Viewer: metadata only. Operator: sanitized. Admin: raw.
    """
    device = Device.query.get_or_404(device_id)
    
    snap = ConfigSnapshot.query.filter_by(
        device_id=device_id
    ).order_by(ConfigSnapshot.collected_at.desc()).first()
    
    if not snap:
        return jsonify({"error": "No config snapshots found for this device"}), 404
    
    _audit_log("GET_LATEST_CONFIG", f"device={device.hostname} snap={snap.id}")
    
    return jsonify(_serialize_snapshot(snap, include_config=True))


# ── Specific Snapshot ────────────────────────────────────────────────

@api_bp.route("/configs/<uuid:snap_id>", methods=["GET"])
@require_auth
def get_config_snapshot(snap_id):
    """Get a specific config snapshot.
    
    Access controlled by role (viewer=meta, operator=sanitized, admin=raw).
    """
    snap = ConfigSnapshot.query.get_or_404(snap_id)
    
    _audit_log("GET_CONFIG", f"snap={snap_id} device={snap.device_id}")
    
    return jsonify(_serialize_snapshot(snap, include_config=True))


# ── Diff Between Snapshots ───────────────────────────────────────────

@api_bp.route("/configs/<uuid:snap_id>/diff/<uuid:other_snap_id>", methods=["GET"])
@require_auth
@require_role("operator", "admin")
def diff_config_snapshots(snap_id, other_snap_id):
    """Generate unified diff between two config snapshots.
    
    Requires operator or admin role (viewers cannot see config text).
    Operator sees sanitized diff, admin sees raw diff.
    """
    snap_a = ConfigSnapshot.query.get_or_404(snap_id)
    snap_b = ConfigSnapshot.query.get_or_404(other_snap_id)
    
    # Verify both snapshots are for the same device
    if snap_a.device_id != snap_b.device_id:
        return jsonify({"error": "Snapshots must be from the same device"}), 400
    
    text_a = snap_a.get_config_text() or ""
    text_b = snap_b.get_config_text() or ""
    
    # Sanitize for operator role
    if _user_role() == "operator":
        text_a = sanitize_config(text_a)
        text_b = sanitize_config(text_b)
    
    # Generate unified diff
    diff_lines = list(difflib.unified_diff(
        text_a.splitlines(keepends=True),
        text_b.splitlines(keepends=True),
        fromfile=f"snapshot {snap_id} ({snap_a.collected_at})",
        tofile=f"snapshot {other_snap_id} ({snap_b.collected_at})",
        lineterm="",
    ))
    
    # Compute stats
    added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))
    
    _audit_log("DIFF_CONFIGS", f"snap_a={snap_id} snap_b={other_snap_id} device={snap_a.device_id}")
    
    return jsonify({
        "device_id": str(snap_a.device_id),
        "snapshot_a": {"id": str(snap_id), "collected_at": snap_a.collected_at.isoformat()},
        "snapshot_b": {"id": str(other_snap_id), "collected_at": snap_b.collected_at.isoformat()},
        "diff": "\n".join(diff_lines),
        "stats": {"added": added, "removed": removed, "total_lines": len(diff_lines)},
    })


# ── Admin: Delete Snapshot ───────────────────────────────────────────

@api_bp.route("/configs/<uuid:snap_id>", methods=["DELETE"])
@require_auth
@require_role("admin")
def delete_config_snapshot(snap_id):
    """Delete a config snapshot. Admin only."""
    from app.extensions import db
    
    snap = ConfigSnapshot.query.get_or_404(snap_id)
    
    _audit_log("DELETE_CONFIG", f"snap={snap_id} device={snap.device_id}")
    
    db.session.delete(snap)
    db.session.commit()
    
    return jsonify({"deleted": True})


# ── Admin: Raw Config Download ───────────────────────────────────────

@api_bp.route("/configs/<uuid:snap_id>/raw", methods=["GET"])
@require_auth
@require_role("admin")
def get_raw_config(snap_id):
    """Download raw config text (unsanitized). Admin only.
    
    Returns plain text response for download/copy.
    """
    snap = ConfigSnapshot.query.get_or_404(snap_id)
    config_text = snap.get_config_text()
    
    if not config_text:
        return jsonify({"error": "Config text not available (deduped snapshot)"}), 404
    
    _audit_log("DOWNLOAD_RAW_CONFIG", f"snap={snap_id} device={snap.device_id}")
    
    from flask import Response
    return Response(
        config_text,
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename=config_{snap_id}.txt"}
    )
