"""Scanner Service - orchestrates the scanning process."""
import logging
from datetime import datetime
from typing import Optional

from app.extensions import db
from app.models import Scan, Rule, Result, RuleException, DataSource
from app.engine import RuleEvaluator
from app.providers import GitLabProvider, SSHProvider, APIProvider
from app.providers.base import ConfigSourceProvider

logger = logging.getLogger(__name__)


class ScannerService:
    """
    Main scanning orchestrator.
    
    Workflow:
    1. Get list of devices
    2. Get applicable rules
    3. Fetch configs from data sources
    4. Evaluate rules against configs
    5. Check exceptions
    6. Save results
    """
    
    def __init__(self):
        self.evaluator = RuleEvaluator()
    
    def initialize_scan(self, scan_id: str, device_ids: Optional[list[str]] = None) -> list[str]:
        """
        Initialize scan record and return list of devices to scan.
        """
        scan = Scan.query.get(scan_id)
        if not scan:
            raise ValueError(f"Scan {scan_id} not found")
            
        scan.status = "running"
        db.session.commit()
        
        # Get data sources
        data_sources = DataSource.query.filter_by(is_active=True).all()
        if not data_sources:
            raise ValueError("No active data sources configured")
            
        # Get devices
        devices = device_ids or self._get_devices_from_sources(data_sources)
        scan.total_devices = len(devices)
        
        # Get active rules
        rules = self._get_applicable_rules(scan.policies_filter)
        scan.total_rules = len(rules)
        
        db.session.commit()
        
        if not rules:
            raise ValueError("No active rules found")
            
        return devices

    def scan_single_device(self, scan_id: str, device_id: str) -> tuple[int, int, int]:
        """
        Process a single device part of a scan.
        Returns (passed, failed, errors).
        """
        scan = Scan.query.get(scan_id)
        if not scan:
            return 0, 0, 0
            
        # Re-fetch context needed for processing
        data_sources = DataSource.query.filter_by(is_active=True).all()
        rules = self._get_applicable_rules(scan.policies_filter)
        
        passed, failed, errors = 0, 0, 0
        try:
            passed, failed, errors = self._process_device(
                scan, device_id, rules, data_sources
            )
        except Exception as e:
            logger.error(f"Error processing device {device_id}: {e}")
            errors += 1 # Count device itself as error
            
        return passed, failed, errors

    def complete_empty_scan(self, scan_id: str):
        """Mark scan as completed if no devices found."""
        scan = Scan.query.get(scan_id)
        if scan:
            scan.status = "completed"
            scan.finished_at = datetime.utcnow()
            scan.passed_count = 0
            scan.failed_count = 0
            scan.error_count = 0
            db.session.commit()

    # Legacy execute method removed in favor of async flow

    
    def _get_devices_from_sources(self, data_sources: list[DataSource]) -> list[str]:
        """Collect devices from all data sources."""
        all_devices = set()
        
        for ds in data_sources:
            provider = self._create_provider(ds)
            if provider:
                devices = provider.list_available_devices()
                all_devices.update(devices)
                provider.close()
        
        return list(all_devices)
    
    def _get_applicable_rules(self, policies_filter: Optional[list] = None) -> list[Rule]:
        """Get active rules, optionally filtered by policies."""
        query = Rule.query.filter_by(is_active=True)
        
        if policies_filter:
            query = query.filter(Rule.policy_id.in_(policies_filter))
        
        return query.all()
    
    def _process_device(
        self, 
        scan: Scan, 
        device_id: str, 
        rules: list[Rule],
        data_sources: list[DataSource]
    ) -> tuple[int, int, int]:
        """Process a single device. Returns (passed, failed, errors)."""
        passed = 0
        failed = 0
        errors = 0
        
        # Fetch config
        config = None
        device_vendor = None
        
        for ds in data_sources:
            provider = self._create_provider(ds)
            if provider:
                # Try to get vendor from provider metadata if available
                # (This would require providers to implement get_device_vendor, currently we guess or need metadata)
                # For now, we will rely on config parsing or default to None (wildcard)
                
                result = provider.fetch_config(device_id)
                if result.success:
                    config = result.config
                    # Attempt to detect vendor from metadata or config content if possible
                    # Ideally, inventory should provide this.
                    if result.metadata and "vendor" in result.metadata:
                         device_vendor = result.metadata["vendor"]
                    
                    provider.close()
                    break
                provider.close()
        
        if config is None:
            # Create error results for all rules
            for rule in rules:
                result = Result(
                    scan_id=scan.id,
                    device_id=device_id,
                    rule_id=rule.id,
                    status="ERROR",
                    message="Could not fetch configuration"
                )
                db.session.add(result)
                errors += 1
            db.session.commit()
            return passed, failed, errors
        
        # Determine vendor if not explicitly found (Simplified heuristic)
        if not device_vendor:
            # Heuristics for demo/test
            if "! Vendor: cisco_ios" in config:
                device_vendor = "cisco_ios"
            elif "# Vendor: juniper_junos" in config:
                device_vendor = "juniper_junos"
            # Standard heuristics
            elif "version" in config.lower() and "cisco" in config.lower():
                device_vendor = "cisco_ios"
            elif "system {" in config and "host-name" in config:
                device_vendor = "juniper_junos"
        
        # Evaluate each rule
        for rule in rules:
            # 1. Vendor Check: Skip if rule has specific vendor AND device has known vendor AND they mismatch
            if rule.vendor_code and rule.vendor_code != "any":
                 if device_vendor and rule.vendor_code != device_vendor:
                     # Skip silently or log as SKIPPED? 
                     # For reporting clarity, let's just skip entirely to avoid noise in the report
                     continue

            # 2. Exception Check
            if self._has_active_exception(device_id, rule.id):
                result = Result(
                    scan_id=scan.id,
                    device_id=device_id,
                    rule_id=rule.id,
                    status="SKIPPED",
                    message="Exception/waiver active"
                )
                db.session.add(result)
                continue
            
            # 3. Evaluate rule
            try:
                check_result = self.evaluator.evaluate(
                    config=config,
                    logic_type=rule.logic_type,
                    logic_payload=rule.logic_payload
                )
                
                result = Result(
                    scan_id=scan.id,
                    device_id=device_id,
                    rule_id=rule.id,
                    status=check_result.status.value,
                    message=check_result.message,
                    diff_data=check_result.diff_data,
                    raw_value=str(check_result.raw_value) if check_result.raw_value else None
                )
                
                if check_result.passed:
                    passed += 1
                elif check_result.status.value == "ERROR":
                    errors += 1
                else:
                    failed += 1
                    
            except Exception as e:
                logger.error(f"Error evaluating rule {rule.id} for {device_id}: {e}")
                result = Result(
                    scan_id=scan.id,
                    device_id=device_id,
                    rule_id=rule.id,
                    status="ERROR",
                    message=str(e)
                )
                errors += 1
            
            db.session.add(result)
        
        db.session.commit()
        return passed, failed, errors
    
    def _has_active_exception(self, device_id: str, rule_id) -> bool:
        """Check for active exception for device + rule."""
        from datetime import date
        
        exc = RuleException.query.filter(
            RuleException.rule_id == rule_id,
            RuleException.is_active == True,
            (RuleException.expiry_date == None) | (RuleException.expiry_date >= date.today()),
            (RuleException.device_id == device_id) | (RuleException.device_id == None)
        ).first()
        
        return exc is not None
    
    def _create_provider(self, ds: DataSource) -> Optional[ConfigSourceProvider]:
        """Create appropriate provider using Registry."""
        from app.core.registry import get_config_provider
        import os
        
        # Get credentials
        token = os.environ.get(ds.credentials_ref, "") if ds.credentials_ref else ""
        
        # Prepare config
        config = ds.connection_params or {}
        
        # Inject standard credentials if provider expects them
        # (This logic might need refinement depending on provider specifics)
        if "token" not in config:
            config["token"] = token
        if "password" not in config and token:
             config["password"] = token
        
        # Automatically map common proxy params if present in DS config
        # E.g., if user put "ssh_config_file" in database JSONB connection_params, it is already in `config` dict
             
        try:
            return get_config_provider(ds.type, config)
        except ValueError as e:
            logger.warning(f"Failed to create provider for {ds.type}: {e}")
            return None
