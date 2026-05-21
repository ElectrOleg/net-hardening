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
    from datetime import datetime, timedelta
    from app.models import Device, ConfigSnapshot

    # Time period filter
    period = request.args.get("period", "30d")
    now = datetime.utcnow()
    
    if period == "7d":
        start_date = now - timedelta(days=7)
    elif period == "all":
        start_date = None
    else:  # default 30d
        period = "30d"
        start_date = now - timedelta(days=30)

    # 1. Get IDs of active devices
    active_devices = Device.query.filter_by(is_active=True).all()
    active_device_ids = [d.id for d in active_devices]
    total_active_devices = len(active_device_ids)

    latest_results = []
    top_failing_rules = []
    
    if active_device_ids:
        # Subquery to find the latest completed scan started_at for each active device
        latest_scans_sub = db.session.query(
            Result.device_uuid,
            func.max(Scan.started_at).label("max_started_at")
        ).join(Scan, Result.scan_id == Scan.id)\
         .filter(Scan.status == "completed")\
         .filter(Result.device_uuid.in_(active_device_ids))\
         .group_by(Result.device_uuid).subquery()
         
        # Join back to Scan to get the scan ID
        latest_scans = db.session.query(
            Result.device_uuid,
            Scan.id.label("scan_id")
        ).join(Scan, Result.scan_id == Scan.id)\
         .join(
             latest_scans_sub,
             (Result.device_uuid == latest_scans_sub.c.device_uuid) &
             (Scan.started_at == latest_scans_sub.c.max_started_at)
         ).distinct().subquery()
         
        # Fetch the results of those latest scans for each active device
        latest_results = db.session.query(
            Result.status,
            Result.device_uuid,
            Result.rule_id,
            Rule.severity,
            Device.vendor_code,
            Device.hostname
        ).join(Rule, Result.rule_id == Rule.id)\
         .join(Device, Result.device_uuid == Device.id)\
         .join(
             latest_scans,
             (Result.device_uuid == latest_scans.c.device_uuid) &
             (Result.scan_id == latest_scans.c.scan_id)
         ).all()
         
        # Fetch top 5 failing rules from these latest scans
        top_failing_rules = db.session.query(
            Rule.id,
            Rule.title,
            Rule.severity,
            func.count(Result.id).label("fail_count")
        ).join(Result, Result.rule_id == Rule.id)\
         .join(Scan, Result.scan_id == Scan.id)\
         .join(Device, Result.device_uuid == Device.id)\
         .join(
             latest_scans,
             (Result.device_uuid == latest_scans.c.device_uuid) &
             (Result.scan_id == latest_scans.c.scan_id)
         ).filter(Result.status == "FAIL")\
          .group_by(Rule.id, Rule.title, Rule.severity)\
          .order_by(func.count(Result.id).desc())\
          .limit(5).all()

    # Aggregate stats from latest scans of active devices
    passed = 0
    failed = 0
    errors = 0
    
    severity_stats = {
        "critical": {"passed": 0, "failed": 0, "errors": 0},
        "high": {"passed": 0, "failed": 0, "errors": 0},
        "medium": {"passed": 0, "failed": 0, "errors": 0},
        "low": {"passed": 0, "failed": 0, "errors": 0},
        "info": {"passed": 0, "failed": 0, "errors": 0},
    }
    
    vendor_stats = {}
    vendors = Vendor.query.all()
    vendor_names = {v.code: v.name for v in vendors}
    
    for r in latest_results:
        status = r.status
        severity = (r.severity or "medium").lower()
        vendor = r.vendor_code or "unknown"
        
        if status == "PASS":
            passed += 1
        elif status == "FAIL":
            failed += 1
        elif status == "ERROR":
            errors += 1
            
        if severity in severity_stats:
            if status == "PASS":
                severity_stats[severity]["passed"] += 1
            elif status == "FAIL":
                severity_stats[severity]["failed"] += 1
            elif status == "ERROR":
                severity_stats[severity]["errors"] += 1
                
        if vendor not in vendor_stats:
            vendor_stats[vendor] = {"passed": 0, "failed": 0, "errors": 0}
            
        if status == "PASS":
            vendor_stats[vendor]["passed"] += 1
        elif status == "FAIL":
            vendor_stats[vendor]["failed"] += 1
        elif status == "ERROR":
            vendor_stats[vendor]["errors"] += 1

    total_checks = passed + failed + errors
    infra_score = round((passed / total_checks) * 100, 1) if total_checks > 0 else 100.0
    
    # Format stats dict for template compatibility
    stats = {
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "devices": total_active_devices
    }

    # Format severity breakdown list
    severity_breakdown = []
    for sev_name, counts in severity_stats.items():
        total_sev = counts["passed"] + counts["failed"] + counts["errors"]
        score_sev = round((counts["passed"] / total_sev) * 100, 1) if total_sev > 0 else 100.0
        if total_sev > 0:
            severity_breakdown.append({
                "name": sev_name.capitalize(),
                "code": sev_name,
                "passed": counts["passed"],
                "failed": counts["failed"],
                "errors": counts["errors"],
                "total": total_sev,
                "score": score_sev
            })
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    severity_breakdown.sort(key=lambda x: severity_order.get(x["code"], 99))
    
    # Format vendor breakdown list
    vendor_breakdown = []
    for v_code, counts in vendor_stats.items():
        total_v = counts["passed"] + counts["failed"] + counts["errors"]
        score_v = round((counts["passed"] / total_v) * 100, 1) if total_v > 0 else 100.0
        vendor_breakdown.append({
            "name": vendor_names.get(v_code, v_code.upper()),
            "code": v_code,
            "passed": counts["passed"],
            "failed": counts["failed"],
            "errors": counts["errors"],
            "total": total_v,
            "score": score_v
        })
    vendor_breakdown.sort(key=lambda x: x["score"])

    # Period-based stats
    scans_run_query = Scan.query.filter_by(status="completed")
    if start_date:
        scans_run_query = scans_run_query.filter(Scan.finished_at >= start_date)
    scans_run_count = scans_run_query.count()
    
    config_changes_query = ConfigSnapshot.query.filter_by(is_changed=True)
    if start_date:
        config_changes_query = config_changes_query.filter(ConfigSnapshot.collected_at >= start_date)
    config_changes_count = config_changes_query.count()
    
    unique_devices_sub = db.session.query(Result.device_uuid)\
        .join(Scan, Result.scan_id == Scan.id)\
        .filter(Scan.status == "completed")
    if start_date:
        unique_devices_sub = unique_devices_sub.filter(Scan.finished_at >= start_date)
    unique_devices_count = unique_devices_sub.distinct().count()

    period_stats = {
        "scans_run": scans_run_count,
        "config_changes": config_changes_count,
        "unique_devices": unique_devices_count
    }

    # Trend graph data (last 15 scans within period/generally)
    trend_scans_query = Scan.query.filter_by(status="completed")
    if start_date:
        trend_scans_query = trend_scans_query.filter(Scan.finished_at >= start_date)
    trend_scans = trend_scans_query.order_by(Scan.finished_at.desc()).limit(15).all()
    trend_scans.reverse()
    
    trend_data = []
    for s in trend_scans:
        trend_data.append({
            "date": (s.finished_at or s.started_at).strftime("%d.%m %H:%M"),
            "score": s.score,
            "passed": s.passed_count,
            "failed": s.failed_count,
            "errors": s.error_count
        })

    # Recent completed/running scans
    recent_scans = Scan.query.order_by(Scan.started_at.desc()).limit(5).all()
    
    # Recent failures across active devices
    if active_device_ids:
        recent_failures = Result.query.join(Device, Result.device_uuid == Device.id)\
            .filter(Result.status == "FAIL")\
            .filter(Device.is_active == True)\
            .order_by(Result.checked_at.desc())\
            .limit(10).all()
    else:
        recent_failures = []
    
    return render_template(
        "dashboard.html",
        score=infra_score,
        stats=stats,
        recent_failures=recent_failures,
        recent_scans=recent_scans,
        period=period,
        period_stats=period_stats,
        severity_breakdown=severity_breakdown,
        vendor_breakdown=vendor_breakdown,
        top_failing_rules=top_failing_rules,
        trend_data=trend_data
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


@web_bp.route("/devices")
def devices_list():
    """Device inventory with compliance status."""
    from app.models import Device, DeviceGroup
    
    devices = (
        Device.query
        .filter_by(is_active=True)
        .order_by(Device.hostname)
        .all()
    )
    
    # Get last completed scan for compliance data
    latest_scan = Scan.query.filter_by(status="completed").order_by(Scan.finished_at.desc()).first()
    
    # Build device compliance map from latest scan
    device_compliance = {}
    if latest_scan:
        results = Result.query.filter_by(scan_id=latest_scan.id).all()
        for r in results:
            did = r.device_id
            if did not in device_compliance:
                device_compliance[did] = {"passed": 0, "failed": 0, "errors": 0}
            if r.status == "PASS":
                device_compliance[did]["passed"] += 1
            elif r.status == "FAIL":
                device_compliance[did]["failed"] += 1
            elif r.status == "ERROR":
                device_compliance[did]["errors"] += 1
    
    vendors = Vendor.query.all()
    groups = DeviceGroup.query.filter_by(is_active=True).all()
    
    return render_template(
        "devices/list.html",
        devices=devices,
        device_compliance=device_compliance,
        latest_scan=latest_scan,
        vendors=vendors,
        groups=groups,
    )


@web_bp.route("/rules")
def rules_list():
    """List of rules grouped by vendor."""
    from collections import OrderedDict
    
    show_inactive = request.args.get("show_inactive", "false").lower() == "true"
    filter_policy = request.args.get("policy")
    filter_vendor = request.args.get("vendor")
    filter_severity = request.args.get("severity")
    
    query = Rule.query
    if not show_inactive:
        query = query.filter_by(is_active=True)
    if filter_policy:
        query = query.filter_by(policy_id=filter_policy)
    if filter_vendor:
        query = query.filter_by(vendor_code=filter_vendor)
    if filter_severity:
        query = query.filter_by(severity=filter_severity)
    
    rules = query.order_by(Rule.vendor_code, Rule.title).all()
    
    # Group by vendor
    vendor_groups = OrderedDict()
    for rule in rules:
        vcode = rule.vendor_code or "unknown"
        vname = rule.vendor.name if rule.vendor else vcode
        if vcode not in vendor_groups:
            vendor_groups[vcode] = {"name": vname, "rules": []}
        vendor_groups[vcode]["rules"].append(rule)
    
    policies = Policy.query.filter_by(is_active=True).all()
    vendors = Vendor.query.all()
    return render_template(
        "rules/list.html",
        vendor_groups=vendor_groups,
        rules=rules,
        show_inactive=show_inactive,
        policies=policies,
        vendors=vendors,
        filter_policy=filter_policy,
        filter_vendor=filter_vendor,
        filter_severity=filter_severity,
    )


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
