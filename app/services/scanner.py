"""Scanner Service - orchestrates the scanning process."""
import logging
from datetime import datetime
from typing import Optional

from app.extensions import db
from app.models import Scan, Rule, Result, RuleException, DataSource, Device
from app.engine import RuleEvaluator
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
    
    Device identification convention:
        device_id is always a hostname string (Device.hostname).
        When a matching Device record exists, device_uuid stores the
        internal UUID for FK linkage in Result.
    """
    
    # Per-scan caches (populated by scan_single_device)
    _cached_scan_id: Optional[str] = None
    _cached_rules: Optional[list] = None
    _cached_data_sources: Optional[list] = None
    
    def __init__(self):
        self.evaluator = RuleEvaluator()
        self._cached_scan_id = None
        self._cached_rules = None
        self._cached_data_sources = None
    
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
            
        # Cache rules/sources per scan to avoid N+1 queries
        if self._cached_scan_id != scan_id:
            self._cached_data_sources = DataSource.query.filter_by(is_active=True).all()
            self._cached_rules = self._get_applicable_rules(scan.policies_filter)
            self._cached_scan_id = scan_id
        
        passed, failed, errors = 0, 0, 0
        try:
            passed, failed, errors = self._process_device(
                scan, device_id, self._cached_rules, self._cached_data_sources
            )
        except Exception as e:
            logger.error(f"Error processing device {device_id}: {e}")
            errors += 1
            
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

    def _get_devices_from_sources(self, data_sources: list[DataSource]) -> list[str]:
        """Collect devices from all data sources."""
        all_devices = set()
        
        for ds in data_sources:
            provider = self._create_provider(ds)
            if provider:
                devices = provider.list_devices()
                all_devices.update(devices)
                provider.close()
        
        return list(all_devices)
    
    def _get_applicable_rules(self, policies_filter: Optional[list] = None) -> list[Rule]:
        """Get active rules, optionally filtered by policies."""
        query = Rule.query.filter_by(is_active=True)
        
        if policies_filter:
            query = query.filter(Rule.policy_id.in_(policies_filter))
        
        return query.all()
    
    def _detect_vendor(self, config: str, device_obj: Optional[Device] = None) -> Optional[str]:
        """Detect vendor for a device.
        
        Priority:
        1. Device inventory record (device_obj.vendor_code)
        2. VendorMapping database rules
        3. None (unknown)
        """
        # 1. From inventory
        if device_obj and device_obj.vendor_code:
            return device_obj.vendor_code
        
        # 2. From VendorMapping database rules
        try:
            from app.services.inventory_sync import VendorDetector
            vendor = VendorDetector.detect(config)
            if vendor:
                return vendor
        except Exception as e:
            logger.debug(f"VendorDetector unavailable: {e}")
        
        return None
    
    def _check_applicability(self, rule: Rule, device_obj: Optional[Device]) -> bool:
        """Check if a rule applies to a device based on rule.applicability conditions.
        
        Returns True if the rule should be applied (all conditions match or no conditions set).
        
        Condition key formats:
        - "field_name"           → exact match against Device.field_name
        - "field_name_regex"     → regex match against Device.field_name
        - "field_name_contains"  → substring match against Device.field_name
        - "extra_data.key"       → exact match against Device.extra_data["key"]
        - "extra_data.key_regex" → regex match against Device.extra_data["key"]
        
        All conditions are AND-joined. If device_obj is None, conditions
        referencing device fields are skipped (permissive).
        """
        import re as re_module
        
        conditions = rule.applicability
        if not conditions or not isinstance(conditions, dict):
            return True  # No conditions → rule applies to all
        
        if device_obj is None:
            # Can't check device fields without a device record → permissive
            return True
        
        extra = device_obj.extra_data or {}
        
        for cond_key, cond_value in conditions.items():
            if cond_value is None:
                continue
            
            # Resolve the device value for this condition
            device_value = self._resolve_device_field(device_obj, extra, cond_key)
            
            if device_value is None:
                # Field doesn't exist on device → skip this condition (permissive)
                continue
            
            device_value_str = str(device_value)
            cond_value_str = str(cond_value)
            
            # Determine match type from key suffix
            if cond_key.endswith("_regex"):
                try:
                    if not re_module.search(cond_value_str, device_value_str):
                        return False
                except re_module.error:
                    logger.warning(f"Invalid regex in rule applicability: {cond_value_str}")
                    return False
            elif cond_key.endswith("_contains"):
                if cond_value_str.lower() not in device_value_str.lower():
                    return False
            else:
                # Exact match (case-insensitive for strings)
                if device_value_str.lower() != cond_value_str.lower():
                    return False
        
        return True
    
    @staticmethod
    def _resolve_device_field(device_obj: Device, extra: dict, cond_key: str):
        """Resolve a condition key to a device field value.
        
        Strips _regex/_contains suffixes, then checks:
        1. extra_data.X path → extra["X"]
        2. Standard Device attribute
        """
        # Strip match-type suffix to get the real field name
        field_key = cond_key
        for suffix in ("_regex", "_contains"):
            if field_key.endswith(suffix):
                field_key = field_key[:-len(suffix)]
                break
        
        # Check extra_data path: "extra_data.department" → extra["department"]
        if field_key.startswith("extra_data."):
            extra_key = field_key[11:]  # strip "extra_data."
            return extra.get(extra_key)
        
        # Standard Device attribute
        return getattr(device_obj, field_key, None)

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
        
        # Resolve Device UUID from inventory
        device_obj = Device.query.filter(
            (Device.hostname == device_id) | (Device.ip_address == device_id)
        ).first()
        device_uuid = device_obj.id if device_obj else None
        
        # Pre-filter by Policy scope_filter (skip entire policy if device doesn't match)
        if device_obj:
            _policy_cache: dict[str, bool] = {}
            filtered_rules = []
            for rule in rules:
                pid = str(rule.policy_id)
                if pid not in _policy_cache:
                    sf = rule.policy.scope_filter if rule.policy else None
                    if sf and isinstance(sf, dict):
                        class _ScopeShim:
                            applicability = sf
                        _policy_cache[pid] = self._check_applicability(_ScopeShim(), device_obj)
                    else:
                        _policy_cache[pid] = True
                if _policy_cache[pid]:
                    filtered_rules.append(rule)
            rules = filtered_rules
        
        # --- Group rules by data_source_id ---
        # None key = rules that should use any available source (legacy/default behavior)
        from collections import defaultdict
        rule_groups: dict[str | None, list[Rule]] = defaultdict(list)
        for rule in rules:
            ds_key = str(rule.data_source_id) if rule.data_source_id else None
            rule_groups[ds_key].append(rule)
        
        # Build a lookup of data sources by id
        ds_by_id = {str(ds.id): ds for ds in data_sources}
        
        # Cache for fetched configs: data_source_id -> (config, vendor)
        config_cache: dict[str | None, tuple[str | None, str | None]] = {}
        
        device_vendor = None  # Will be set once from first successful fetch
        
        def _fetch_config_for_source(ds_id: str | None) -> tuple[str | None, str | None]:
            """Fetch config for a specific source id, or any source if None."""
            nonlocal device_vendor
            
            if ds_id is not None:
                # Specific data source
                ds = ds_by_id.get(ds_id)
                if not ds:
                    logger.warning(f"DataSource {ds_id} not found for device {device_id}")
                    return None, None
                provider = self._create_provider(ds)
                if provider:
                    result = provider.fetch_config(device_id)
                    provider.close()
                    if result.success:
                        v = result.metadata.get("vendor") if result.metadata else None
                        if v and not device_vendor:
                            device_vendor = v
                        return result.config, v
                return None, None
            else:
                # Any available source (legacy behavior)
                for ds in data_sources:
                    provider = self._create_provider(ds)
                    if provider:
                        result = provider.fetch_config(device_id)
                        if result.success:
                            v = result.metadata.get("vendor") if result.metadata else None
                            if v and not device_vendor:
                                device_vendor = v
                            provider.close()
                            return result.config, v
                        provider.close()
                return None, None
        
        # --- Process each rule group ---
        for ds_key, group_rules in rule_groups.items():
            # Fetch config (with caching to avoid redundant fetches)
            if ds_key not in config_cache:
                config_cache[ds_key] = _fetch_config_for_source(ds_key)
            
            config, _vendor = config_cache[ds_key]
            
            if config is None:
                # Config unavailable for this source — mark all rules as ERROR
                ds_name = ds_by_id[ds_key].name if ds_key and ds_key in ds_by_id else "any"
                for rule in group_rules:
                    result = Result(
                        scan_id=scan.id,
                        device_id=device_id,
                        device_uuid=device_uuid,
                        rule_id=rule.id,
                        status="ERROR",
                        message=f"Could not fetch configuration from source: {ds_name}"
                    )
                    db.session.add(result)
                    errors += 1
                continue
            
            # Detect vendor once (from first successful config)
            if not device_vendor:
                device_vendor = self._detect_vendor(config, device_obj)
            
            # Evaluate each rule against its source's config
            for rule in group_rules:
                # 1. Vendor Check
                if rule.vendor_code and rule.vendor_code != "any":
                    if device_vendor and rule.vendor_code != device_vendor:
                        continue

                # 2. Applicability Check
                if not self._check_applicability(rule, device_obj):
                    continue

                # 3. Exception Check
                if self._has_active_exception(device_id, rule.id):
                    result = Result(
                        scan_id=scan.id,
                        device_id=device_id,
                        device_uuid=device_uuid,
                        rule_id=rule.id,
                        status="SKIPPED",
                        message="Exception/waiver active"
                    )
                    db.session.add(result)
                    continue
                
                # 4. Evaluate rule
                try:
                    check_result = self.evaluator.evaluate(
                        config=config,
                        logic_type=rule.logic_type,
                        logic_payload=rule.logic_payload
                    )
                    
                    result = Result(
                        scan_id=scan.id,
                        device_id=device_id,
                        device_uuid=device_uuid,
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
                        device_uuid=device_uuid,
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
        from app.core.credentials import resolve_credential
        
        # Get credentials via CredentialResolver
        token = resolve_credential(ds.credentials_ref) if ds.credentials_ref else ""
        
        # Prepare config
        config = dict(ds.connection_params or {})
        
        # Provider-type-aware credential injection
        if token:
            if ds.type in ("gitlab", "api", "checkpoint", "fortigate", "usergate", "paloalto"):
                config.setdefault("token", token)
            if ds.type in ("ssh", "netconf", "checkpoint", "usergate"):
                config.setdefault("password", token)
            if ds.type in ("fortigate",) and config.get("auth_type") == "api_key":
                config.setdefault("api_key", token)
            if ds.type in ("paloalto",):
                config.setdefault("api_key", token)
             
        try:
            return get_config_provider(ds.type, config)
        except ValueError as e:
            logger.warning(f"Failed to create provider for {ds.type}: {e}")
            return None

