import pytest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch
from contextlib import contextmanager

from app.models import Scan, Device
from app.models.scan_schedule import ScanSchedule
from app.models.system_setting import SystemSetting
from app.tasks.maintenance_tasks import auto_run_scheduled_scans

class DummyLock:
    @contextmanager
    def acquire(self, key, ttl=600):
        yield "dummy_token"

def test_auto_run_scheduled_scans(app, session):
    """Test that auto_run_scheduled_scans correctly schedules due scans via run_scan.delay."""
    # Enable automatic scans
    SystemSetting.set("scan.auto_enabled", "true")
    session.commit()
    
    # 1. Create a schedule
    schedule = ScanSchedule(
        id=uuid.uuid4(),
        name="Nightly Cisco Scan",
        cron_expression="0 2 * * *",
        is_enabled=True,
        next_run_at=datetime.utcnow() - timedelta(minutes=1),
        policies_filter=["f47ac10b-58cc-4372-a567-0e02b2c3d479"],
        devices_filter={"vendor": "cisco_ios"}
    )
    session.add(schedule)
    session.commit()
    
    # 2. Run task with mocked lock and Celery run_scan
    with patch("app.utils.distributed_lock.get_lock") as mock_get_lock, \
         patch("app.tasks.scan_tasks.run_scan.delay") as mock_run_scan_delay:
        mock_get_lock.return_value = DummyLock()
        result = auto_run_scheduled_scans()
        
        # Verify the return value
        assert result == {"started": 1, "checked": 1}
        
        # Verify run_scan.delay was called
        mock_run_scan_delay.assert_called_once()
        called_scan_id = mock_run_scan_delay.call_args[0][0]
        
        # Verify the created Scan object (converting to UUID to prevent SQLite error)
        scan = Scan.query.get(uuid.UUID(called_scan_id))
        assert scan is not None
        assert scan.status == "pending"
        assert scan.policies_filter == ["f47ac10b-58cc-4372-a567-0e02b2c3d479"]
        assert scan.devices_filter == {"vendor": "cisco_ios"}
        assert scan.started_by == "schedule: Nightly Cisco Scan"
        
        # Verify schedule was updated
        updated_schedule = ScanSchedule.query.get(schedule.id)
        assert updated_schedule.last_run_at is not None
        assert updated_schedule.last_scan_id == scan.id
        assert updated_schedule.next_run_at > datetime.utcnow()


def test_get_devices_from_inventory_filtering(app, session):
    """Test that _get_devices_from_inventory applies vendor/group filters and parses UUIDs correctly."""
    from app.services import ScannerService
    from app.models import Device, Vendor
    from app.models.device_group import DeviceGroup
    
    # Clean database from leaking test data
    Device.query.delete()
    DeviceGroup.query.delete()
    session.commit()
    
    # Setup vendors and groups
    v_cisco = Vendor.query.filter_by(code="cisco_ios").first()
    if not v_cisco:
        v_cisco = Vendor(code="cisco_ios", name="Cisco")
        session.add(v_cisco)
        
    v_juniper = Vendor(code="juniper_junos", name="Juniper")
    session.add(v_juniper)
    
    group_a = DeviceGroup(id=uuid.uuid4(), name="Group A")
    group_b = DeviceGroup(id=uuid.uuid4(), name="Group B")
    session.add_all([group_a, group_b])
    session.commit()
    
    # Create devices
    d1 = Device(id=uuid.uuid4(), hostname="router1", vendor_code="cisco_ios", group_id=group_a.id, is_active=True)
    d2 = Device(id=uuid.uuid4(), hostname="router2", vendor_code="cisco_ios", group_id=group_b.id, is_active=True)
    d3 = Device(id=uuid.uuid4(), hostname="switch1", vendor_code="juniper_junos", group_id=group_a.id, is_active=True)
    d4 = Device(id=uuid.uuid4(), hostname="inactive", vendor_code="cisco_ios", group_id=group_a.id, is_active=False)
    session.add_all([d1, d2, d3, d4])
    session.commit()
    
    service = ScannerService()
    
    # Test case 1: No filters
    devices = service._get_devices_from_inventory(rules=None, devices_filter=None)
    assert set(devices) == {"router1", "router2", "switch1"}
    
    # Test case 2: Vendor filter
    devices = service._get_devices_from_inventory(rules=None, devices_filter={"vendor": "cisco_ios"})
    assert set(devices) == {"router1", "router2"}
    
    # Test case 3: Group filter (UUID object)
    devices = service._get_devices_from_inventory(rules=None, devices_filter={"group_id": group_a.id})
    assert set(devices) == {"router1", "switch1"}
    
    # Test case 4: Group filter (string UUID representation)
    devices = service._get_devices_from_inventory(rules=None, devices_filter={"group_id": str(group_a.id)})
    assert set(devices) == {"router1", "switch1"}
    
    # Test case 5: Combined vendor and group filters
    devices = service._get_devices_from_inventory(rules=None, devices_filter={"vendor": "cisco_ios", "group_id": str(group_a.id)})
    assert set(devices) == {"router1"}
