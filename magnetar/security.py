"""
magnetar.security
-----------------
Fail2ban firewall integration and active ban manager.
"""

from __future__ import annotations

import re
import subprocess
from typing import Optional


def _run_fail2ban_cmd(args: list[str]) -> str:
    """Execute fail2ban-client command safely with non-interactive sudo fallback."""
    cmd = ["sudo", "-n", "/usr/bin/fail2ban-client"] + args
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    # Fallback to direct without sudo
    try:
        res = subprocess.run(["/usr/bin/fail2ban-client"] + args, capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return ""


def get_active_jails() -> list[str]:
    out = _run_fail2ban_cmd(["status"])
    if not out:
        return []
    match = re.search(r"Jail list:\s+(.*)", out)
    if match:
        raw = match.group(1)
        return [j.strip() for j in raw.split(",") if j.strip()]
    return []


def get_jail_details(jail_name: str) -> dict:
    out = _run_fail2ban_cmd(["status", jail_name])
    if not out:
        return {
            "jail": jail_name,
            "currently_failed": 0,
            "total_failed": 0,
            "currently_banned": 0,
            "total_banned": 0,
            "banned_ips": [],
        }

    cur_failed = int(re.search(r"Currently failed:\s+(\d+)", out).group(1)) if re.search(r"Currently failed:\s+(\d+)", out) else 0
    tot_failed = int(re.search(r"Total failed:\s+(\d+)", out).group(1)) if re.search(r"Total failed:\s+(\d+)", out) else 0
    cur_banned = int(re.search(r"Currently banned:\s+(\d+)", out).group(1)) if re.search(r"Currently banned:\s+(\d+)", out) else 0
    tot_banned = int(re.search(r"Total banned:\s+(\d+)", out).group(1)) if re.search(r"Total banned:\s+(\d+)", out) else 0

    banned_ips = []
    ip_match = re.search(r"Banned IP list:\s*(.*)", out)
    if ip_match:
        ips_str = ip_match.group(1).strip()
        if ips_str:
            banned_ips = [ip.strip() for ip in ips_str.split() if ip.strip()]

    return {
        "jail": jail_name,
        "currently_failed": cur_failed,
        "total_failed": tot_failed,
        "currently_banned": cur_banned,
        "total_banned": tot_banned,
        "banned_ips": banned_ips,
    }


def get_security_overview() -> dict:
    jails = get_active_jails()
    details = [get_jail_details(j) for j in jails]
    all_banned: list[dict] = []
    for d in details:
        for ip in d["banned_ips"]:
            all_banned.append({
                "ip": ip,
                "jail": d["jail"],
            })

    total_cur = sum(d["currently_banned"] for d in details)
    total_all = sum(d["total_banned"] for d in details)

    return {
        "is_active": len(jails) > 0,
        "jails": details,
        "banned_entries": all_banned,
        "total_currently_banned": total_cur,
        "total_all_time_banned": total_all,
    }


def get_banned_ips_set() -> set[str]:
    overview = get_security_overview()
    return set(entry["ip"] for entry in overview["banned_entries"])


def unban_ip_action(jail: str, ip: str) -> bool:
    res = _run_fail2ban_cmd(["set", jail, "unbanip", ip])
    return bool(res and ("1" in res or ip in res or "unbanned" in res.lower()))


def ban_ip_action(jail: str, ip: str) -> bool:
    res = _run_fail2ban_cmd(["set", jail, "banip", ip])
    return bool(res and ("1" in res or ip in res or "banned" in res.lower()))
