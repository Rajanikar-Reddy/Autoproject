# netmon: Linux network monitoring dashboard

A small, containerised network monitor. It runs DNS, TCP port, ICMP ping and HTTP checks
against a list of targets on a schedule, and serves the results as a live web dashboard,
a JSON API and Prometheus metrics. Every push to `main` is linted, tested, built into a
Docker image, smoke-tested, pushed to GitHub Container Registry and deployed to Render.

## What it shows

| Area | How |
|---|---|
| Linux | Runs as a non-root user in a slim Debian image, uses the system `ping` binary, gunicorn process model, container `HEALTHCHECK` |
| Networking | DNS resolution (`getaddrinfo`), TCP three-way handshake (what `nc -zv` does), ICMP echo with a TCP fallback where ICMP is blocked, HTTP status and latency |
| DevOps | GitHub Actions pipeline, multi-stage Docker build, image registry, infrastructure as code (`render.yaml`), `/healthz` and `/metrics` endpoints |

## Architecture

```
            push to main
                 │
     ┌───────────▼────────────┐
     │     GitHub Actions     │
     │ lint → test → build →  │
     │ smoke test → push GHCR │
     └───────────┬────────────┘
                 │ deploy hook
     ┌───────────▼────────────┐        DNS / TCP / ICMP / HTTP
     │  Render (Docker web)   │ ─────────────────────────────▶  targets.yaml
     │  gunicorn + Flask      │
     │  background monitor    │ ◀── browser: /  /api/status  /metrics  /healthz
     └────────────────────────┘
```

## Endpoints

- `/`: live dashboard (refreshes every 5 seconds, latency sparklines, uptime %)
- `/api/status`: JSON with status, latency, uptime and history for every target
- `/metrics`: Prometheus format (`netmon_target_up`, `netmon_latency_ms`)
- `/healthz`: liveness check used by Docker and Render

## Configure targets

Edit `targets.yaml`:

```yaml
interval: 30
targets:
  - {name: Google DNS, type: tcp, host: 8.8.8.8, port: 53}
  - {name: github.com DNS, type: dns, host: github.com}
  - {name: Cloudflare ping, type: ping, host: 1.1.1.1}
  - {name: My site, type: http, url: https://example.com, expect_status: 200}
```

`NETMON_INTERVAL` overrides the interval and `NETMON_CONFIG` points at a different file.

## Deploy (all doable from a phone browser)

1. **Create the service on Render.** Sign in at render.com with GitHub → New → Blueprint →
   pick this repo. Render reads `render.yaml` and creates a free Docker web service.
2. **Connect the pipeline.** In the Render service go to Settings → Deploy Hook and copy
   the URL. In GitHub go to this repo's Settings → Secrets and variables → Actions → New
   repository secret, name it `RENDER_DEPLOY_HOOK_URL` and paste the URL.
3. **Ship.** Push any commit to `main` (or run the workflow from the Actions tab). The
   pipeline tests and builds the image, then triggers the deploy only if everything passes.

The Docker image is also published to `ghcr.io/<owner>/<repo>`, so it can run anywhere:

```bash
docker run -p 8080:8080 ghcr.io/<owner>/<repo>:latest
```

> Render's free tier sleeps after 15 minutes without traffic, so history resets after a
> sleep and the first visit takes a few seconds to wake up.

## Run locally

```bash
pip install -r requirements-dev.txt
pytest                      # offline tests, only touch localhost
python wsgi.py              # http://localhost:8080
# or
docker compose up --build
```

## Project layout

```
netmon/checks.py     DNS, TCP, ping and HTTP checks (standard library only)
netmon/monitor.py    background thread, parallel checks, rolling history
netmon/app.py        Flask routes and config validation
netmon/templates/    dashboard
tests/               pytest suite
Dockerfile           multi-stage, non-root, healthcheck
render.yaml          Render infrastructure as code
.github/workflows/   CI/CD pipeline
```

## Ideas to extend

- Alerts to Slack or email when a target goes down
- Terraform to run it on an AWS EC2 instance instead of Render
- Grafana dashboard reading `/metrics` through Prometheus
- Traceroute view showing each hop for a target
