import logging
import os
import sys
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Set DATABASE_URL in the environment before app imports so Pydantic settings loads it
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_remediation.db"))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app import create_app, db
from app.models import ConfigSnapshot, Device, Scan, Vendor
from app.services.ansible_executor import SSHAnsibleExecutor
from app.tasks.maintenance_tasks import cleanup_old_data
from app.utils import utc_now


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_remediation_safety")


def test_ansible_escaping():
    logger.info("Testing Ansible command shell-escaping...")
    with patch("netmiko.ConnectHandler") as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.send_command.return_value = "unreachable=0 failed=0"

        executor = SSHAnsibleExecutor(
            {
                "host": "test-host",
                "username": "test-user",
                "playbook_dir": "/tmp/playbooks; rm -rf /",
                "inventory_file": "/etc/ansible/hosts; echo inject",
            }
        )

        res = executor.execute(
            playbook_name="test.yml",
            playbook_content="...",
            extra_vars={"var": "val'; inject_here"},
        )

        # Verify call arguments
        calls = mock_conn.send_command.call_args_list
        mkdir_cmd = calls[0][0][0]
        cat_cmd = calls[1][0][0]
        run_cmd = calls[2][0][0]

        logger.info(f"mkdir command: {mkdir_cmd}")
        logger.info(f"cat command: {cat_cmd}")
        logger.info(f"run command: {run_cmd}")

        # Ensure semicolon/spaces are quoted and not exposed as bare shell syntax
        assert "; rm -rf /" not in mkdir_cmd.split()
        assert "; echo inject" not in run_cmd.split()
        assert "val';" not in run_cmd

        logger.info("✔ Ansible command shell-escaping test passed.")


def test_at_rest_encryption(app):
    logger.info("Testing Data-at-Rest Encryption on ConfigSnapshot...")
    with app.app_context():
        # Setup device & vendor
        v = Vendor(code="cisco_ios", name="Cisco IOS")
        db.session.add(v)
        d = Device(id=uuid.uuid4(), hostname="test-router", vendor_code="cisco_ios", is_active=True)
        db.session.add(d)
        db.session.commit()

        # Create config snapshot
        secret_config = (
            "hostname test-router\ninterface GigabitEthernet1\n ip address 10.0.0.1 255.255.255.0"
        )
        snap = ConfigSnapshot(
            id=uuid.uuid4(),
            device_id=d.id,
            config_text=secret_config,
            config_hash="test-hash",
            config_size=len(secret_config),
            vendor_code="cisco_ios",
            is_changed=True,
        )
        db.session.add(snap)
        db.session.commit()

        # Query using raw SQL (direct database access)
        raw_result = db.session.execute(
            db.text("SELECT config_text FROM hcs_config_snapshots WHERE id = :snap_id"),
            {"snap_id": snap.id.hex},
        ).scalar()

        logger.info(f"Raw DB value: {raw_result}")
        assert raw_result != secret_config
        # Fernet tokens start with gAAAAA
        assert raw_result.startswith("gAAAAA")

        # Query using SQLAlchemy Model
        snap_loaded = db.session.get(ConfigSnapshot, snap.id)
        assert snap_loaded.config_text == secret_config
        logger.info("✔ Transparent Encryption & Decryption passed.")

        # Test fallback: Insert unencrypted string directly
        legacy_id = uuid.uuid4()
        legacy_config = "hostname legacy-router\nno service password-encryption"
        db.session.execute(
            db.text(
                "INSERT INTO hcs_config_snapshots (id, device_id, config_text, config_hash, config_size, vendor_code, is_changed) "
                "VALUES (:id, :device_id, :config_text, 'legacy-hash', :config_size, 'cisco_ios', 1)"
            ),
            {
                "id": legacy_id.hex,
                "device_id": d.id.hex,
                "config_text": legacy_config,
                "config_size": len(legacy_config),
            },
        )
        db.session.commit()

        # Load legacy row via Model
        legacy_loaded = db.session.get(ConfigSnapshot, legacy_id)
        assert legacy_loaded.config_text == legacy_config
        logger.info("✔ Transparent Legacy Decryption Fallback passed.")


def test_stuck_scans_valve(app):
    logger.info("Testing Stuck Scans Safety Valve...")
    with app.app_context():
        now = utc_now()

        # Create Scans with different ages and statuses
        # 1. Stuck running scan (5 hours old) -> should fail
        scan_stuck_running = Scan(
            id=uuid.uuid4(), status="running", started_at=now - timedelta(hours=5), total_devices=1
        )
        # 2. Stuck pending scan (4.5 hours old) -> should fail
        scan_stuck_pending = Scan(
            id=uuid.uuid4(),
            status="pending",
            started_at=now - timedelta(hours=4.5),
            total_devices=1,
        )
        # 3. Active running scan (1 hour old) -> should remain running
        scan_active_running = Scan(
            id=uuid.uuid4(), status="running", started_at=now - timedelta(hours=1), total_devices=1
        )
        # 4. Active pending scan (2 hours old) -> should remain pending
        scan_active_pending = Scan(
            id=uuid.uuid4(), status="pending", started_at=now - timedelta(hours=2), total_devices=1
        )
        # 5. Completed scan (6 hours old) -> should remain completed
        scan_completed = Scan(
            id=uuid.uuid4(),
            status="completed",
            started_at=now - timedelta(hours=6),
            finished_at=now - timedelta(hours=5.8),
            total_devices=1,
        )

        db.session.add_all(
            [
                scan_stuck_running,
                scan_stuck_pending,
                scan_active_running,
                scan_active_pending,
                scan_completed,
            ]
        )
        db.session.commit()

        # Run cleanup_old_data task
        results = cleanup_old_data()
        logger.info(f"Cleanup task results: {results}")

        # Assertions
        s1 = db.session.get(Scan, scan_stuck_running.id)
        assert s1.status == "failed"
        assert s1.error_message == "Scan timed out / worker terminated unexpectedly"
        assert s1.finished_at is not None

        s2 = db.session.get(Scan, scan_stuck_pending.id)
        assert s2.status == "failed"
        assert s2.error_message == "Scan timed out / worker terminated unexpectedly"
        assert s2.finished_at is not None

        s3 = db.session.get(Scan, scan_active_running.id)
        assert s3.status == "running"

        s4 = db.session.get(Scan, scan_active_pending.id)
        assert s4.status == "pending"

        s5 = db.session.get(Scan, scan_completed.id)
        assert s5.status == "completed"

        assert results.get("stuck_scans_failed") == 2
        logger.info("✔ Stuck Scans Safety Valve passed.")


def main():
    # Remove old test DB
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    app = create_app()
    with app.app_context():
        db.create_all()

    try:
        test_ansible_escaping()
        test_at_rest_encryption(app)
        test_stuck_scans_valve(app)
        logger.info("🎉 All remediation safety tests completed successfully!")
    finally:
        # Clean up database
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)


if __name__ == "__main__":
    main()
