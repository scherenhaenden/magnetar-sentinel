"""Tests for magnetar.log_parser"""
import pytest
from magnetar.log_parser import Hit

VALID_LINE = (
    '114.119.128.40 - - [30/Aug/2026:17:41:28 +0200] '
    '"GET /blog/getting-started HTTP/2.0" 200 776 '
    '"-" "Mozilla/5.0 PetalBot" "-"'
)
INTERNAL_LINE = (
    '127.0.0.1 - - [30/Aug/2026:17:41:22 +0200] '
    '"GET / HTTP/2.0" 200 1628 "-" "curl/8.14.1" "-"'
)
ATTACK_LINE = (
    '1.2.3.4 - - [30/Aug/2026:17:41:28 +0200] '
    '"GET /wp-admin/admin.php HTTP/1.1" 404 0 "-" "scanner/1.0" "-"'
)


def test_valid_line_parsed():
    h = Hit.from_line(VALID_LINE)
    assert h is not None
    assert h.ip == "114.119.128.40"
    assert h.path == "/blog/getting-started"
    assert h.status == 200
    assert h.is_bot is True  # PetalBot
    assert h.is_page is True


def test_internal_ip_filtered():
    assert Hit.from_line(INTERNAL_LINE) is None


def test_asset_not_page():
    css_line = (
        '5.6.7.8 - - [30/Aug/2026:17:41:28 +0200] '
        '"GET /styles-ABC.css HTTP/2.0" 200 100 "-" "Mozilla/5.0" "-"'
    )
    h = Hit.from_line(css_line)
    assert h is not None
    assert h.is_page is False


def test_human_detection():
    human_line = (
        '85.50.46.161 - - [30/Aug/2026:17:41:28 +0200] '
        '"GET /blog/overview HTTP/2.0" 200 776 '
        '"-" "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120" "-"'
    )
    h = Hit.from_line(human_line)
    assert h is not None
    assert h.is_bot is False


def test_malformed_line_returns_none():
    assert Hit.from_line("this is not a log line") is None
    assert Hit.from_line("") is None
