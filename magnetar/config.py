"""
magnetar.config
---------------
Application configuration and environment variables.

To keep credentials secure in production:
1. Set environment variables via systemd (EnvironmentFile=/etc/magnetar/magnetar.env)
2. OR create /etc/magnetar/magnetar.env (with `chmod 600`)
3. OR specify MS_CONFIG_FILE=/path/to/secure/config.env
DO NOT store credentials in the public repository or web root.
"""

from __future__ import annotations

import os


def _load_external_env() -> None:
    """Load configuration from a secure file outside the web root if present."""
    custom_path = os.getenv("MS_CONFIG_FILE")
    candidate_paths = [custom_path] if custom_path else []
    candidate_paths.extend([
        "/etc/magnetar/magnetar.env",
        os.path.expanduser("~/.config/magnetar/magnetar.env"),
    ])

    for path in candidate_paths:
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
                break
            except Exception:
                pass


_load_external_env()

SSH_HOST     = os.getenv("MS_SSH_HOST", "127.0.0.1")
SSH_USER     = os.getenv("MS_SSH_USER", "admin")
SSH_KEY      = os.path.expanduser(os.getenv("MS_SSH_KEY", "~/.ssh/id_rsa"))
GEOIP_DB     = os.getenv("MS_GEOIP_DB", "/usr/share/GeoIP/GeoLite2-City.mmdb")
DAYS         = int(os.getenv("MS_DAYS", "7"))
DASH_USER    = os.getenv("MS_DASHBOARD_USER", "admin")
DASH_PASS    = os.getenv("MS_DASHBOARD_PASS", "ChangeMeImmediately!")
PORT         = int(os.getenv("MS_PORT", "5050"))
LOG_DIR      = os.getenv("MS_LOG_DIR", "/var/log/nginx")
DATABASE_URL = os.getenv("MS_DATABASE_URL", "sqlite:///magnetar.db")

GEOIP_PATH   = GEOIP_DB if os.path.exists(GEOIP_DB) else None
