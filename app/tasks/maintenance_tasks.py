"""Maintenance Celery tasks — data retention cleanup."""
import logging
from datetime import datetime, timedelta

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="hcs.cleanup_old_data")
def cleanup_old_data():
    """Daily cleanup based on SystemSetting retention values.
    
    - Deletes scan results older than retention.scan_days 
      (but keeps at least retention.min_scans)
    - Purges inactive devices older than retention.inactive_device_days
    """
    from app.extensions import db
    from app.models import Scan, Result, Device
    from app.models.system_setting import SystemSetting
    
    now = datetime.utcnow()
    
    # --- Scan retention ---
    scan_days = SystemSetting.get_int("retention.scan_days", 90)
    min_scans = SystemSetting.get_int("retention.min_scans", 10)
    
    cutoff_date = now - timedelta(days=scan_days)
    
    # Count total scans to ensure we keep minimum
    total_scans = Scan.query.filter(
        Scan.status == "completed"
    ).count()
    
    deleted_results = 0
    deleted_scans = 0
    
    if total_scans > min_scans:
        # Find old scans beyond the minimum
        old_scans = Scan.query.filter(
            Scan.finished_at < cutoff_date,
            Scan.status == "completed"
        ).order_by(Scan.finished_at.asc()).all()
        
        # Don't delete more than would leave us below min_scans
        max_deletable = total_scans - min_scans
        scans_to_delete = old_scans[:max_deletable]
        
        for scan in scans_to_delete:
            # Delete results first (FK constraint)
            count = Result.query.filter_by(scan_id=scan.id).delete()
            deleted_results += count
            db.session.delete(scan)
            deleted_scans += 1
        
        if deleted_scans > 0:
            db.session.commit()
            logger.info(
                f"Retention cleanup: deleted {deleted_scans} scans "
                f"and {deleted_results} results (older than {scan_days} days)"
            )
    else:
        logger.debug(
            f"Retention: only {total_scans} scans, "
            f"minimum {min_scans} — skipping cleanup"
        )
    
    # --- Inactive device purge ---
    inactive_days = SystemSetting.get_int("retention.inactive_device_days", 180)
    inactive_cutoff = now - timedelta(days=inactive_days)
    
    # Delete devices that have been inactive for too long
    purged = Device.query.filter(
        Device.is_active == False,
        Device.updated_at < inactive_cutoff
    ).delete(synchronize_session="fetch")
    
    if purged > 0:
        db.session.commit()
        logger.info(
            f"Retention cleanup: purged {purged} inactive devices "
            f"(inactive for >{inactive_days} days)"
        )
    
    return {
        "scans_deleted": deleted_scans,
        "results_deleted": deleted_results,
        "devices_purged": purged,
    }


@shared_task(name="hcs.auto_run_scheduled_scans")
def auto_run_scheduled_scans():
    """Check scan schedules and start scans that are due.
    
    Runs every minute via Celery Beat. For each enabled ScanSchedule
    where next_run_at <= now, starts a scan and updates the schedule.
    """
    from app.extensions import db
    from app.models.scan_schedule import ScanSchedule
    from app.models.system_setting import SystemSetting
    
    # Global kill switch
    if not SystemSetting.get_bool("scan.auto_enabled", False):
        return {"skipped": True, "reason": "scan.auto_enabled is false"}
    
    now = datetime.utcnow()
    
    schedules = ScanSchedule.query.filter(
        ScanSchedule.is_enabled == True,
        ScanSchedule.next_run_at <= now
    ).all()
    
    started = 0
    
    for schedule in schedules:
        try:
            # Import scan task to queue it
            from app.tasks.scan_tasks import scan_device_task, scan_completion_handler
            from app.models import Scan
            from celery import group as celery_group
            
            # Create scan record
            scan = Scan(
                status="running",
                policies_filter=schedule.policies_filter,
                devices_filter=schedule.devices_filter,
            )
            db.session.add(scan)
            db.session.flush()  # Get scan.id
            
            # Determine devices to scan
            from app.models import Device
            device_query = Device.query.filter_by(is_active=True)
            
            if schedule.devices_filter:
                if "vendor" in schedule.devices_filter:
                    device_query = device_query.filter_by(
                        vendor_code=schedule.devices_filter["vendor"]
                    )
                if "group_id" in schedule.devices_filter:
                    device_query = device_query.filter_by(
                        group_id=schedule.devices_filter["group_id"]
                    )
            
            devices = device_query.all()
            scan.total_devices = len(devices)
            
            # Queue device scan tasks
            if devices:
                task_group = celery_group(
                    scan_device_task.s(str(scan.id), d.hostname)
                    for d in devices
                )
                chord_result = (task_group | scan_completion_handler.s(str(scan.id))).apply_async()
            
            # Update schedule
            schedule.last_run_at = now
            schedule.last_scan_id = scan.id
            schedule.next_run_at = schedule.calculate_next_run()
            
            db.session.commit()
            started += 1
            
            logger.info(
                f"Scheduled scan '{schedule.name}' started: "
                f"scan_id={scan.id}, devices={len(devices)}"
            )
            
        except Exception as e:
            logger.error(f"Failed to start scheduled scan '{schedule.name}': {e}")
            db.session.rollback()
    
    return {"started": started, "checked": len(schedules)}
