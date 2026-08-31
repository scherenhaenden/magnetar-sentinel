"""
magnetar.scheduler
------------------
APScheduler background sync with dynamically configurable interval.
The interval is read from SyncConfig table and can be changed at runtime.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from threading import Thread
import logging

from .models import SyncConfig
from .db import get_db_session

logger = logging.getLogger(__name__)

def _get_interval_from_db() -> int:
    """Reads the sync interval from DB. Default to 3600 if not set or invalid."""
    try:
        with get_db_session() as session:
            config = session.get(SyncConfig, 'interval_seconds')
            if config and config.value:
                return int(config.value)
    except Exception as e:
        logger.error(f"Error reading interval from DB: {e}")
    return 3600

def init_scheduler(app, sync_fn) -> BackgroundScheduler:
    """
    Starts the scheduler and reads the interval from DB.
    Valid intervals: 60, 300, 900, 3600, 0 (0 = manual only)
    """
    scheduler = BackgroundScheduler()
    
    interval = _get_interval_from_db()
    
    if interval > 0:
        scheduler.add_job(
            func=sync_fn,
            trigger=IntervalTrigger(seconds=interval),
            id='sync_job',
            name='Log Synchronization Job',
            replace_existing=True
        )
        
    scheduler.start()
    return scheduler

def update_interval(scheduler: BackgroundScheduler, seconds: int):
    """
    Reschedules the job with new interval.
    If seconds is 0, removes/pauses the job.
    """
    # Persist the new interval
    try:
        with get_db_session() as session:
            config = session.get(SyncConfig, 'interval_seconds')
            if not config:
                config = SyncConfig(key='interval_seconds')
                session.add(config)
            config.value = str(seconds)
    except Exception as e:
        logger.error(f"Failed to save new interval to DB: {e}")

    job = scheduler.get_job('sync_job')
    
    if seconds == 0:
        if job:
            scheduler.remove_job('sync_job')
    else:
        if job:
            scheduler.reschedule_job('sync_job', trigger=IntervalTrigger(seconds=seconds))
        else:
            # Need a reference to the actual sync_fn, but the app should probably call init again 
            # or pass the function. Assuming the job might be missing, it's safer to only modify if exists.
            logger.warning("Job not found to update interval. Restart scheduler to take effect.")

def trigger_now(sync_fn):
    """
    Runs sync immediately in a separate thread to prevent blocking.
    """
    thread = Thread(target=sync_fn, name="ManualSyncThread")
    thread.daemon = True
    thread.start()
    return thread
