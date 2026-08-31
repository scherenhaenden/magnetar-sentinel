"""
magnetar.blueprints.security
----------------------------
Dedicated Security & Firewall Shield page (/security).
"""

from __future__ import annotations

from flask import Blueprint, render_template

from magnetar.auth import login_required
from magnetar.context_processors import get_sync_info
from magnetar.security import get_security_overview

security_bp = Blueprint("security", __name__)


@security_bp.route("/security")
@login_required
def security_page():
    try:
        sec = get_security_overview()
    except Exception:
        sec = {"is_active": False, "jails": [], "banned_entries": [], "total_currently_banned": 0, "total_all_time_banned": 0}

    return render_template(
        "security.html",
        security=sec,
        last_sync=get_sync_info(),
    )
