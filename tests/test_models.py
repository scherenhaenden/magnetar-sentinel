"""Tests for magnetar.db — engine factory and deduplication"""
import tempfile
import pytest
import sqlalchemy as sa

from magnetar.db import get_engine, init_db, get_db_session, get_db_info
from magnetar.models import Hit, SyncConfig, Visitor
from datetime import datetime, timezone


@pytest.fixture
def sqlite_engine(tmp_path):
    url = f"sqlite:///{tmp_path}/test.db"
    engine = get_engine(url)
    init_db(engine)
    return engine


def test_sqlite_engine_created(sqlite_engine):
    assert sqlite_engine is not None
    assert "sqlite" in str(sqlite_engine.url)


def test_all_tables_created(sqlite_engine):
    insp = sa.inspect(sqlite_engine)
    tables = insp.get_table_names()
    for expected in ["hits", "sessions", "visitors", "events", "journey_steps",
                     "funnel_defs", "funnel_steps", "sync_config", "daily_summaries"]:
        assert expected in tables, f"Table '{expected}' not found"


def test_hit_deduplication(sqlite_engine):
    """Inserting same hit twice should not raise and should result in 1 row."""
    dt = datetime(2026, 8, 31, 10, 0, 0)
    h1 = Hit(ip="1.2.3.4", occurred_at=dt, method="GET",
             path="/article/test", status=200, bytes_sent=500,
             referer="-", user_agent="Mozilla/5.0", is_bot=False)
    h2 = Hit(ip="1.2.3.4", occurred_at=dt, method="GET",
             path="/article/test", status=200, bytes_sent=500,
             referer="-", user_agent="Mozilla/5.0", is_bot=False)

    with get_db_session() as db:
        db.add(h1)
        db.commit()

    # Second insert should be ignored (dedup)
    try:
        with get_db_session() as db:
            db.add(h2)
            db.commit()
    except Exception:
        pass  # Expected if DB raises integrity error

    with get_db_session() as db:
        count = db.execute(
            sa.select(sa.func.count(Hit.id)).where(Hit.ip == "1.2.3.4")
        ).scalar()
    assert count == 1, f"Expected 1 hit, got {count}"


def test_sync_config_upsert(sqlite_engine):
    with get_db_session() as db:
        db.add(SyncConfig(key="interval_seconds", value="300"))
        db.commit()

    with get_db_session() as db:
        cfg = db.get(SyncConfig, "interval_seconds")
        assert cfg.value == "300"


def test_db_info(sqlite_engine):
    info = get_db_info(sqlite_engine)
    assert "dialect" in info
    assert info["dialect"] == "sqlite"
    assert "password" not in info.get("url_display", "")
