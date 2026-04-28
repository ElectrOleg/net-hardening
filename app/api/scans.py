"""Scans API endpoints."""
from flask import request, jsonify
from app.api import api_bp
from app.api.pagination import paginate_query
from app.extensions import db
from app.models import Scan
from app.auth import require_auth


@api_bp.route("/scans", methods=["GET"])
def list_scans():
    """List recent scans."""
    query = Scan.query.order_by(Scan.started_at.desc())
    result = paginate_query(query)
    result["items"] = [s.to_dict() for s in result["items"]]
    return jsonify(result)


@api_bp.route("/scans/<uuid:scan_id>", methods=["GET"])
def get_scan(scan_id):
    """Get scan details."""
    scan = Scan.query.get_or_404(scan_id)
    return jsonify(scan.to_dict())


@api_bp.route("/scans/<uuid:scan_id>/status", methods=["GET"])
def get_scan_status(scan_id):
    """Lightweight status endpoint for polling (no joins, no results)."""
    scan = Scan.query.get_or_404(scan_id)
    return jsonify({
        "status": scan.status,
        "passed_count": scan.passed_count,
        "failed_count": scan.failed_count,
        "error_count": scan.error_count,
        "total_devices": scan.total_devices,
        "score": scan.score,
    })


@api_bp.route("/scans", methods=["POST"])
@require_auth
def start_scan():
    """Start a new scan (async via Celery)."""
    data = request.get_json() or {}
    
    policies_filter = data.get("policies")
    devices_filter = data.get("devices")
    use_stored_config = data.get("use_stored_config", False)
    
    # Dedup guard: refuse if a scan with the same filters is already running
    existing_query = Scan.query.filter(Scan.status.in_(["pending", "running"]))
    if policies_filter:
        existing_query = existing_query.filter(Scan.policies_filter == policies_filter)
    if devices_filter:
        existing_query = existing_query.filter(Scan.devices_filter == devices_filter)
    
    existing = existing_query.first()
    if existing:
        return jsonify({
            "error": "A scan with the same parameters is already running",
            "existing_scan_id": str(existing.id),
            "status": existing.status,
        }), 409
    
    # Create scan record
    scan = Scan(
        started_by=data.get("started_by", "api"),
        status="pending",
        devices_filter=devices_filter,
        policies_filter=policies_filter,
    )
    
    db.session.add(scan)
    db.session.commit()
    
    # Queue the scan task
    from app.tasks.scan_tasks import run_scan
    run_scan.delay(str(scan.id))
    
    return jsonify({
        "scan_id": str(scan.id),
        "status": "pending",
        "message": "Scan queued"
    }), 202


@api_bp.route("/scans/<uuid:scan_id>/cancel", methods=["POST"])
@require_auth
def cancel_scan(scan_id):
    """Cancel a running scan."""
    scan = Scan.query.get_or_404(scan_id)
    
    if scan.status not in ("pending", "running"):
        return jsonify({"error": "Scan is not running"}), 400
    
    scan.status = "cancelled"
    db.session.commit()
    
    # Revoke the Celery orchestrator task (and any child tasks it spawned)
    if scan.celery_task_id:
        from app.extensions import celery as celery_app
        celery_app.control.revoke(scan.celery_task_id, terminate=True, signal="SIGTERM")
    
    return jsonify({"status": "cancelled"})


@api_bp.route("/scans/latest", methods=["GET"])
def get_latest_scan():
    """Get the latest completed scan."""
    scan = Scan.query.filter_by(status="completed").order_by(Scan.finished_at.desc()).first()
    if not scan:
        return jsonify({"error": "No completed scans found"}), 404
    return jsonify(scan.to_dict())
