# ---- build stage: install Python deps into a virtualenv ----
FROM python:3.13-slim AS build
WORKDIR /app
RUN python -m venv /venv
COPY requirements.txt .
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt

# ---- runtime stage: small image, non-root user ----
FROM python:3.13-slim
# iputils-ping gives the ICMP check a real `ping` binary
RUN apt-get update \
 && apt-get install -y --no-install-recommends iputils-ping \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 netmon
WORKDIR /app
COPY --from=build /venv /venv
COPY netmon/ netmon/
COPY wsgi.py targets.yaml ./
ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8080
USER netmon
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz', timeout=2)"
# One worker so there is one background monitor thread; threads handle concurrent requests.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --access-logfile - wsgi:app"]
