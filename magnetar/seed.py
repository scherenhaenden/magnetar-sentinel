"""
magnetar.seed
-------------
Generates rich, realistic synthetic data for Magnetar Sentinel across multiple demo domains:
  - example.com
  - docs.example.com
  - shop.example.com
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from magnetar.db import get_db_session, get_engine, init_db
from magnetar.models import (
    DailySummary, Event, FunnelDef, FunnelStep, Hit, JourneyStep,
    Session as VisitSession, SyncConfig, Visitor,
)

DOMAINS_CONFIG = {
    "example.com": {
        "articles": [
            "/blog/getting-started-with-python-2026",
            "/blog/high-performance-sqlite-wal-mode",
            "/blog/modern-web-development-architecture",
            "/blog/docker-compose-production-hardening",
            "/blog/distributed-systems-design-patterns",
            "/blog/nginx-real-time-log-monitoring-guide",
            "/blog/fail2ban-automated-intrusion-defense",
            "/blog/building-fast-lightweight-dashboards",
        ],
        "home": "/",
        "weight": 0.60,
    },
    "docs.example.com": {
        "articles": [
            "/docs/api/v1/authentication",
            "/docs/api/v1/endpoints-overview",
            "/docs/deployment/systemd-service",
            "/docs/security/best-practices",
            "/docs/configuration/environment-variables",
        ],
        "home": "/docs",
        "weight": 0.25,
    },
    "shop.example.com": {
        "articles": [
            "/products/pro-developer-laptop",
            "/products/mechanical-keyboard-rgb",
            "/products/wireless-noise-cancelling-headphones",
        ],
        "home": "/",
        "weight": 0.15,
    },
}

COUNTRIES = [
    ("Spain", "ES", "Madrid", 0.22),
    ("Spain", "ES", "Barcelona", 0.15),
    ("Colombia", "CO", "Bogotá", 0.14),
    ("Colombia", "CO", "Medellín", 0.08),
    ("Chile", "CL", "Santiago", 0.09),
    ("Mexico", "MX", "Ciudad de México", 0.09),
    ("Argentina", "AR", "Buenos Aires", 0.06),
    ("Peru", "PE", "Lima", 0.04),
    ("United States", "US", "New York", 0.04),
    ("Germany", "DE", "Munich", 0.03),
    ("France", "FR", "Paris", 0.02),
    ("United Kingdom", "GB", "London", 0.02),
    ("Netherlands", "NL", "Amsterdam", 0.01),
    ("Canada", "CA", "Toronto", 0.01),
]

REFERRERS = [
    ("https://www.google.com/", 0.20),
    ("https://www.bing.com/", 0.08),
    ("https://www.bing.com/search?q=high+performance+sqlite+wal+mode", 0.08),
    ("https://www.bing.com/search?q=docker+compose+production+hardening", 0.06),
    ("https://duckduckgo.com/?q=nginx+real+time+log+monitoring", 0.07),
    ("https://duckduckgo.com/?q=fail2ban+firewall+integration", 0.05),
    ("https://www.google.com/search?q=modern+python+dashboards", 0.06),
    ("https://reddit.com/r/python/comments/high_performance_wal_mode", 0.07),
    ("https://reddit.com/r/devops/comments/nginx_log_parsing", 0.05),
    ("https://news.ycombinator.com/item?id=39820145", 0.04),
    ("https://t.co/dev2026?utm_source=twitter&utm_medium=social&utm_campaign=tech_preview", 0.08),
    ("https://github.com/topics/analytics-dashboard", 0.08),
    ("-", 0.08),
]

HUMAN_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
]

BOT_UAS = [
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "Mozilla/5.0 (compatible; PetalBot;+https://webmaster.petalsearch.com/site/petalbot)",
    "Mozilla/5.0 (compatible; Applebot/0.1; +http://www.apple.com/go/applebot)",
    "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)",
]


def weighted_choice(items):
    choices, weights = zip(*items)
    return random.choices(choices, weights=weights, k=1)[0]


def seed_all(num_visitors=240, clear_existing=True):
    import os
    db_url = os.getenv("MS_DATABASE_URL", "sqlite:///magnetar.db")
    engine = get_engine(db_url)
    init_db(engine)

    now = datetime.now(timezone.utc)
    random.seed(42)

    with get_db_session() as db:
        if clear_existing:
            db.execute(sa.delete(Event))
            db.execute(sa.delete(JourneyStep))
            db.execute(sa.delete(FunnelStep))
            db.execute(sa.delete(FunnelDef))
            db.execute(sa.delete(VisitSession))
            db.execute(sa.delete(Hit))
            db.execute(sa.delete(Visitor))
            db.execute(sa.delete(DailySummary))
            db.execute(sa.delete(SyncConfig))
            db.commit()

        # 1. Create Default Funnels
        funnel1 = FunnelDef(domain="example.com", name="Blog Readers Journey", created_at=now - timedelta(days=20))
        db.add(funnel1)
        db.flush()
        db.add(FunnelStep(funnel_id=funnel1.id, step_index=0, name="Home", path_pattern=r"^/$|/home"))
        db.add(FunnelStep(funnel_id=funnel1.id, step_index=1, name="Main Article", path_pattern=r"/blog/"))
        db.add(FunnelStep(funnel_id=funnel1.id, step_index=2, name="Next Article", path_pattern=r"/blog/"))

        funnel2 = FunnelDef(domain="docs.example.com", name="Documentation Flow", created_at=now - timedelta(days=15))
        db.add(funnel2)
        db.flush()
        db.add(FunnelStep(funnel_id=funnel2.id, step_index=0, name="Docs Home", path_pattern=r"^/docs"))
        db.add(FunnelStep(funnel_id=funnel2.id, step_index=1, name="API Guide", path_pattern=r"/docs/api/"))

        # 2. Generate Visitors across Domains
        domain_choices = [
            ("example.com", DOMAINS_CONFIG["example.com"]["weight"]),
            ("docs.example.com", DOMAINS_CONFIG["docs.example.com"]["weight"]),
            ("shop.example.com", DOMAINS_CONFIG["shop.example.com"]["weight"]),
        ]

        for v_idx in range(1, num_visitors + 1):
            domain = weighted_choice(domain_choices)
            cfg = DOMAINS_CONFIG[domain]
            articles = cfg["articles"]
            home_path = cfg["home"]

            is_bot = random.random() < 0.14
            country_item = weighted_choice([(c[:3], c[3]) for c in COUNTRIES])
            country, country_code, city = country_item

            week_offset = random.choices([0, 1, 2, 3, 4], weights=[0.30, 0.25, 0.20, 0.15, 0.10])[0]
            days_ago = week_offset * 7 + random.randint(0, 6)
            first_seen = now - timedelta(days=days_ago, hours=random.randint(0, 23), minutes=random.randint(0, 59))

            ip = f"{random.randint(31, 210)}.{random.randint(10, 240)}.{random.randint(1, 250)}.{random.randint(1, 250)}"
            ua = random.choice(BOT_UAS) if is_bot else random.choice(HUMAN_UAS)

            num_sessions = 1
            if not is_bot:
                r_val = random.random()
                if week_offset >= 3 and r_val < 0.35:
                    num_sessions = random.randint(3, 6)
                elif week_offset >= 1 and r_val < 0.50:
                    num_sessions = random.randint(2, 4)

            visitor = db.get(Visitor, ip)
            if not visitor:
                visitor = Visitor(
                    ip=ip,
                    first_seen=first_seen,
                    last_seen=first_seen,
                    total_sessions=num_sessions,
                    total_hits=0,
                    country=country,
                    country_code=country_code,
                    city=city,
                )
                db.add(visitor)

            session_times = []
            for s_idx in range(num_sessions):
                if s_idx == 0:
                    s_time = first_seen
                else:
                    gap_days = random.randint(1, max(1, days_ago))
                    s_time = first_seen + timedelta(days=gap_days, hours=random.randint(0, 12))
                    if s_time > now:
                        s_time = now - timedelta(hours=random.randint(1, 10))
                session_times.append(s_time)

            session_times.sort()
            visitor.last_seen = session_times[-1]

            for s_time in session_times:
                if is_bot:
                    paths = [random.choice(articles)]
                else:
                    journey_type = random.choice(["home_first", "direct_article", "multi_article"])
                    if journey_type == "home_first":
                        paths = [home_path, random.choice(articles)]
                        if random.random() < 0.45:
                            paths.append(random.choice(articles))
                    elif journey_type == "direct_article":
                        paths = [random.choice(articles)]
                        if random.random() < 0.50:
                            paths.append(home_path)
                    else:
                        art1, art2 = random.sample(articles, min(2, len(articles)))
                        paths = [home_path, art1, art2]

                session = VisitSession(
                    domain=domain,
                    visitor_ip=ip,
                    started_at=s_time,
                    ended_at=s_time + timedelta(minutes=len(paths) * 2),
                    hit_count=len(paths),
                    entry_path=paths[0],
                    exit_path=paths[-1],
                    country=country,
                    country_code=country_code,
                )
                db.add(session)
                db.flush()

                ref = weighted_choice(REFERRERS)

                hit_dt = s_time
                for step_idx, path in enumerate(paths):
                    hit_dt += timedelta(seconds=random.randint(10, 120))
                    hit = Hit(
                        domain=domain,
                        ip=ip,
                        occurred_at=hit_dt,
                        method="GET",
                        path=path,
                        status=200,
                        bytes_sent=random.randint(1200, 45000),
                        referer=ref if step_idx == 0 else f"https://{domain}" + paths[step_idx - 1],
                        user_agent=ua,
                        is_bot=is_bot,
                    )
                    db.add(hit)
                    db.flush()

                    visitor.total_hits += 1

                    j_step = JourneyStep(
                        session_id=session.id,
                        step_index=step_idx,
                        path=path,
                        occurred_at=hit_dt,
                    )
                    db.add(j_step)

                    if is_bot:
                        ev_type = "bot_probe"
                    elif "article" in path or "posts" in path:
                        ev_type = "article_read"
                    elif "home" in path or path == "/":
                        ev_type = "home_visit"
                    elif any(s in ref for s in ["google", "bing", "duckduck"]):
                        ev_type = "search_referral"
                    else:
                        ev_type = "article_read"

                    event = Event(
                        domain=domain,
                        hit_id=hit.id,
                        event_type=ev_type,
                        path=path,
                        ip=ip,
                        occurred_at=hit_dt,
                    )
                    db.add(event)

            if random.random() < 0.20:
                probe_path = random.choice(["/wp-login.php", "/xmlrpc.php", "/.env", "/not-found-page", "/wp-admin"])
                probe_dt = first_seen + timedelta(minutes=random.randint(5, 40))
                p_hit = Hit(
                    domain=domain,
                    ip=ip,
                    occurred_at=probe_dt,
                    method="GET",
                    path=probe_path,
                    status=404,
                    bytes_sent=280,
                    referer="-",
                    user_agent=ua,
                    is_bot=True,
                )
                db.add(p_hit)
                db.flush()
                db.add(Event(
                    domain=domain,
                    hit_id=p_hit.id,
                    event_type="attack_probe" if "wp-" in probe_path or ".env" in probe_path else "404_error",
                    path=probe_path,
                    ip=ip,
                    occurred_at=probe_dt,
                ))

        # 3. Add Sync History & Config
        db.add(SyncConfig(key="interval_seconds", value="300"))
        db.add(SyncConfig(key="last_sync_at", value=now.strftime("%Y-%m-%d %H:%M:%S")))
        db.add(SyncConfig(key="last_sync_status", value="ok"))
        for h_i in range(1, 6):
            h_time = (now - timedelta(minutes=h_i * 5)).strftime("%H:%M:%S")
            hist_val = json.dumps({
                "time": h_time,
                "hits": random.randint(80, 320),
                "sessions": random.randint(15, 60),
                "events": random.randint(70, 290),
                "duration_ms": random.randint(120, 480),
            })
            db.add(SyncConfig(key=f"sync_history_{6 - h_i}", value=hist_val))

        db.commit()
        print(f"✅ Seeding complete! Generated {num_visitors} visitors across domains ({', '.join(DOMAINS_CONFIG.keys())}).")


if __name__ == "__main__":
    seed_all(num_visitors=240)
