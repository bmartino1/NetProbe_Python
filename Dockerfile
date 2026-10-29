# NetProbe 2.1 development image: one image, Nginx + Python monitoring backend.
# Build context is always the repository root.
# Python 3.15.2 is the current stable maintenance release (2026-10-25).
# Pin Debian Trixie explicitly; keep Python and OS upgrades reviewable.
FROM python:3.15.2-slim-trixie
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" WEB_PORT=8080 GUNICORN_TIMEOUT=240 \
    DB_ENGINE=sqlite DB_PATH=/config/data/netprobe.sqlite \
    NETPROBE_CONFIG_DIR=/config SPEEDTEST_OOKLA_ACCEPTANCE_FILE=/config/data/ookla-eula-accepted.txt
# Packages here provide: HTTPS edge (nginx/openssl), ICMP (iputils-ping),
# route discovery (iproute2), DNS utilities and optional installer tooling.
# Python monitoring code and the browser frontend are copied from probe/.
# Neither PostgreSQL SERVER nor Grafana is installed in this image.
# Two separate Speedtest implementations:
#   Python speedtest-cli: installed by pip from requirements.txt into /opt/venv.
#   Official Ookla speedtest: NOT bundled, installed separately by the
#   user-approved /usr/local/bin/netprobe-ookla-accept helper at runtime.
# The helper script is copied; the proprietary Ookla BINARY is not copied.
# All file creation, TLS fallback handling and service supervision happen
# in container/scripts/entrypoint.sh at runtime, not as image build side effects.
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx openssl ca-certificates iputils-ping iproute2 dnsutils curl gnupg bash \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN python -m venv /opt/venv
COPY probe/requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt
COPY probe/app.py /app/app.py
COPY probe/templates /app/templates
COPY probe/static /app/static
COPY probe/defaults /opt/netprobe/defaults
COPY probe/ookla-accept.sh /usr/local/bin/netprobe-ookla-accept
COPY container/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY container/scripts/entrypoint.sh /usr/local/bin/netprobe-entrypoint
RUN chmod 0755 /usr/local/bin/netprobe-ookla-accept /usr/local/bin/netprobe-entrypoint \
    && rm -f /etc/nginx/sites-enabled/default \
    && mkdir -p /config/data /run/nginx
# No VOLUME instruction: a mount-free docker run uses the writable image layer.
# For persistence, explicitly mount one host directory or named volume at /config.
# A running PID is not proof the WebUI is responsive. Check the internal Flask
# health route AND the Nginx HTTPS proxy; HTTPS uses the intentionally local
# self-signed certificate, so certificate verification is disabled ONLY here.
# The application itself still serves HTTPS to browsers.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python -c 'import ssl,urllib.request; urllib.request.urlopen("http://127.0.0.1:8080/healthz",timeout=3).read(); urllib.request.urlopen("https://127.0.0.1:8443/healthz",context=ssl._create_unverified_context(),timeout=3).read()' || exit 1
EXPOSE 80 8443
STOPSIGNAL SIGTERM
ENTRYPOINT ["/usr/local/bin/netprobe-entrypoint"]
