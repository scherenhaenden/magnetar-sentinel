"""
magnetar.blueprints.analytics
-----------------------------
Deep analytics routes:
  - /journey (User paths & Sankey flow)
  - /retention (Weekly retention matrix)
  - /cohorts (Acquisition cohorts)
  - /funnels (Conversion funnels & builder)
  - /events (Real-time event stream)
"""

from __future__ import annotations

import re
import traceback
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import sqlalchemy as sa
from flask import Blueprint, jsonify, render_template, request

from magnetar.auth import login_required
from magnetar.context_processors import get_domain_stats, get_sync_info, parse_domain_filter
from magnetar.db import get_db_session
from magnetar.models import (
    Event, FunnelDef, FunnelStep, Hit, JourneyStep, Session as VisitSession, Visitor,
)

analytics_bp = Blueprint("analytics", __name__)


# ── Journey ──────────────────────────────────────────────────────────────────
@analytics_bp.route("/journey")
@login_required
def journey():
    days = int(request.args.get("days", 7))
    raw_domain = request.args.get("domain", "all")
    selected_domains = parse_domain_filter(raw_domain)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    top_paths = []
    transitions = []

    try:
        domain_stats = get_domain_stats(since, selected_domains)
        with get_db_session() as db:
            q = sa.select(VisitSession).where(VisitSession.started_at >= since)
            if selected_domains:
                q = q.where(VisitSession.domain.in_(selected_domains))

            sessions_q = db.execute(q.order_by(VisitSession.started_at.desc()).limit(2000)).scalars().all()

            path_sequences: Counter = Counter()
            transition_counter: Counter = Counter()

            for sess in sessions_q:
                steps = db.execute(
                    sa.select(JourneyStep)
                    .where(JourneyStep.session_id == sess.id)
                    .order_by(JourneyStep.step_index)
                ).scalars().all()
                paths = [s.path for s in steps]
                if len(paths) >= 2:
                    short = [p[:50] for p in paths[:5]]
                    path_sequences[tuple(short)] += 1
                    for i in range(len(paths) - 1):
                        transition_counter[(paths[i][:45], paths[i + 1][:45])] += 1

            top_paths = [
                {"path_sequence": list(seq), "count": cnt}
                for seq, cnt in path_sequences.most_common(20)
            ]
            transitions = [
                {"from_path": fr, "to_path": to, "count": cnt}
                for (fr, to), cnt in transition_counter.most_common(12)
            ]
    except Exception as exc:
        return render_template(
            "error.html",
            error_title="Journey data unavailable",
            error_message=str(exc),
            error_detail=traceback.format_exc(),
            last_sync=get_sync_info(),
        ), 500

    return render_template(
        "journey.html",
        top_paths=top_paths,
        transitions=transitions,
        days=days,
        domain_stats=domain_stats,
        raw_domain=raw_domain,
        last_sync=get_sync_info(),
    )


# ── Retention ────────────────────────────────────────────────────────────────
@analytics_bp.route("/retention")
@login_required
def retention():
    raw_domain = request.args.get("domain", "all")
    selected_domains = parse_domain_filter(raw_domain)
    cohorts = []
    now_date = datetime.now(timezone.utc).date()

    try:
        with get_db_session() as db:
            # 1. Fetch sessions for the selected domain(s)
            sq = sa.select(VisitSession.visitor_ip, VisitSession.started_at)
            if selected_domains:
                sq = sq.where(VisitSession.domain.in_(selected_domains))
            sessions = db.execute(sq).all()

            # Map active IPs by week and identify each IP's first session week
            active_ips_by_week: dict[date, set[str]] = defaultdict(set)
            first_week_by_ip: dict[str, date] = {}

            for ip, started_at in sessions:
                if not started_at:
                    continue
                s_date = started_at.date()
                w_start = s_date - timedelta(days=s_date.weekday())
                active_ips_by_week[w_start].add(ip)

                if ip not in first_week_by_ip or w_start < first_week_by_ip[ip]:
                    first_week_by_ip[ip] = w_start

            cohort_ips_by_week: dict[date, set[str]] = defaultdict(set)
            for ip, first_w in first_week_by_ip.items():
                cohort_ips_by_week[first_w].add(ip)

            sorted_weeks = sorted(cohort_ips_by_week.keys())
            # Keep the last 12 cohorts at most for clean display
            if len(sorted_weeks) > 12:
                sorted_weeks = sorted_weeks[-12:]

            for w_start in sorted_weeks:
                cohort_ips = cohort_ips_by_week[w_start]
                week_label = w_start.strftime("%b %d")
                retention_row = [100.0]

                for offset in range(1, 5):
                    target_week = w_start + timedelta(weeks=offset)
                    if target_week > now_date:
                        retention_row.append(None)
                    else:
                        active_in_target = active_ips_by_week.get(target_week, set())
                        retained = cohort_ips & active_in_target
                        pct = round(len(retained) / len(cohort_ips) * 100, 1) if cohort_ips else 0.0
                        retention_row.append(pct)

                while len(retention_row) < 5:
                    retention_row.append(None)

                cohorts.append({
                    "week_label": week_label,
                    "new_ips": len(cohort_ips),
                    "retention": retention_row,
                })
    except Exception as exc:
        return render_template(
            "error.html",
            error_title="Retention data unavailable",
            error_message=str(exc),
            error_detail=traceback.format_exc(),
            last_sync=get_sync_info(),
        ), 500

    return render_template(
        "retention.html",
        cohorts=cohorts,
        raw_domain=raw_domain,
        last_sync=get_sync_info(),
    )


# ── Cohorts ──────────────────────────────────────────────────────────────────
@analytics_bp.route("/cohorts")
@login_required
def cohorts():
    raw_domain = request.args.get("domain", "all")
    selected_domains = parse_domain_filter(raw_domain)
    cohort_rows = []

    try:
        with get_db_session() as db:
            # 1. Fetch domain hits for accurate weekly hit and visitor metrics
            hq = sa.select(Hit.ip, Hit.occurred_at, Hit.is_bot)
            if selected_domains:
                hq = hq.where(Hit.domain.in_(selected_domains))
            hits = db.execute(hq).all()

            first_seen_by_ip: dict[str, date] = {}
            hits_by_week: dict[date, int] = Counter()
            bot_hits_by_week: dict[date, int] = Counter()

            for ip, dt, is_bot in hits:
                if not dt:
                    continue
                d = dt.date()
                w = d - timedelta(days=d.weekday())
                hits_by_week[w] += 1
                if is_bot:
                    bot_hits_by_week[w] += 1
                if ip not in first_seen_by_ip or d < first_seen_by_ip[ip]:
                    first_seen_by_ip[ip] = d

            new_visitors_by_week: dict[date, int] = Counter()
            cohort_ips_by_week: dict[date, list[str]] = defaultdict(list)
            for ip, fdate in first_seen_by_ip.items():
                fw = fdate - timedelta(days=fdate.weekday())
                new_visitors_by_week[fw] += 1
                cohort_ips_by_week[fw].append(ip)

            # Get country info for top countries
            all_first_ips = list(first_seen_by_ip.keys())
            vis_map = {}
            if all_first_ips:
                v_rows = db.execute(sa.select(Visitor.ip, Visitor.country).where(Visitor.ip.in_(all_first_ips[:2000]))).all()
                vis_map = {row[0]: row[1] for row in v_rows if row[1]}

            sorted_weeks = sorted(hits_by_week.keys())
            if len(sorted_weeks) > 12:
                sorted_weeks = sorted_weeks[-12:]

            for w in sorted_weeks:
                wk_str = w.strftime("%b %d")
                t_hits = hits_by_week[w]
                b_hits = bot_hits_by_week[w]
                b_pct = round(b_hits / t_hits * 100, 1) if t_hits else 0.0

                w_ips = cohort_ips_by_week.get(w, [])
                c_counts = Counter(vis_map[ip] for ip in w_ips if ip in vis_map)
                top_c = [c for c, _ in c_counts.most_common(3)]

                cohort_rows.append({
                    "week": wk_str,
                    "new_visitors": new_visitors_by_week[w],
                    "total_hits": t_hits,
                    "bot_pct": b_pct,
                    "top_countries": top_c or ["Various"],
                })
    except Exception as exc:
        return render_template(
            "error.html",
            error_title="Cohort data unavailable",
            error_message=str(exc),
            error_detail=traceback.format_exc(),
            last_sync=get_sync_info(),
        ), 500

    return render_template(
        "cohorts.html",
        cohort_rows=cohort_rows,
        raw_domain=raw_domain,
        last_sync=get_sync_info(),
    )


# ── Funnels ──────────────────────────────────────────────────────────────────
def _compute_funnel_step_counts(db, funnel_data: dict, selected_domains: list[str]) -> dict[str, int]:
    steps = funnel_data["steps"]
    if not steps:
        return {}

    q = sa.select(JourneyStep).join(VisitSession, JourneyStep.session_id == VisitSession.id)
    if selected_domains:
        q = q.where(VisitSession.domain.in_(selected_domains))

    all_journey_steps = db.execute(q.order_by(JourneyStep.session_id, JourneyStep.step_index)).scalars().all()

    by_session: dict[int, list[str]] = defaultdict(list)
    for js in all_journey_steps:
        by_session[js.session_id].append(js.path or "")

    step_patterns = [re.compile(s.path_pattern or ".*", re.I) for s in steps]
    step_counts = [0] * len(steps)

    for session_paths in by_session.values():
        step_idx = 0
        for path in session_paths:
            if step_idx >= len(step_patterns):
                break
            if step_patterns[step_idx].search(path):
                step_counts[step_idx] += 1
                step_idx += 1

    return {step.name: count for step, count in zip(steps, step_counts)}


def _compute_funnel_stats(db, funnel_data: dict, selected_domains: list[str]) -> dict:
    steps = funnel_data["steps"]
    if not steps:
        return {"overall_conversion": 0}

    counts = _compute_funnel_step_counts(db, funnel_data, selected_domains)
    step_names = [s.name for s in steps]
    first_count = counts.get(step_names[0], 0) if step_names else 0
    last_count = counts.get(step_names[-1], 0) if step_names else 0
    overall = round((last_count / first_count * 100), 1) if first_count > 0 else 0
    return {"overall_conversion": overall}


@analytics_bp.route("/funnels")
@login_required
def funnels_list():
    raw_domain = request.args.get("domain", "all")
    selected_domains = parse_domain_filter(raw_domain)
    selected_funnel = None
    funnel_stats = {}

    try:
        with get_db_session() as db:
            q = sa.select(FunnelDef)
            if selected_domains:
                q = q.where(sa.or_(FunnelDef.domain.in_(selected_domains), FunnelDef.domain == "all"))

            all_funnels = db.execute(q.order_by(FunnelDef.created_at.desc())).scalars().all()

            funnels_data = []
            for f in all_funnels:
                steps = db.execute(
                    sa.select(FunnelStep)
                    .where(FunnelStep.funnel_id == f.id)
                    .order_by(FunnelStep.step_index)
                ).scalars().all()

                stats = _compute_funnel_stats(db, {"funnel": f, "steps": steps}, selected_domains)
                overall_conv = stats.get("overall_conversion", 0) if stats else 0
                funnels_data.append({
                    "id": f.id,
                    "name": f.name,
                    "domain": f.domain,
                    "steps": steps,
                    "conversion_rate": overall_conv,
                })

            selected_id = request.args.get("funnel", type=int)
            if not selected_id and funnels_data:
                selected_id = funnels_data[0]["id"]

            if selected_id:
                for fd in funnels_data:
                    if fd["id"] == selected_id:
                        selected_funnel = fd
                        funnel_stats = _compute_funnel_step_counts(db, fd, selected_domains)
                        break

    except Exception as exc:
        return render_template(
            "error.html",
            error_title="Funnels unavailable",
            error_message=str(exc),
            error_detail=traceback.format_exc(),
            last_sync=get_sync_info(),
        ), 500

    return render_template(
        "funnels.html",
        funnels=funnels_data,
        selected_funnel=selected_funnel,
        funnel_stats=funnel_stats,
        raw_domain=raw_domain,
        last_sync=get_sync_info(),
    )


@analytics_bp.route("/funnels", methods=["POST"])
@login_required
def create_funnel():
    data = request.get_json()
    if not data or not data.get("name") or not data.get("steps"):
        return jsonify({"error": "name and steps are required"}), 400

    domain = data.get("domain", "all")

    try:
        with get_db_session() as db:
            funnel = FunnelDef(domain=domain, name=data["name"], created_at=datetime.utcnow())
            db.add(funnel)
            db.flush()
            for i, step in enumerate(data["steps"]):
                db.add(FunnelStep(
                    funnel_id=funnel.id,
                    step_index=i,
                    name=step["name"],
                    path_pattern=step["pattern"],
                ))
            db.commit()
            return jsonify({"id": funnel.id, "name": funnel.name}), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@analytics_bp.route("/funnels/<int:funnel_id>", methods=["DELETE"])
@login_required
def delete_funnel(funnel_id: int):
    try:
        with get_db_session() as db:
            f = db.get(FunnelDef, funnel_id)
            if not f:
                return jsonify({"error": "not found"}), 404
            db.delete(f)
            db.commit()
            return jsonify({"deleted": funnel_id})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Events ───────────────────────────────────────────────────────────────────
@analytics_bp.route("/events")
@login_required
def events():
    active_filter = request.args.get("type", "")
    raw_domain = request.args.get("domain", "all")
    selected_domains = parse_domain_filter(raw_domain)
    days = int(request.args.get("days", 30))
    since = datetime.now(timezone.utc) - timedelta(days=days)

    events_list = []
    event_counts: dict[str, int] = {}

    try:
        with get_db_session() as db:
            q = sa.select(Event).where(Event.occurred_at >= since)
            if selected_domains:
                q = q.where(Event.domain.in_(selected_domains))
            if active_filter:
                q = q.where(Event.event_type == active_filter)

            events_list = db.execute(q.order_by(Event.occurred_at.desc()).limit(300)).scalars().all()

            cq = sa.select(Event.event_type, sa.func.count(Event.id)).where(Event.occurred_at >= since)
            if selected_domains:
                cq = cq.where(Event.domain.in_(selected_domains))

            counts_q = db.execute(cq.group_by(Event.event_type)).all()
            event_counts = {row[0]: row[1] for row in counts_q}
    except Exception as exc:
        return render_template(
            "error.html",
            error_title="Events data unavailable",
            error_message=str(exc),
            error_detail=traceback.format_exc(),
            last_sync=get_sync_info(),
        ), 500

    return render_template(
        "events.html",
        events=events_list,
        active_filter=active_filter,
        event_counts=event_counts,
        days=days,
        raw_domain=raw_domain,
        last_sync=get_sync_info(),
    )
