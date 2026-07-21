FROM python:3.14-slim

# Local/private build option only. The default public-compatible image does not
# contain the proprietary Ookla executable.
ARG INSTALL_OOKLA_SPEEDTEST=false

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    SPEEDTEST_OOKLA_ACCEPTANCE_FILE=/data/ookla-eula-accepted.txt

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    iputils-ping \
    iproute2 \
    dnsutils \
    curl \
    gnupg \
    bash \
  && if [ "${INSTALL_OOKLA_SPEEDTEST}" = "true" ]; then \
       case "$(dpkg --print-architecture)" in \
         amd64|arm64|armhf|armel|i386) \
           curl -fsSL https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash; \
           apt-get update; \
           apt-get install -y --no-install-recommends speedtest; \
           ;; \
         *) \
           echo "Ookla Speedtest CLI is not published for architecture $(dpkg --print-architecture); skipping official backend binary."; \
           ;; \
       esac; \
     fi \
  && rm -rf /var/lib/apt/lists/*

# NetProbe can use two separate Speedtest clients:
#   /opt/venv/bin/speedtest-cli -> Python sivel/speedtest-cli package
#   /usr/bin/speedtest          -> official Ookla CLI, only in a local/private
#                                  build made with INSTALL_OOKLA_SPEEDTEST=true
#
# The Docker build installs the optional package but NEVER runs speedtest or
# pre-accepts its terms. End-user acknowledgement happens at container runtime
# through SPEEDTEST_OOKLA_ACCEPT_LICENSE=I_ACCEPT or the interactive helper.
# Neither method grants redistribution or commercial-use rights.

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
 && python -m pip install --no-cache-dir --upgrade -r requirements.txt

# App code (Flask/Gunicorn web server, probe logic, templates, static assets)
COPY app.py ./app.py
COPY templates ./templates
COPY static ./static
COPY ookla-accept.sh /usr/local/bin/netprobe-ookla-accept
RUN chmod 0755 /usr/local/bin/netprobe-ookla-accept

ENV WEB_PORT=8080 \
    GUNICORN_TIMEOUT=240

CMD ["sh", "-c", "exec gunicorn -b 0.0.0.0:${WEB_PORT:-8080} --workers 1 --timeout ${GUNICORN_TIMEOUT:-240} --log-level info app:app"]
