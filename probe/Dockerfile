FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    iproute2 \
    dnsutils \
    curl \
    bash \
  && rm -rf /var/lib/apt/lists/*

# Optional Debian speedtest-cli package:
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     speedtest-cli \
#   && rm -rf /var/lib/apt/lists/*
#
# NetProbe currently uses the Python speedtest-cli package installed through
# requirements.txt. That package provides both:
#   1. The Python module used by app.py: import speedtest
#   2. The speedtest-cli command-line utility
#
# Installing the Debian package is therefore not required and would create a
# Second system-level copy separate from the Python virtual environment.

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code (Flask/gunicorn webserver app, probe logic, templates, static assets)
COPY app.py ./app.py
COPY templates ./templates
COPY static ./static

# Default port (can be overridden via WEB_PORT env)
ENV WEB_PORT=8080

# Use Gunicorn instead of Flask dev server
#CMD ["sh", "-c", "gunicorn -w 2 -b 0.0.0.0:${WEB_PORT:-8080} app:app"]
CMD ["gunicorn", "-b", "0.0.0.0:8080", "--workers", "1", "--log-level", "info", "app:app"]
