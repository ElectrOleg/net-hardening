import logging
import os
import sys
import uuid
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Set DATABASE_URL in the environment before app imports so Pydantic settings loads it
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_dashboard.db"))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app import create_app, db
from app.models import ConfigSnapshot, Device, Policy, Result, Rule, Scan, Vendor


# Tell SQLAlchemy how to compile JSONB for SQLite databases during tests
@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_dashboard")


def seed_test_data():
    """Seeds a mockup database with controlled state to verify query math."""
    logger.info("Seeding database with test data...")

    # 1. Create Vendors
    v_cisco = Vendor(code="cisco", name="Cisco Systems")
    v_juniper = Vendor(code="juniper", name="Juniper Networks")
    v_eltex = Vendor(code="eltex", name="Eltex Enterprise")
    db.session.add_all([v_cisco, v_juniper, v_eltex])

    # 2. Create Active Devices
    d1 = Device(id=uuid.uuid4(), hostname="cisco-router-1", vendor_code="cisco", is_active=True)
    d2 = Device(id=uuid.uuid4(), hostname="juniper-switch-1", vendor_code="juniper", is_active=True)
    d3 = Device(id=uuid.uuid4(), hostname="eltex-cpe-1", vendor_code="eltex", is_active=True)
    # Inactive device (should be ignored by active state aggregation)
    d4 = Device(id=uuid.uuid4(), hostname="retired-device", vendor_code="cisco", is_active=False)
    db.session.add_all([d1, d2, d3, d4])
    db.session.commit()

    # 3. Create Policy and Rules
    pol = Policy(id=uuid.uuid4(), name="Default Test Policy")
    db.session.add(pol)
    db.session.commit()

    r_ssh = Rule(
        id=uuid.uuid4(),
        policy_id=pol.id,
        title="Enable SSH version 2",
        severity="critical",
        vendor_code="cisco",
        is_active=True,
        logic_type="simple_match",
        logic_payload={},
    )
    r_banner = Rule(
        id=uuid.uuid4(),
        policy_id=pol.id,
        title="Login Banner Set",
        severity="medium",
        vendor_code="cisco",
        is_active=True,
        logic_type="simple_match",
        logic_payload={},
    )
    r_snmp = Rule(
        id=uuid.uuid4(),
        policy_id=pol.id,
        title="SNMP Public Community Disabled",
        severity="high",
        vendor_code="juniper",
        is_active=True,
        logic_type="simple_match",
        logic_payload={},
    )
    r_ntp = Rule(
        id=uuid.uuid4(),
        policy_id=pol.id,
        title="NTP Configured",
        severity="low",
        vendor_code="eltex",
        is_active=True,
        logic_type="simple_match",
        logic_payload={},
    )
    db.session.add_all([r_ssh, r_banner, r_snmp, r_ntp])
    db.session.commit()

    # 4. Create Scans
    now = datetime.utcnow()
    # Scan 1: 5 days ago, completed (D1, D2 scanned)
    s1 = Scan(
        id=uuid.uuid4(),
        started_by="cron",
        status="completed",
        started_at=now - timedelta(days=5),
        finished_at=now - timedelta(days=5),
        passed_count=1,
        failed_count=1,
        error_count=0,
        total_devices=2,
    )
    # Scan 2: 2 days ago, completed (D1 scanned)
    s2 = Scan(
        id=uuid.uuid4(),
        started_by="admin",
        status="completed",
        started_at=now - timedelta(days=2),
        finished_at=now - timedelta(days=2),
        passed_count=2,
        failed_count=0,
        error_count=0,
        total_devices=1,
    )
    # Scan 3: 1 day ago, completed (D2, D3 scanned)
    s3 = Scan(
        id=uuid.uuid4(),
        started_by="admin",
        status="completed",
        started_at=now - timedelta(days=1),
        finished_at=now - timedelta(days=1),
        passed_count=1,
        failed_count=1,
        error_count=0,
        total_devices=2,
    )
    db.session.add_all([s1, s2, s3])
    db.session.commit()

    # 5. Create scan results
    # Scan 1: D1 passed r_ssh, D2 failed r_snmp
    res1 = Result(
        id=uuid.uuid4(),
        scan_id=s1.id,
        device_uuid=d1.id,
        device_id=d1.hostname,
        rule_id=r_ssh.id,
        status="PASS",
        checked_at=s1.finished_at,
    )
    res2 = Result(
        id=uuid.uuid4(),
        scan_id=s1.id,
        device_uuid=d2.id,
        device_id=d2.hostname,
        rule_id=r_snmp.id,
        status="FAIL",
        checked_at=s1.finished_at,
    )

    # Scan 2: D1 passed both r_ssh & r_banner (latest results for D1)
    res3 = Result(
        id=uuid.uuid4(),
        scan_id=s2.id,
        device_uuid=d1.id,
        device_id=d1.hostname,
        rule_id=r_ssh.id,
        status="PASS",
        checked_at=s2.finished_at,
    )
    res4 = Result(
        id=uuid.uuid4(),
        scan_id=s2.id,
        device_uuid=d1.id,
        device_id=d1.hostname,
        rule_id=r_banner.id,
        status="PASS",
        checked_at=s2.finished_at,
    )

    # Scan 3: D2 passed r_snmp (latest result for D2); D3 failed r_ntp (latest result for D3)
    res5 = Result(
        id=uuid.uuid4(),
        scan_id=s3.id,
        device_uuid=d2.id,
        device_id=d2.hostname,
        rule_id=r_snmp.id,
        status="PASS",
        checked_at=s3.finished_at,
    )
    res6 = Result(
        id=uuid.uuid4(),
        scan_id=s3.id,
        device_uuid=d3.id,
        device_id=d3.hostname,
        rule_id=r_ntp.id,
        status="FAIL",
        checked_at=s3.finished_at,
    )

    db.session.add_all([res1, res2, res3, res4, res5, res6])

    # 6. Config Snapshots
    # D1 snapshot in Scan 1
    snap1 = ConfigSnapshot(
        id=uuid.uuid4(),
        device_id=d1.id,
        scan_id=s1.id,
        config_hash="h1",
        is_changed=True,
        collected_at=s1.finished_at,
        vendor_code="cisco",
    )
    # D1 snapshot in Scan 2 (changed config)
    snap2 = ConfigSnapshot(
        id=uuid.uuid4(),
        device_id=d1.id,
        scan_id=s2.id,
        config_hash="h2",
        is_changed=True,
        collected_at=s2.finished_at,
        vendor_code="cisco",
    )
    # D2 snapshot in Scan 3 (unchanged config)
    snap3 = ConfigSnapshot(
        id=uuid.uuid4(),
        device_id=d2.id,
        scan_id=s3.id,
        config_hash="h3",
        is_changed=False,
        collected_at=s3.finished_at,
        vendor_code="juniper",
    )

    db.session.add_all([snap1, snap2, snap3])
    db.session.commit()

    logger.info("Test data successfully seeded.")
    return {
        "devices": [d1, d2, d3, d4],
        "rules": [r_ssh, r_banner, r_snmp, r_ntp],
        "scans": [s1, s2, s3],
    }


def run_dashboard_test():
    app = create_app()
    # Force SQLite test database
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{TEST_DB_PATH}"
    app.config["TESTING"] = True

    # Clean up test DB if it exists
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    with app.app_context():
        db.create_all()
        seed_test_data()

        logger.info("Executing dashboard queries on SQLite database...")

        # 1. Fetch active devices
        active_devices = Device.query.filter_by(is_active=True).all()
        active_device_ids = [d.id for d in active_devices]
        total_active_devices = len(active_device_ids)
        assert total_active_devices == 3, f"Expected 3 active devices, got {total_active_devices}"

        # 2. Latest completed scan started_at per active device
        latest_scans_sub = (
            db.session.query(Result.device_uuid, func.max(Scan.started_at).label("max_started_at"))
            .join(Scan, Result.scan_id == Scan.id)
            .filter(Scan.status == "completed")
            .filter(Result.device_uuid.in_(active_device_ids))
            .group_by(Result.device_uuid)
            .subquery()
        )

        latest_scans = (
            db.session.query(Result.device_uuid, Scan.id.label("scan_id"))
            .join(Scan, Result.scan_id == Scan.id)
            .join(
                latest_scans_sub,
                (Result.device_uuid == latest_scans_sub.c.device_uuid)
                & (Scan.started_at == latest_scans_sub.c.max_started_at),
            )
            .distinct()
            .subquery()
        )

        # Fetch the results of those latest scans for each active device
        latest_results = (
            db.session.query(Result.status, Result.device_uuid, Rule.severity, Device.vendor_code)
            .join(Rule, Result.rule_id == Rule.id)
            .join(Device, Result.device_uuid == Device.id)
            .join(
                latest_scans,
                (Result.device_uuid == latest_scans.c.device_uuid)
                & (Result.scan_id == latest_scans.c.scan_id),
            )
            .all()
        )

        # Assertions on Latest Results:
        # D1: res3 (PASS) and res4 (PASS)
        # D2: res5 (PASS)
        # D3: res6 (FAIL)
        # Total: 4 results (3 PASS, 1 FAIL)
        assert len(latest_results) == 4, f"Expected 4 active results, got {len(latest_results)}"

        passed = sum(1 for r in latest_results if r.status == "PASS")
        failed = sum(1 for r in latest_results if r.status == "FAIL")
        errors = sum(1 for r in latest_results if r.status == "ERROR")

        assert passed == 3, f"Expected 3 PASS, got {passed}"
        assert failed == 1, f"Expected 1 FAIL, got {failed}"
        assert errors == 0, f"Expected 0 ERROR, got {errors}"

        score = round((passed / len(latest_results)) * 100, 1)
        assert score == 75.0, f"Expected 75.0% compliance, got {score}%"
        logger.info(f"✔ Infrastructure Score aggregation validated successfully: {score}%")

        # 3. Vendor breakdown:
        # Cisco: 2 checks (both PASS) -> 100% compliance
        # Juniper: 1 check (PASS) -> 100% compliance
        # Eltex: 1 check (FAIL) -> 0% compliance
        vendor_stats = {}
        for r in latest_results:
            v_code = r.vendor_code or "unknown"
            if v_code not in vendor_stats:
                vendor_stats[v_code] = {"passed": 0, "failed": 0, "errors": 0}
            if r.status == "PASS":
                vendor_stats[v_code]["passed"] += 1
            elif r.status == "FAIL":
                vendor_stats[v_code]["failed"] += 1

        assert vendor_stats["cisco"]["passed"] == 2
        assert vendor_stats["juniper"]["passed"] == 1
        assert vendor_stats["eltex"]["failed"] == 1
        logger.info("✔ Vendor breakdowns validated successfully.")

        # 4. Severity breakdown:
        # Critical (r_ssh): 1 check (PASS) -> 100%
        # High (r_snmp): 1 check (PASS) -> 100%
        # Medium (r_banner): 1 check (PASS) -> 100%
        # Low (r_ntp): 1 check (FAIL) -> 0%
        severity_stats = {
            "critical": {"passed": 0, "failed": 0, "errors": 0},
            "high": {"passed": 0, "failed": 0, "errors": 0},
            "medium": {"passed": 0, "failed": 0, "errors": 0},
            "low": {"passed": 0, "failed": 0, "errors": 0},
        }
        for r in latest_results:
            sev = (r.severity or "medium").lower()
            if sev in severity_stats:
                if r.status == "PASS":
                    severity_stats[sev]["passed"] += 1
                elif r.status == "FAIL":
                    severity_stats[sev]["failed"] += 1

        assert severity_stats["critical"]["passed"] == 1
        assert severity_stats["low"]["failed"] == 1
        logger.info("✔ Severity/criticality breakdowns validated successfully.")

        # 5. Period stats (within last 30 days, which is all)
        scans_run_count = Scan.query.filter_by(status="completed").count()
        config_changes_count = ConfigSnapshot.query.filter_by(is_changed=True).count()

        assert scans_run_count == 3, f"Expected 3 scans, got {scans_run_count}"
        assert config_changes_count == 2, (
            f"Expected 2 changed config snapshots (snap1, snap2), got {config_changes_count}"
        )
        logger.info("✔ Period metrics (scans, config changes) validated successfully.")

        # 6. Top failing rules
        top_rules = (
            db.session.query(Rule.title, func.count(Result.id).label("fail_count"))
            .join(Result, Result.rule_id == Rule.id)
            .join(Scan, Result.scan_id == Scan.id)
            .join(Device, Result.device_uuid == Device.id)
            .join(
                latest_scans,
                (Result.device_uuid == latest_scans.c.device_uuid)
                & (Result.scan_id == latest_scans.c.scan_id),
            )
            .filter(Result.status == "FAIL")
            .group_by(Rule.id, Rule.title)
            .order_by(func.count(Result.id).desc())
            .limit(5)
            .all()
        )

        assert len(top_rules) == 1, f"Expected 1 failing rule, got {len(top_rules)}"
        assert top_rules[0].title == "NTP Configured"
        assert top_rules[0].fail_count == 1
        logger.info("✔ Top failing rules query validated successfully.")

        # Clean up database tables
        db.drop_all()

    # Delete DB file
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    logger.info(
        "🎉 All dashboard queries verified and passed successfully on SQLite mockup database!"
    )


if __name__ == "__main__":
    run_dashboard_test()
