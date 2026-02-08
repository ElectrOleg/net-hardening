"""Prometheus / OpenMetrics endpoint for external monitoring integration.

Exposes compliance metrics at GET /metrics in Prometheus text format.
Compatible with Prometheus, Grafana Agent, Zabbix HTTP agent, VictoriaMetrics.

Metrics exposed:
  hcs_compliance_score           — per-device compliance score (gauge)
  hcs_rules_total                — total rules checked (counter-like gauge)
  hcs_rules_passed_total         — passed rules (counter-like gauge)
  hcs_rules_failed_total         — failed rules (counter-like gauge)
  hcs_rules_error_total          — errored rules (counter-like gauge)
  hcs_scan_last_timestamp        — Unix timestamp of last completed scan
  hcs_scan_duration_seconds      — duration of last completed scan
  hcs_devices_total              — total devices by status
  hcs_policy_compliance_score    — compliance score per policy
"""
from flask import Response, Blueprint
from sqlalchemy import func

from app.extensions import db
from app.models import Scan, Result, Rule, Device

metrics_bp = Blueprint("metrics", __name__)


def _prometheus_line(name: str, value, labels: dict | None = None, 
                     metric_type: str | None = None, help_text: str | None = None) -> str:
    """Format a single Prometheus metric line."""
    lines = []
    if help_text:
        lines.append(f"# HELP {name} {help_text}")
    if metric_type:
        lines.append(f"# TYPE {name} {metric_type}")
    
    if labels:
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items() if v is not None)
        lines.append(f"{name}{{{label_str}}} {value}")
    else:
        lines.append(f"{name} {value}")
    
    return "\n".join(lines)


@metrics_bp.route("/metrics", methods=["GET"])
def prometheus_metrics():
    """Prometheus-compatible metrics endpoint."""
    lines = []
    
    # ── Last scan info ──────────────────────────────────────────────
    last_scan = Scan.query.filter_by(status="completed").order_by(
        Scan.finished_at.desc()
    ).first()
    
    if last_scan:
        # Scan timestamp
        ts = last_scan.finished_at.timestamp() if last_scan.finished_at else 0
        lines.append(_prometheus_line(
            "hcs_scan_last_timestamp", ts,
            metric_type="gauge",
            help_text="Unix timestamp of the last completed scan"
        ))
        
        # Scan duration
        if last_scan.started_at and last_scan.finished_at:
            duration = (last_scan.finished_at - last_scan.started_at).total_seconds()
            lines.append(_prometheus_line(
                "hcs_scan_duration_seconds", round(duration, 2),
                metric_type="gauge",
                help_text="Duration of the last completed scan in seconds"
            ))
        
        # Global scan score
        lines.append(_prometheus_line(
            "hcs_scan_score", last_scan.score,
            metric_type="gauge",
            help_text="Overall compliance score of the last scan (0-100)"
        ))
        
        # Global rule counts
        lines.append(_prometheus_line(
            "hcs_rules_total", 
            last_scan.passed_count + last_scan.failed_count + last_scan.error_count,
            metric_type="gauge",
            help_text="Total rules evaluated in the last scan"
        ))
        lines.append(_prometheus_line(
            "hcs_rules_passed_total", last_scan.passed_count,
            metric_type="gauge",
            help_text="Rules passed in the last scan"
        ))
        lines.append(_prometheus_line(
            "hcs_rules_failed_total", last_scan.failed_count,
            metric_type="gauge",
            help_text="Rules failed in the last scan"
        ))
        lines.append(_prometheus_line(
            "hcs_rules_error_total", last_scan.error_count,
            metric_type="gauge",
            help_text="Rules errored in the last scan"
        ))
        
        scan_id = last_scan.id
        
        # ── Per-device compliance ───────────────────────────────────
        device_stats = db.session.query(
            Result.device_id,
            Result.status,
            func.count(Result.id)
        ).filter(
            Result.scan_id == scan_id
        ).group_by(Result.device_id, Result.status).all()
        
        # Aggregate per device
        devices: dict[str, dict] = {}
        for device_id, status, count in device_stats:
            if device_id not in devices:
                devices[device_id] = {"PASS": 0, "FAIL": 0, "ERROR": 0, "SKIPPED": 0}
            devices[device_id][status] = count
        
        # Enrich with Device metadata (vendor, location, extra_data)
        device_meta: dict[str, dict] = {}
        if devices:
            device_objs = Device.query.filter(
                (Device.hostname.in_(devices.keys())) | 
                (Device.ip_address.in_(devices.keys()))
            ).all()
            for d in device_objs:
                key = d.hostname if d.hostname in devices else d.ip_address
                if key:
                    device_meta[key] = {
                        "vendor": d.vendor_code or "unknown",
                        "location": d.location or "unknown",
                        "os_version": d.os_version or "",
                        "hardware": d.hardware or "",
                    }
        
        lines.append("")
        lines.append(f"# HELP hcs_compliance_score Per-device compliance score (0-100)")
        lines.append(f"# TYPE hcs_compliance_score gauge")
        
        for device_id, stats in devices.items():
            total = stats["PASS"] + stats["FAIL"] + stats["ERROR"]
            score = round((stats["PASS"] / total) * 100, 1) if total > 0 else 100.0
            
            meta = device_meta.get(device_id, {})
            labels = {
                "device": device_id,
                "vendor": meta.get("vendor", "unknown"),
                "location": meta.get("location", "unknown"),
            }
            
            label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
            lines.append(f"hcs_compliance_score{{{label_str}}} {score}")
        
        # ── Per-device rule counts ──────────────────────────────────
        lines.append("")
        lines.append("# HELP hcs_device_rules_passed Per-device passed rules count")
        lines.append("# TYPE hcs_device_rules_passed gauge")
        for device_id, stats in devices.items():
            meta = device_meta.get(device_id, {})
            label_str = f'device="{device_id}",vendor="{meta.get("vendor", "unknown")}"'
            lines.append(f"hcs_device_rules_passed{{{label_str}}} {stats['PASS']}")
        
        lines.append("")
        lines.append("# HELP hcs_device_rules_failed Per-device failed rules count")
        lines.append("# TYPE hcs_device_rules_failed gauge")
        for device_id, stats in devices.items():
            meta = device_meta.get(device_id, {})
            label_str = f'device="{device_id}",vendor="{meta.get("vendor", "unknown")}"'
            lines.append(f"hcs_device_rules_failed{{{label_str}}} {stats['FAIL']}")
        
        # ── Per-policy compliance ───────────────────────────────────
        policy_stats = db.session.query(
            Rule.policy_id,
            Result.status,
            func.count(Result.id)
        ).join(Rule, Result.rule_id == Rule.id).filter(
            Result.scan_id == scan_id
        ).group_by(Rule.policy_id, Result.status).all()
        
        policies: dict[str, dict] = {}
        for policy_id, status, count in policy_stats:
            pid = str(policy_id)
            if pid not in policies:
                policies[pid] = {"PASS": 0, "FAIL": 0, "ERROR": 0}
            policies[pid][status] = count
        
        if policies:
            lines.append("")
            lines.append("# HELP hcs_policy_compliance_score Per-policy compliance score (0-100)")
            lines.append("# TYPE hcs_policy_compliance_score gauge")
            for pid, stats in policies.items():
                total = stats["PASS"] + stats["FAIL"] + stats["ERROR"]
                score = round((stats["PASS"] / total) * 100, 1) if total > 0 else 100.0
                lines.append(f'hcs_policy_compliance_score{{policy_id="{pid}"}} {score}')
    
    # ── Device inventory counts ─────────────────────────────────────
    active_count = Device.query.filter_by(is_active=True).count()
    inactive_count = Device.query.filter_by(is_active=False).count()
    
    lines.append("")
    lines.append(_prometheus_line(
        "hcs_devices_total", active_count,
        labels={"status": "active"},
        metric_type="gauge",
        help_text="Total number of devices in inventory"
    ))
    lines.append(_prometheus_line(
        "hcs_devices_total", inactive_count,
        labels={"status": "inactive"},
    ))
    
    output = "\n".join(lines) + "\n"
    
    return Response(output, mimetype="text/plain; version=0.0.4; charset=utf-8")
