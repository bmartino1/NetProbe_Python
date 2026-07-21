import json
import logging
import os
import re
import shutil
import sqlite3
import statistics
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request
import dns.resolver
import speedtest

try:
    import psycopg2
except ImportError:
    psycopg2 = None

# -------------------------
# Logging setup
# -------------------------

logger = logging.getLogger("netprobe")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logger.setLevel(logging.INFO)


# -------------------------
# In-memory live log buffer
# -------------------------
#
# The app already writes human-readable probe and speedtest lines to stdout.
# We keep a rolling in-memory copy as well so the web UI can "tail" recent
# activity without changing the Docker logging driver or shelling out to
# docker logs from inside the container.
LOG_BUFFER_MAX_LINES = 1000
LOG_BUFFER = deque(maxlen=LOG_BUFFER_MAX_LINES)
LOG_BUFFER_LOCK = threading.Lock()
LOG_SEQUENCE = 0


class InMemoryLogHandler(logging.Handler):
    def emit(self, record):
        global LOG_SEQUENCE
        try:
            line = self.format(record)
        except Exception:
            line = record.getMessage()
        with LOG_BUFFER_LOCK:
            LOG_SEQUENCE += 1
            LOG_BUFFER.append({"seq": LOG_SEQUENCE, "line": line})


live_log_handler = InMemoryLogHandler()
live_log_handler.setLevel(logging.INFO)
live_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(live_log_handler)


def get_live_logs(since_seq=0, limit=250):
    """
    Return buffered log lines newer than the provided sequence number.

    The caller passes the last seen sequence number and gets back only the new
    lines plus the newest sequence marker to continue tailing from the UI.
    """
    try:
        since_seq = int(since_seq)
    except (TypeError, ValueError):
        since_seq = 0

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 250

    limit = max(1, min(limit, LOG_BUFFER_MAX_LINES))

    with LOG_BUFFER_LOCK:
        lines = [entry for entry in LOG_BUFFER if entry["seq"] > since_seq]
        if len(lines) > limit:
            lines = lines[-limit:]
        next_seq = LOG_SEQUENCE

    return {
        "lines": [entry["line"] for entry in lines],
        "next_seq": next_seq,
        "buffer_size": LOG_BUFFER_MAX_LINES,
    }


# -------------------------
# Small config helpers
# -------------------------


def parse_bool_env(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def parse_optional_bool(value, variable_name):
    """Parse an optional bool supplied by JSON, form data, or environment-like text."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False

    raise ValueError(f"{variable_name} must be true or false")


def normalize_speedtest_backend(value, variable_name="SPEEDTEST_BACKEND"):
    """Normalize a Speedtest backend name to ``python`` or ``ookla``."""
    normalized = str(value or "python").strip().lower()
    aliases = {
        "python": "python",
        "legacy": "python",
        "speedtest-cli": "python",
        "ookla": "ookla",
        "official": "ookla",
        "speedtest": "ookla",
    }
    if normalized not in aliases:
        raise ValueError(
            f"{variable_name} must be either 'python' or 'ookla'"
        )
    return aliases[normalized]


def parse_csv_env(name, default=""):
    """
    Parse a comma-separated environment variable into a clean list.

    This is used for ping sites, DNS lookup sites, and optional server lists.
    Empty items are ignored so values like "a.com, b.com, , c.com" still work.
    """
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_speedtest_server_list(raw_value, variable_name, allow_count_prefix=False):
    """
    Parse a comma-separated list of numeric Speedtest server IDs.

    ``SPEEDTEST_CSV_SERVERS`` also accepts the counted format requested for
    Docker/Unraid templates. For example, ``2,12345,23456`` declares two
    server IDs. A plain list such as ``12345,23456`` remains valid as well.

    Duplicate IDs are removed while preserving the configured order.
    """
    if raw_value is None:
        return []

    raw_items = [item.strip() for item in str(raw_value).split(",") if item.strip()]
    if not raw_items:
        return []

    for item in raw_items:
        if not item.isdigit():
            raise ValueError(
                f"{variable_name} must contain only comma-separated numeric server IDs"
            )

    server_ids = raw_items
    if allow_count_prefix and len(raw_items) >= 2:
        declared_count = int(raw_items[0])
        if declared_count == len(raw_items) - 1:
            server_ids = raw_items[1:]

    unique_ids = []
    seen = set()
    for server_id in server_ids:
        normalized = str(int(server_id))
        if normalized not in seen:
            seen.add(normalized)
            unique_ids.append(normalized)

    return unique_ids


# -------------------------
# Config from environment
# -------------------------

WEB_PORT = int(os.getenv("WEB_PORT", "8080"))

# Built-in defaults if the container is started with no env vars.
DEFAULT_DB_PATH = "/data/netprobe.sqlite"
DEFAULT_DB_ENGINE = "sqlite"

DB_PATH = os.getenv("DB_PATH", DEFAULT_DB_PATH)

# Database backend: sqlite (file) or postgres.
DB_ENGINE = os.getenv("DB_ENGINE", "").strip().lower()
USE_POSTGRES_FLAG = parse_bool_env("USE_POSTGRES", default=False)

# Legacy behavior: USE_POSTGRES=true forces postgres unless DB_ENGINE is set.
if not DB_ENGINE and USE_POSTGRES_FLAG:
    DB_ENGINE = "postgres"

# If DB_ENGINE is missing or invalid, fall back to sqlite file backend.
if DB_ENGINE not in ("sqlite", "postgres"):
    DB_ENGINE = DEFAULT_DB_ENGINE

USING_POSTGRES = DB_ENGINE == "postgres"

PROBE_INTERVAL = int(os.getenv("PROBE_INTERVAL", "30"))
PING_COUNT = int(os.getenv("PING_COUNT", "4"))
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "UTC")

# Ping targets used by the regular ICMP checks.
SITES = parse_csv_env("SITES", "fast.com,google.com,youtube.com")

# Optional router IP on the LAN.
ROUTER_IP = os.getenv("ROUTER_IP", "").strip()

# DNS lookup targets.
#
# Backward compatibility:
# - DNS_TEST_SITES supports multiple comma-separated domains.
# - DNS_TEST_SITE still works as the legacy single-domain variable.
DNS_TEST_SITES = parse_csv_env(
    "DNS_TEST_SITES",
    os.getenv("DNS_TEST_SITE", "google.com"),
)
if not DNS_TEST_SITES:
    DNS_TEST_SITES = ["google.com"]

# Preserve a single representative value for older UI logic if needed.
DNS_TEST_SITE = DNS_TEST_SITES[0]

# Default DNS servers if none are provided via environment variables.
DEFAULT_DNS_SERVERS = {
    1: ("Google_DNS", "8.8.8.8"),
    2: ("Quad9_DNS", "9.9.9.9"),
    3: ("CloudFlare_DNS", "1.1.1.1"),
}

DNS_SERVERS = []
DNS_SERVERS_DETAIL = []
for i in range(1, 5):
    def_name, def_ip = DEFAULT_DNS_SERVERS.get(i, ("", ""))
    name = os.getenv(f"DNS_NAMESERVER_{i}", def_name).strip()
    ip = os.getenv(f"DNS_NAMESERVER_{i}_IP", def_ip).strip()
    if ip:
        DNS_SERVERS.append(ip)
        DNS_SERVERS_DETAIL.append({"name": name or None, "ip": ip})

# -------------------------------
# Internet Quality Score Weights
# -------------------------------
WEIGHT_LOSS = float(os.getenv("WEIGHT_LOSS", "0.6"))
WEIGHT_LATENCY = float(os.getenv("WEIGHT_LATENCY", "0.15"))
WEIGHT_JITTER = float(os.getenv("WEIGHT_JITTER", "0.2"))
WEIGHT_DNS_LATENCY = float(os.getenv("WEIGHT_DNS_LATENCY", "0.05"))

# -------------------------------
# Internet Quality Score Thresholds
# -------------------------------
THRESHOLD_LOSS = float(os.getenv("THRESHOLD_LOSS", "5"))
THRESHOLD_LATENCY = float(os.getenv("THRESHOLD_LATENCY", "100"))
THRESHOLD_JITTER = float(os.getenv("THRESHOLD_JITTER", "30"))
THRESHOLD_DNS_LATENCY = float(os.getenv("THRESHOLD_DNS_LATENCY", "100"))

# -------------------------------
# Speedtest configuration
# -------------------------------
SPEEDTEST_ENABLED = parse_bool_env("SPEEDTEST_ENABLED", default=True)
SPEEDTEST_INTERVAL = int(os.getenv("SPEEDTEST_INTERVAL", "14400"))

# Backend selector:
# - python: existing sivel/speedtest-cli Python library.
# - ookla: official /usr/bin/speedtest CLI installed by the end user from
#   Ookla's repository, or included in an explicitly requested private build.
# The Python backend remains the default for backward compatibility.
SPEEDTEST_BACKEND = normalize_speedtest_backend(
    os.getenv("SPEEDTEST_BACKEND", "python")
)

# Use HTTPS when communicating through the Python speedtest-cli backend.
# The official Ookla backend uses its native protocol and ignores this value.
SPEEDTEST_SECURE = parse_bool_env("SPEEDTEST_SECURE", default=True)

# Official Ookla CLI settings. The end-user acknowledgement is evaluated at
# runtime, never during the Docker image build. Administrators can either set
# SPEEDTEST_OOKLA_ACCEPT_LICENSE=I_ACCEPT (True/Yes remain accepted for the
# unreleased compatibility path) or run the interactive helper, which writes a
# marker into the persistent /data volume.
SPEEDTEST_OOKLA_PATH = os.getenv(
    "SPEEDTEST_OOKLA_PATH", "/usr/bin/speedtest"
).strip() or "/usr/bin/speedtest"
SPEEDTEST_OOKLA_ACCEPT_LICENSE_RAW = os.getenv(
    "SPEEDTEST_OOKLA_ACCEPT_LICENSE", ""
).strip()
SPEEDTEST_OOKLA_ACCEPTANCE_FILE = os.getenv(
    "SPEEDTEST_OOKLA_ACCEPTANCE_FILE",
    "/data/ookla-eula-accepted.txt",
).strip() or "/data/ookla-eula-accepted.txt"
OOKLA_EULA_URL = "https://www.speedtest.net/about/eula"
OOKLA_TERMS_URL = "https://www.speedtest.net/about/terms"
OOKLA_PRIVACY_URL = "https://www.speedtest.net/about/privacy"


def ookla_acceptance_status():
    """Return ``(accepted, source)`` for the optional Ookla backend."""
    env_value = SPEEDTEST_OOKLA_ACCEPT_LICENSE_RAW.strip()
    normalized = env_value.lower()
    if env_value.upper() in {"I_ACCEPT", "I ACCEPT"} or normalized in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True, "environment"

    try:
        with open(SPEEDTEST_OOKLA_ACCEPTANCE_FILE, "r", encoding="utf-8") as handle:
            first_line = handle.readline().strip()
        if first_line == "I_ACCEPT":
            return True, "persistent-file"
    except (FileNotFoundError, PermissionError, OSError):
        pass

    return False, None
try:
    SPEEDTEST_OOKLA_TIMEOUT = max(
        30, int(os.getenv("SPEEDTEST_OOKLA_TIMEOUT", "180"))
    )
except (TypeError, ValueError):
    SPEEDTEST_OOKLA_TIMEOUT = 180

# Optional preferred speedtest server.
# Empty / unset means automatic server selection.
SPEEDTEST_SERVER = os.getenv("SPEEDTEST_SERVER", "").strip()

# Optional multi-server pool. When enabled, this takes precedence over the
# legacy SPEEDTEST_SERVER value. SPEEDTEST_CSV_SERVERS accepts either a plain
# list (12345,23456) or a counted list (2,12345,23456).
SPEEDTEST_CSV = parse_bool_env("SPEEDTEST_CSV", default=False)
SPEEDTEST_CSV_SERVERS_RAW = os.getenv("SPEEDTEST_CSV_SERVERS", "").strip()
SPEEDTEST_CSV_SERVERS = parse_speedtest_server_list(
    SPEEDTEST_CSV_SERVERS_RAW,
    "SPEEDTEST_CSV_SERVERS",
    allow_count_prefix=True,
)

# Global exclusion list applied to automatic, single-server, CSV-pool, and
# one-off manual tests. The Python backend passes this directly to the library.
# The Ookla backend selects an allowed server from the official --servers list.
SPEEDTEST_EXCLUDE_RAW = os.getenv("SPEEDTEST_EXCLUDE", "").strip()
SPEEDTEST_EXCLUDE = parse_speedtest_server_list(
    SPEEDTEST_EXCLUDE_RAW,
    "SPEEDTEST_EXCLUDE",
)

# Browser log-tail polling interval. This only affects the UI refresh cadence.
# Invalid or missing values fall back to 2 seconds.
try:
    LIVE_LOG_POLL_SECONDS = max(1, int(os.getenv("LIVE_LOG_POLL_SECONDS", "2")))
except (TypeError, ValueError):
    LIVE_LOG_POLL_SECONDS = 2

logger.info(
    "Netprobe 2.0 starting with PROBE_INTERVAL=%ss, PING_COUNT=%s",
    PROBE_INTERVAL,
    PING_COUNT,
)
logger.info("Database backend: %s (DB_PATH=%s)", DB_ENGINE, DB_PATH)
logger.info(
    "Targets: gateway(auto), router=%s, sites=%s, dns_servers=%s, dns_test_sites=%s",
    ROUTER_IP or "(none)",
    ", ".join(SITES) or "(none)",
    ", ".join(DNS_SERVERS) or "(none)",
    ", ".join(DNS_TEST_SITES) or "(none)",
)
logger.info("Speedtest backend: %s", SPEEDTEST_BACKEND)
if SPEEDTEST_BACKEND == "ookla":
    ookla_accepted, ookla_acceptance_source = ookla_acceptance_status()
    logger.info(
        "Official Ookla CLI: path=%s installed=%s terms_accepted=%s acceptance_source=%s",
        SPEEDTEST_OOKLA_PATH,
        bool(
            shutil.which(SPEEDTEST_OOKLA_PATH)
            or (
                os.path.isfile(SPEEDTEST_OOKLA_PATH)
                and os.access(SPEEDTEST_OOKLA_PATH, os.X_OK)
            )
        ),
        ookla_accepted,
        ookla_acceptance_source or "none",
    )
    if not ookla_accepted:
        logger.warning(
            "Ookla backend is locked until the end user sets "
            "SPEEDTEST_OOKLA_ACCEPT_LICENSE=I_ACCEPT or runs "
            "netprobe-ookla-accept interactively."
        )
if SPEEDTEST_CSV:
    logger.info(
        "Preferred speedtest selection: CSV pool (%s)",
        ", ".join(SPEEDTEST_CSV_SERVERS) or "empty",
    )
elif SPEEDTEST_SERVER:
    logger.info("Preferred speedtest selection: server ID %s", SPEEDTEST_SERVER)
else:
    logger.info("Preferred speedtest selection: auto")
logger.info(
    "Excluded speedtest server IDs: %s",
    ", ".join(SPEEDTEST_EXCLUDE) or "none",
)
logger.info(
    "Python speedtest-cli protocol: %s%s",
    "HTTPS (secure)" if SPEEDTEST_SECURE else "HTTP (non-secure)",
    " (not used by Ookla backend)" if SPEEDTEST_BACKEND == "ookla" else "",
)
logger.info("Live log poll interval: %ss", LIVE_LOG_POLL_SECONDS)


# -------------------------
# Database helpers
# -------------------------


class _WrappedPostgresCursor:
    def __init__(self, inner):
        self._inner = inner

    def execute(self, query, params=None):
        if params is None:
            params = ()
        # Translate SQLite-style "?" placeholders to psycopg2 "%s".
        # Our SQL never contains literal question marks in strings.
        query = query.replace("?", "%s")
        return self._inner.execute(query, params)

    def fetchone(self):
        return self._inner.fetchone()

    def fetchall(self):
        return self._inner.fetchall()

    def __iter__(self):
        return iter(self._inner)


class _WrappedPostgresConnection:
    def __init__(self, inner):
        self._inner = inner

    def cursor(self):
        return _WrappedPostgresCursor(self._inner.cursor())

    def commit(self):
        return self._inner.commit()

    def close(self):
        return self._inner.close()


def get_db_connection():
    """
    Return a DB-API-compatible connection to SQLite or Postgres.
    """
    if USING_POSTGRES:
        if psycopg2 is None:
            raise RuntimeError(
                "psycopg2 is required for Postgres backend (DB_ENGINE=postgres)"
            )
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            dbname=os.getenv("POSTGRES_DB", "netprobe"),
            user=os.getenv("POSTGRES_USER", "netprobe"),
            password=os.getenv("POSTGRES_PASSWORD", "netprobe"),
        )
        return _WrappedPostgresConnection(conn)

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)


def ensure_db():
    conn = get_db_connection()
    cur = conn.cursor()

    if USING_POSTGRES:
        id_col = "id SERIAL PRIMARY KEY"
    else:
        id_col = "id INTEGER PRIMARY KEY AUTOINCREMENT"

    # Aggregate probe metrics.
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS measurements (
            {id_col},
            ts INTEGER NOT NULL,
            avg_latency_ms REAL,
            avg_jitter_ms REAL,
            avg_loss_pct REAL,
            avg_dns_latency_ms REAL,
            score REAL
        );
        """
    )

    # Detailed DNS per-server values, one row per (timestamp, server_ip).
    # Each row stores the average latency for that DNS server across all
    # configured DNS test domains during that probe cycle.
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS dns_measurements (
            {id_col},
            ts INTEGER NOT NULL,
            server_ip TEXT NOT NULL,
            latency_ms REAL
        );
        """
    )

    # Speedtest results.
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS speedtests (
            {id_col},
            ts INTEGER NOT NULL,
            ping_ms REAL,
            download_mbps REAL,
            upload_mbps REAL,
            server_id TEXT,
            server_name TEXT,
            server_host TEXT,
            server_country TEXT,
            requested_server_id TEXT,
            backend TEXT
        );
        """
    )

    conn.commit()
    conn.close()


def ensure_speedtests_schema():
    """
    Small schema migration for older installs.

    Existing SQLite/Postgres deployments may already have the speedtests table
    without newer server-selection/backend fields. We add them in place if missing.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        if USING_POSTGRES:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'speedtests'
                """
            )
        else:
            cur.execute("PRAGMA table_info(speedtests)")

        rows = cur.fetchall() or []
        if USING_POSTGRES:
            existing = {r[0] for r in rows}
        else:
            existing = {r[1] for r in rows}

        if "server_id" not in existing:
            cur.execute("ALTER TABLE speedtests ADD COLUMN server_id TEXT")
        if "requested_server_id" not in existing:
            cur.execute(
                "ALTER TABLE speedtests ADD COLUMN requested_server_id TEXT"
            )
        if "backend" not in existing:
            cur.execute("ALTER TABLE speedtests ADD COLUMN backend TEXT")

        conn.commit()
    finally:
        conn.close()


def insert_measurement(ts, avg_latency, avg_jitter, avg_loss, avg_dns, score):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO measurements
        (ts, avg_latency_ms, avg_jitter_ms, avg_loss_pct,
         avg_dns_latency_ms, score)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (ts, avg_latency, avg_jitter, avg_loss, avg_dns, score),
    )
    conn.commit()
    conn.close()


def insert_dns_measurements(ts, dns_map):
    """dns_map: {server_ip: latency_ms} for this probe timestamp."""
    if not dns_map:
        return
    conn = get_db_connection()
    cur = conn.cursor()
    for ip, lat in dns_map.items():
        cur.execute(
            """
            INSERT INTO dns_measurements (ts, server_ip, latency_ms)
            VALUES (?, ?, ?)
            """,
            (ts, ip, float(lat)),
        )
    conn.commit()
    conn.close()


def fetch_recent(limit=2880):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ts, avg_latency_ms, avg_jitter_ms,
               avg_loss_pct, avg_dns_latency_ms, score
        FROM measurements
        ORDER BY ts DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    rows.reverse()
    return rows


def fetch_dns_for_timestamps(ts_list):
    """
    Return mapping: ts -> {server_ip: latency_ms} for the provided timestamps.
    """
    if not ts_list:
        return {}

    conn = get_db_connection()
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in ts_list)
    cur.execute(
        f"""
        SELECT ts, server_ip, latency_ms
        FROM dns_measurements
        WHERE ts IN ({placeholders})
        """,
        ts_list,
    )
    rows = cur.fetchall()
    conn.close()

    out = {}
    for ts, ip, lat in rows:
        out.setdefault(ts, {})[ip] = lat
    return out


def fetch_latest():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ts, avg_latency_ms, avg_jitter_ms,
               avg_loss_pct, avg_dns_latency_ms, score
        FROM measurements
        ORDER BY ts DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    conn.close()
    return row


def insert_speedtest(
    ts,
    ping_ms,
    download_mbps,
    upload_mbps,
    server,
    requested_server_id=None,
    backend=None,
):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO speedtests
        (ts, ping_ms, download_mbps, upload_mbps,
         server_id, server_name, server_host, server_country,
         requested_server_id, backend)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts,
            ping_ms,
            download_mbps,
            upload_mbps,
            str(server.get("id")) if server and server.get("id") is not None else None,
            server.get("name") if server else None,
            server.get("host") if server else None,
            server.get("country") if server else None,
            str(requested_server_id) if requested_server_id else None,
            backend,
        ),
    )
    conn.commit()
    conn.close()


def fetch_speedtests(limit=100):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ts, ping_ms, download_mbps, upload_mbps,
               server_id, server_name, server_host, server_country,
               requested_server_id, backend
        FROM speedtests
        ORDER BY ts DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    rows.reverse()
    return rows


def fetch_latest_speedtest():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ts, ping_ms, download_mbps, upload_mbps,
               server_id, server_name, server_host, server_country,
               requested_server_id, backend
        FROM speedtests
        ORDER BY ts DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    conn.close()
    return row


# -------------------------
# Measurement helpers
# -------------------------


def get_default_gateway():
    """Return the default gateway IP inside the container, or None."""
    try:
        out = subprocess.check_output(
            ["sh", "-c", "ip route | awk '/default/ {print $3; exit}'"],
            text=True,
        ).strip()
        if out:
            logger.info("Detected default gateway inside container: %s", out)
        else:
            logger.warning("No default gateway detected via ip route")
        return out or None
    except Exception as exc:
        logger.error("Failed to get default gateway: %s", exc)
        return None


def run_ping(host, count):
    """
    Run ping and return latency (avg ms), jitter (max-min), and loss (%).
    """
    out = ""
    err = ""
    timeout = max(5, count * 2)

    try:
        proc = subprocess.run(
            ["ping", "-q", "-c", str(count), host],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        out = proc.stdout or ""
        err = proc.stderr or ""

        if proc.returncode != 0:
            logger.warning(
                "ping to %s exited with code %s, stderr=%r",
                host,
                proc.returncode,
                err.strip(),
            )

        if not out.strip():
            raise RuntimeError("no ping stdout")

        lines = out.splitlines()
        loss_line = next((line for line in lines if "packet loss" in line), None)
        if not loss_line:
            raise RuntimeError("no packet loss line in ping output")

        loss_str = loss_line.split("%")[0].split()[-1]
        loss = float(loss_str)

        rtt_line = next(
            (
                line
                for line in lines
                if "min/avg/max" in line or "min/mean/max" in line
            ),
            None,
        )

        if rtt_line:
            stats_part = rtt_line.split("=")[1].split()[0]
            rtt_stats = stats_part.split("/")
            rtt_min, rtt_avg, rtt_max = map(float, rtt_stats[:3])
            jitter = rtt_max - rtt_min
        else:
            rtt_avg = THRESHOLD_LATENCY * 2
            jitter = THRESHOLD_JITTER * 2

        logger.info(
            "ping %s -> loss=%.1f%% avg=%.1fms jitter=%.1fms",
            host,
            loss,
            rtt_avg,
            jitter,
        )
        return {"host": host, "latency": rtt_avg, "jitter": jitter, "loss": loss}

    except Exception as exc:
        logger.error(
            "ping to %s failed: %s; stdout=%r stderr=%r",
            host,
            exc,
            out,
            err,
        )
        return {
            "host": host,
            "latency": THRESHOLD_LATENCY * 2,
            "jitter": THRESHOLD_JITTER * 2,
            "loss": 100.0,
        }


def measure_dns_latency(domain, server, count):
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = [server]
    times = []

    for _ in range(count):
        start = time.perf_counter()
        try:
            resolver.resolve(domain, "A", lifetime=3)
        except Exception:
            pass
        elapsed = (time.perf_counter() - start) * 1000.0
        times.append(elapsed)

    if not times:
        return None
    return sum(times) / len(times)


def measure_dns_latency_multi(domains, server, count):
    """
    Measure a DNS server against multiple domains and return a single average.

    This keeps the existing DB/UI model simple: one value per DNS server per
    probe timestamp, while allowing multiple DNS target domains to contribute.
    """
    times = []
    for domain in domains:
        latency = measure_dns_latency(domain, server, count)
        if latency is not None:
            times.append(latency)

    if not times:
        return None
    return sum(times) / len(times)


def compute_score(avg_loss, avg_latency, avg_jitter, avg_dns):
    """Compute the 0-100 internet quality score."""

    def eval_metric(value, threshold):
        if threshold <= 0:
            return 0.0
        ratio = value / threshold
        return 1.0 if ratio >= 1.0 else ratio

    e_loss = eval_metric(avg_loss, THRESHOLD_LOSS)
    e_lat = eval_metric(avg_latency, THRESHOLD_LATENCY)
    e_jit = eval_metric(avg_jitter, THRESHOLD_JITTER)
    e_dns = eval_metric(avg_dns, THRESHOLD_DNS_LATENCY)

    raw = 1.0 - (
        WEIGHT_LOSS * e_loss
        + WEIGHT_LATENCY * e_lat
        + WEIGHT_JITTER * e_jit
        + WEIGHT_DNS_LATENCY * e_dns
    )
    raw = max(0.0, min(1.0, raw))
    return raw * 100.0


def parse_speedtest_server_id(raw_value):
    """
    Normalize an optional speedtest server ID.

    The env or request value may come in as an int-like string. Empty values
    return None so the default automatic server selection is used.
    """
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    if not value:
        return None
    if not value.isdigit():
        raise ValueError("speedtest server ID must be numeric")
    return str(int(value))


def resolve_speedtest_selection(requested_server_id=None, force_auto=False):
    """
    Resolve the effective Speedtest server selection.

    Priority:
    1. A one-off API/manual force-auto request.
    2. A non-empty one-off API/manual server ID.
    3. SPEEDTEST_CSV=true with SPEEDTEST_CSV_SERVERS.
    4. Legacy SPEEDTEST_SERVER.
    5. Automatic server selection.

    SPEEDTEST_EXCLUDE is global and applies to every mode.
    """
    force_auto = bool(force_auto)
    manual_server_id = parse_speedtest_server_id(requested_server_id)

    if force_auto:
        mode = "auto"
        server_ids = []
    elif manual_server_id:
        mode = "manual"
        server_ids = [manual_server_id]
    elif SPEEDTEST_CSV:
        if not SPEEDTEST_CSV_SERVERS:
            raise ValueError(
                "SPEEDTEST_CSV is true but SPEEDTEST_CSV_SERVERS is empty"
            )
        mode = "csv"
        server_ids = list(SPEEDTEST_CSV_SERVERS)
    else:
        configured_server_id = parse_speedtest_server_id(SPEEDTEST_SERVER)
        if configured_server_id:
            mode = "single"
            server_ids = [configured_server_id]
        else:
            mode = "auto"
            server_ids = []

    excluded_ids = list(SPEEDTEST_EXCLUDE)
    conflicts = sorted(set(server_ids).intersection(excluded_ids), key=int)
    if conflicts:
        raise ValueError(
            "Speedtest server ID(s) are both selected and excluded: "
            + ",".join(conflicts)
        )

    return {
        "mode": mode,
        "server_ids": server_ids,
        "excluded_ids": excluded_ids,
        "forced_auto": force_auto,
    }


class SpeedtestRunError(RuntimeError):
    """A Speedtest failure rewritten into a useful message for the UI/API."""


def format_python_speedtest_error(exc, selection, secure):
    """Return a useful error even when speedtest-cli raises an empty exception."""
    exception_name = type(exc).__name__
    exception_text = str(exc).strip()
    protocol = "HTTPS/secure" if secure else "HTTP/non-secure"
    requested = ",".join(selection.get("server_ids", [])) or "automatic selection"

    if exception_name == "NoMatchedServers":
        return (
            f"No matching Speedtest server was found for {requested} using {protocol}. "
            "Speedtest server IDs can differ between HTTP and HTTPS lists. "
            "Toggle Secure / HTTPS, verify the ID with speedtest-cli, or use "
            "Force auto selection."
        )

    if exception_text:
        detail = f"{exception_name}: {exception_text}"
    else:
        detail = exception_name

    return (
        f"{detail}. The selected Python speedtest-cli server may be unavailable. "
        "Try toggling Secure / HTTPS or use Force auto selection."
    )


def resolve_speedtest_backend(requested_backend=None):
    if requested_backend is None or str(requested_backend).strip() == "":
        return SPEEDTEST_BACKEND
    return normalize_speedtest_backend(requested_backend, "backend")


def ookla_binary_available():
    return bool(
        shutil.which(SPEEDTEST_OOKLA_PATH)
        or (
            os.path.isfile(SPEEDTEST_OOKLA_PATH)
            and os.access(SPEEDTEST_OOKLA_PATH, os.X_OK)
        )
    )


def require_ookla_ready():
    if not ookla_binary_available():
        raise SpeedtestRunError(
            f"The official Ookla Speedtest CLI was not found at "
            f"{SPEEDTEST_OOKLA_PATH}. After reviewing Ookla's terms, run "
            "'docker exec -it <container> netprobe-ookla-accept' to "
            "acknowledge and install it, or select the Python backend."
        )

    accepted, _source = ookla_acceptance_status()
    if not accepted:
        raise SpeedtestRunError(
            "The Ookla backend is locked until the end user reviews and "
            "accepts Ookla's EULA, Terms of Use, and Privacy Policy. Set "
            "SPEEDTEST_OOKLA_ACCEPT_LICENSE=I_ACCEPT when launching the "
            "container, or run 'docker exec -it <container> "
            "netprobe-ookla-accept'."
        )


def extract_json_object(output):
    """Extract the first complete JSON object/list from CLI output."""
    cleaned = str(output or "").strip()
    if not cleaned:
        raise ValueError("Ookla Speedtest returned no JSON output")

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    starts = [idx for idx in (cleaned.find("{"), cleaned.find("[")) if idx >= 0]
    if not starts:
        raise ValueError("Ookla Speedtest did not return JSON output")
    start_index = min(starts)
    end_index = max(cleaned.rfind("}"), cleaned.rfind("]"))
    if end_index < start_index:
        raise ValueError("Ookla Speedtest returned incomplete JSON output")
    return json.loads(cleaned[start_index : end_index + 1])


def run_ookla_process(extra_args, timeout=None):
    require_ookla_ready()
    command = [
        SPEEDTEST_OOKLA_PATH,
        "--accept-license",
        "--accept-gdpr",
        "--progress=no",
    ] + list(extra_args)

    logger.info("Ookla CLI command: %s", " ".join(command))
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout or SPEEDTEST_OOKLA_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SpeedtestRunError(
            f"Official Ookla Speedtest timed out after "
            f"{timeout or SPEEDTEST_OOKLA_TIMEOUT} seconds"
        ) from exc
    except OSError as exc:
        raise SpeedtestRunError(f"Unable to execute Ookla Speedtest: {exc}") from exc

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        detail = stderr or stdout or f"exit code {completed.returncode}"
        raise SpeedtestRunError(f"Official Ookla Speedtest failed: {detail}")
    return stdout


def parse_ookla_server_listing(output):
    """Parse IDs from Ookla ``--servers`` JSON or human-readable output."""
    servers = []
    cleaned = str(output or "").strip()
    if not cleaned:
        return servers

    try:
        payload = extract_json_object(cleaned)
    except (ValueError, json.JSONDecodeError):
        payload = None

    candidates = []
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        for key in ("servers", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates = value
                break
        if not candidates and payload.get("id") is not None:
            candidates = [payload]

    for item in candidates:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        server_id = str(item.get("id")).strip()
        if server_id.isdigit():
            normalized = dict(item)
            normalized["id"] = str(int(server_id))
            servers.append(normalized)

    if servers:
        return servers

    # Some CLI builds may emit one JSON object per line for machine-readable
    # listings. Accept that form before falling back to the human table.
    for line in cleaned.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("id") is not None:
            server_id = str(item.get("id")).strip()
            if server_id.isdigit():
                normalized = dict(item)
                normalized["id"] = str(int(server_id))
                if not any(server.get("id") == normalized["id"] for server in servers):
                    servers.append(normalized)

    if servers:
        return servers

    # Human output starts each server row with a numeric ID. Metadata columns
    # vary by CLI version, so only the stable ID is required for selection.
    for line in cleaned.splitlines():
        match = re.match(r"^\s*(\d+)\s+", line)
        if match:
            server_id = str(int(match.group(1)))
            if not any(server.get("id") == server_id for server in servers):
                servers.append({"id": server_id, "display": line.strip()})
    return servers


def list_ookla_servers():
    # Current releases generally accept --format=json with --servers. Fall back
    # to the traditional table because older builds may reject that combination.
    try:
        output = run_ookla_process(["--servers", "--format=json"])
    except SpeedtestRunError as json_error:
        logger.info(
            "Ookla JSON server listing unavailable; retrying text output: %s",
            json_error,
        )
        output = run_ookla_process(["--servers"])

    servers = parse_ookla_server_listing(output)
    if not servers:
        raise SpeedtestRunError(
            "The official Ookla CLI returned no selectable servers from --servers"
        )
    return servers


def normalize_ookla_result(payload):
    if not isinstance(payload, dict):
        raise SpeedtestRunError("Official Ookla Speedtest returned invalid JSON")

    ping = payload.get("ping") or {}
    download = payload.get("download") or {}
    upload = payload.get("upload") or {}
    raw_server = payload.get("server") or {}
    raw_result = payload.get("result") or {}

    try:
        ping_ms = float(ping.get("latency"))
        download_mbps = float(download.get("bandwidth")) * 8 / 1_000_000
        upload_mbps = float(upload.get("bandwidth")) * 8 / 1_000_000
    except (TypeError, ValueError) as exc:
        raise SpeedtestRunError(
            "Official Ookla Speedtest JSON was missing ping or bandwidth data"
        ) from exc

    host = raw_server.get("host")
    port = raw_server.get("port")
    host_display = host
    if host and port and f":{port}" not in str(host):
        host_display = f"{host}:{port}"

    server = {
        "id": str(raw_server.get("id")) if raw_server.get("id") is not None else None,
        "name": raw_server.get("name") or raw_server.get("sponsor"),
        "host": host_display,
        "country": raw_server.get("country"),
        "location": raw_server.get("location"),
        "ip": raw_server.get("ip"),
        "port": port,
    }

    return {
        "ping_ms": ping_ms,
        "download_mbps": download_mbps,
        "upload_mbps": upload_mbps,
        "server": server,
        "jitter_ms": ping.get("jitter"),
        "packet_loss_pct": payload.get("packetLoss"),
        "isp": payload.get("isp"),
        "result_url": raw_result.get("url"),
    }


def execute_ookla_test(server_id=None):
    args = ["--format=json"]
    if server_id:
        args.append(f"--server-id={server_id}")
    output = run_ookla_process(args)
    try:
        payload = extract_json_object(output)
    except (ValueError, json.JSONDecodeError) as exc:
        raise SpeedtestRunError(f"Unable to parse Ookla Speedtest JSON: {exc}") from exc
    return normalize_ookla_result(payload)


def build_ookla_candidate_order(selection):
    """Return server IDs to try for Ookla filtered modes."""
    requested_ids = list(selection["server_ids"])
    excluded = set(selection["excluded_ids"])
    mode = selection["mode"]

    if mode in ("manual", "single"):
        return requested_ids

    if mode == "csv":
        # Prefer candidate IDs in the order returned by the official nearest
        # server list, then retain configured IDs as fallbacks.
        listed_ids = [server["id"] for server in list_ookla_servers()]
        ordered = [server_id for server_id in listed_ids if server_id in requested_ids]
        ordered.extend(server_id for server_id in requested_ids if server_id not in ordered)
        return ordered

    if mode == "auto" and excluded:
        return [
            server["id"]
            for server in list_ookla_servers()
            if server["id"] not in excluded
        ]

    return []


def run_python_speedtest(selection, secure_mode):
    try:
        st = speedtest.Speedtest(secure=secure_mode)
        server_filter = [int(server_id) for server_id in selection["server_ids"]]
        exclude_filter = [int(server_id) for server_id in selection["excluded_ids"]]

        if server_filter or exclude_filter:
            st.get_servers(
                servers=server_filter or None,
                exclude=exclude_filter or None,
            )

        st.get_best_server()
        down_bps = st.download()
        up_bps = st.upload()
        res = st.results.dict()
    except Exception as exc:
        raise SpeedtestRunError(
            format_python_speedtest_error(exc, selection, secure_mode)
        ) from exc

    return {
        "ping_ms": res.get("ping"),
        # Preserve the application's existing conversion for this legacy backend.
        "download_mbps": down_bps / (1024 * 1024),
        "upload_mbps": up_bps / (1024 * 1024),
        "server": res.get("server", {}) or {},
        "jitter_ms": None,
        "packet_loss_pct": None,
        "isp": res.get("client", {}).get("isp") if isinstance(res.get("client"), dict) else None,
        "result_url": res.get("share"),
        "protocol": "https" if secure_mode else "http",
        "secure": secure_mode,
    }


def run_ookla_speedtest(selection):
    candidate_ids = build_ookla_candidate_order(selection)

    if selection["mode"] == "auto" and selection["excluded_ids"] and not candidate_ids:
        raise SpeedtestRunError(
            "No allowed Ookla servers remained after applying SPEEDTEST_EXCLUDE"
        )

    # Unfiltered automatic mode lets the official CLI choose directly.
    if selection["mode"] == "auto" and not selection["excluded_ids"]:
        result = execute_ookla_test()
        result.update(protocol="ookla", secure=None)
        return result

    failures = []
    for server_id in candidate_ids:
        try:
            result = execute_ookla_test(server_id)
            result.update(protocol="ookla", secure=None)
            return result
        except SpeedtestRunError as exc:
            failures.append(f"{server_id}: {exc}")
            logger.warning("Ookla candidate %s failed: %s", server_id, exc)

    requested = ",".join(candidate_ids or selection["server_ids"]) or "automatic"
    detail = "; ".join(failures[-3:]) or "no candidates were available"
    raise SpeedtestRunError(
        f"Official Ookla Speedtest could not complete using {requested}: {detail}"
    )


# -------------------------
# Probe & speedtest loops
# -------------------------

last_speedtest_ts = 0
last_speedtest_lock = threading.Lock()
speedtest_run_lock = threading.Lock()


def run_speedtest_internal(
    requested_server_id=None,
    secure=None,
    force_auto=False,
    backend=None,
):
    """Run a speedtest with the configured or one-off selected backend."""
    selected_backend = resolve_speedtest_backend(backend)
    secure_override = parse_optional_bool(secure, "secure")
    secure_mode = SPEEDTEST_SECURE if secure_override is None else secure_override
    force_auto_value = parse_optional_bool(force_auto, "force_auto")
    force_auto_mode = bool(force_auto_value) if force_auto_value is not None else False

    selection = resolve_speedtest_selection(
        requested_server_id,
        force_auto=force_auto_mode,
    )
    selection_mode = selection["mode"]
    requested_server_ids = selection["server_ids"]
    excluded_server_ids = selection["excluded_ids"]
    requested_server_value = ",".join(requested_server_ids) or None

    if not speedtest_run_lock.acquire(blocking=False):
        raise SpeedtestRunError(
            "A Speedtest is already running. Wait for it to finish and try again."
        )

    try:
        logger.info("Starting speedtest run...")
        logger.info(
            "Speedtest selection: backend=%s protocol=%s mode=%s requested=%s excluded=%s forced_auto=%s",
            selected_backend,
            (
                "https" if secure_mode else "http"
            ) if selected_backend == "python" else "ookla-native",
            selection_mode,
            requested_server_value or "auto",
            ",".join(excluded_server_ids) or "none",
            selection["forced_auto"],
        )

        if selected_backend == "python":
            normalized = run_python_speedtest(selection, secure_mode)
        else:
            normalized = run_ookla_speedtest(selection)

        ping_ms = normalized["ping_ms"]
        download_mbps = normalized["download_mbps"]
        upload_mbps = normalized["upload_mbps"]
        server = normalized["server"]
        ts = int(time.time())

        insert_speedtest(
            ts,
            ping_ms,
            download_mbps,
            upload_mbps,
            server,
            requested_server_id=requested_server_value,
            backend=selected_backend,
        )

        logger.info(
            "Speedtest: backend=%s ping=%sms down=%.2fMbps up=%.2fMbps server=%s protocol=%s selection_mode=%s requested_server_ids=%s excluded_server_ids=%s forced_auto=%s",
            selected_backend,
            ping_ms,
            download_mbps,
            upload_mbps,
            server.get("name"),
            normalized["protocol"],
            selection_mode,
            requested_server_value or "auto",
            ",".join(excluded_server_ids) or "none",
            selection["forced_auto"],
        )

        return {
            "timestamp": ts,
            "ping_ms": ping_ms,
            "download_mbps": download_mbps,
            "upload_mbps": upload_mbps,
            "server": server,
            "requested_server_id": requested_server_value,
            "requested_server_ids": requested_server_ids,
            "selection_mode": selection_mode,
            "excluded_server_ids": excluded_server_ids,
            "backend": selected_backend,
            "protocol": normalized["protocol"],
            "secure": normalized["secure"],
            "forced_auto": selection["forced_auto"],
            "jitter_ms": normalized.get("jitter_ms"),
            "packet_loss_pct": normalized.get("packet_loss_pct"),
            "isp": normalized.get("isp"),
            "result_url": normalized.get("result_url"),
        }
    finally:
        speedtest_run_lock.release()


def run_speedtest_if_due():
    global last_speedtest_ts
    if not SPEEDTEST_ENABLED:
        return

    now = time.time()
    with last_speedtest_lock:
        if now - last_speedtest_ts < SPEEDTEST_INTERVAL:
            return
        last_speedtest_ts = now

    try:
        run_speedtest_internal()
    except Exception as exc:
        logger.exception("Periodic speedtest failed: %s", exc)


def probe_loop():
    gw = get_default_gateway()

    while True:
        ts = int(time.time())

        # ---------- Ping probes ----------
        ping_targets = []
        if gw:
            ping_targets.append(gw)
        if ROUTER_IP:
            ping_targets.append(ROUTER_IP)
        ping_targets.extend(SITES)

        ping_results = [run_ping(host, PING_COUNT) for host in ping_targets]

        latencies = [r["latency"] for r in ping_results]
        jitters = [r["jitter"] for r in ping_results]
        losses = [r["loss"] for r in ping_results]

        avg_latency = statistics.mean(latencies) if latencies else 0.0
        avg_jitter = statistics.mean(jitters) if jitters else 0.0
        avg_loss = statistics.mean(losses) if losses else 0.0

        # ---------- DNS probes ----------
        dns_times = []
        dns_per_server = {}
        for server_ip in DNS_SERVERS:
            measured = measure_dns_latency_multi(
                DNS_TEST_SITES,
                server_ip,
                count=3,
            )
            if measured is not None:
                dns_times.append(measured)
                dns_per_server[server_ip] = measured

        avg_dns = statistics.mean(dns_times) if dns_times else 0.0

        # ---------- Score + persistence ----------
        score = compute_score(avg_loss, avg_latency, avg_jitter, avg_dns)
        insert_measurement(ts, avg_latency, avg_jitter, avg_loss, avg_dns, score)
        insert_dns_measurements(ts, dns_per_server)

        logger.info(
            "Probe ts=%s score=%.2f loss=%.2f%% latency=%.1fms jitter=%.1fms dns=%.1fms",
            ts,
            score,
            avg_loss,
            avg_latency,
            avg_jitter,
            avg_dns,
        )

        if SPEEDTEST_ENABLED:
            threading.Thread(target=run_speedtest_if_due, daemon=True).start()

        time.sleep(PROBE_INTERVAL)


# -------------------------
# Flask web app
# -------------------------

app = Flask(__name__)


@app.route("/")
def index():
    return render_template(
        "index.html",
        probe_interval=PROBE_INTERVAL,
        app_timezone=APP_TIMEZONE,
        weight_loss=WEIGHT_LOSS,
        weight_latency=WEIGHT_LATENCY,
        weight_jitter=WEIGHT_JITTER,
        weight_dns_latency=WEIGHT_DNS_LATENCY,
    )


@app.route("/api/score/recent")
def api_recent():
    try:
        limit = int(request.args.get("limit", "2880"))
    except ValueError:
        limit = 2880

    rows = fetch_recent(limit)
    ts_list = [row[0] for row in rows]
    dns_detail_map = fetch_dns_for_timestamps(ts_list)

    data = []
    for row in rows:
        ts = row[0]
        item = {
            "ts": ts,
            "iso": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
            "avg_latency_ms": row[1],
            "avg_jitter_ms": row[2],
            "avg_loss_pct": row[3],
            "avg_dns_latency_ms": row[4],
            "score": row[5],
        }
        if ts in dns_detail_map:
            item["dns_per_server"] = dns_detail_map[ts]
        data.append(item)

    return jsonify(data=data)


@app.route("/api/score/latest")
def api_latest():
    row = fetch_latest()
    if not row:
        return jsonify(data=None)

    ts = row[0]
    data = {
        "ts": ts,
        "iso": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
        "avg_latency_ms": row[1],
        "avg_jitter_ms": row[2],
        "avg_loss_pct": row[3],
        "avg_dns_latency_ms": row[4],
        "score": row[5],
    }
    return jsonify(data=data)


@app.route("/api/config")
def api_config():
    gw = get_default_gateway()
    return jsonify(
        probe_interval=PROBE_INTERVAL,
        ping_count=PING_COUNT,
        app_timezone=APP_TIMEZONE,
        gateway_ip=gw,
        router_ip=ROUTER_IP or None,
        sites=SITES,
        dns_test_site=DNS_TEST_SITE,
        dns_test_sites=DNS_TEST_SITES,
        dns_servers=DNS_SERVERS,
        dns_servers_detail=DNS_SERVERS_DETAIL,
        weight_loss=WEIGHT_LOSS,
        weight_latency=WEIGHT_LATENCY,
        weight_jitter=WEIGHT_JITTER,
        weight_dns_latency=WEIGHT_DNS_LATENCY,
        threshold_loss=THRESHOLD_LOSS,
        threshold_latency=THRESHOLD_LATENCY,
        threshold_jitter=THRESHOLD_JITTER,
        threshold_dns_latency=THRESHOLD_DNS_LATENCY,
        speedtest_enabled=SPEEDTEST_ENABLED,
        speedtest_interval=SPEEDTEST_INTERVAL,
        speedtest_backend=SPEEDTEST_BACKEND,
        speedtest_backends_available={
            "python": True,
            "ookla": ookla_binary_available(),
        },
        speedtest_secure=SPEEDTEST_SECURE,
        speedtest_ookla_path=SPEEDTEST_OOKLA_PATH,
        speedtest_ookla_installed=ookla_binary_available(),
        speedtest_ookla_accept_license=ookla_acceptance_status()[0],
        speedtest_ookla_acceptance_source=ookla_acceptance_status()[1],
        speedtest_ookla_acceptance_file=SPEEDTEST_OOKLA_ACCEPTANCE_FILE,
        speedtest_ookla_terms={
            "eula": OOKLA_EULA_URL,
            "terms": OOKLA_TERMS_URL,
            "privacy": OOKLA_PRIVACY_URL,
        },
        speedtest_ookla_timeout=SPEEDTEST_OOKLA_TIMEOUT,
        speedtest_server=SPEEDTEST_SERVER or None,
        speedtest_csv=SPEEDTEST_CSV,
        speedtest_csv_servers=SPEEDTEST_CSV_SERVERS,
        speedtest_exclude=SPEEDTEST_EXCLUDE,
        speedtest_selection_mode=(
            "csv" if SPEEDTEST_CSV else "single" if SPEEDTEST_SERVER else "auto"
        ),
        live_log_poll_seconds=LIVE_LOG_POLL_SECONDS,
        db_engine=DB_ENGINE,
    )


@app.route("/api/speedtest/history")
def api_speedtest_history():
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        limit = 100

    rows = fetch_speedtests(limit)
    tests = [
        {
            "ts": row[0],
            "iso": datetime.fromtimestamp(row[0], timezone.utc).isoformat(),
            "ping_ms": row[1],
            "download_mbps": row[2],
            "upload_mbps": row[3],
            "server_id": row[4],
            "server_name": row[5],
            "server_host": row[6],
            "server_country": row[7],
            "requested_server_id": row[8],
            "requested_server_ids": row[8].split(",") if row[8] else [],
            "backend": row[9] or "python",
        }
        for row in rows
    ]
    return jsonify(tests=tests)


@app.route("/api/speedtest/latest")
def api_speedtest_latest():
    row = fetch_latest_speedtest()
    if not row:
        return jsonify(result=None)

    data = {
        "ts": row[0],
        "iso": datetime.fromtimestamp(row[0], timezone.utc).isoformat(),
        "ping_ms": row[1],
        "download_mbps": row[2],
        "upload_mbps": row[3],
        "server": {
            "id": row[4],
            "name": row[5],
            "host": row[6],
            "country": row[7],
        },
        "requested_server_id": row[8],
        "requested_server_ids": row[8].split(",") if row[8] else [],
        "backend": row[9] or "python",
    }
    return jsonify(result=data)


@app.route("/api/speedtest/run", methods=["POST"])
def api_speedtest_run():
    try:
        payload = request.get_json(silent=True) or {}
        requested_server_id = payload.get("server_id")
        secure = payload.get("secure")
        force_auto = payload.get("force_auto", False)
        backend = payload.get("backend")
        result = run_speedtest_internal(
            requested_server_id=requested_server_id,
            secure=secure,
            force_auto=force_auto,
            backend=backend,
        )
        return jsonify(success=True, result=result)
    except Exception as exc:
        error_message = str(exc).strip() or type(exc).__name__
        logger.exception("Manual speedtest failed: %s", error_message)
        return jsonify(success=False, error=error_message), 500


@app.route("/api/logs/live")
def api_logs_live():
    """
    Return recent in-memory log lines for the browser log tail panel.

    Query parameters:
    - since: last seen sequence number
    - limit: maximum number of lines to return
    """
    since = request.args.get("since", "0")
    limit = request.args.get("limit", "250")
    return jsonify(get_live_logs(since_seq=since, limit=limit))


def start_background_thread():
    thread = threading.Thread(target=probe_loop, daemon=True)
    thread.start()


# Start probe loop when imported (for gunicorn worker start).
ensure_db()
ensure_speedtests_schema()
start_background_thread()


def main():
    # For local development only.
    app.run(host="0.0.0.0", port=WEB_PORT)


if __name__ == "__main__":
    main()
