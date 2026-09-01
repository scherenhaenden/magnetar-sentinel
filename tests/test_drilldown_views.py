"""Tests for visitor profile drilldown and route breakdown views."""
import base64
from datetime import datetime, timezone
import pytest
import sqlalchemy as sa
from app import app
from magnetar.config import DASH_PASS, DASH_USER
from magnetar.db import get_db_session
from magnetar.models import Hit, Visitor


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _auth_headers():
    token = base64.b64encode(f"{DASH_USER}:{DASH_PASS}".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(scope="module", autouse=True)
def seed_sample_data():
    with get_db_session() as db:
        # Clean up test records first
        db.execute(sa.delete(Hit).where(Hit.ip == "4.204.224.164"))
        db.execute(sa.delete(Visitor).where(Visitor.ip == "4.204.224.164"))
        db.commit()

        v = Visitor(
            ip="4.204.224.164",
            country="Canada",
            country_code="CA",
            city="Toronto",
            first_seen=datetime(2026, 9, 1, 4, 47, 0),
            last_seen=datetime(2026, 9, 1, 5, 28, 0),
            total_sessions=3,
            total_hits=2,
        )
        db.add(v)

        h1 = Hit(
            domain="example.com",
            ip="4.204.224.164",
            occurred_at=datetime(2026, 9, 1, 4, 47, 12),
            method="GET",
            path="/myshell.php",
            status=200,
            bytes_sent=1200,
            referer="-",
            user_agent="Mozilla/5.0 (Windows NT 10.0)",
            is_bot=False,
        )
        h2 = Hit(
            domain="example.com",
            ip="4.204.224.164",
            occurred_at=datetime(2026, 9, 1, 5, 28, 30),
            method="POST",
            path="/myshell.php",
            status=404,
            bytes_sent=280,
            referer="-",
            user_agent="Mozilla/5.0 (Windows NT 10.0)",
            is_bot=False,
        )
        db.add(h1)
        db.add(h2)
        db.commit()

    yield

    with get_db_session() as db:
        db.execute(sa.delete(Hit).where(Hit.ip == "4.204.224.164"))
        db.execute(sa.delete(Visitor).where(Visitor.ip == "4.204.224.164"))
        db.commit()


def test_visitor_detail_unauthenticated(client):
    res = client.get("/visitors/4.204.224.164")
    assert res.status_code == 401


def test_visitor_detail_authenticated(client):
    headers = _auth_headers()
    res = client.get("/visitors/4.204.224.164", headers=headers)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "4.204.224.164" in html
    assert "Canada" in html
    assert "/myshell.php" in html
    assert "timeline-canvas" in html
    assert "Bloquear IP en Firewall" in html or "Desbanear" in html


def test_page_detail_unauthenticated(client):
    res = client.get("/pages/detail?path=/myshell.php")
    assert res.status_code == 401


def test_page_detail_missing_path(client):
    headers = _auth_headers()
    res = client.get("/pages/detail", headers=headers)
    assert res.status_code == 400


def test_page_detail_authenticated(client):
    headers = _auth_headers()
    res = client.get("/pages/detail?path=/myshell.php", headers=headers)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "/myshell.php" in html
    assert "4.204.224.164" in html
    assert "Canada" in html
    assert "Visitantes Desglosados" in html


def test_visitors_page_contains_detail_links(client):
    headers = _auth_headers()
    res = client.get("/visitors", headers=headers)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "/visitors/4.204.224.164" in html
    assert "/pages/detail?path=" in html


def test_pages_page_contains_detail_links(client):
    headers = _auth_headers()
    res = client.get("/pages", headers=headers)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "/pages/detail?path=" in html


def test_pagination_and_sorting_components_rendered(client):
    headers = _auth_headers()
    # Check visitors view has paginator and sorting engine
    res = client.get("/visitors", headers=headers)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "TablePaginator" in html
    assert "makeTableSortable" in html
    assert "visitors-pagination-container" in html

    # Check visitor detail view has paginator and sorting
    res2 = client.get("/visitors/4.204.224.164", headers=headers)
    assert res2.status_code == 200
    html2 = res2.get_data(as_text=True)
    assert "hits-pagination-container" in html2

    # Check pages view has paginator and sorting
    res3 = client.get("/pages", headers=headers)
    assert res3.status_code == 200
    html3 = res3.get_data(as_text=True)
    assert "pages-pagination-container" in html3
