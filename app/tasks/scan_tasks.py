"""Celery tasks for scanning."""
import logging
from app.extensions import celery, db
from app.services import ScannerService, get_notification_service
from celery import chord

logger = logging.getLogger(__name__)


@celery.task(bind=True, max_retries=3)
def scan_device_task(self, scan_id: str, device_id: str):
    """
    Scan a single device.
    """
    try:
        service = ScannerService()
        # process_single_device is a new method we need to expose or use existent internal
        passed, failed, errors = service.scan_single_device(scan_id, device_id)
        return {"device_id": device_id, "passed": passed, "failed": failed, "errors": errors}
    except Exception as e:
        logger.exception(f"Device scan failed {device_id}: {e}")
        try:
            self.retry(exc=e, countdown=2 ** self.request.retries)
        except self.MaxRetriesExceededError:
            return {"device_id": device_id, "error": str(e)}


@celery.task
def scan_completion_handler(results, scan_id: str):
    """
    Called when all device scans are finished.
    Aggregates results and sends notification.
    """
    logger.info(f"All tasks for scan {scan_id} completed. Aggregating results.")
    
    from app.models import Scan
    from datetime import datetime
    
    scan = Scan.query.get(scan_id)
    if not scan:
        return
    
    # Don't overwrite cancelled status
    if scan.status == "cancelled":
        logger.info(f"Scan {scan_id} was cancelled, skipping completion.")
        return

    total_passed = 0
    total_failed = 0
    total_errors = 0
    
    # Results is a list of dicts from scan_device_task
    for res in results:
        if not isinstance(res, dict):
            continue
        if "error" in res:
            # Catastrophic task failure — count as single error
            total_errors += 1
        else:
            total_passed += res.get("passed", 0)
            total_failed += res.get("failed", 0)
            total_errors += res.get("errors", 0)

    scan.passed_count = total_passed
    scan.failed_count = total_failed
    scan.error_count = total_errors
    scan.status = "completed"
    scan.finished_at = datetime.utcnow()
    
    db.session.commit()
    
    # Notification
    try:
        notifier = get_notification_service()
        notifier.send_scan_alert(
            scan_id=scan_id,
            score=scan.score,
            passed=scan.passed_count,
            failed=scan.failed_count,
            devices=scan.total_devices
        )
    except Exception as e:
        logger.warning(f"Notification failed: {e}")


@celery.task(bind=True)
def run_scan(self, scan_id: str, device_ids: list[str] = None):
    """
    Orchestrator: Discovers devices and launches parallel tasks.
    """
    logger.info(f"Starting scan orchestrator: {scan_id}")
    
    try:
        service = ScannerService()
        # Initialize scan (get devices, rules, set status to running)
        devices = service.initialize_scan(scan_id, device_ids)
        
        if not devices:
            logger.warning(f"No devices found for scan {scan_id}")
            service.complete_empty_scan(scan_id)
            return

        # Create a chord: parallel tasks → single callback
        job = chord(
            [scan_device_task.s(scan_id, d_id) for d_id in devices],
            scan_completion_handler.s(scan_id)
        )
        chord_result = job.apply_async()
        
        # Save orchestrator task ID for revocation
        from app.models import Scan as ScanModel
        scan_obj = ScanModel.query.get(scan_id)
        if scan_obj:
            scan_obj.celery_task_id = self.request.id
            db.session.commit()
        
        logger.info(f"Launched {len(devices)} parallel scan tasks for {scan_id}")
        
    except Exception as e:
        logger.exception(f"Scan orchestrator failed: {e}")
        # Mark scan as failed
        from app.models import Scan
        scan = Scan.query.get(scan_id)
        if scan:
            scan.status = "failed"
            scan.error_message = str(e)
            db.session.commit()


@celery.task
def scheduled_scan():
    """Periodic scan task."""
    from app.models import Scan
    
    logger.info("Starting scheduled scan")
    
    scan = Scan(
        started_by="scheduler",
        status="pending"
    )
    db.session.add(scan)
    db.session.commit()
    
    run_scan.delay(str(scan.id))
    
    return str(scan.id)
