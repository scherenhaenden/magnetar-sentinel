"""
magnetar.blueprints.api
-----------------------
REST and AJAX APIs for live metrics, drilldowns, sync triggers, and scheduler management.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import sqlalchemy as sa
from flask import Blueprint, current_app, jsonify, request

from magnetar.auth import login_required
from magnetar.config import DAYS, GEOIP_PATH, LOG_DIR, SSH_HOST, SSH_KEY, SSH_USER
from magnetar.context_processors import get_sync_info, parse_domain_filter
from magnetar.db import get_db_session
from magnetar.models import Hit, SyncConfig, Visitor, Session as VisitSession
from magnetar.scheduler import update_interval
from magnetar.sync import run_sync

api_bp = Blueprint("api", __name__)


# ── Drilldown API ─────────────────────────────────────────────────────────────
@api_bp.route("/api/drilldown/country")
@login_required
def api_drilldown_country():
    country_name = request.args.get("country", "")
    country_code = request.args.get("code", "")
    days = int(request.args.get("days", 7))
    raw_domain = request.args.get("domain", "all")
    selected_domains = parse_domain_filter(raw_domain)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        with get_db_session() as db:
            vq = sa.select(Visitor.ip)
            if country_name:
                vq = vq.where(sa.or_(Visitor.country == country_name, Visitor.country_code == country_code))
            country_ips = set(db.execute(vq).scalars().all())

            sq = sa.select(VisitSession.visitor_ip).where(VisitSession.started_at >= since)
            if country_name:
                sq = sq.where(sa.or_(VisitSession.country == country_name, VisitSession.country_code == country_code))
            if selected_domains:
                sq = sq.where(VisitSession.domain.in_(selected_domains))
            session_ips = set(db.execute(sq).scalars().all())

            all_target_ips = country_ips | session_ips
            if not all_target_ips:
                return jsonify({
                    "country": country_name, "country_code": country_code,
                    "total_hits": 0, "unique_ips": 0, "human_hits": 0, "bot_hits": 0,
                    "top_pages": [], "top_referrers": [], "top_domains": []
                })

            hq = sa.select(Hit).where(Hit.occurred_at >= since, Hit.ip.in_(all_target_ips))
            if selected_domains:
                hq = hq.where(Hit.domain.in_(selected_domains))
            hits = db.execute(hq).scalars().all()

            pages_counter: Counter = Counter()
            ref_counter: Counter = Counter()
            dom_counter: Counter = Counter()
            human_hits = 0
            bot_hits = 0
            unique_ips = set()

            for h in hits:
                unique_ips.add(h.ip)
                if h.is_bot:
                    bot_hits += 1
                else:
                    human_hits += 1
                if h.path:
                    pages_counter[h.path] += 1
                if h.referer and h.referer != "-":
                    ref_counter[h.referer] += 1
                if h.domain:
                    dom_counter[h.domain] += 1

            return jsonify({
                "country": country_name,
                "country_code": country_code,
                "total_hits": len(hits),
                "unique_ips": len(unique_ips),
                "human_hits": human_hits,
                "bot_hits": bot_hits,
                "top_pages": [{"path": p, "hits": c} for p, c in pages_counter.most_common(15)],
                "top_referrers": [{"referer": r, "hits": c} for r, c in ref_counter.most_common(10)],
                "top_domains": [{"domain": d, "hits": c} for d, c in dom_counter.most_common(5)],
            })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@api_bp.route("/api/drilldown/referrer")
@login_required
def api_drilldown_referrer():
    referer = request.args.get("referer", "")
    days = int(request.args.get("days", 7))
    raw_domain = request.args.get("domain", "all")
    selected_domains = parse_domain_filter(raw_domain)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        with get_db_session() as db:
            hq = sa.select(Hit).where(Hit.occurred_at >= since)
            if referer == "-" or referer.lower() == "direct / none":
                hq = hq.where(sa.or_(Hit.referer == "-", Hit.referer.is_(None)))
            else:
                hq = hq.where(Hit.referer.like(f"%{referer}%"))

            if selected_domains:
                hq = hq.where(Hit.domain.in_(selected_domains))

            hits = db.execute(hq).scalars().all()
            target_pages: Counter = Counter()
            target_ips = set()
            domains_counter: Counter = Counter()

            for h in hits:
                target_ips.add(h.ip)
                if h.path:
                    target_pages[h.path] += 1
                if h.domain:
                    domains_counter[h.domain] += 1

            countries_counter: Counter = Counter()
            if target_ips:
                v_rows = db.execute(
                    sa.select(Visitor.country, Visitor.country_code).where(Visitor.ip.in_(target_ips))
                ).all()
                for c_name, c_code in v_rows:
                    if c_name:
                        countries_counter[(c_name, c_code or "??")] += 1

            total_h = len(hits)
            from_to = [
                {"target_path": p, "hits": c, "pct": round(c / total_h * 100, 1) if total_h else 0}
                for p, c in target_pages.most_common(15)
            ]
            country_list = [
                {"country": c[0], "country_code": c[1], "count": cnt}
                for c, cnt in countries_counter.most_common(10)
            ]

            return jsonify({
                "referer": referer,
                "total_hits": total_h,
                "unique_ips": len(target_ips),
                "from_to_pages": from_to,
                "top_countries": country_list,
                "top_domains": [{"domain": d, "hits": c} for d, c in domains_counter.most_common(5)],
            })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Seed Demo Data ────────────────────────────────────────────────────────────
@api_bp.route("/api/seed", methods=["POST"])
@login_required
def api_seed():
    try:
        from magnetar.seed import seed_all
        seed_all(num_visitors=240, clear_existing=True)
        return jsonify({"status": "ok", "message": "Synthetic demo data generated successfully across multiple domains."})
    except Exception as exc:
        return jsonify({"status": "error", "error": str(exc)}), 500


# ── Sync Endpoints ────────────────────────────────────────────────────────────
@api_bp.route("/api/sync/now", methods=["POST"])
@login_required
def api_sync_now():
    try:
        result = {}
        with get_db_session() as db:
            result = run_sync(
                ssh_host=SSH_HOST,
                ssh_user=SSH_USER,
                ssh_key=SSH_KEY,
                log_dir=LOG_DIR,
                db_session=db,
                geoip_db_path=GEOIP_PATH,
                days=DAYS,
            )
        return jsonify({"status": "ok", **result})
    except Exception as exc:
        return jsonify({"status": "error", "error": str(exc)}), 500


@api_bp.route("/api/sync/interval", methods=["POST"])
@login_required
def api_sync_interval():
    data = request.get_json()
    seconds = data.get("seconds", 300) if data else 300
    valid = [0, 60, 300, 900, 3600]
    if seconds not in valid:
        return jsonify({"error": f"Invalid interval. Valid: {valid}"}), 400

    try:
        with get_db_session() as db:
            db.merge(SyncConfig(key="interval_seconds", value=str(seconds)))
            db.commit()

        scheduler = current_app.config.get("SCHEDULER")
        if scheduler:
            update_interval(scheduler, seconds)
        return jsonify({"status": "ok", "interval_seconds": seconds})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@api_bp.route("/api/status")
@login_required
def api_status():
    sync_info = get_sync_info()
    try:
        with get_db_session() as db:
            hit_count = db.execute(sa.select(sa.func.count(Hit.id))).scalar() or 0
    except Exception:
        hit_count = 0
    return jsonify({
        "status": "ok",
        "version": "0.4.0",
        "hits_in_db": hit_count,
        **sync_info,
    })


@api_bp.route("/api/security/status")
@login_required
def api_security_status():
    from magnetar.security import get_security_overview
    return jsonify(get_security_overview())


@api_bp.route("/api/security/unban", methods=["POST"])
@login_required
def api_security_unban():
    data = request.get_json() or {}
    jail = data.get("jail", "nginx-botsearch")
    ip = data.get("ip", "").strip()
    if not ip:
        return jsonify({"error": "ip is required"}), 400

    from magnetar.security import unban_ip_action
    ok = unban_ip_action(jail, ip)
    if ok:
        return jsonify({"status": "ok", "message": f"IP {ip} unbanned from jail {jail}"})
    return jsonify({"status": "error", "error": f"Failed to unban {ip} from {jail}"}), 500


@api_bp.route("/api/security/ban", methods=["POST"])
@login_required
def api_security_ban():
    data = request.get_json() or {}
    jail = data.get("jail", "nginx-botsearch")
    ip = data.get("ip", "").strip()
    if not ip:
        return jsonify({"error": "ip is required"}), 400

    from magnetar.security import ban_ip_action
    ok = ban_ip_action(jail, ip)
    if ok:
        return jsonify({"status": "ok", "message": f"IP {ip} banned in jail {jail}"})
    return jsonify({"status": "error", "error": f"Failed to ban {ip} in {jail}"}), 500


@api_bp.route("/health")
def health():
    return jsonify({"status": "ok", "version": "0.4.0"})
