"""
magnetar.blueprints.reports
---------------------------
Dedicated full-page report views:
  - /pages (Pages & Articles)
  - /referrers (Origins & Acquisition Channels)
  - /countries (Geographic distribution)
  - /visitors (Audience & Session log)
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import sqlalchemy as sa
from flask import Blueprint, render_template, request

from magnetar.auth import login_required
from magnetar.blueprints.dashboard import build_summary_from_db
from magnetar.context_processors import get_sync_info, parse_domain_filter
from magnetar.db import get_db_session
from magnetar.models import Hit, Session as VisitSession, Visitor

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/referrers")
@login_required
def referrers_page():
    days = int(request.args.get("days", 7))
    raw_domain = request.args.get("domain", "all")
    selected_domains = parse_domain_filter(raw_domain)

    summary = build_summary_from_db(days, selected_domains)
    return render_template(
        "referrers.html",
        summary=summary,
        days=days,
        raw_domain=raw_domain,
        last_sync=get_sync_info(),
    )


@reports_bp.route("/countries")
@login_required
def countries_page():
    days = int(request.args.get("days", 7))
    raw_domain = request.args.get("domain", "all")
    selected_domains = parse_domain_filter(raw_domain)

    summary = build_summary_from_db(days, selected_domains)
    return render_template(
        "countries.html",
        summary=summary,
        days=days,
        raw_domain=raw_domain,
        last_sync=get_sync_info(),
    )


@reports_bp.route("/pages")
@login_required
def pages_page():
    days = int(request.args.get("days", 7))
    raw_domain = request.args.get("domain", "all")
    selected_domains = parse_domain_filter(raw_domain)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    pages_data = []
    try:
        with get_db_session() as db:
            q = sa.select(Hit).where(Hit.occurred_at >= since)
            if selected_domains:
                q = q.where(Hit.domain.in_(selected_domains))
            hits = db.execute(q).scalars().all()

            paths_stats: dict[str, dict] = defaultdict(lambda: {
                "hits": 0, "human_hits": 0, "bot_hits": 0, "ips": set(), "referrers": Counter(), "domains": Counter()
            })

            for h in hits:
                p = (h.path or "/").split("?")[0]
                if p in {"/favicon.ico", "/robots.txt"}:
                    continue
                d = paths_stats[p]
                d["hits"] += 1
                d["ips"].add(h.ip)
                if h.is_bot:
                    d["bot_hits"] += 1
                else:
                    d["human_hits"] += 1
                if h.referer and h.referer != "-":
                    d["referrers"][h.referer] += 1
                if h.domain:
                    d["domains"][h.domain] += 1

            for p, st in sorted(paths_stats.items(), key=lambda x: x[1]["hits"], reverse=True):
                top_refs = [r for r, _ in st["referrers"].most_common(3)]
                pages_data.append({
                    "path": p,
                    "hits": st["hits"],
                    "unique_ips": len(st["ips"]),
                    "human_hits": st["human_hits"],
                    "bot_hits": st["bot_hits"],
                    "top_referrers": top_refs,
                    "domains": list(st["domains"].keys()),
                })
    except Exception:
        pass

    return render_template(
        "pages.html",
        pages_data=pages_data,
        days=days,
        raw_domain=raw_domain,
        last_sync=get_sync_info(),
    )


@reports_bp.route("/visitors")
@login_required
def visitors_page():
    filter_type = request.args.get("type", "all")
    days = int(request.args.get("days", 30))
    raw_domain = request.args.get("domain", "all")
    selected_domains = parse_domain_filter(raw_domain)

    visitors_list = []
    try:
        from magnetar.security import get_banned_ips_set
        banned_ips_set = get_banned_ips_set()
    except Exception:
        banned_ips_set = set()

    try:
        with get_db_session() as db:
            if not selected_domains:
                visitors = db.execute(sa.select(Visitor).order_by(Visitor.last_seen.desc()).limit(200)).scalars().all()
            else:
                s_rows = db.execute(sa.select(VisitSession.visitor_ip).where(VisitSession.domain.in_(selected_domains))).scalars().all()
                dom_ips = set(s_rows)
                visitors = db.execute(sa.select(Visitor).where(Visitor.ip.in_(dom_ips)).order_by(Visitor.last_seen.desc()).limit(200)).scalars().all()

            for v in visitors:
                recent_hit = db.execute(
                    sa.select(Hit).where(Hit.ip == v.ip).order_by(Hit.occurred_at.desc()).limit(1)
                ).scalars().first()

                is_bot = recent_hit.is_bot if recent_hit else False
                if filter_type == "human" and is_bot:
                    continue
                if filter_type == "bot" and not is_bot:
                    continue

                visitors_list.append({
                    "ip": v.ip,
                    "country": v.country or "Unknown",
                    "country_code": v.country_code or "??",
                    "city": v.city or "",
                    "total_sessions": v.total_sessions or 1,
                    "total_hits": v.total_hits or 1,
                    "first_seen": v.first_seen.strftime("%Y-%m-%d %H:%M") if v.first_seen else "-",
                    "last_seen": v.last_seen.strftime("%Y-%m-%d %H:%M") if v.last_seen else "-",
                    "is_bot": is_bot,
                    "is_banned": v.ip in banned_ips_set,
                    "last_path": recent_hit.path if recent_hit else "/",
                    "last_ua": recent_hit.user_agent if recent_hit else "",
                })
    except Exception:
        pass

    return render_template(
        "visitors.html",
        visitors=visitors_list,
        filter_type=filter_type,
        days=days,
        raw_domain=raw_domain,
        last_sync=get_sync_info(),
    )
