"""Scans API endpoints."""
from flask import request, jsonify
from app.api import api_bp
from app.extensions import db
from app.models import Scan


@api_bp.route("/scans", methods=["GET"])
def list_scans():
    """List recent scans."""
    limit = request.args.get("limit", 20, type=int)
    scans = Scan.query.order_by(Scan.started_at.desc()).limit(limit).all()
    return jsonify([s.to_dict() for s in scans])


@api_bp.route("/scans/<uuid:scan_id>", methods=["GET"])
def get_scan(scan_id):
    """Get scan details."""
    scan = Scan.query.get_or_404(scan_id)
    return jsonify(scan.to_dict())


@api_bp.route("/scans", methods=["POST"])
def start_scan():
    """Start a new scan (async via Celery)."""
    data = request.get_json() or {}
    
    # Create scan record
    scan = Scan(
        started_by=data.get("started_by", "api"),
        status="pending",
        devices_filter=data.get("devices"),
        policies_filter=data.get("policies")
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
def cancel_scan(scan_id):
    """Cancel a running scan."""
    scan = Scan.query.get_or_404(scan_id)
    
    if scan.status not in ("pending", "running"):
        return jsonify({"error": "Scan is not running"}), 400
    
    scan.status = "cancelled"
    db.session.commit()
    
    # TODO: Actually revoke the Celery task
    
    return jsonify({"status": "cancelled"})


@api_bp.route("/scans/latest", methods=["GET"])
def get_latest_scan():
    """Get the latest completed scan."""
    scan = Scan.query.filter_by(status="completed").order_by(Scan.finished_at.desc()).first()
    if not scan:
        return jsonify({"error": "No completed scans found"}), 404
    return jsonify(scan.to_dict())
