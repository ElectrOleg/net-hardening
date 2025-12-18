"""Export Service - PDF and CSV report generation."""
import io
import csv
from datetime import datetime
from typing import Optional

from app.models import Scan, Result, Rule, Policy


class ExportService:
    """Service for generating export reports."""
    
    def export_scan_csv(self, scan_id: str) -> str:
        """Export scan results to CSV."""
        scan = Scan.query.get(scan_id)
        if not scan:
            raise ValueError("Scan not found")
        
        results = Result.query.filter_by(scan_id=scan_id).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            "Device",
            "Rule",
            "Policy",
            "Vendor",
            "Status",
            "Message",
            "Diff Data",
            "Checked At"
        ])
        
        # Data rows
        for r in results:
            writer.writerow([
                r.device_id,
                r.rule.title if r.rule else "",
                r.rule.policy.name if r.rule and r.rule.policy else "",
                r.rule.vendor_code if r.rule else "",
                r.status,
                r.message or "",
                (r.diff_data or "").replace("\n", " | "),
                r.checked_at.isoformat() if r.checked_at else ""
            ])
        
        return output.getvalue()
    
    def export_matrix_csv(self, scan_id: Optional[str] = None) -> str:
        """Export compliance matrix to CSV."""
        from sqlalchemy import func
        from app.extensions import db
        
        if not scan_id:
            scan = Scan.query.filter_by(status="completed").order_by(Scan.finished_at.desc()).first()
            if not scan:
                raise ValueError("No completed scans")
            scan_id = scan.id
        
        # Get all results with rule info
        results = db.session.query(Result, Rule).join(Rule).filter(
            Result.scan_id == scan_id
        ).all()
        
        # Build matrix
        matrix = {}
        policies_set = set()
        
        for result, rule in results:
            device = result.device_id
            policy_id = str(rule.policy_id)
            policies_set.add(policy_id)
            
            if device not in matrix:
                matrix[device] = {}
            if policy_id not in matrix[device]:
                matrix[device][policy_id] = {"pass": 0, "fail": 0, "total": 0}
            
            if result.status == "PASS":
                matrix[device][policy_id]["pass"] += 1
            elif result.status == "FAIL":
                matrix[device][policy_id]["fail"] += 1
            matrix[device][policy_id]["total"] += 1
        
        # Get policy names
        policies = {str(p.id): p.name for p in Policy.query.all()}
        policy_ids = sorted(policies_set)
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        header = ["Device"] + [policies.get(pid, pid[:8]) for pid in policy_ids] + ["Total Score"]
        writer.writerow(header)
        
        # Data rows
        for device in sorted(matrix.keys()):
            row = [device]
            total_pass = 0
            total_total = 0
            
            for pid in policy_ids:
                cell = matrix[device].get(pid, {"pass": 0, "total": 0})
                if cell["total"] > 0:
                    pct = round((cell["pass"] / cell["total"]) * 100)
                    row.append(f"{pct}%")
                else:
                    row.append("N/A")
                total_pass += cell["pass"]
                total_total += cell["total"]
            
            # Total score
            total_pct = round((total_pass / total_total) * 100) if total_total > 0 else 100
            row.append(f"{total_pct}%")
            
            writer.writerow(row)
        
        return output.getvalue()
    
    def export_failures_csv(self, scan_id: str) -> str:
        """Export only failures to CSV."""
        results = Result.query.filter_by(scan_id=scan_id, status="FAIL").all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow([
            "Device",
            "Rule",
            "Description",
            "Remediation",
            "Diff Data"
        ])
        
        for r in results:
            writer.writerow([
                r.device_id,
                r.rule.title if r.rule else "",
                r.rule.description if r.rule else "",
                r.rule.remediation if r.rule else "",
                r.diff_data or ""
            ])
        
        return output.getvalue()
    
    def generate_summary_report(self, scan_id: str) -> dict:
        """Generate summary report data."""
        scan = Scan.query.get(scan_id)
        if not scan:
            raise ValueError("Scan not found")
        
        results = Result.query.filter_by(scan_id=scan_id).all()
        
        # Group by device
        devices = {}
        for r in results:
            if r.device_id not in devices:
                devices[r.device_id] = {"pass": 0, "fail": 0, "error": 0}
            devices[r.device_id][r.status.lower()] = devices[r.device_id].get(r.status.lower(), 0) + 1
        
        # Find worst devices
        worst_devices = sorted(
            devices.items(),
            key=lambda x: x[1].get("fail", 0),
            reverse=True
        )[:10]
        
        # Top failing rules
        rule_failures = {}
        for r in results:
            if r.status == "FAIL" and r.rule:
                rule_id = str(r.rule_id)
                if rule_id not in rule_failures:
                    rule_failures[rule_id] = {"title": r.rule.title, "count": 0}
                rule_failures[rule_id]["count"] += 1
        
        top_failing_rules = sorted(
            rule_failures.values(),
            key=lambda x: x["count"],
            reverse=True
        )[:10]
        
        return {
            "scan_id": str(scan_id),
            "scan_date": scan.started_at.isoformat(),
            "score": scan.score,
            "total_devices": scan.total_devices,
            "passed": scan.passed_count,
            "failed": scan.failed_count,
            "errors": scan.error_count,
            "worst_devices": worst_devices,
            "top_failing_rules": top_failing_rules,
            "compliant_devices": sum(1 for d in devices.values() if d.get("fail", 0) == 0)
        }


# Singleton
export_service = ExportService()
