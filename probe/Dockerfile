FROM python:3.12-slim

# System tools required by the probes
RUN apt-get update && apt-get install -y --no-install-recommends \
      iputils-ping \
      iproute2 \
      dnsutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create and use a virtualenv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code (Flask app, probe logic, templates, etc.)
COPY app.py ./app.py
COPY templates ./templates
COPY static ./static

# -------------------------------
# Default environment variables
# (all can be overridden at runtime)
# -------------------------------

# Web UI
ENV WEB_PORT=8080

# SQLite DB path inside container
ENV DB_PATH=/data/netprobe.sqlite

# Probe timing
ENV PROBE_INTERVAL=30
ENV PING_COUNT=20

# Ping targets
ENV SITES="fast.com,google.com,youtube.com,amazon.com"
ENV ROUTER_IP=""

# DNS configuration
ENV DNS_TEST_SITE="google.com"

ENV DNS_NAMESERVER_1="Google_DNS"
ENV DNS_NAMESERVER_1_IP="8.8.8.8"

ENV DNS_NAMESERVER_2="Quad9_DNS"
ENV DNS_NAMESERVER_2_IP="9.9.9.9"

ENV DNS_NAMESERVER_3="CloudFlare_DNS"
ENV DNS_NAMESERVER_3_IP="1.1.1.1"

ENV DNS_NAMESERVER_4="My_DNS_Server"
ENV DNS_NAMESERVER_4_IP="192.168.1.1"

# Internet Quality Score weights (should sum to 1.0)
ENV WEIGHT_LOSS=0.6
ENV WEIGHT_LATENCY=0.15
ENV WEIGHT_JITTER=0.2
ENV WEIGHT_DNS_LATENCY=0.05

# Internet Quality Score thresholds
ENV THRESHOLD_LOSS=5
ENV THRESHOLD_LATENCY=100
ENV THRESHOLD_JITTER=30
ENV THRESHOLD_DNS_LATENCY=100

# Speedtest configuration
ENV SPEEDTEST_ENABLED="True"
ENV SPEEDTEST_INTERVAL=14400

# Persistent storage for SQLite DB
VOLUME ["/data"]

# Expose web UI port
EXPOSE 8080

# Run the probe/web app
CMD ["python", "app.py"]
