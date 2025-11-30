FROM python:3.12-slim

# System tools we need
RUN apt-get update && apt-get install -y --no-install-recommends \
      iputils-ping \
      iproute2 \
      dnsutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python env
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default envs – can all be overridden
ENV DB_PATH=/data/netprobe.sqlite
ENV WEB_PORT=8080
ENV PROBE_INTERVAL=30
ENV PING_COUNT=20
ENV EXTERNAL_PING_TARGETS="8.8.8.8,1.1.1.1,google.com"
ENV ROUTER_IP=""
ENV DNS_TEST_DOMAIN="google.com"
ENV DNS_SERVERS="1.1.1.1,8.8.8.8"
ENV DNS_QUERY_COUNT=3
ENV SPEEDTEST_ENABLED="False"
ENV SPEEDTEST_INTERVAL=3600

# scoring weights (must sum ≈ 1)
ENV WEIGHT_LOSS=0.6
ENV WEIGHT_LATENCY=0.15
ENV WEIGHT_JITTER=0.2
ENV WEIGHT_DNS_LATENCY=0.05

# thresholds (where “bad” saturates)
ENV THRESHOLD_LOSS=5
ENV THRESHOLD_LATENCY=100
ENV THRESHOLD_JITTER=30
ENV THRESHOLD_DNS_LATENCY=100

VOLUME ["/data"]
EXPOSE 8080

CMD ["python", "app.py"]
