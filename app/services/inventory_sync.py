"""Inventory Sync Service - synchronize devices from external inventory sources.

Handles:
- Upsert (create or update) devices from inventory providers
- Deactivation of stale devices not found in upstream
- Vendor resolution via config-driven VendorMapping or inventory data
"""
import re
import logging
from datetime import datetime
from typing import Optional

from app.extensions import db
from app.models import Device, InventorySource
from app.models.vendor_mapping import VendorMapping
from app.inventory import InventoryDevice
from app.core.registry import get_inventory_provider
from app.core.credentials import resolve_credential

logger = logging.getLogger(__name__)


class SyncResult:
    """Result of an inventory sync operation."""
    
    def __init__(self):
        self.created = 0
        self.updated = 0
        self.deactivated = 0
        self.errors: list[str] = []
    
    @property
    def total(self):
        return self.created + self.updated
    
    def to_dict(self):
        return {
            "created": self.created,
            "updated": self.updated,
            "deactivated": self.deactivated,
            "total": self.total,
            "errors": self.errors,
        }


class InventorySyncService:
    """Synchronize devices from external inventory sources into hcs_devices."""
    
    def sync(self, source: InventorySource, trigger: str = "manual") -> SyncResult:
        """Run a full sync for a single inventory source.
        
        1. Fetch devices from provider
        2. Upsert into hcs_devices
        3. Deactivate stale records
        4. Update source.last_sync_at
        5. Write SyncLog audit entry
        
        Args:
            source: The inventory source to sync
            trigger: How this sync was initiated — 'manual', 'scheduled', or 'api'
        """
        from app.models.sync_log import SyncLog
        
        result = SyncResult()
        start_time = datetime.utcnow()
        
        # Resolve credentials
        password = resolve_credential(source.credentials_ref) if source.credentials_ref else ""
        
        # Prepare config
        config = dict(source.connection_params or {})
        if "password" not in config and password:
            config["password"] = password
        if "token" not in config and password:
            config["token"] = password
        
        # Get provider
        try:
            provider = get_inventory_provider(source.type, config)
        except ValueError as e:
            result.errors.append(f"Failed to create provider: {e}")
            self._write_sync_log(source, result, start_time, trigger)
            return result
        
        # Fetch devices
        try:
            remote_devices = provider.list_devices()
        except Exception as e:
            result.errors.append(f"Failed to fetch devices: {e}")
            self._write_sync_log(source, result, start_time, trigger)
            return result
        finally:
            provider.close()
        
        if not remote_devices:
            logger.info(f"No devices returned from source '{source.name}'")
            # Don't deactivate all devices if provider returns empty —
            # this might be a transient error
            source.last_sync_at = datetime.utcnow()
            db.session.commit()
            self._write_sync_log(source, result, start_time, trigger)
            return result
        
        # Track which external_ids we've seen
        seen_external_ids = set()
        
        # Column mapping from source config
        vendor_mapping = (source.connection_params or {}).get("vendor_mapping", {})
        
        for rd in remote_devices:
            ext_id = rd.id or rd.hostname
            if not ext_id:
                result.errors.append(f"Skipping device with no ID or hostname")
                continue
            
            seen_external_ids.add(ext_id)
            
            # Resolve vendor code
            vendor_code = rd.vendor_code
            if vendor_code and vendor_mapping:
                # Apply vendor code translation from source config
                vendor_code = vendor_mapping.get(vendor_code, vendor_code)
            
            try:
                device = Device.query.filter_by(
                    external_id=ext_id,
                    source_id=source.id
                ).first()
                
                if device:
                    # Update existing
                    device.hostname = rd.hostname
                    device.ip_address = rd.ip_address
                    device.vendor_code = vendor_code or device.vendor_code
                    if rd.group:
                        # Note: group assignment by name would require DeviceGroup lookup
                        pass
                    device.location = rd.location or device.location
                    device.os_version = rd.os_version or device.os_version
                    device.hardware = rd.hardware or device.hardware
                    device.is_active = rd.is_active
                    device.last_sync_at = datetime.utcnow()
                    
                    # Full replacement of extra_data from provider
                    # (cleans stale keys that no longer exist upstream)
                    if rd.metadata:
                        device.extra_data = dict(rd.metadata)
                    else:
                        device.extra_data = {}
                    
                    result.updated += 1
                else:
                    # Create new
                    device = Device(
                        external_id=ext_id,
                        hostname=rd.hostname,
                        ip_address=rd.ip_address,
                        vendor_code=vendor_code,
                        location=rd.location,
                        os_version=rd.os_version,
                        hardware=rd.hardware,
                        source_id=source.id,
                        is_active=rd.is_active,
                        last_sync_at=datetime.utcnow(),
                        extra_data=rd.metadata or {},
                    )
                    db.session.add(device)
                    result.created += 1
                    
            except Exception as e:
                logger.error(f"Error syncing device '{ext_id}': {e}")
                result.errors.append(f"Device '{ext_id}': {e}")
        
        # Deactivate stale devices from this source
        stale_count = Device.query.filter(
            Device.source_id == source.id,
            Device.is_active == True,
            Device.external_id.notin_(seen_external_ids)
        ).update({"is_active": False}, synchronize_session="fetch")
        result.deactivated = stale_count
        
        # Update source timestamp
        source.last_sync_at = datetime.utcnow()
        
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            result.errors.append(f"Database commit failed: {e}")
        
        logger.info(
            f"Sync '{source.name}': "
            f"created={result.created}, updated={result.updated}, "
            f"deactivated={result.deactivated}, errors={len(result.errors)}"
        )
        
        # Write audit log
        self._write_sync_log(source, result, start_time, trigger)
        
        return result
    
    @staticmethod
    def _write_sync_log(source: InventorySource, result: SyncResult,
                        start_time: datetime, trigger: str):
        """Write a SyncLog audit entry."""
        from app.models.sync_log import SyncLog
        
        now = datetime.utcnow()
        duration = (now - start_time).total_seconds()
        
        status = "success"
        if result.errors and result.total > 0:
            status = "partial"
        elif result.errors and result.total == 0:
            status = "failed"
        
        log = SyncLog(
            source_id=source.id,
            started_at=start_time,
            finished_at=now,
            trigger=trigger,
            created=result.created,
            updated=result.updated,
            deactivated=result.deactivated,
            status=status,
            errors=result.errors[:50],  # Cap error list size
            duration_seconds=round(duration, 2),
        )
        
        try:
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            logger.warning(f"Failed to write SyncLog: {e}")
            db.session.rollback()


class VendorDetector:
    """Detect device vendor from config content using VendorMapping rules."""
    
    _cache: Optional[list[VendorMapping]] = None
    
    @classmethod
    def detect(cls, config_content: str, match_field: str = "config_content") -> Optional[str]:
        """Detect vendor_code from configuration content.
        
        Args:
            config_content: The configuration text to analyze
            match_field: Which field type we're matching against
            
        Returns:
            vendor_code string or None
        """
        mappings = cls._get_mappings(match_field)
        
        for mapping in mappings:
            try:
                if re.search(mapping.pattern, config_content):
                    return mapping.vendor_code
            except re.error as e:
                logger.warning(f"Invalid regex in VendorMapping {mapping.id}: {e}")
        
        return None
    
    @classmethod
    def _get_mappings(cls, match_field: str) -> list[VendorMapping]:
        """Get active mappings sorted by priority, filtered by match_field."""
        if cls._cache is None:
            try:
                cls._cache = VendorMapping.query.filter_by(
                    is_active=True
                ).order_by(VendorMapping.priority).all()
            except Exception:
                # Table might not exist yet
                cls._cache = []
        
        return [m for m in cls._cache if m.match_field == match_field]
    
    @classmethod
    def invalidate_cache(cls):
        """Clear cached mappings (call after updating VendorMapping table)."""
        cls._cache = None
