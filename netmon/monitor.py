"""Background monitor that runs every check on an interval and keeps history."""

import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from .checks import run_check


class Monitor:
    def __init__(self, targets, interval=30, history_size=60):
        self.targets = targets
        self.interval = interval
        self._history = {t["name"]: deque(maxlen=history_size) for t in targets}
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self.last_run = None

    def run_once(self):
        """Run all checks in parallel and record the results."""
        with ThreadPoolExecutor(max_workers=max(1, len(self.targets))) as pool:
            results = list(pool.map(run_check, self.targets))
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._lock:
            for target, result in zip(self.targets, results, strict=True):
                self._history[target["name"]].append({"time": now, **result})
            self.last_run = now

    def _loop(self):
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self.interval)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="netmon")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def snapshot(self):
        """Current state of every target, plus uptime and latency history."""
        with self._lock:
            items = []
            for target in self.targets:
                history = list(self._history[target["name"]])
                latest = history[-1] if history else None
                checks_ok = sum(1 for h in history if h["ok"])
                latencies = [h["latency_ms"] for h in history if h["latency_ms"] is not None]
                items.append(
                    {
                        "name": target["name"],
                        "type": target["type"],
                        "target": target.get("url") or _host_port(target),
                        "status": "pending" if latest is None else ("up" if latest["ok"] else "down"),
                        "latency_ms": latest["latency_ms"] if latest else None,
                        "detail": latest["detail"] if latest else "waiting for first check",
                        "uptime_pct": round(100 * checks_ok / len(history), 1) if history else None,
                        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
                        "history": [h["latency_ms"] if h["ok"] else None for h in history],
                    }
                )
            return {"last_run": self.last_run, "interval": self.interval, "targets": items}


def _host_port(target):
    if "port" in target:
        return f"{target['host']}:{target['port']}"
    return target.get("host", "")
