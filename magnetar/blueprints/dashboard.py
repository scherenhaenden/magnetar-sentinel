"""
magnetar.blueprints.dashboard
-----------------------------
Dashboard route and summary aggregators.
"""

from __future__ import annotations

import traceback
from datetime import datetime, timedelta, timezone
import sqlalchemy as sa
from flask import Blueprint, render_template, request

from magnetar.aggregator import Summary, build_summary
from magnetar.auth import login_required
from magnetar.config import DAYS, GEOIP_PATH, LOG_DIR, SSH_HOST, SSH_KEY, SSH_USER
from magnetar.context_processors import get_domain_stats, get_sync_info, parse_domain_filter
from magnetar.db import get_db_session
from magnetar.log_parser import Hit as HitDC, parse_logs
from magnetar.models import Hit

dashboard_bp = Blueprint("dashboard", __name__)


def remote_log_paths(days: int) -> list[str]:
    paths = [f"{LOG_DIR}/access.log"]
    today = datetime.now(timezone.utc).date()
    for i in range(days):
        d = today - timedelta(days=i)
        paths.append(f"{LOG_DIR}/access.log-{d.strftime('%Y-%m-%d')}")
    return paths


def build_summary_from_db(days: int, selected_domains: list[str]) -> Summary:
    since = datetime.now(timezone.utc) - timedelta(days=days)

    with get_db_session() as db:
        q = sa.select(Hit).where(Hit.occurred_at >= since)
        if selected_domains:
            q = q.where(Hit.domain.in_(selected_domains))

        hits_q = db.execute(q).scalars().all()

        hit_dcs = []
        for h in hits_q:
            hdc = HitDC(
                ip=h.ip,
                dt=h.occurred_at,
                method=h.method or "GET",
                path=h.path,
                status=h.status or 200,
                bytes_sent=h.bytes_sent or 0,
                referer=h.referer or "-",
                user_agent=h.user_agent or "",
                is_bot=h.is_bot,
            )
            hit_dcs.append(hdc)

    return build_summary(hit_dcs, geoip_db_path=GEOIP_PATH, top_n=30)


@dashboard_bp.route("/")
@dashboard_bp.route("/dashboard")
@login_required
def index():
    days = int(request.args.get("days", DAYS))
    raw_domain = request.args.get("domain", "all")
    selected_domains = parse_domain_filter(raw_domain)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        with get_db_session() as db:
            hit_count = db.execute(sa.select(sa.func.count(Hit.id))).scalar() or 0

        domain_stats = get_domain_stats(since, selected_domains)

        if hit_count > 0:
            summary = build_summary_from_db(days, selected_domains)
        else:
            try:
                log_paths = remote_log_paths(days)
                hits = parse_logs(SSH_HOST, SSH_USER, SSH_KEY, log_paths)
                summary = build_summary(hits, geoip_db_path=GEOIP_PATH, top_n=30)
            except Exception:
                summary = Summary(
                    total_hits=0, unique_ips=0, human_hits=0, bot_hits=0,
                    top_visitors=[], countries=[], referrers=[], top_articles=[]
                )

    except Exception as exc:
        return render_template(
            "error.html",
            error_title="Failed to load dashboard",
            error_message=str(exc),
            error_detail=traceback.format_exc(),
            last_sync=get_sync_info(),
        ), 500

    try:
        from magnetar.security import get_security_overview
        sec_overview = get_security_overview()
        banned_count = sec_overview.get("total_currently_banned", 0)
    except Exception:
        banned_count = 0

    return render_template(
        "dashboard.html",
        summary=summary,
        days=days,
        domain_stats=domain_stats,
        raw_domain=raw_domain,
        selected_domains=selected_domains,
        banned_count=banned_count,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        last_sync=get_sync_info(),
    )
