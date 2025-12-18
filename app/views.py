"""Web views for HCS UI."""
from flask import Blueprint, render_template
from app.models import Scan, Result, Rule, Policy, Vendor

web_bp = Blueprint("web", __name__)


@web_bp.route("/")
def dashboard():
    """Main dashboard."""
    latest_scan = Scan.query.filter_by(status="completed").order_by(Scan.finished_at.desc()).first()
    
    if latest_scan:
        score = latest_scan.score
        stats = {
            "passed": latest_scan.passed_count,
            "failed": latest_scan.failed_count,
            "errors": latest_scan.error_count,
            "devices": latest_scan.total_devices
        }
        recent_failures = Result.query.filter_by(
            scan_id=latest_scan.id, 
            status="FAIL"
        ).limit(10).all()
    else:
        score = 100
        stats = {"passed": 0, "failed": 0, "errors": 0, "devices": 0}
        recent_failures = []
    
    recent_scans = Scan.query.order_by(Scan.started_at.desc()).limit(5).all()
    
    return render_template(
        "dashboard.html",
        score=score,
        stats=stats,
        recent_failures=recent_failures,
        recent_scans=recent_scans
    )


@web_bp.route("/scans")
def scans_list():
    """List of scans."""
    scans = Scan.query.order_by(Scan.started_at.desc()).limit(50).all()
    return render_template("scans/list.html", scans=scans)


@web_bp.route("/scans/<uuid:scan_id>")
def scan_detail(scan_id):
    """Scan detail view."""
    scan = Scan.query.get_or_404(scan_id)
    results = Result.query.filter_by(scan_id=scan_id).all()
    
    # Group by device
    devices = {}
    for r in results:
        if r.device_id not in devices:
            devices[r.device_id] = []
        devices[r.device_id].append(r)
    
    return render_template("scans/detail.html", scan=scan, devices=devices)


@web_bp.route("/rules")
def rules_list():
    """List of rules."""
    rules = Rule.query.filter_by(is_active=True).all()
    return render_template("rules/list.html", rules=rules)


@web_bp.route("/rules/new")
def rule_builder():
    """Rule builder page."""
    policies = Policy.query.filter_by(is_active=True).all()
    vendors = Vendor.query.all()
    return render_template("rules/builder.html", policies=policies, vendors=vendors)


@web_bp.route("/policies")
def policies_list():
    """List of policies."""
    policies = Policy.query.filter_by(is_active=True).all()
    return render_template("policies/list.html", policies=policies)


@web_bp.route("/exceptions")
def exceptions_list():
    """List of exceptions/waivers."""
    rules = Rule.query.filter_by(is_active=True).all()
    return render_template("exceptions/list.html", rules=rules)


@web_bp.route("/matrix")
def compliance_matrix():
    """Device × Policy compliance matrix."""
    scans = Scan.query.filter_by(status="completed").order_by(Scan.finished_at.desc()).limit(20).all()
    return render_template("matrix.html", scans=scans)


@web_bp.route("/remediation/<uuid:scan_id>")
def remediation(scan_id):
    """Remediation playbook page for a scan."""
    return render_template("remediation.html", scan_id=scan_id)
