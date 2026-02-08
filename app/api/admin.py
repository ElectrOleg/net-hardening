"""Administration API — system settings, scan schedules, sync logs."""
from flask import jsonify, request
from app.api import api_bp
from app.extensions import db
from app.auth import require_auth


# ─── System Settings ───────────────────────────────────────────────

@api_bp.route("/admin/settings", methods=["GET"])
@require_auth
def get_system_settings():
    """Get all system settings (with defaults for missing keys)."""
    from app.models.system_setting import SystemSetting
    settings = SystemSetting.get_all()
    return jsonify(settings)


@api_bp.route("/admin/settings", methods=["PUT"])
@require_auth
def update_system_settings():
    """Update one or more system settings.
    
    Body: {"key1": "value1", "key2": "value2", ...}
    """
    from app.models.system_setting import SystemSetting
    
    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Expected JSON object with key-value pairs"}), 400
    
    updated = []
    for key, value in data.items():
        setting = SystemSetting.set(key, str(value))
        updated.append(setting.to_dict())
    
    db.session.commit()
    return jsonify({"updated": updated})


# ─── Scan Schedules ────────────────────────────────────────────────

@api_bp.route("/admin/scan-schedules", methods=["GET"])
@require_auth
def list_scan_schedules():
    """List all scan schedules."""
    from app.models.scan_schedule import ScanSchedule
    schedules = ScanSchedule.query.order_by(ScanSchedule.name).all()
    return jsonify([s.to_dict() for s in schedules])


@api_bp.route("/admin/scan-schedules", methods=["POST"])
@require_auth
def create_scan_schedule():
    """Create a new scan schedule."""
    from app.models.scan_schedule import ScanSchedule
    
    data = request.get_json()
    if not data or not data.get("name") or not data.get("cron_expression"):
        return jsonify({"error": "name and cron_expression are required"}), 400
    
    # Validate cron expression
    cron_expr = data["cron_expression"]
    try:
        from croniter import croniter
        if not croniter.is_valid(cron_expr):
            return jsonify({"error": f"Invalid cron expression: {cron_expr}"}), 400
    except ImportError:
        pass  # croniter not installed — skip validation
    
    schedule = ScanSchedule(
        name=data["name"],
        description=data.get("description"),
        cron_expression=cron_expr,
        policies_filter=data.get("policies_filter"),
        devices_filter=data.get("devices_filter"),
        is_enabled=data.get("is_enabled", True),
    )
    
    # Calculate first next_run
    schedule.next_run_at = schedule.calculate_next_run()
    
    db.session.add(schedule)
    db.session.commit()
    
    return jsonify(schedule.to_dict()), 201


@api_bp.route("/admin/scan-schedules/<uuid:schedule_id>", methods=["PUT"])
@require_auth
def update_scan_schedule(schedule_id):
    """Update a scan schedule."""
    from app.models.scan_schedule import ScanSchedule
    
    schedule = ScanSchedule.query.get_or_404(schedule_id)
    data = request.get_json()
    
    if "name" in data:
        schedule.name = data["name"]
    if "description" in data:
        schedule.description = data["description"]
    if "cron_expression" in data:
        schedule.cron_expression = data["cron_expression"]
        schedule.next_run_at = schedule.calculate_next_run()
    if "policies_filter" in data:
        schedule.policies_filter = data["policies_filter"]
    if "devices_filter" in data:
        schedule.devices_filter = data["devices_filter"]
    if "is_enabled" in data:
        schedule.is_enabled = data["is_enabled"]
    
    db.session.commit()
    return jsonify(schedule.to_dict())


@api_bp.route("/admin/scan-schedules/<uuid:schedule_id>", methods=["DELETE"])
@require_auth
def delete_scan_schedule(schedule_id):
    """Delete a scan schedule."""
    from app.models.scan_schedule import ScanSchedule
    
    schedule = ScanSchedule.query.get_or_404(schedule_id)
    db.session.delete(schedule)
    db.session.commit()
    
    return jsonify({"deleted": True})


# ─── Sync Logs ─────────────────────────────────────────────────────

@api_bp.route("/admin/sync-logs", methods=["GET"])
@require_auth
def list_sync_logs():
    """List sync logs with optional filtering.
    
    Query params:
    - source_id: filter by source UUID
    - status: success, partial, failed
    - limit: max results (default 50)
    - offset: pagination offset
    """
    from app.models.sync_log import SyncLog
    
    query = SyncLog.query.order_by(SyncLog.started_at.desc())
    
    source_id = request.args.get("source_id")
    if source_id:
        query = query.filter_by(source_id=source_id)
    
    status = request.args.get("status")
    if status:
        query = query.filter_by(status=status)
    
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "limit and offset must be integers"}), 400
    
    total = query.count()
    logs = query.offset(offset).limit(limit).all()
    
    return jsonify({
        "total": total,
        "offset": offset,
        "limit": limit,
        "logs": [log.to_dict() for log in logs],
    })
