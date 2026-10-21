"""Tests run offline: they only touch localhost and fake check results."""

import socket
import threading

import pytest

from netmon import checks
from netmon.app import create_app, load_config
from netmon.monitor import Monitor


@pytest.fixture
def listening_port():
    """A real TCP server on localhost so the port check has something to hit."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]
    stop = threading.Event()

    def accept():
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
                conn.close()
            except OSError:
                pass

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield port
    stop.set()
    server.close()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_tcp_open(listening_port):
    result = checks.check_tcp("127.0.0.1", listening_port)
    assert result["ok"] is True
    assert result["latency_ms"] >= 0


def test_tcp_closed():
    result = checks.check_tcp("127.0.0.1", free_port(), timeout=1)
    assert result["ok"] is False
    assert "refused" in result["detail"] or "error" in result["detail"]


def test_dns_localhost():
    result = checks.check_dns("localhost")
    assert result["ok"] is True


def test_dns_invalid():
    result = checks.check_dns("does-not-exist.invalid")
    assert result["ok"] is False


def test_unknown_type():
    assert checks.run_check({"type": "smtp"})["ok"] is False


def test_missing_field():
    result = checks.run_check({"type": "tcp", "host": "127.0.0.1"})
    assert result["ok"] is False
    assert "port" in result["detail"]


def test_monitor_records_history(monkeypatch):
    results = iter(
        [
            {"ok": True, "latency_ms": 10.0, "detail": "fine"},
            {"ok": False, "latency_ms": None, "detail": "down"},
        ]
    )
    monkeypatch.setattr("netmon.monitor.run_check", lambda t: next(results))
    mon = Monitor([{"name": "a", "type": "dns", "host": "x"}])
    mon.run_once()
    mon.run_once()
    target = mon.snapshot()["targets"][0]
    assert target["status"] == "down"
    assert target["uptime_pct"] == 50.0
    assert target["avg_latency_ms"] == 10.0
    assert target["history"] == [10.0, None]


def test_config_validation(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("targets:\n  - name: x\n    type: tcp\n    host: a\n")
    with pytest.raises(ValueError, match="port"):
        load_config(bad)


def test_default_config_is_valid():
    assert load_config("targets.yaml")["targets"]


@pytest.fixture
def client(tmp_path, listening_port):
    cfg = tmp_path / "targets.yaml"
    cfg.write_text(f"targets:\n  - {{name: local, type: tcp, host: 127.0.0.1, port: {listening_port}}}\n")
    app = create_app(cfg, start_monitor=False)
    app.config["MONITOR"].run_once()
    return app.test_client()


def test_healthz(client):
    assert client.get("/healthz").json == {"status": "ok"}


def test_api_status(client):
    data = client.get("/api/status").json
    assert data["targets"][0]["status"] == "up"


def test_metrics(client):
    body = client.get("/metrics").get_data(as_text=True)
    assert 'netmon_target_up{name="local",type="tcp"} 1' in body
    assert "netmon_latency_ms" in body


def test_dashboard(client):
    assert b"netmon" in client.get("/").data
