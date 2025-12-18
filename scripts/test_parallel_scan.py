import sys
import os
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import Scan, DataSource, Policy, Rule, Result
from app.tasks.scan_tasks import run_scan
from app.core.registry import registry

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_simulation")

def setup_test_data():
    """Create dummy data for the test."""
    logger.info("Setting up test data...")
    
    # 1. Create Data Source (Local)
    ds = DataSource.query.filter_by(name="Test Local Source").first()
    if not ds:
        ds = DataSource(
            name="Test Local Source",
            type="local", 
            connection_params={"path": "/tmp/test_configs"},
            is_active=True
        )
        db.session.add(ds)
    
    # 2. Create Policy
    policy = Policy.query.filter_by(name="Test Policy").first()
    if not policy:
        policy = Policy(name="Test Policy", description="For testing")
        db.session.add(policy)
        db.session.commit() # Need ID
    
    # 3. Create Rules (Cisco & Juniper)
    rule_cisco = Rule.query.filter_by(title="Cisco Hostname Check").first()
    if not rule_cisco:
        rule_cisco = Rule(
            title="Cisco Hostname Check",
            policy_id=policy.id,
            vendor_code="cisco_ios",
            logic_type="simple_match",
            logic_payload={"pattern": "hostname", "match_mode": "must_exist"},
            is_active=True
        )
        db.session.add(rule_cisco)

    rule_juniper = Rule.query.filter_by(title="Juniper Hostname Check").first()
    if not rule_juniper:
        rule_juniper = Rule(
            title="Juniper Hostname Check",
            policy_id=policy.id,
            vendor_code="juniper_junos",
            logic_type="simple_match",
            logic_payload={"pattern": "system { host-name", "match_mode": "must_exist"},
            is_active=True
        )
        db.session.add(rule_juniper)
    
    db.session.commit()
    return ds

def create_dummy_config():
    """Create a dummy config file."""
    os.makedirs("/tmp/test_configs", exist_ok=True)
    # Device 1: Cisco
    with open("/tmp/test_configs/device1.cfg", "w") as f:
        f.write("! Vendor: cisco_ios\nhostname device1\ninterface Gi0/0\n ip address 1.1.1.1 255.255.255.0")
    # Device 2: Juniper (simulated)
    with open("/tmp/test_configs/device2.cfg", "w") as f:
        f.write("# Vendor: juniper_junos\nsystem { host-name device2; }")

def run_test():
    """Run the simulation."""
    app = create_app()
    # Force IPv4 to hit Docker
    app.config['SQLALCHEMY_DATABASE_URI'] = "postgresql://hcs:hcs@127.0.0.1:5432/hcs"
    app.config['CELERY_TASK_ALWAYS_EAGER'] = True # Run synchronously for test
    app.config['WaitDurationSeconds'] = 0 # No wait
    
    with app.app_context():
        # Ensure registry is initialized
        if not registry._initialized:
            registry.initialize_defaults()
            
        create_dummy_config()
        setup_test_data()
        
        logger.info("Creating Scan record...")
        scan = Scan(started_by="tester", status="pending")
        db.session.add(scan)
        db.session.commit()
        
        logger.info(f"Triggering run_scan for Scan ID: {scan.id}...")
        
        # Determine devices (our Local provider will find device1.cfg and device2.cfg)
        # We pass None for device_ids to let scanner discover them
        try:
            run_scan.apply(args=[str(scan.id)], throw=True)
        except Exception as e:
            logger.error(f"Scan task failed: {e}")
            return
            
        # Refetch scan
        db.session.refresh(scan)
        logger.info("="*30)
        logger.info(f"Scan Status: {scan.status}")
        logger.info(f"Devices Scanned: {scan.total_devices}")
        logger.info(f"Passed: {scan.passed_count}")
        logger.info(f"Failed: {scan.failed_count}")
        logger.info(f"Errors: {scan.error_count}")
        logger.info("="*30)
        
        # Check Results
        results = Result.query.filter_by(scan_id=scan.id).all()
        for res in results:
            logger.info(f"Device: {res.device_id} | Rule: {res.rule_id} | Status: {res.status}")

if __name__ == "__main__":
    run_test()
