"""Inventory auto-sync Celery tasks.

Periodic task that checks all InventorySources with sync_enabled=True
and runs sync when the interval has elapsed since last_sync_at.
"""
import logging
from datetime import datetime, timedelta

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="hcs.sync_all_inventory", bind=True, max_retries=0)
def auto_sync_inventory(self):
    """Periodic task: sync all inventory sources that are due.
    
    Checks each InventorySource where:
    - is_active = True
    - sync_enabled = True
    - last_sync_at + sync_interval_minutes < now()  (or never synced)
    
    Runs inside Flask app context.
    """
    from app.extensions import db
    from app.models import InventorySource
    from app.services.inventory_sync import InventorySyncService
    
    now = datetime.utcnow()
    service = InventorySyncService()
    
    # Find sources due for sync
    sources = InventorySource.query.filter_by(
        is_active=True,
        sync_enabled=True
    ).all()
    
    total_synced = 0
    total_errors = 0
    
    for source in sources:
        # Check if interval has elapsed
        if source.last_sync_at:
            interval = timedelta(minutes=source.sync_interval_minutes or 60)
            next_sync_at = source.last_sync_at + interval
            if now < next_sync_at:
                logger.debug(
                    f"Source '{source.name}' not due yet "
                    f"(next sync at {next_sync_at.isoformat()})"
                )
                continue
        
        # Run sync
        logger.info(f"Auto-syncing source '{source.name}' (interval={source.sync_interval_minutes}m)")
        try:
            result = service.sync(source, trigger="scheduled")
            total_synced += 1
            
            if result.errors:
                total_errors += len(result.errors)
                logger.warning(
                    f"Source '{source.name}' synced with {len(result.errors)} errors: "
                    f"created={result.created}, updated={result.updated}, "
                    f"deactivated={result.deactivated}"
                )
            else:
                logger.info(
                    f"Source '{source.name}' synced OK: "
                    f"created={result.created}, updated={result.updated}, "
                    f"deactivated={result.deactivated}"
                )
        except Exception as e:
            total_errors += 1
            logger.error(f"Auto-sync failed for source '{source.name}': {e}")
    
    return {
        "sources_synced": total_synced,
        "total_errors": total_errors,
        "checked_at": now.isoformat(),
    }


@shared_task(name="hcs.sync_single_source", bind=True, max_retries=1)
def sync_single_source(self, source_id: str, trigger: str = "api"):
    """Sync a single inventory source by ID (for manual/API triggers)."""
    from app.extensions import db
    from app.models import InventorySource
    from app.services.inventory_sync import InventorySyncService
    
    source = InventorySource.query.get(source_id)
    if not source:
        return {"error": f"Source {source_id} not found"}
    
    service = InventorySyncService()
    result = service.sync(source, trigger=trigger)
    
    return result.to_dict()
