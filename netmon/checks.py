"""Network checks: DNS, TCP port, ICMP ping and HTTP.

Each check returns a dict:
    {"ok": bool, "latency_ms": float | None, "detail": str}
Only the Python standard library is used, so the checks behave the same
on any Linux host or container.
"""

import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request


def _result(ok, latency_ms=None, detail=""):
    return {
        "ok": ok,
        "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
        "detail": detail,
    }


def check_dns(host, timeout=3.0):
    """Resolve a hostname to its IPv4/IPv6 addresses."""
    socket.setdefaulttimeout(timeout)
    start = time.perf_counter()
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        return _result(False, detail=f"DNS lookup failed: {exc.strerror}")
    finally:
        socket.setdefaulttimeout(None)
    elapsed = (time.perf_counter() - start) * 1000
    addresses = sorted({info[4][0] for info in infos})
    return _result(True, elapsed, ", ".join(addresses[:3]))


def check_tcp(host, port, timeout=3.0):
    """Open a TCP connection (the same handshake `nc -zv host port` does)."""
    start = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            elapsed = (time.perf_counter() - start) * 1000
            return _result(True, elapsed, f"port {port} open")
    except TimeoutError:
        return _result(False, detail=f"port {port} timed out")
    except ConnectionRefusedError:
        return _result(False, detail=f"port {port} refused")
    except OSError as exc:
        return _result(False, detail=f"port {port} error: {exc.strerror or exc}")


_PING_TIME = re.compile(r"time[=<]([\d.]+)\s*ms")


def check_ping(host, timeout=3.0):
    """ICMP echo using the system `ping` binary.

    Many cloud hosts block ICMP, so if ping is missing or not permitted the
    check falls back to a TCP connect on port 443 and says so.
    """
    if shutil.which("ping"):
        try:
            proc = subprocess.run(
                ["ping", "-c", "1", "-W", str(int(timeout)), host],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout + 2,
            )
            match = _PING_TIME.search(proc.stdout)
            if proc.returncode == 0 and match:
                return _result(True, float(match.group(1)), "ICMP echo reply")
            if "permitted" not in (proc.stderr + proc.stdout).lower():
                return _result(False, detail="no ICMP reply")
        except subprocess.TimeoutExpired:
            return _result(False, detail="ping timed out")
    fallback = check_tcp(host, 443, timeout)
    fallback["detail"] = "ICMP unavailable, TCP/443 " + ("reachable" if fallback["ok"] else "unreachable")
    return fallback


def check_http(url, timeout=5.0, expect_status=200):
    """Fetch a URL and compare the status code."""
    req = urllib.request.Request(url, headers={"User-Agent": "netmon/1.0"})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return _result(False, detail=f"HTTP error: {reason}")
    elapsed = (time.perf_counter() - start) * 1000
    ok = status == int(expect_status)
    return _result(ok, elapsed, f"HTTP {status}")


CHECKS = {
    "dns": lambda t: check_dns(t["host"]),
    "tcp": lambda t: check_tcp(t["host"], t["port"]),
    "ping": lambda t: check_ping(t["host"]),
    "http": lambda t: check_http(t["url"], expect_status=t.get("expect_status", 200)),
}


def run_check(target):
    """Run the check named by target['type']."""
    check = CHECKS.get(target.get("type"))
    if check is None:
        return _result(False, detail=f"unknown check type: {target.get('type')}")
    try:
        return check(target)
    except KeyError as exc:
        return _result(False, detail=f"missing config field: {exc.args[0]}")
