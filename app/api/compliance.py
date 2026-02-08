"""Compliance API — per-device, per-rule, per-policy compliance scores and filtering.

Endpoints:
  GET /api/compliance/devices/<id>           — single device compliance
  GET /api/compliance/devices                — aggregated compliance with filters
  GET /api/compliance/rules/<id>             — per-rule compliance across devices
  GET /api/compliance/policies/<id>          — per-policy compliance across devices
  GET /api/compliance/summary                — overall compliance summary
"""
from flask import request, jsonify
from sqlalchemy import func, case

from app.api import api_bp
from app.extensions import db
from app.models import Result, Scan, Rule, Device


def _get_latest_scan_id():
    """Get the ID of the latest completed scan."""
    scan_id = request.args.get("scan_id")
    if scan_id:
        return scan_id
    
    scan = Scan.query.filter_by(status="completed").order_by(
        Scan.finished_at.desc()
    ).first()
    return str(scan.id) if scan else None


def _compute_score(passed: int, failed: int, errors: int) -> float:
    """Compute compliance score (0–100)."""
    total = passed + failed + errors
    if total == 0:
        return 100.0
    return round((passed / total) * 100, 1)


# ── Single device compliance ───────────────────────────────────────

@api_bp.route("/compliance/devices/<uuid:device_id>", methods=["GET"])
def get_device_compliance(device_id):
    """Get compliance details for a single device.
    
    Query params:
      scan_id  — specific scan (default: latest completed)
    """
    device = Device.query.get_or_404(device_id)
    scan_id = _get_latest_scan_id()
    
    if not scan_id:
        return jsonify({"error": "No completed scans found"}), 404
    
    # Get result stats
    stats = db.session.query(
        Result.status,
        func.count(Result.id)
    ).filter(
        Result.scan_id == scan_id,
        Result.device_uuid == device.id
    ).group_by(Result.status).all()
    
    counts = {"PASS": 0, "FAIL": 0, "ERROR": 0, "SKIPPED": 0}
    for status, count in stats:
        counts[status] = count
    
    # Get failed rules details
    failures = db.session.query(Result, Rule).join(
        Rule, Result.rule_id == Rule.id
    ).filter(
        Result.scan_id == scan_id,
        Result.device_uuid == device.id,
        Result.status == "FAIL"
    ).all()
    
    failure_details = []
    for result, rule in failures:
        failure_details.append({
            "rule_id": str(rule.id),
            "rule_title": rule.title,
            "severity": rule.severity,
            "message": result.message,
            "diff_data": result.diff_data,
        })
    
    return jsonify({
        "device_id": str(device.id),
        "hostname": device.hostname,
        "ip_address": device.ip_address,
        "vendor_code": device.vendor_code,
        "location": device.location,
        "os_version": device.os_version,
        "hardware": device.hardware,
        "extra_data": device.extra_data,
        "scan_id": scan_id,
        "score": _compute_score(counts["PASS"], counts["FAIL"], counts["ERROR"]),
        "passed": counts["PASS"],
        "failed": counts["FAIL"],
        "errors": counts["ERROR"],
        "skipped": counts["SKIPPED"],
        "failures": failure_details,
    })


# ── Aggregated device compliance with filters ──────────────────────

@api_bp.route("/compliance/devices", methods=["GET"])
def get_devices_compliance():
    """Get compliance scores for multiple devices, with optional filters.
    
    Query params:
      scan_id     — specific scan (default: latest completed)
      vendor      — filter by vendor_code
      location    — filter by location
      group_id    — filter by group_id
      os_version  — filter by os_version (substring match)
      hardware    — filter by hardware (substring match)
      extra.<key> — filter by extra_data JSONB field, e.g. extra.service=Core
      sort        — sort by: score, hostname, vendor, location (default: score)
      order       — asc/desc (default: asc for score)
    """
    scan_id = _get_latest_scan_id()
    if not scan_id:
        return jsonify({"error": "No completed scans found"}), 404
    
    # Build device filter query
    device_query = Device.query.filter_by(is_active=True)
    
    vendor = request.args.get("vendor")
    if vendor:
        device_query = device_query.filter(Device.vendor_code == vendor)
    
    location = request.args.get("location")
    if location:
        device_query = device_query.filter(Device.location == location)
    
    group_id = request.args.get("group_id")
    if group_id:
        device_query = device_query.filter(Device.group_id == group_id)
    
    os_version = request.args.get("os_version")
    if os_version:
        device_query = device_query.filter(Device.os_version.ilike(f"%{os_version}%"))
    
    hardware = request.args.get("hardware")
    if hardware:
        device_query = device_query.filter(Device.hardware.ilike(f"%{hardware}%"))
    
    # Extra data filters: extra.service=Core → extra_data->>'service' = 'Core'
    for key, value in request.args.items():
        if key.startswith("extra."):
            json_key = key[6:]  # strip "extra."
            device_query = device_query.filter(
                Device.extra_data[json_key].astext == value
            )
    
    filtered_devices = device_query.all()
    if not filtered_devices:
        return jsonify({"scan_id": scan_id, "devices": [], "summary": {}})
    
    device_ids = [d.id for d in filtered_devices]
    device_map = {d.id: d for d in filtered_devices}
    
    # Get results for all filtered devices
    stats = db.session.query(
        Result.device_uuid,
        Result.status,
        func.count(Result.id)
    ).filter(
        Result.scan_id == scan_id,
        Result.device_uuid.in_(device_ids)
    ).group_by(Result.device_uuid, Result.status).all()
    
    # Aggregate per device
    device_scores: dict[str, dict] = {}
    for device_uuid, status, count in stats:
        did = str(device_uuid)
        if did not in device_scores:
            device_scores[did] = {"PASS": 0, "FAIL": 0, "ERROR": 0, "SKIPPED": 0}
        device_scores[did][status] = count
    
    # Build response
    results = []
    total_pass = 0
    total_fail = 0
    total_error = 0
    
    for dev in filtered_devices:
        did = str(dev.id)
        counts = device_scores.get(did, {"PASS": 0, "FAIL": 0, "ERROR": 0, "SKIPPED": 0})
        score = _compute_score(counts["PASS"], counts["FAIL"], counts["ERROR"])
        
        total_pass += counts["PASS"]
        total_fail += counts["FAIL"]
        total_error += counts["ERROR"]
        
        results.append({
            "device_id": did,
            "hostname": dev.hostname,
            "ip_address": dev.ip_address,
            "vendor_code": dev.vendor_code,
            "location": dev.location,
            "os_version": dev.os_version,
            "score": score,
            "passed": counts["PASS"],
            "failed": counts["FAIL"],
            "errors": counts["ERROR"],
        })
    
    # Sort
    sort_key = request.args.get("sort", "score")
    sort_order = request.args.get("order", "asc")
    reverse = sort_order == "desc"
    
    if sort_key in ("score", "passed", "failed", "errors"):
        results.sort(key=lambda r: r.get(sort_key, 0), reverse=reverse)
    elif sort_key in ("hostname", "vendor_code", "location"):
        results.sort(key=lambda r: (r.get(sort_key) or ""), reverse=reverse)
    
    return jsonify({
        "scan_id": scan_id,
        "total_devices": len(results),
        "summary": {
            "average_score": _compute_score(total_pass, total_fail, total_error),
            "total_passed": total_pass,
            "total_failed": total_fail,
            "total_errors": total_error,
        },
        "devices": results,
    })


# ── Per-rule compliance ────────────────────────────────────────────

@api_bp.route("/compliance/rules/<uuid:rule_id>", methods=["GET"])
def get_rule_compliance(rule_id):
    """Get compliance status of a specific rule across all devices.
    
    Query params:
      scan_id  — specific scan (default: latest completed)
    """
    rule = Rule.query.get_or_404(rule_id)
    scan_id = _get_latest_scan_id()
    
    if not scan_id:
        return jsonify({"error": "No completed scans found"}), 404
    
    # Count by status
    stats = db.session.query(
        Result.status,
        func.count(Result.id)
    ).filter(
        Result.scan_id == scan_id,
        Result.rule_id == rule.id
    ).group_by(Result.status).all()
    
    counts = {"PASS": 0, "FAIL": 0, "ERROR": 0, "SKIPPED": 0}
    for status, count in stats:
        counts[status] = count
    
    # Get devices that failed
    failed_devices = db.session.query(
        Result.device_id, Result.device_uuid, Result.message
    ).filter(
        Result.scan_id == scan_id,
        Result.rule_id == rule.id,
        Result.status == "FAIL"
    ).all()
    
    return jsonify({
        "rule_id": str(rule.id),
        "rule_title": rule.title,
        "severity": rule.severity,
        "vendor_code": rule.vendor_code,
        "scan_id": scan_id,
        "score": _compute_score(counts["PASS"], counts["FAIL"], counts["ERROR"]),
        "passed": counts["PASS"],
        "failed": counts["FAIL"],
        "errors": counts["ERROR"],
        "failed_devices": [
            {
                "device_id": d.device_id,
                "device_uuid": str(d.device_uuid) if d.device_uuid else None,
                "message": d.message
            }
            for d in failed_devices
        ],
    })


# ── Per-policy compliance ──────────────────────────────────────────

@api_bp.route("/compliance/policies/<uuid:policy_id>", methods=["GET"])
def get_policy_compliance(policy_id):
    """Get compliance status of all rules in a policy.
    
    Query params:
      scan_id  — specific scan (default: latest completed)
    """
    from app.models import Policy
    policy = Policy.query.get_or_404(policy_id)
    scan_id = _get_latest_scan_id()
    
    if not scan_id:
        return jsonify({"error": "No completed scans found"}), 404
    
    # Per-rule stats within this policy
    rule_stats = db.session.query(
        Rule.id,
        Rule.title,
        Rule.severity,
        Result.status,
        func.count(Result.id)
    ).join(Result, Result.rule_id == Rule.id).filter(
        Rule.policy_id == policy_id,
        Result.scan_id == scan_id
    ).group_by(Rule.id, Rule.title, Rule.severity, Result.status).all()
    
    rules_map: dict[str, dict] = {}
    for rule_id, title, severity, status, count in rule_stats:
        rid = str(rule_id)
        if rid not in rules_map:
            rules_map[rid] = {
                "rule_id": rid,
                "title": title,
                "severity": severity,
                "PASS": 0, "FAIL": 0, "ERROR": 0, "SKIPPED": 0
            }
        rules_map[rid][status] = count
    
    # Build response
    total_pass = 0
    total_fail = 0
    total_error = 0
    rules_list = []
    
    for r in rules_map.values():
        score = _compute_score(r["PASS"], r["FAIL"], r["ERROR"])
        total_pass += r["PASS"]
        total_fail += r["FAIL"]
        total_error += r["ERROR"]
        
        rules_list.append({
            "rule_id": r["rule_id"],
            "title": r["title"],
            "severity": r["severity"],
            "score": score,
            "passed": r["PASS"],
            "failed": r["FAIL"],
            "errors": r["ERROR"],
        })
    
    # Sort by score ascending (worst first)
    rules_list.sort(key=lambda x: x["score"])
    
    return jsonify({
        "policy_id": str(policy.id),
        "policy_name": policy.name,
        "scan_id": scan_id,
        "score": _compute_score(total_pass, total_fail, total_error),
        "total_passed": total_pass,
        "total_failed": total_fail,
        "total_errors": total_error,
        "rules": rules_list,
    })


# ── Overall compliance summary ─────────────────────────────────────

@api_bp.route("/compliance/summary", methods=["GET"])
def get_compliance_summary():
    """Get overall compliance summary with breakdowns.
    
    Query params:
      scan_id  — specific scan (default: latest completed)
    """
    scan_id = _get_latest_scan_id()
    if not scan_id:
        return jsonify({"error": "No completed scans found"}), 404
    
    scan = Scan.query.get(scan_id)
    if not scan:
        return jsonify({"error": "Scan not found"}), 404
    
    # By vendor
    vendor_stats = db.session.query(
        Device.vendor_code,
        Result.status,
        func.count(Result.id)
    ).join(Device, Result.device_uuid == Device.id).filter(
        Result.scan_id == scan_id,
        Result.device_uuid.isnot(None)
    ).group_by(Device.vendor_code, Result.status).all()
    
    vendors: dict[str, dict] = {}
    for vendor, status, count in vendor_stats:
        v = vendor or "unknown"
        if v not in vendors:
            vendors[v] = {"PASS": 0, "FAIL": 0, "ERROR": 0}
        vendors[v][status] = count
    
    vendor_scores = {
        v: _compute_score(s["PASS"], s["FAIL"], s["ERROR"])
        for v, s in vendors.items()
    }
    
    # By location
    location_stats = db.session.query(
        Device.location,
        Result.status,
        func.count(Result.id)
    ).join(Device, Result.device_uuid == Device.id).filter(
        Result.scan_id == scan_id,
        Result.device_uuid.isnot(None)
    ).group_by(Device.location, Result.status).all()
    
    locations: dict[str, dict] = {}
    for loc, status, count in location_stats:
        l = loc or "unknown"
        if l not in locations:
            locations[l] = {"PASS": 0, "FAIL": 0, "ERROR": 0}
        locations[l][status] = count
    
    location_scores = {
        l: _compute_score(s["PASS"], s["FAIL"], s["ERROR"])
        for l, s in locations.items()
    }
    
    # By severity
    severity_stats = db.session.query(
        Rule.severity,
        Result.status,
        func.count(Result.id)
    ).join(Rule, Result.rule_id == Rule.id).filter(
        Result.scan_id == scan_id
    ).group_by(Rule.severity, Result.status).all()
    
    severities: dict[str, dict] = {}
    for sev, status, count in severity_stats:
        s = sev or "medium"
        if s not in severities:
            severities[s] = {"PASS": 0, "FAIL": 0, "ERROR": 0}
        severities[s][status] = count
    
    severity_scores = {
        s: _compute_score(d["PASS"], d["FAIL"], d["ERROR"])
        for s, d in severities.items()
    }
    
    return jsonify({
        "scan_id": str(scan.id),
        "scan_date": scan.finished_at.isoformat() if scan.finished_at else None,
        "overall_score": scan.score,
        "total_devices": scan.total_devices,
        "total_rules": scan.total_rules,
        "by_vendor": vendor_scores,
        "by_location": location_scores,
        "by_severity": severity_scores,
    })
