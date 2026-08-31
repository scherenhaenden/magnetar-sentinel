"""
magnetar.sync
-------------
Incremental log synchronization engine supporting both local filesystem and remote SSH reading.
Automatically ingests logs for configured domains on the server:
  - example.com
  - blog.example.com
  - api.example.com
"""

from __future__ import annotations

import glob
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import paramiko
import sqlalchemy as sa
from sqlalchemy import select

from .models import Event, Hit, JourneyStep, Session as VisitSession, SyncConfig, Visitor

# Mapping of log paths to domains (customizable via config / settings)
DEFAULT_SITE_LOGS = {
    "example.com": "/var/log/nginx/example.com",
    "blog.example.com": "/var/log/nginx/blog",
    "api.example.com": "/var/log/nginx/api",
}

INTERNAL_IPS = {"127.0.0.1", "::1", "172.19.0.2", "10.0.0.1"}

LOG_LINE_RE = re.compile(
    r'^(?P<ip>[0-9a-fA-F\.:]+)\s+-\s+\S+\s+\[(?P<time>[^\]]+)\]\s+"(?P<method>[A-Z]+)\s+(?P<path>\S+)(?:\s+HTTP/[0-9\.]+)?\"\s+(?P<status>\d{3})\s+(?P<bytes>\d+)\s+"(?P<referer>[^"]*)"\s+"(?P<ua>[^"]*)"'
)

BOT_KEYWORDS = {
    "googlebot", "bingbot", "petalbot", "applebot", "yandexbot", "baiduspider",
    "ahrefsbot", "semrushbot", "dotbot", "mj12bot", "megaindex", "blexbot",
    "seekport", "bytespider", "gptbot", "claudebot", "turnitin", "crawler",
    "spider", "bot", "uptime-kuma", "curl", "wget", "python-requests",
    "letsencrypt", "lets encrypt", "leakix", "l9scan", "censys", "shodan",
    "databot", "forestengine",
}

_ARTICLE_PATTERN = re.compile(r'^/(?:article|post|news|blog)/', re.I)
_HOME_PATTERN = re.compile(r'^/?(?:home|index)?/?$', re.I)
_SEARCH_REFERRERS = {'google.com', 'bing.com', 'duckduckgo.com', 'yahoo.com', 'ecosia.org'}
_ATTACK_PATTERNS = re.compile(r'wp-admin|phpMyAdmin|\.env|\.git|etc/passwd|eval\(|base64|xmlrpc', re.I)


def parse_nginx_log_line(line: str, domain: str = "example.com") -> Optional[dict]:
    line = line.strip()
    if not line:
        return None
    m = LOG_LINE_RE.match(line)
    if not m:
        return None

    data = m.groupdict()
    ip = data["ip"]
    if ip in INTERNAL_IPS:
        return None

    try:
        # Format: 31/Aug/2026:17:41:28 +0200
        time_part = data["time"].split()[0]
        occurred_at = datetime.strptime(time_part, "%d/%b/%Y:%H:%M:%S")
    except Exception:
        return None

    ua = data.get("ua", "")
    ua_lower = ua.lower()
    is_bot = any(kw in ua_lower for kw in BOT_KEYWORDS)
    referer = data.get("referer", "-")
    if referer == "-":
        referer = None

    return {
        "domain": domain,
        "ip": ip,
        "occurred_at": occurred_at,
        "method": data["method"],
        "path": data["path"],
        "status": int(data["status"]),
        "bytes_sent": int(data["bytes"]),
        "referer": referer,
        "user_agent": ua if ua != "-" else None,
        "is_bot": is_bot,
    }


def infer_event_type(hit: Hit) -> Optional[str]:
    if hit.is_bot:
        return "bot_probe"
    if hit.status == 404:
        return "404_error"
    if hit.path and _ATTACK_PATTERNS.search(hit.path):
        return "attack_probe"
    if hit.status == 200:
        if hit.path and _ARTICLE_PATTERN.match(hit.path):
            return "article_read"
        if hit.path and _HOME_PATTERN.match(hit.path):
            return "home_visit"
    if hit.referer:
        try:
            d = urlparse(hit.referer).netloc.lower()
            if d.startswith("www."):
                d = d[4:]
            if d in _SEARCH_REFERRERS:
                return "search_referral"
        except Exception:
            pass
    return "article_read" if "article" in (hit.path or "") else None


def _get_geo_data(ip: str, reader) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not reader:
        return None, None, None
    try:
        resp = reader.country(ip)
        country_name = resp.country.name or "Unknown"
        country_code = resp.country.iso_code or "??"
        return country_name, country_code, None
    except Exception:
        return None, None, None


def get_last_sync_info(db_session) -> dict:
    last_sync = db_session.get(SyncConfig, "last_sync_at")
    status = db_session.get(SyncConfig, "last_sync_status")
    interval = db_session.get(SyncConfig, "interval_seconds")
    return {
        "last_sync_at": last_sync.value if last_sync else None,
        "status": status.value if status else "ok",
        "interval_seconds": int(interval.value) if interval else 300,
    }


def _read_lines_from_source(ssh_host: str, ssh_user: str, ssh_key: str, log_dir: str) -> list[str]:
    lines = []
    # If log directory exists locally on this machine, read directly from disk!
    if os.path.exists(log_dir):
        patterns = [f"{log_dir}/access.log", f"{log_dir}/access.log-*"]
        for pattern in patterns:
            for filepath in glob.glob(pattern):
                try:
                    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                        lines.extend(f.readlines())
                except Exception:
                    pass
        return lines

    # Otherwise read over SSH
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(ssh_host, username=ssh_user, key_filename=ssh_key, timeout=10)
        cmd = f"cat {log_dir}/access.log {log_dir}/access.log-* 2>/dev/null || true"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        lines = stdout.readlines()
        ssh.close()
    except Exception:
        pass
    return lines


def run_sync(
    ssh_host: str = "127.0.0.1",
    ssh_user: str = "admin",
    ssh_key: str = "~/.ssh/id_rsa",
    log_dir: str = "/var/log/nginx",
    db_session=None,
    geoip_db_path: Optional[str] = None,
    days: int = 7,
) -> Dict[str, Any]:
    start_time = time.time()
    stats = {"new_hits": 0, "new_sessions": 0, "new_events": 0, "duration_ms": 0}

    sync_info = get_last_sync_info(db_session)
    last_sync_str = sync_info.get("last_sync_at")
    last_sync_dt = datetime.strptime(last_sync_str, "%Y-%m-%d %H:%M:%S") if last_sync_str and last_sync_str != "Never" else datetime.min

    geoip_reader = None
    if geoip_db_path and os.path.exists(geoip_db_path):
        try:
            import geoip2.database
            geoip_reader = geoip2.database.Reader(geoip_db_path)
        except Exception:
            pass

    # Read existing hit signatures to prevent duplicate queries
    existing_hits_raw = db_session.execute(
        select(Hit.ip, Hit.occurred_at, Hit.method, Hit.path, Hit.domain)
    ).all()
    existing_hit_keys = set(existing_hits_raw)

    # Ingest across all known site log paths
    site_targets = dict(DEFAULT_SITE_LOGS)
    if log_dir not in site_targets.values():
        site_targets["custom"] = log_dir

    all_parsed_hits = []
    for domain, s_dir in site_targets.items():
        lines = _read_lines_from_source(ssh_host, ssh_user, ssh_key, s_dir)
        for line in lines:
            parsed = parse_nginx_log_line(line, domain=domain)
            if parsed and parsed["occurred_at"] > last_sync_dt:
                key = (parsed["ip"], parsed["occurred_at"], parsed["method"], parsed["path"], parsed["domain"])
                if key not in existing_hit_keys:
                    existing_hit_keys.add(key)
                    all_parsed_hits.append(parsed)

    all_parsed_hits.sort(key=lambda x: x["occurred_at"])

    for parsed in all_parsed_hits:
        try:
            with db_session.begin_nested():
                hit = Hit(**parsed)
                db_session.add(hit)
                db_session.flush()
        except Exception:
            continue
        stats["new_hits"] += 1

        # Sessions & Visitors
        country, country_code, city = _get_geo_data(hit.ip, geoip_reader)

        # Update Visitor
        visitor = db_session.get(Visitor, hit.ip)
        if not visitor:
            visitor = Visitor(
                ip=hit.ip,
                first_seen=hit.occurred_at,
                last_seen=hit.occurred_at,
                total_sessions=1,
                total_hits=1,
                country=country or "Unknown",
                country_code=country_code or "??",
                city=city or "",
            )
            db_session.add(visitor)
        else:
            visitor.last_seen = hit.occurred_at
            visitor.total_hits = (visitor.total_hits or 0) + 1

        # Check existing open session
        sess = db_session.execute(
            select(VisitSession)
            .where(VisitSession.visitor_ip == hit.ip, VisitSession.domain == hit.domain)
            .order_by(VisitSession.ended_at.desc())
            .limit(1)
        ).scalars().first()

        if not sess or (sess.ended_at and (hit.occurred_at - sess.ended_at) > timedelta(minutes=30)):
            sess = VisitSession(
                domain=hit.domain,
                visitor_ip=hit.ip,
                started_at=hit.occurred_at,
                ended_at=hit.occurred_at,
                hit_count=1,
                entry_path=hit.path,
                exit_path=hit.path,
                country=country,
                country_code=country_code,
            )
            db_session.add(sess)
            db_session.flush()
            stats["new_sessions"] += 1
            if visitor:
                visitor.total_sessions = (visitor.total_sessions or 0) + 1
        else:
            sess.ended_at = hit.occurred_at
            sess.hit_count = (sess.hit_count or 0) + 1
            sess.exit_path = hit.path

        # Journey Step
        step_idx = db_session.execute(
            select(sa.func.count(JourneyStep.id)).where(JourneyStep.session_id == sess.id)
        ).scalar() or 0

        j_step = JourneyStep(
            session_id=sess.id,
            step_index=step_idx,
            path=hit.path,
            occurred_at=hit.occurred_at,
        )
        db_session.add(j_step)

        # Event
        ev_type = infer_event_type(hit)
        if ev_type:
            event = Event(
                domain=hit.domain,
                hit_id=hit.id,
                event_type=ev_type,
                path=hit.path,
                ip=hit.ip,
                occurred_at=hit.occurred_at,
            )
            db_session.add(event)
            stats["new_events"] += 1

    # Record sync metadata
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    now_short = datetime.now(timezone.utc).strftime("%H:%M:%S")
    duration_ms = int((time.time() - start_time) * 1000)
    stats["duration_ms"] = duration_ms

    db_session.merge(SyncConfig(key="last_sync_at", value=now_str))
    db_session.merge(SyncConfig(key="last_sync_status", value="ok"))

    # Shift history
    hist_entry = json.dumps({
        "time": now_short,
        "hits": stats["new_hits"],
        "sessions": stats["new_sessions"],
        "events": stats["new_events"],
        "duration_ms": duration_ms,
    })
    db_session.merge(SyncConfig(key="sync_history_1", value=hist_entry))

    db_session.commit()
    return stats
