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


@reports_bp.route("/visitors/<path:ip>")
@login_required
def visitor_detail(ip: str):
    raw_domain = request.args.get("domain", "all")
    selected_domains = parse_domain_filter(raw_domain)

    hits_data = []
    sessions_data = []
    visitor_info = {}

    try:
        from magnetar.security import get_security_overview
        sec_info = get_security_overview()
        banned_entries = sec_info.get("banned_entries", [])
        is_banned = False
        jail_name = None
        for b in banned_entries:
            if b.get("ip") == ip:
                is_banned = True
                jail_name = b.get("jail")
                break
        available_jails = [j.get("jail") for j in sec_info.get("jails", [])] or ["nginx-botsearch", "nginx-badbots", "recidive", "sshd"]
    except Exception:
        is_banned = False
        jail_name = None
        available_jails = ["nginx-botsearch", "nginx-badbots", "recidive", "sshd"]

    try:
        with get_db_session() as db:
            visitor = db.get(Visitor, ip)

            hq = sa.select(Hit).where(Hit.ip == ip)
            if selected_domains:
                hq = hq.where(Hit.domain.in_(selected_domains))
            hits = db.execute(hq.order_by(Hit.occurred_at.desc())).scalars().all()

            sq = sa.select(VisitSession).where(VisitSession.visitor_ip == ip)
            if selected_domains:
                sq = sq.where(VisitSession.domain.in_(selected_domains))
            sessions = db.execute(sq.order_by(VisitSession.started_at.desc())).scalars().all()

            status_counts = Counter()
            domain_counts = Counter()
            method_counts = Counter()
            is_bot = False

            for h in hits:
                status_counts[h.status or 200] += 1
                if h.domain:
                    domain_counts[h.domain] += 1
                if h.method:
                    method_counts[h.method] += 1
                if h.is_bot:
                    is_bot = True

                hits_data.append({
                    "id": h.id,
                    "occurred_at": h.occurred_at.strftime("%Y-%m-%d %H:%M:%S") if h.occurred_at else "-",
                    "timestamp_iso": h.occurred_at.isoformat() if h.occurred_at else "",
                    "timestamp_epoch": int(h.occurred_at.timestamp()) if h.occurred_at else 0,
                    "method": h.method or "GET",
                    "path": h.path,
                    "status": h.status or 200,
                    "bytes_sent": h.bytes_sent or 0,
                    "referer": h.referer or "-",
                    "user_agent": h.user_agent or "-",
                    "domain": h.domain or "default",
                    "is_bot": h.is_bot,
                })

            country = visitor.country if visitor and visitor.country else (sessions[0].country if (sessions and sessions[0].country) else "Unknown")
            country_code = visitor.country_code if visitor and visitor.country_code else (sessions[0].country_code if (sessions and sessions[0].country_code) else "??")
            city = visitor.city if visitor and visitor.city else (sessions[0].country if False else "")
            first_seen = visitor.first_seen.strftime("%Y-%m-%d %H:%M:%S") if visitor and visitor.first_seen else (hits_data[-1]["occurred_at"] if hits_data else "-")
            last_seen = visitor.last_seen.strftime("%Y-%m-%d %H:%M:%S") if visitor and visitor.last_seen else (hits_data[0]["occurred_at"] if hits_data else "-")
            total_sessions = visitor.total_sessions if visitor and visitor.total_sessions else (len(sessions) or 1)
            total_hits = visitor.total_hits if visitor and visitor.total_hits else len(hits_data)

            visitor_info = {
                "ip": ip,
                "country": country,
                "country_code": country_code,
                "city": city,
                "total_sessions": total_sessions,
                "total_hits": total_hits,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "is_bot": is_bot,
                "is_banned": is_banned,
                "jail": jail_name,
                "last_path": hits_data[0]["path"] if hits_data else "/",
                "last_ua": hits_data[0]["user_agent"] if hits_data else "",
                "status_counts": dict(status_counts.most_common()),
                "domain_counts": dict(domain_counts.most_common()),
                "method_counts": dict(method_counts.most_common()),
            }

            for s in sessions:
                sessions_data.append({
                    "id": s.id,
                    "started_at": s.started_at.strftime("%Y-%m-%d %H:%M:%S") if s.started_at else "-",
                    "ended_at": s.ended_at.strftime("%Y-%m-%d %H:%M:%S") if s.ended_at else "-",
                    "hit_count": s.hit_count or 0,
                    "entry_path": s.entry_path or "-",
                    "exit_path": s.exit_path or "-",
                    "domain": s.domain or "default",
                })

    except Exception as exc:
        return render_template(
            "error.html",
            error_title="Visitor profile unavailable",
            error_message=str(exc),
            error_detail=traceback.format_exc() if "traceback" in globals() else str(exc),
            last_sync=get_sync_info(),
        ), 500

    return render_template(
        "visitor_detail.html",
        visitor=visitor_info,
        hits=hits_data,
        sessions=sessions_data,
        available_jails=available_jails,
        raw_domain=raw_domain,
        last_sync=get_sync_info(),
    )


@reports_bp.route("/pages/detail")
@login_required
def page_detail():
    path = request.args.get("path", "").strip()
    if not path:
        return render_template(
            "error.html",
            error_title="Invalid Page Request",
            error_message="A valid path parameter is required to view route details.",
            error_detail=None,
            last_sync=get_sync_info(),
        ), 400

    days = int(request.args.get("days", 30))
    raw_domain = request.args.get("domain", "all")
    selected_domains = parse_domain_filter(raw_domain)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        from magnetar.security import get_banned_ips_set
        banned_ips_set = get_banned_ips_set()
    except Exception:
        banned_ips_set = set()

    try:
        with get_db_session() as db:
            hq = sa.select(Hit).where(Hit.path == path, Hit.occurred_at >= since)
            if selected_domains:
                hq = hq.where(Hit.domain.in_(selected_domains))
            hits = db.execute(hq.order_by(Hit.occurred_at.desc())).scalars().all()

            if not hits and "?" in path:
                base_p = path.split("?")[0]
                hq = sa.select(Hit).where(Hit.path == base_p, Hit.occurred_at >= since)
                if selected_domains:
                    hq = hq.where(Hit.domain.in_(selected_domains))
                hits = db.execute(hq.order_by(Hit.occurred_at.desc())).scalars().all()

            visitors_map: dict[str, dict] = defaultdict(lambda: {
                "hits": 0, "first_seen": None, "last_seen": None,
                "status_codes": Counter(), "methods": Counter(), "domains": Counter(),
                "user_agents": Counter(), "is_bot": False
            })

            all_ips = set()
            status_distribution = Counter()
            referer_distribution = Counter()
            human_hits = 0
            bot_hits = 0
            hits_data = []

            for h in hits:
                all_ips.add(h.ip)
                v = visitors_map[h.ip]
                v["hits"] += 1
                if h.occurred_at:
                    if not v["last_seen"] or h.occurred_at > v["last_seen"]:
                        v["last_seen"] = h.occurred_at
                    if not v["first_seen"] or h.occurred_at < v["first_seen"]:
                        v["first_seen"] = h.occurred_at
                if h.status:
                    v["status_codes"][h.status] += 1
                    status_distribution[h.status] += 1
                if h.method:
                    v["methods"][h.method] += 1
                if h.domain:
                    v["domains"][h.domain] += 1
                if h.user_agent:
                    v["user_agents"][h.user_agent] += 1
                if h.is_bot:
                    v["is_bot"] = True
                    bot_hits += 1
                else:
                    human_hits += 1
                if h.referer and h.referer != "-":
                    referer_distribution[h.referer] += 1

                hits_data.append({
                    "id": h.id,
                    "occurred_at": h.occurred_at.strftime("%Y-%m-%d %H:%M:%S") if h.occurred_at else "-",
                    "timestamp_iso": h.occurred_at.isoformat() if h.occurred_at else "",
                    "timestamp_epoch": int(h.occurred_at.timestamp()) if h.occurred_at else 0,
                    "ip": h.ip,
                    "method": h.method or "GET",
                    "status": h.status or 200,
                    "bytes_sent": h.bytes_sent or 0,
                    "referer": h.referer or "-",
                    "user_agent": h.user_agent or "-",
                    "domain": h.domain or "default",
                    "is_bot": h.is_bot,
                })

            visitor_records = {}
            if all_ips:
                v_rows = db.execute(sa.select(Visitor).where(Visitor.ip.in_(all_ips))).scalars().all()
                for vr in v_rows:
                    visitor_records[vr.ip] = vr

            visitors_breakdown = []
            for ip_addr, vdata in visitors_map.items():
                vr = visitor_records.get(ip_addr)
                top_ua = vdata["user_agents"].most_common(1)[0][0] if vdata["user_agents"] else ""
                status_list = [f"{st} ({cnt})" for st, cnt in vdata["status_codes"].most_common()]
                visitors_breakdown.append({
                    "ip": ip_addr,
                    "country": vr.country if vr and vr.country else "Unknown",
                    "country_code": vr.country_code if vr and vr.country_code else "??",
                    "city": vr.city if vr and vr.city else "",
                    "hits": vdata["hits"],
                    "first_seen": vdata["first_seen"].strftime("%Y-%m-%d %H:%M:%S") if vdata["first_seen"] else "-",
                    "last_seen": vdata["last_seen"].strftime("%Y-%m-%d %H:%M:%S") if vdata["last_seen"] else "-",
                    "is_bot": vdata["is_bot"],
                    "is_banned": ip_addr in banned_ips_set,
                    "top_ua": top_ua,
                    "status_codes": status_list,
                })

            visitors_breakdown.sort(key=lambda x: x["hits"], reverse=True)

        page_summary = {
            "path": path,
            "total_hits": len(hits_data),
            "unique_visitors": len(all_ips),
            "human_hits": human_hits,
            "bot_hits": bot_hits,
            "status_distribution": dict(status_distribution.most_common(5)),
            "top_referrers": [{"referer": r, "count": c} for r, c in referer_distribution.most_common(6)],
        }
    except Exception as exc:
        return render_template(
            "error.html",
            error_title="Route details unavailable",
            error_message=str(exc),
            error_detail=str(exc),
            last_sync=get_sync_info(),
        ), 500

    return render_template(
        "page_detail.html",
        page=page_summary,
        visitors=visitors_breakdown,
        hits=hits_data,
        days=days,
        raw_domain=raw_domain,
        last_sync=get_sync_info(),
    )

