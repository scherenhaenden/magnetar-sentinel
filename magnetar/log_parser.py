"""
magnetar.log_parser
-------------------
Reads Nginx access logs from the remote server via SSH and returns
structured Hit records ready for aggregation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, Sequence

import paramiko

# Nginx `main` log format:
# $remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent" "$http_x_forwarded_for"
_LOG_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<dt>[^\]]+)\] '
    r'"(?P<req>[^"]*)" (?P<status>\d+) (?P<bytes>\d+) '
    r'"(?P<referer>[^"]*)" "(?P<ua>[^"]*)"'
)

_DT_FMT = "%d/%b/%Y:%H:%M:%S %z"

BOT_KEYWORDS = {
    "bot", "crawl", "spider", "slurp", "petalbot", "bingbot", "googlebot",
    "yandex", "duckduck", "mj12", "semrush", "ahrefs", "bytespider",
    "gptbot", "claude", "curl", "python-requests", "libwww", "scanner",
    "facebookexternalhit", "applebot", "letsencrypt", "lets encrypt",
    "leakix", "l9scan", "censys", "shodan", "databot", "forestengine",
}

INTERNAL_IPS = {"127.0.0.1", "172.19.0.2", "10.0.0.1"}


@dataclass
class Hit:
    ip: str
    dt: datetime
    method: str
    path: str
    status: int
    bytes_sent: int
    referer: str
    user_agent: str
    is_bot: bool = field(default=False, compare=False)

    @property
    def is_page(self) -> bool:
        """True for HTML page requests (not assets / API)."""
        p = self.path.lower()
        skip = (
            p.startswith("/api")
            or p.startswith("/static")
            or p.startswith("/.well-known")
            or any(p.endswith(ext) for ext in (
                ".css", ".js", ".png", ".jpg", ".jpeg", ".gif",
                ".svg", ".ico", ".woff", ".woff2", ".ttf", ".map",
                ".webp", ".mp4", ".gz", ".zip",
            ))
        )
        return not skip

    @classmethod
    def from_line(cls, line: str) -> "Hit | None":
        m = _LOG_RE.match(line)
        if not m:
            return None
        ip = m.group("ip")
        if ip in INTERNAL_IPS:
            return None
        try:
            dt = datetime.strptime(m.group("dt"), _DT_FMT)
        except ValueError:
            return None

        req = m.group("req")
        parts = req.split()
        method = parts[0] if len(parts) >= 1 else "?"
        path = parts[1] if len(parts) >= 2 else "/"

        ua = m.group("ua")
        ua_lower = ua.lower()
        is_bot = any(k in ua_lower for k in BOT_KEYWORDS)

        return cls(
            ip=ip,
            dt=dt,
            method=method,
            path=path,
            status=int(m.group("status")),
            bytes_sent=int(m.group("bytes")),
            referer=m.group("referer"),
            user_agent=ua,
            is_bot=is_bot,
        )


def _fetch_logs_via_ssh(
    host: str,
    user: str,
    key_path: str,
    log_paths: Sequence[str],
) -> Iterator[str]:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, key_filename=key_path)
    try:
        files = " ".join(f'"{p}"' for p in log_paths)
        _, stdout, _ = client.exec_command(f"cat {files} 2>/dev/null")
        for line in stdout:
            yield line.rstrip("\n")
    finally:
        client.close()


def parse_logs(
    host: str,
    user: str,
    key_path: str,
    log_paths: Sequence[str],
) -> list[Hit]:
    hits: list[Hit] = []
    for raw in _fetch_logs_via_ssh(host, user, key_path, log_paths):
        hit = Hit.from_line(raw)
        if hit:
            hits.append(hit)
    return hits
