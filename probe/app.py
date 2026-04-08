import os
import time
import threading
import sqlite3
import subprocess
import statistics
import logging
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


def parse_csv_env(name, default=""):
    """
    Parse a comma-separated environment variable into a clean list.

    This is used for ping sites, DNS lookup sites, and optional server lists.
    Empty items are ignored so values like "a.com, b.com, , c.com" still work.
    """
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


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

# Optional preferred speedtest server.
# Empty / unset means automatic server selection.
SPEEDTEST_SERVER = os.getenv("SPEEDTEST_SERVER", "").strip()

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
if SPEEDTEST_SERVER:
    logger.info("Preferred speedtest server ID: %s", SPEEDTEST_SERVER)
else:
    logger.info("Preferred speedtest server ID: auto")
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
            requested_server_id TEXT
        );
        """
    )

    conn.commit()
    conn.close()


def ensure_speedtests_schema():
    """
    Small schema migration for older installs.

    Existing SQLite/Postgres deployments may already have the speedtests table
    without server_id/requested_server_id. We add them in place if missing.
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
):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO speedtests
        (ts, ping_ms, download_mbps, upload_mbps,
         server_id, server_name, server_host, server_country, requested_server_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
               requested_server_id
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
               requested_server_id
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
    return value


# -------------------------
# Probe & speedtest loops
# -------------------------

last_speedtest_ts = 0
last_speedtest_lock = threading.Lock()


def run_speedtest_internal(requested_server_id=None):
    """
    Run a speedtest.

    Priority:
    1. explicit API/manual override
    2. SPEEDTEST_SERVER environment variable
    3. automatic best server selection
    """
    requested_server_id = parse_speedtest_server_id(
        requested_server_id if requested_server_id is not None else SPEEDTEST_SERVER
    )

    logger.info("Starting speedtest run...")
    st = speedtest.Speedtest()

    if requested_server_id:
        logger.info("Using requested speedtest server ID: %s", requested_server_id)
        st.get_servers([int(requested_server_id)])
        st.get_best_server()
    else:
        st.get_best_server()

    down_bps = st.download()
    up_bps = st.upload()
    res = st.results.dict()

    ping_ms = res.get("ping")
    download_mbps = down_bps / (1024 * 1024)
    upload_mbps = up_bps / (1024 * 1024)
    server = res.get("server", {}) or {}
    ts = int(time.time())

    insert_speedtest(
        ts,
        ping_ms,
        download_mbps,
        upload_mbps,
        server,
        requested_server_id=requested_server_id,
    )

    logger.info(
        "Speedtest: ping=%sms down=%.2fMbps up=%.2fMbps server=%s requested_server_id=%s",
        ping_ms,
        download_mbps,
        upload_mbps,
        server.get("name"),
        requested_server_id or "auto",
    )

    return {
        "timestamp": ts,
        "ping_ms": ping_ms,
        "download_mbps": download_mbps,
        "upload_mbps": upload_mbps,
        "server": server,
        "requested_server_id": requested_server_id,
    }


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
        logger.error("Periodic speedtest failed: %s", exc)


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
        speedtest_server=SPEEDTEST_SERVER or None,
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
    }
    return jsonify(result=data)


@app.route("/api/speedtest/run", methods=["POST"])
def api_speedtest_run():
    try:
        payload = request.get_json(silent=True) or {}
        requested_server_id = payload.get("server_id")
        result = run_speedtest_internal(requested_server_id=requested_server_id)
        return jsonify(success=True, result=result)
    except Exception as exc:
        logger.error("Manual speedtest failed: %s", exc)
        return jsonify(success=False, error=str(exc)), 500


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
