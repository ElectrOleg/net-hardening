"""Maintenance Celery tasks — data retention cleanup."""

import logging
from datetime import timedelta

from celery import shared_task

from app.utils import utc_now

logger = logging.getLogger(__name__)


@shared_task(name="hcs.cleanup_old_data")
def cleanup_old_data():
    """Daily cleanup based on SystemSetting retention values.

    - Deletes scan results older than retention.scan_days
      (but keeps at least retention.min_scans)
    - Purges inactive devices older than retention.inactive_device_days
    """
    from app.extensions import db
    from app.models import Device, Result, Scan
    from app.models.system_setting import SystemSetting

    now = utc_now()

    # --- Scan retention ---
    scan_days = SystemSetting.get_int("retention.scan_days", 90)
    min_scans = SystemSetting.get_int("retention.min_scans", 10)

    cutoff_date = now - timedelta(days=scan_days)

    # Count total scans to ensure we keep minimum
    total_scans = Scan.query.filter(Scan.status == "completed").count()

    deleted_results = 0
    deleted_scans = 0

    if total_scans > min_scans:
        # Find old scans beyond the minimum
        old_scans = (
            Scan.query.filter(Scan.finished_at < cutoff_date, Scan.status == "completed")
            .order_by(Scan.finished_at.asc())
            .all()
        )

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
        logger.debug(f"Retention: only {total_scans} scans, minimum {min_scans} — skipping cleanup")

    # --- Inactive device purge ---
    inactive_days = SystemSetting.get_int("retention.inactive_device_days", 180)
    inactive_cutoff = now - timedelta(days=inactive_days)

    # Delete devices that have been inactive for too long
    purged = Device.query.filter(
        Device.is_active == False, Device.updated_at < inactive_cutoff
    ).delete(synchronize_session="fetch")

    if purged > 0:
        db.session.commit()
        logger.info(
            f"Retention cleanup: purged {purged} inactive devices "
            f"(inactive for >{inactive_days} days)"
        )

    # --- Config snapshot retention ---
    config_days = SystemSetting.get_int("retention.config_snapshot_days", 90)
    config_cutoff = now - timedelta(days=config_days)
    deleted_snapshots = 0

    try:
        from sqlalchemy import func as sqla_func

        from app.models.config_snapshot import ConfigSnapshot

        # Find the latest snapshot per device (to preserve)
        latest_per_device = (
            db.session.query(
                ConfigSnapshot.device_id,
                sqla_func.max(ConfigSnapshot.collected_at).label("max_date"),
            )
            .group_by(ConfigSnapshot.device_id)
            .subquery()
        )

        # Delete old snapshots that are NOT the latest for their device
        old_snapshots = ConfigSnapshot.query.filter(
            ConfigSnapshot.collected_at < config_cutoff
        ).all()

        for snap in old_snapshots:
            # Check if this is the only/latest snapshot for the device
            latest = (
                ConfigSnapshot.query.filter_by(device_id=snap.device_id)
                .order_by(ConfigSnapshot.collected_at.desc())
                .first()
            )

            if latest and latest.id != snap.id:
                db.session.delete(snap)
                deleted_snapshots += 1

        if deleted_snapshots > 0:
            db.session.commit()
            logger.info(
                f"Retention cleanup: deleted {deleted_snapshots} config snapshots "
                f"(older than {config_days} days)"
            )
    except Exception as e:
        logger.warning(f"Config snapshot cleanup failed: {e}")
        db.session.rollback()

    # --- Stuck scan safety valve ---
    stuck_cutoff = now - timedelta(hours=4)
    stuck_count = 0
    try:
        stuck_scans = Scan.query.filter(
            Scan.status.in_(["pending", "running"]), Scan.started_at < stuck_cutoff
        ).all()

        for scan in stuck_scans:
            scan.status = "failed"
            scan.finished_at = now
            scan.error_message = "Scan timed out / worker terminated unexpectedly"
            stuck_count += 1

        if stuck_count > 0:
            db.session.commit()
            logger.info(f"Stuck scan safety valve: marked {stuck_count} stuck scans as failed")
    except Exception as e:
        logger.error(f"Stuck scan safety valve failed: {e}")
        db.session.rollback()

    return {
        "scans_deleted": deleted_scans,
        "results_deleted": deleted_results,
        "devices_purged": purged,
        "config_snapshots_deleted": deleted_snapshots,
        "stuck_scans_failed": stuck_count,
    }


@shared_task(name="hcs.auto_run_scheduled_scans")
def auto_run_scheduled_scans():
    """Check scan schedules and start scans that are due.

    Runs every minute via Celery Beat. For each enabled ScanSchedule
    where next_run_at <= now, starts a scan and updates the schedule.

    Protected by distributed lock to prevent duplicate execution
    when multiple Beat instances are running.
    """
    from app.utils.distributed_lock import LockNotAcquired, get_lock

    lock = get_lock()
    try:
        with lock.acquire("beat:scheduled_scans", ttl=120):
            return _auto_run_scheduled_scans_inner()
    except LockNotAcquired:
        return {"skipped": True, "reason": "another beat instance is processing schedules"}


def _auto_run_scheduled_scans_inner():
    """Inner logic for scheduled scan execution."""
    from app.extensions import db
    from app.models import Scan
    from app.models.scan_schedule import ScanSchedule
    from app.models.system_setting import SystemSetting

    # Global kill switch
    if not SystemSetting.get_bool("scan.auto_enabled", False):
        return {"skipped": True, "reason": "scan.auto_enabled is false"}

    now = utc_now()

    schedules = ScanSchedule.query.filter(
        ScanSchedule.is_enabled == True, ScanSchedule.next_run_at <= now
    ).all()

    started = 0

    for schedule in schedules:
        try:
            # Create scan record
            scan = Scan(
                status="pending",
                policies_filter=schedule.policies_filter,
                devices_filter=schedule.devices_filter,
                started_by=f"schedule: {schedule.name}",
            )
            db.session.add(scan)
            db.session.flush()  # Get scan.id

            # Queue the scan task
            from app.tasks.scan_tasks import run_scan

            run_scan.delay(str(scan.id))

            # Update schedule
            schedule.last_run_at = now
            schedule.last_scan_id = scan.id
            schedule.next_run_at = schedule.calculate_next_run()

            db.session.commit()
            started += 1

            logger.info(f"Scheduled scan '{schedule.name}' queued: scan_id={scan.id}")

        except Exception as e:
            logger.error(f"Failed to start scheduled scan '{schedule.name}': {e}")
            db.session.rollback()

    return {"started": started, "checked": len(schedules)}
