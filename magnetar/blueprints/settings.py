"""
magnetar.blueprints.settings
----------------------------
Settings view and database inspector.
"""

from __future__ import annotations

import json
import os
import sqlalchemy as sa
from flask import Blueprint, render_template

from magnetar.auth import login_required
from magnetar.config import DATABASE_URL
from magnetar.context_processors import get_sync_info
from magnetar.db import get_db_info, get_db_session, get_engine
from magnetar.models import Event, Hit, Session as VisitSession, SyncConfig, Visitor

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/settings")
@login_required
def settings_page():
    engine = get_engine(DATABASE_URL)
    sync_info = get_sync_info()
    db_info = get_db_info(engine)

    try:
        with get_db_session() as db:
            db_info["engine"]   = db_info.get("dialect", "sqlite").upper()
            db_info["database"] = db_info.get("url_display", DATABASE_URL)
            db_info["size"]     = f"{os.path.getsize('magnetar.db') / (1024*1024):.2f} MB" if os.path.exists("magnetar.db") else "N/A"
            db_info["hits"]     = db.execute(sa.select(sa.func.count(Hit.id))).scalar() or 0
            db_info["sessions"] = db.execute(sa.select(sa.func.count(VisitSession.id))).scalar() or 0
            db_info["events"]   = db.execute(sa.select(sa.func.count(Event.id))).scalar() or 0
            db_info["visitors"] = db.execute(sa.select(sa.func.count(Visitor.ip))).scalar() or 0

            history_raw = db.execute(
                sa.select(SyncConfig).where(SyncConfig.key.like("sync_history_%"))
                .order_by(SyncConfig.key.desc())
                .limit(5)
            ).scalars().all()
            sync_history = [json.loads(h.value) for h in history_raw]
    except Exception:
        sync_history = []

    try:
        from magnetar.security import get_security_overview
        security_overview = get_security_overview()
    except Exception:
        security_overview = {"is_active": False, "jails": [], "banned_entries": [], "total_currently_banned": 0, "total_all_time_banned": 0}

    return render_template(
        "settings.html",
        sync_interval=int(sync_info.get("interval_seconds", 300)),
        last_sync=sync_info,
        sync_history=sync_history,
        db_info=db_info,
        security=security_overview,
    )
