"""
magnetar.context_processors
---------------------------
Context processors and domain filtering helpers.
"""

from __future__ import annotations

from datetime import datetime
import sqlalchemy as sa
from flask import request

from magnetar.db import get_db_session
from magnetar.models import Hit, SyncConfig
from magnetar.sync import get_last_sync_info


def parse_domain_filter(raw: str | None) -> list[str]:
    """Parse comma-separated or 'all' domain query parameter."""
    if not raw or raw.strip().lower() in ("all", "*", ""):
        return []
    parts = [d.strip() for d in raw.split(",") if d.strip()]
    return [p for p in parts if p.lower() != "all"]


def get_sync_info() -> dict:
    try:
        with get_db_session() as db:
            return get_last_sync_info(db)
    except Exception:
        return {"last_sync_at": "Never", "interval_seconds": 300, "status": "unknown"}


def get_domain_stats(since: datetime, selected_domains: list[str]) -> list[dict]:
    with get_db_session() as db:
        rows = db.execute(
            sa.select(Hit.domain, sa.func.count(Hit.id))
            .where(Hit.occurred_at >= since)
            .group_by(Hit.domain)
        ).all()
        total_hits = sum(r[1] for r in rows) or 1
        stats = []
        for dom, count in rows:
            if not dom:
                continue
            pct = round((count / total_hits * 100), 1)
            is_sel = (len(selected_domains) == 0) or (dom in selected_domains)
            stats.append({
                "domain": dom,
                "hits": count,
                "pct": pct,
                "selected": is_sel,
            })
        return sorted(stats, key=lambda x: x["hits"], reverse=True)


def domain_context_processor():
    raw_dom = request.args.get("domain", "all")
    selected_list = parse_domain_filter(raw_dom)
    domains_list = []
    try:
        with get_db_session() as db:
            # Dynamically pull all domains that have actual traffic registered in the logs
            rows = db.execute(
                sa.select(Hit.domain, sa.func.count(Hit.id))
                .where(Hit.domain.is_not(None), Hit.domain != "", Hit.domain != "custom")
                .group_by(Hit.domain)
                .order_by(sa.func.count(Hit.id).desc())
            ).all()
            if rows:
                domains_list = [r[0] for r in rows if r[0]]
    except Exception:
        pass

    if not domains_list:
        domains_list = ["example.com", "blog.example.com", "api.example.com"]

    return {
        "raw_domain_param": raw_dom,
        "selected_domains": selected_list,
        "is_all_domains": len(selected_list) == 0,
        "available_domains": domains_list,
    }
