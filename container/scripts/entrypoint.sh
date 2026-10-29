#!/bin/sh
# NetProbe container bootstrap and two-process supervisor.
# Container responsibilities live here; Flask owns monitoring, DB schemas,
# authentication and live WebUI setting validation.
#
# /config is the ONLY optional application mount:
#   settings.json            WebUI-managed monitoring settings (Flask creates it)
#   database.json            WebUI-managed database connection profile (Flask)
#   admin.hash, session.key  WebUI authentication state (Flask)
#   tls/server.{crt,key}     HTTPS certificate and private key (this script)
#   data/netprobe.sqlite     SQLite history / PostgreSQL fallback (Flask)
#   data/ookla-*.txt        Optional license acknowledgement (Ookla helper)
# Mounting /config is recommended; without a mount these files live in the
# container writable layer and disappear when the container is recreated.
set -eu
umask 077

log() { printf '[netprobe-entrypoint] %s\n' "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

CONFIG_ROOT="${NETPROBE_CONFIG_DIR:-/config}"
# Nginx config currently references /config/tls, not an alternate path.
[ "$CONFIG_ROOT" = /config ] || die "NETPROBE_CONFIG_DIR must be /config in the bundled Nginx configuration"

# Phase 1: verify installed tools without ever auto-installing the official
# Ookla executable. /opt/venv/bin/speedtest-cli comes from Python pip;
# /usr/bin/speedtest is a separate OPTIONAL proprietary Ookla program.
for tool in nginx gunicorn openssl python; do
  command -v "$tool" >/dev/null 2>&1 || die "Required executable missing: $tool"
done
if command -v speedtest-cli >/dev/null 2>&1; then
  log "Python speedtest-cli: available (default backend)"
else
  log "WARNING: Python speedtest-cli executable not found; check pip dependencies"
fi
if [ -x "${SPEEDTEST_OOKLA_PATH:-/usr/bin/speedtest}" ]; then
  log "Official Ookla speedtest: installed at ${SPEEDTEST_OOKLA_PATH:-/usr/bin/speedtest} (requires separate accepted terms)"
else
  log "Official Ookla speedtest: not installed (expected on fresh images)"
fi

# Phase 2: create persistent directories only when missing. This works for
# a bind mount, a named volume or the container's unmounted writable layer.
mkdir -p /config/tls /config/data /config/backups /run/nginx
[ -w /config ] && [ -w /config/data ] && [ -w /config/tls ] ||
  die "/config must be writable; check host bind-mount permissions"
chmod 700 /config/tls /config/backups 2>/dev/null || true

# Phase 3: HTTPS certificate selection.
# - Both cert and key exist: preserve them; never overwrite custom TLS.
# - Neither exists: generate one self-signed fallback pair (local testing).
# - Only one exists: STOP instead of silently replacing a user-supplied file.
# - Validate certificate and key; STOP on invalid or mismatched TLS files.
CERT=/config/tls/server.crt
KEY=/config/tls/server.key
if [ -s "$CERT" ] && [ -s "$KEY" ]; then
  log "Keeping existing TLS certificate and key"
elif [ ! -e "$CERT" ] && [ ! -e "$KEY" ]; then
  log "Generating self-signed HTTPS fallback certificate"
  openssl req -x509 -nodes -newkey rsa:3072 -days 365 \
    -keyout "$KEY" -out "$CERT" -subj "/CN=netprobe.local" \
    >/dev/null 2>&1 || die "TLS certificate generation failed"
else
  die "Incomplete TLS pair: provide both $CERT and $KEY, or neither"
fi
openssl x509 -in "$CERT" -noout >/dev/null 2>&1 ||
  die "TLS certificate is invalid: $CERT"
openssl pkey -in "$KEY" -noout >/dev/null 2>&1 ||
  die "TLS private key is invalid: $KEY"
cert_pub="$(openssl x509 -in "$CERT" -pubkey -noout | openssl pkey -pubin -outform DER | openssl dgst -sha256)"
key_pub="$(openssl pkey -in "$KEY" -pubout -outform DER | openssl dgst -sha256)"
[ "$cert_pub" = "$key_pub" ] || die "TLS certificate and private key do not match"
chmod 600 "$KEY"

# Phase 4: validate proxy config before starting services.
nginx -t || die "Nginx configuration validation failed"
log "Starting Gunicorn on 127.0.0.1:8080 (one worker: one probe scheduler)"
gunicorn --bind 127.0.0.1:8080 --workers 1 \
  --timeout "${GUNICORN_TIMEOUT:-240}" --log-level info app:app &
web_pid=$!
log "Starting Nginx HTTPS proxy on :8443"
nginx -g "daemon off;" &
proxy_pid=$!

# Phase 5: respond to Docker signals and stop both processes if either fails.
# Do not leave an apparently running container with a dead API or TLS proxy.
shutdown() {
  trap - TERM INT
  kill -TERM "$web_pid" "$proxy_pid" 2>/dev/null || true
  wait "$web_pid" 2>/dev/null || true
  wait "$proxy_pid" 2>/dev/null || true
}
trap 'shutdown; exit 0' TERM INT
while kill -0 "$web_pid" 2>/dev/null && kill -0 "$proxy_pid" 2>/dev/null; do
  sleep 2 &
  wait $! || true
done
log "A required child process exited; stopping both services"
shutdown
exit 1
