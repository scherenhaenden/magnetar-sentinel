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
from datetime import datetime, timedelta, timezone
import sqlalchemy as sa
from flask import Blueprint, jsonify, render_template, request

from magnetar.auth import login_required
from magnetar.context_processors import get_domain_stats, get_sync_info, parse_domain_filter
from magnetar.db import get_db_session
from magnetar.models import (
    Event, FunnelDef, FunnelStep, JourneyStep, Session as VisitSession, Visitor,
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

    try:
        with get_db_session() as db:
            if not selected_domains:
                visitors = db.execute(sa.select(Visitor).order_by(Visitor.first_seen)).scalars().all()
            else:
                all_sessions = db.execute(sa.select(VisitSession).where(VisitSession.domain.in_(selected_domains))).scalars().all()
                dom_ips = set(s.visitor_ip for s in all_sessions)
                visitors = db.execute(sa.select(Visitor).where(Visitor.ip.in_(dom_ips)).order_by(Visitor.first_seen)).scalars().all()

            week_cohorts: dict[str, set[str]] = defaultdict(set)
            for v in visitors:
                if not v.first_seen:
                    continue
                week_start = v.first_seen.date() - timedelta(days=v.first_seen.weekday())
                week_label = week_start.strftime("%b %d")
                week_cohorts[week_label].add(v.ip)

            all_weeks = sorted(week_cohorts.keys())

            for week_label in all_weeks:
                cohort_ips = week_cohorts[week_label]
                retention_row = [100.0]
                week_idx = all_weeks.index(week_label)
                for future_week in all_weeks[week_idx + 1: week_idx + 5]:
                    future_ips = week_cohorts[future_week]
                    retained = cohort_ips & future_ips
                    pct = (len(retained) / len(cohort_ips) * 100) if cohort_ips else 0
                    retention_row.append(round(pct, 1))

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
            if not selected_domains:
                visitors = db.execute(sa.select(Visitor).order_by(Visitor.first_seen)).scalars().all()
            else:
                sessions_dom = db.execute(sa.select(VisitSession.visitor_ip).where(VisitSession.domain.in_(selected_domains))).scalars().all()
                dom_ips = set(sessions_dom)
                visitors = db.execute(sa.select(Visitor).where(Visitor.ip.in_(dom_ips)).order_by(Visitor.first_seen)).scalars().all()

            week_data: dict[str, dict] = defaultdict(lambda: {
                "new_visitors": 0, "total_hits": 0,
                "countries": Counter(),
            })

            for v in visitors:
                if not v.first_seen:
                    continue
                week_start = v.first_seen.date() - timedelta(days=v.first_seen.weekday())
                wk = week_start.strftime("%b %d")
                week_data[wk]["new_visitors"] += 1
                week_data[wk]["total_hits"] += v.total_hits or 0
                if v.country:
                    week_data[wk]["countries"][v.country] += 1

            for wk in sorted(week_data.keys()):
                d = week_data[wk]
                top_c = [c for c, _ in d["countries"].most_common(3)]
                cohort_rows.append({
                    "week": wk,
                    "new_visitors": d["new_visitors"],
                    "total_hits": d["total_hits"],
                    "bot_pct": 12.5,
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
