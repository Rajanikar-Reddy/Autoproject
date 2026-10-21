"""Flask web app: dashboard, JSON API, health check and Prometheus metrics."""

import os
from pathlib import Path

import yaml
from flask import Flask, Response, jsonify, render_template

from .monitor import Monitor

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "targets.yaml"
REQUIRED = {"dns": ["host"], "tcp": ["host", "port"], "ping": ["host"], "http": ["url"]}


def load_config(path):
    with open(path) as fh:
        config = yaml.safe_load(fh) or {}
    targets = config.get("targets", [])
    names = set()
    for t in targets:
        if "name" not in t or "type" not in t:
            raise ValueError(f"every target needs a name and type: {t}")
        if t["type"] not in REQUIRED:
            raise ValueError(f"{t['name']}: unknown type '{t['type']}'")
        missing = [f for f in REQUIRED[t["type"]] if f not in t]
        if missing:
            raise ValueError(f"{t['name']}: missing {', '.join(missing)}")
        if t["name"] in names:
            raise ValueError(f"duplicate target name: {t['name']}")
        names.add(t["name"])
    return config


def create_app(config_path=None, start_monitor=True):
    config_path = config_path or os.environ.get("NETMON_CONFIG", DEFAULT_CONFIG)
    config = load_config(config_path)
    interval = int(os.environ.get("NETMON_INTERVAL", config.get("interval", 30)))

    app = Flask(__name__)
    monitor = Monitor(config["targets"], interval=interval)
    app.config["MONITOR"] = monitor
    if start_monitor:
        monitor.start()

    @app.get("/")
    def dashboard():
        return render_template("index.html", interval=interval)

    @app.get("/api/status")
    def status():
        return jsonify(monitor.snapshot())

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.get("/metrics")
    def metrics():
        lines = [
            "# HELP netmon_target_up 1 if the last check succeeded, 0 otherwise.",
            "# TYPE netmon_target_up gauge",
        ]
        snap = monitor.snapshot()["targets"]
        for t in snap:
            if t["status"] != "pending":
                up = 1 if t["status"] == "up" else 0
                lines.append(f'netmon_target_up{{name="{t["name"]}",type="{t["type"]}"}} {up}')
        lines += [
            "# HELP netmon_latency_ms Latency of the last successful check in milliseconds.",
            "# TYPE netmon_latency_ms gauge",
        ]
        for t in snap:
            if t["latency_ms"] is not None:
                lines.append(f'netmon_latency_ms{{name="{t["name"]}",type="{t["type"]}"}} {t["latency_ms"]}')
        return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4")

    return app
