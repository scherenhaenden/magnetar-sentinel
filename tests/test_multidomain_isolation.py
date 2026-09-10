"""
Tests for multi-domain data isolation, days filtering, and cohort retention.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import pytest
import sqlalchemy as sa

from app import app
from magnetar.config import DASH_PASS, DASH_USER
from magnetar.db import get_db_session
from magnetar.models import Hit, Session as VisitSession, Visitor


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _auth_headers():
    token = base64.b64encode(f"{DASH_USER}:{DASH_PASS}".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


TEST_IPS = ["198.51.100.10", "198.51.100.20", "198.51.100.30"]


@pytest.fixture(autouse=True)
def setup_isolation_data():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with get_db_session() as db:
        # Clean up any leftover test data
        db.execute(sa.delete(Hit).where(Hit.ip.in_(TEST_IPS)))
        db.execute(sa.delete(VisitSession).where(VisitSession.visitor_ip.in_(TEST_IPS)))
        db.execute(sa.delete(Visitor).where(Visitor.ip.in_(TEST_IPS)))
        db.commit()

        # Visitor 1: 198.51.100.10 visits siteA.com 2 days ago, and siteB.com 1 hour ago
        v1 = Visitor(
            ip="198.51.100.10",
            first_seen=now - timedelta(days=2),
            last_seen=now - timedelta(hours=1),
            total_sessions=3,
            total_hits=5,
            country="Spain",
            country_code="ES",
        )
        db.add(v1)

        # Hits on siteA.com
        h1_a = Hit(
            domain="siteA.com",
            ip="198.51.100.10",
            occurred_at=now - timedelta(days=2),
            method="GET",
            path="/articulos/rock-nacional",
            status=200,
            bytes_sent=1500,
            referer="https://google.com/",
            user_agent="TestBrowser/1.0",
            is_bot=False,
        )
        h2_a = Hit(
            domain="siteA.com",
            ip="198.51.100.10",
            occurred_at=now - timedelta(days=1),
            method="GET",
            path="/articulos/entrevista-guitarrista",
            status=200,
            bytes_sent=2500,
            referer="https://siteA.com/articulos/rock-nacional",
            user_agent="TestBrowser/1.0",
            is_bot=False,
        )
        sess_a = VisitSession(
            domain="siteA.com",
            visitor_ip="198.51.100.10",
            started_at=now - timedelta(days=2),
            ended_at=now - timedelta(days=1),
            hit_count=2,
            entry_path="/articulos/rock-nacional",
            exit_path="/articulos/entrevista-guitarrista",
            country="Spain",
            country_code="ES",
        )

        # Hits on siteB.com (more recent, different paths)
        h1_b = Hit(
            domain="siteB.com",
            ip="198.51.100.10",
            occurred_at=now - timedelta(hours=2),
            method="GET",
            path="/panel/dashboard",
            status=200,
            bytes_sent=5000,
            referer="-",
            user_agent="TestBrowser/1.0",
            is_bot=False,
        )
        h2_b = Hit(
            domain="siteB.com",
            ip="198.51.100.10",
            occurred_at=now - timedelta(hours=1),
            method="GET",
            path="/panel/settings",
            status=200,
            bytes_sent=3200,
            referer="https://siteB.com/panel/dashboard",
            user_agent="TestBrowser/1.0",
            is_bot=False,
        )
        sess_b = VisitSession(
            domain="siteB.com",
            visitor_ip="198.51.100.10",
            started_at=now - timedelta(hours=2),
            ended_at=now - timedelta(hours=1),
            hit_count=2,
            entry_path="/panel/dashboard",
            exit_path="/panel/settings",
            country="Spain",
            country_code="ES",
        )

        # Visitor 2: 198.51.100.20 visited siteA.com 40 days ago (outside 30-day window)
        v2 = Visitor(
            ip="198.51.100.20",
            first_seen=now - timedelta(days=40),
            last_seen=now - timedelta(days=40),
            total_sessions=1,
            total_hits=1,
            country="Chile",
            country_code="CL",
        )
        h_old = Hit(
            domain="siteA.com",
            ip="198.51.100.20",
            occurred_at=now - timedelta(days=40),
            method="GET",
            path="/archivo/historico",
            status=200,
            bytes_sent=1000,
            referer="-",
            user_agent="TestBrowser/1.0",
            is_bot=False,
        )
        sess_old = VisitSession(
            domain="siteA.com",
            visitor_ip="198.51.100.20",
            started_at=now - timedelta(days=40),
            ended_at=now - timedelta(days=40),
            hit_count=1,
            entry_path="/archivo/historico",
            exit_path="/archivo/historico",
            country="Chile",
            country_code="CL",
        )

        db.add_all([h1_a, h2_a, sess_a, h1_b, h2_b, sess_b, v2, h_old, sess_old])
        db.commit()

    yield

    with get_db_session() as db:
        db.execute(sa.delete(Hit).where(Hit.ip.in_(TEST_IPS)))
        db.execute(sa.delete(VisitSession).where(VisitSession.visitor_ip.in_(TEST_IPS)))
        db.execute(sa.delete(Visitor).where(Visitor.ip.in_(TEST_IPS)))
        db.commit()


def test_visitors_domain_isolation(client):
    """When viewing /visitors?domain=siteA.com, siteB paths and hit counts must NOT leak."""
    headers = _auth_headers()
    res = client.get("/visitors?domain=siteA.com&days=7", headers=headers)
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # 198.51.100.10 must be listed under siteA
    assert "198.51.100.10" in html

    # Last resource for siteA must be /articulos/entrevista-guitarrista, NOT /panel/settings!
    assert "/articulos/entrevista-guitarrista" in html
    assert "/panel/settings" not in html
    assert "/panel/dashboard" not in html


def test_visitors_days_filtering(client):
    """When filtering by days=7, visits from 40 days ago must not appear."""
    headers = _auth_headers()

    # Query with 7 days: 198.51.100.20 (40 days ago) should be absent
    res7 = client.get("/visitors?domain=siteA.com&days=7", headers=headers)
    assert res7.status_code == 200
    html7 = res7.get_data(as_text=True)
    assert "198.51.100.20" not in html7

    # Query with 60 days: 198.51.100.20 should appear
    res60 = client.get("/visitors?domain=siteA.com&days=60", headers=headers)
    assert res60.status_code == 200
    html60 = res60.get_data(as_text=True)
    assert "198.51.100.20" in html60


def test_visitor_detail_domain_isolation(client):
    """Visitor profile drilldown must isolate hits when domain filter is active."""
    headers = _auth_headers()
    res = client.get("/visitors/198.51.100.10?domain=siteA.com", headers=headers)
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Must contain siteA paths
    assert "/articulos/rock-nacional" in html
    assert "/articulos/entrevista-guitarrista" in html

    # Must NOT contain siteB paths in the hit list
    assert "/panel/settings" not in html
    assert "/panel/dashboard" not in html


def test_retention_calculation_tracks_returning_visitors(client):
    """Retention must measure activity across weeks, not empty set intersections."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    retention_ip = "198.51.100.30"
    headers = _auth_headers()

    with get_db_session() as db:
        # User first seen 14 days ago (week 1)
        v = Visitor(
            ip=retention_ip,
            first_seen=now - timedelta(days=14),
            last_seen=now - timedelta(days=2),
            total_sessions=2,
            total_hits=4,
            country="Spain",
            country_code="ES",
        )
        db.add(v)

        # Session in week 1
        s1 = VisitSession(
            domain="siteA.com",
            visitor_ip=retention_ip,
            started_at=now - timedelta(days=14),
            ended_at=now - timedelta(days=14),
            hit_count=2,
        )
        # Session in week 2 (returning visit!)
        s2 = VisitSession(
            domain="siteA.com",
            visitor_ip=retention_ip,
            started_at=now - timedelta(days=7),
            ended_at=now - timedelta(days=7),
            hit_count=2,
        )
        db.add_all([s1, s2])
        db.commit()

    res = client.get("/retention?domain=siteA.com", headers=headers)
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Should not produce all dashes or 0.0% for retention when user returned in week 2
    assert "100.0%" in html
    # A retention cell with > 0% should be rendered in the table
    assert "%" in html

