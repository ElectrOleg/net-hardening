"""Web views for HCS UI."""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g
from sqlalchemy import func
from app.extensions import db
from app.models import Scan, Result, Rule, Policy, Vendor, DataSource

web_bp = Blueprint("web", __name__)


@web_bp.before_app_request
def inject_user():
    """Make current user available in all templates."""
    g.current_user = None
    user_id = session.get("user_id")
    if user_id:
        from app.models.user import User
        user = User.query.get(user_id)
        if user and user.is_active:
            g.current_user = user.to_dict()


@web_bp.route("/login", methods=["GET"])
def login_page():
    """Show login form."""
    if session.get("user_id"):
        return redirect(url_for("web.dashboard"))
    return render_template("login.html")


@web_bp.route("/login", methods=["POST"])
def login_submit():
    """Process login form."""
    from app.auth import authenticate

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    user = authenticate(username, password)
    if not user:
        return render_template("login.html", error="Неверное имя пользователя или пароль")

    session["user_id"] = str(user.id)
    session["username"] = user.username
    session["role"] = user.role
    session.permanent = True

    next_url = request.args.get("next") or url_for("web.dashboard")
    return redirect(next_url)


@web_bp.route("/logout")
def logout():
    """Log out and redirect to login."""
    session.clear()
    return redirect(url_for("web.login_page"))


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
    # Single query: policies with rule count (no N+1)
    policies = db.session.query(
        Policy,
        func.count(Rule.id).label('rule_count')
    ).outerjoin(Rule, (Rule.policy_id == Policy.id) & (Rule.is_active == True)).filter(
        Policy.is_active == True
    ).group_by(Policy.id).order_by(Policy.name).all()
    return render_template("scans/list.html", scans=scans, policies=policies)


@web_bp.route("/scans/<uuid:scan_id>")
def scan_detail(scan_id):
    """Scan detail view."""
    scan = Scan.query.get_or_404(scan_id)
    results = Result.query.filter_by(scan_id=scan_id).all()
    
    # Group by device with aggregated stats
    devices = {}
    for r in results:
        did = r.device_id
        if did not in devices:
            devices[did] = {
                "results": [],
                "passed": 0,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
                "policies": set(),
            }
        devices[did]["results"].append(r)
        if r.status == "PASS":
            devices[did]["passed"] += 1
        elif r.status == "FAIL":
            devices[did]["failed"] += 1
        elif r.status == "ERROR":
            devices[did]["errors"] += 1
        elif r.status == "SKIPPED":
            devices[did]["skipped"] += 1
        if r.rule and r.rule.policy:
            devices[did]["policies"].add(r.rule.policy.name)
    
    # Convert sets to sorted lists for template
    for did in devices:
        devices[did]["policies"] = sorted(devices[did]["policies"])
        devices[did]["total"] = len(devices[did]["results"])
    
    # Sort: devices with failures first, then by name
    devices = dict(sorted(
        devices.items(),
        key=lambda x: (-x[1]["failed"], -x[1]["errors"], x[0])
    ))
    
    return render_template("scans/detail.html", scan=scan, devices=devices)


@web_bp.route("/scans/device/<device_id>/history")
def device_history(device_id):
    """Compliance history for a single device across scans."""
    from collections import OrderedDict
    
    # All completed scans that include this device, newest first
    scan_ids_with_device = (
        db.session.query(Result.scan_id)
        .filter(Result.device_id == device_id)
        .distinct()
        .subquery()
    )
    scans = (
        Scan.query
        .filter(Scan.id.in_(scan_ids_with_device))
        .filter(Scan.status == "completed")
        .order_by(Scan.started_at.desc())
        .limit(20)
        .all()
    )
    
    # Build per-scan summary + per-rule timeline
    scan_summaries = []
    rule_timeline = OrderedDict()  # rule_id -> {title, severity, scans: [{scan_id, status}]}
    
    for scan in scans:
        results = Result.query.filter_by(
            scan_id=scan.id,
            device_id=device_id
        ).all()
        
        passed = sum(1 for r in results if r.status == "PASS")
        failed = sum(1 for r in results if r.status == "FAIL")
        errors = sum(1 for r in results if r.status == "ERROR")
        total = passed + failed + errors
        score = round((passed / total) * 100, 1) if total > 0 else 100.0
        
        scan_summaries.append({
            "scan": scan,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "total": total,
            "score": score,
        })
        
        for r in results:
            rid = str(r.rule_id)
            if rid not in rule_timeline:
                rule_timeline[rid] = {
                    "title": r.rule.title if r.rule else rid,
                    "severity": r.rule.severity if r.rule else None,
                    "results": {},
                }
            rule_timeline[rid]["results"][str(scan.id)] = r.status
    
    return render_template(
        "scans/device_history.html",
        device_id=device_id,
        scans=scans,
        scan_summaries=scan_summaries,
        rule_timeline=rule_timeline,
    )


@web_bp.route("/rules")
def rules_list():
    """List of rules."""
    show_inactive = request.args.get("show_inactive", "false").lower() == "true"
    if show_inactive:
        rules = Rule.query.all()
    else:
        rules = Rule.query.filter_by(is_active=True).all()
    policies = Policy.query.filter_by(is_active=True).all()
    return render_template("rules/list.html", rules=rules, show_inactive=show_inactive, policies=policies)


@web_bp.route("/rules/new")
def rule_builder():
    """Rule builder page."""
    policies = Policy.query.filter_by(is_active=True).all()
    vendors = Vendor.query.all()
    data_sources = DataSource.query.filter_by(is_active=True).all()
    
    # Support cloning from existing rule
    clone_id = request.args.get("clone")
    clone_rule = None
    if clone_id:
        clone_rule = Rule.query.get(clone_id)
    
    return render_template("rules/builder.html", policies=policies, vendors=vendors, data_sources=data_sources, clone_rule=clone_rule)


@web_bp.route("/rules/<uuid:rule_id>/edit")
def rule_edit(rule_id):
    """Edit existing rule."""
    rule = Rule.query.get_or_404(rule_id)
    policies = Policy.query.filter_by(is_active=True).all()
    vendors = Vendor.query.all()
    data_sources = DataSource.query.filter_by(is_active=True).all()
    return render_template("rules/builder.html", policies=policies, vendors=vendors, data_sources=data_sources, rule=rule)


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


@web_bp.route("/settings")
def settings():
    """Settings main page."""
    return render_template("settings/index.html")


@web_bp.route("/settings/data-sources")
def settings_data_sources():
    """Data sources management."""
    from app.models import DataSource
    sources = DataSource.query.order_by(DataSource.name).all()
    return render_template("settings/data_sources.html", sources=sources)


@web_bp.route("/settings/vendors")
def settings_vendors():
    """Vendors reference."""
    vendors = Vendor.query.all()
    return render_template("settings/vendors.html", vendors=vendors)


@web_bp.route("/settings/inventory-sources")
def settings_inventory_sources():
    """Inventory sources management."""
    from app.models import InventorySource
    sources = InventorySource.query.order_by(InventorySource.name).all()
    return render_template("settings/inventory_sources.html", sources=sources)


@web_bp.route("/settings/devices")
def settings_devices():
    """Devices management."""
    from app.models import Device, DeviceGroup, Policy
    devices = Device.query.order_by(Device.hostname).all()
    vendors = Vendor.query.all()
    groups = DeviceGroup.query.filter_by(is_active=True).all()
    policies = Policy.query.filter_by(is_active=True).all()
    return render_template("settings/devices.html", devices=devices, vendors=vendors, groups=groups, policies=policies)


@web_bp.route("/settings/device-groups")
def settings_device_groups():
    """Device groups management."""
    from app.models import DeviceGroup, Policy
    groups = DeviceGroup.query.order_by(DeviceGroup.name).all()
    policies = Policy.query.filter_by(is_active=True).all()
    return render_template("settings/device_groups.html", groups=groups, policies=policies)


@web_bp.route("/admin")
def admin():
    """Administration panel."""
    from app.models import InventorySource, Policy
    sources = InventorySource.query.order_by(InventorySource.name).all()
    policies = Policy.query.filter_by(is_active=True).order_by(Policy.name).all()
    return render_template("admin/index.html", sources=sources, policies=policies)
