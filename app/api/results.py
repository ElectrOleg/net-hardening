"""Results API endpoints."""
from flask import request, jsonify
from sqlalchemy import func
from app.api import api_bp
from app.extensions import db
from app.models import Result, Scan, Rule


@api_bp.route("/results", methods=["GET"])
def list_results():
    """List results with filters."""
    scan_id = request.args.get("scan_id")
    device_id = request.args.get("device_id")
    status = request.args.get("status")
    limit = request.args.get("limit", 100, type=int)
    
    query = Result.query
    
    if scan_id:
        query = query.filter_by(scan_id=scan_id)
    if device_id:
        query = query.filter_by(device_id=device_id)
    if status:
        query = query.filter_by(status=status)
    
    results = query.order_by(Result.checked_at.desc()).limit(limit).all()
    return jsonify([r.to_dict(include_rule=True) for r in results])


@api_bp.route("/results/<uuid:result_id>", methods=["GET"])
def get_result(result_id):
    """Get result details."""
    result = Result.query.get_or_404(result_id)
    return jsonify(result.to_dict(include_rule=True))


@api_bp.route("/results/by-scan/<uuid:scan_id>/summary", methods=["GET"])
def get_scan_summary(scan_id):
    """Get summary of results for a scan."""
    scan = Scan.query.get_or_404(scan_id)
    
    # Group by status
    status_counts = db.session.query(
        Result.status,
        func.count(Result.id)
    ).filter(
        Result.scan_id == scan_id
    ).group_by(Result.status).all()
    
    # Group by device
    device_stats = db.session.query(
        Result.device_id,
        Result.status,
        func.count(Result.id)
    ).filter(
        Result.scan_id == scan_id
    ).group_by(Result.device_id, Result.status).all()
    
    # Process device stats
    devices = {}
    for device_id, status, count in device_stats:
        if device_id not in devices:
            devices[device_id] = {"PASS": 0, "FAIL": 0, "ERROR": 0, "SKIPPED": 0}
        devices[device_id][status] = count
    
    return jsonify({
        "scan_id": str(scan_id),
        "scan_status": scan.status,
        "score": scan.score,
        "status_summary": {s: c for s, c in status_counts},
        "devices": devices
    })


@api_bp.route("/results/by-scan/<uuid:scan_id>/failed", methods=["GET"])
def get_failed_results(scan_id):
    """Get only failed results for a scan."""
    results = Result.query.filter_by(
        scan_id=scan_id,
        status="FAIL"
    ).all()
    return jsonify([r.to_dict(include_rule=True) for r in results])


@api_bp.route("/results/matrix", methods=["GET"])
def get_results_matrix():
    """Get device x policy matrix for latest scan."""
    scan_id = request.args.get("scan_id")
    
    if not scan_id:
        scan = Scan.query.filter_by(status="completed").order_by(Scan.finished_at.desc()).first()
        if not scan:
            return jsonify({"error": "No completed scans"}), 404
        scan_id = scan.id
    
    # Get all results with rule info
    results = db.session.query(Result, Rule).join(Rule).filter(
        Result.scan_id == scan_id
    ).all()
    
    # Build matrix
    matrix = {}
    policies = set()
    
    for result, rule in results:
        device = result.device_id
        policy = str(rule.policy_id)
        
        policies.add(policy)
        
        if device not in matrix:
            matrix[device] = {}
        
        if policy not in matrix[device]:
            matrix[device][policy] = {"pass": 0, "fail": 0, "total": 0}
        
        if result.status == "PASS":
            matrix[device][policy]["pass"] += 1
        elif result.status == "FAIL":
            matrix[device][policy]["fail"] += 1
        matrix[device][policy]["total"] += 1
    
    return jsonify({
        "scan_id": str(scan_id),
        "policies": list(policies),
        "matrix": matrix
    })
