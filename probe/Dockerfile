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

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code (Flask + probe logic + templates/static)
COPY . .

# Default environment values (all overrideable via docker-compose/env)
ENV WEB_PORT=8080
ENV DB_PATH=/data/netprobe.sqlite
ENV PROBE_INTERVAL=30
ENV PING_COUNT=20
ENV SITES="fast.com,google.com,youtube.com,amazon.com"
ENV ROUTER_IP=""

ENV DNS_TEST_SITE="google.com"
ENV DNS_NAMESERVER_1="Google_DNS"
ENV DNS_NAMESERVER_1_IP="8.8.8.8"
ENV DNS_NAMESERVER_2="Quad9_DNS"
ENV DNS_NAMESERVER_2_IP="9.9.9.9"
ENV DNS_NAMESERVER_3="CloudFlare_DNS"
ENV DNS_NAMESERVER_3_IP="1.1.1.1"
ENV DNS_NAMESERVER_4="My_DNS_Server"
ENV DNS_NAMESERVER_4_IP="192.168.1.1"

ENV WEIGHT_LOSS=0.6
ENV WEIGHT_LATENCY=0.15
ENV WEIGHT_JITTER=0.2
ENV WEIGHT_DNS_LATENCY=0.05

ENV THRESHOLD_LOSS=5
ENV THRESHOLD_LATENCY=100
ENV THRESHOLD_JITTER=30
ENV THRESHOLD_DNS_LATENCY=100

ENV SPEEDTEST_ENABLED="True"
ENV SPEEDTEST_INTERVAL=14400

# SQLite lives here; bind-mount this from Unraid
VOLUME ["/data"]

EXPOSE 8080

CMD ["python", "app.py"]
