import os
import time
import threading
import sqlite3
import subprocess
import statistics
import logging
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
# Config from environment
# -------------------------

WEB_PORT = int(os.getenv("WEB_PORT", "8080"))

# Built-in defaults if the container is started with *no* env vars
DEFAULT_DB_PATH = "/data/netprobe.sqlite"
DEFAULT_DB_ENGINE = "sqlite"

DB_PATH = os.getenv("DB_PATH", DEFAULT_DB_PATH)

# Database backend: sqlite (file) or postgres
DB_ENGINE = os.getenv("DB_ENGINE", "").strip().lower()
_use_pg_flag = os.getenv("USE_POSTGRES", "").strip().lower()

# Simple legacy flag: USE_POSTGRES=true forces postgres
if _use_pg_flag in ("1", "true", "yes"):
    DB_ENGINE = "postgres"

# If DB_ENGINE is missing or weird, fall back to sqlite file backend
if DB_ENGINE not in ("sqlite", "postgres"):
    DB_ENGINE = DEFAULT_DB_ENGINE

USING_POSTGRES = DB_ENGINE == "postgres"

PROBE_INTERVAL = int(os.getenv("PROBE_INTERVAL", "30"))
PING_COUNT = int(os.getenv("PING_COUNT", "4"))  # default you wanted
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "UTC")

# Default sites if SITES is not set
SITES = [
    s.strip()
    for s in os.getenv(
        "SITES", "fast.com,google.com,youtube.com"
    ).split(",")
    if s.strip()
]

# Blank router IP by default
ROUTER_IP = os.getenv("ROUTER_IP", "").strip()
DNS_TEST_SITE = os.getenv("DNS_TEST_SITE", "google.com").strip()

# Default DNS servers if none provided via env
DEFAULT_DNS_SERVERS = {
    1: ("Google_DNS", "8.8.8.8"),
    2: ("Quad9_DNS", "9.9.9.9"),
    3: ("CloudFlare_DNS", "1.1.1.1"),
}

DNS_SERVERS = []        # type: list[str]
DNS_SERVERS_DETAIL = [] # type: list[dict]
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

# Speedtest
SPEEDTEST_ENABLED = os.getenv("SPEEDTEST_ENABLED", "True").lower() == "true"
SPEEDTEST_INTERVAL = int(os.getenv("SPEEDTEST_INTERVAL", "14400"))

logger.info(
    "Netprobe 2.0 starting with PROBE_INTERVAL=%ss, PING_COUNT=%s",
    PROBE_INTERVAL,
    PING_COUNT,
)
logger.info("Database backend: %s (DB_PATH=%s)", DB_ENGINE, DB_PATH)
logger.info(
    "Targets: gateway(auto), router=%s, sites=%s, dns_servers=%s",
    ROUTER_IP or "(none)",
    ", ".join(SITES),
    ", ".join(DNS_SERVERS),
)

# -------------------------
# Database helpers
# -------------------------


class _WrappedPostgresCursor:
    def __init__(self, inner):
        self._inner = inner

    def execute(self, query, params=None):
        if params is None:
            params = ()
        # Translate SQLite-style "?" placeholders to psycopg2's "%s".
        # Our SQL never has literal "?" in strings, so this is safe.
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
    Return DB-API compatible connection to SQLite or Postgres.

    - SQLite uses DB_PATH on the local volume.
    - Postgres uses POSTGRES_* environment variables.
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
    else:
        # SQLite file on a local Docker volume
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        return sqlite3.connect(DB_PATH)


def ensure_db():
    conn = get_db_connection()
    cur = conn.cursor()

    if USING_POSTGRES:
        id_col = "id SERIAL PRIMARY KEY"
    else:
        id_col = "id INTEGER PRIMARY KEY AUTOINCREMENT"

    # Aggregate probe metrics
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

    # Detailed DNS per-server values, one row per (ts, server_ip)
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

    # Speedtest results
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS speedtests (
            {id_col},
            ts INTEGER NOT NULL,
            ping_ms REAL,
            download_mbps REAL,
            upload_mbps REAL,
            server_name TEXT,
            server_host TEXT,
            server_country TEXT
        );
        """
    )

    conn.commit()
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
    """dns_map: {ip: latency_ms} for this probe timestamp."""
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
    Return mapping: ts -> {ip: latency_ms}
    for the given timestamps.
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
        if ts not in out:
            out[ts] = {}
        out[ts][ip] = lat
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


def insert_speedtest(ts, ping_ms, download_mbps, upload_mbps, server):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO speedtests
        (ts, ping_ms, download_mbps, upload_mbps,
         server_name, server_host, server_country)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts,
            ping_ms,
            download_mbps,
            upload_mbps,
            server.get("name") if server else None,
            server.get("host") if server else None,
            server.get("country") if server else None,
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
               server_name, server_host, server_country
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
               server_name, server_host, server_country
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
    """Return default gateway IP inside the container, or None."""
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
    except Exception as e:
        logger.error("Failed to get default gateway: %s", e)
        return None


def run_ping(host, count):
    """
    Run ping and return:
      latency (avg ms), jitter (max-min), loss (%).
    Timeout scales with count because ping -q only prints at the end.
    """
    out = ""
    err = ""
    timeout = max(5, count * 2)  # ~2 s per packet

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
        loss_line = next((l for l in lines if "packet loss" in l), None)
        if not loss_line:
            raise RuntimeError("no packet loss line in ping output")

        # e.g. "5 packets transmitted, 5 received, 0% packet loss, time 4004ms"
        loss_str = loss_line.split("%")[0].split()[-1]
        loss = float(loss_str)

        rtt_line = next(
            (l for l in lines if "min/avg/max" in l or "min/mean/max" in l),
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

    except Exception as e:
        logger.error(
            "ping to %s failed: %s; stdout=%r stderr=%r",
            host,
            e,
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
            elapsed = (time.perf_counter() - start) * 1000.0
            times.append(elapsed)
        except Exception:
            elapsed = (time.perf_counter() - start) * 1000.0
            times.append(elapsed)
    if not times:
        return None
    return sum(times) / len(times)


def compute_score(avg_loss, avg_latency, avg_jitter, avg_dns):
    """
    Internet Quality Score:
      - normalize each metric vs threshold,
      - weight them,
      - subtract from 1, scale to 0–100.
    """

    def eval_metric(value, threshold):
        if threshold <= 0:
            return 0.0
        r = value / threshold
        return 1.0 if r >= 1.0 else r

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


# -------------------------
# Probe & speedtest loops
# -------------------------

last_speedtest_ts = 0
last_speedtest_lock = threading.Lock()


def run_speedtest_internal():
    logger.info("Starting speedtest run…")
    st = speedtest.Speedtest()
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
    )
    logger.info(
        "Speedtest: ping=%sms down=%.2fMbps up=%.2fMbps server=%s",
        ping_ms,
        download_mbps,
        upload_mbps,
        server.get("name"),
    )
    return {
        "timestamp": ts,
        "ping_ms": ping_ms,
        "download_mbps": download_mbps,
        "upload_mbps": upload_mbps,
        "server": server,
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
    except Exception as e:
        logger.error("Periodic speedtest failed: %s", e)


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

        ping_results = [run_ping(h, PING_COUNT) for h in ping_targets]

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
            t = measure_dns_latency(DNS_TEST_SITE, server_ip, count=3)
            if t is not None:
                dns_times.append(t)
                dns_per_server[server_ip] = t

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
    ts_list = [r[0] for r in rows]
    dns_detail_map = fetch_dns_for_timestamps(ts_list)

    data = []
    for r in rows:
        ts = r[0]
        item = {
            "ts": ts,
            "iso": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
            "avg_latency_ms": r[1],
            "avg_jitter_ms": r[2],
            "avg_loss_pct": r[3],
            "avg_dns_latency_ms": r[4],
            "score": r[5],
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
            "ts": r[0],
            "iso": datetime.fromtimestamp(r[0], timezone.utc).isoformat(),
            "ping_ms": r[1],
            "download_mbps": r[2],
            "upload_mbps": r[3],
            "server_name": r[4],
            "server_host": r[5],
            "server_country": r[6],
        }
        for r in rows
    ]
    return jsonify(tests=tests)


@app.route("/api/speedtest/latest")
def api_speedtest_latest():
    row = fetch_latest_speedtest()
    if not row:
        return jsonify(result=None)
    r = row
    data = {
        "ts": r[0],
        "iso": datetime.fromtimestamp(r[0], timezone.utc).isoformat(),
        "ping_ms": r[1],
        "download_mbps": r[2],
        "upload_mbps": r[3],
        "server": {
            "name": r[4],
            "host": r[5],
            "country": r[6],
        },
    }
    return jsonify(result=data)


@app.route("/api/speedtest/run", methods=["POST"])
def api_speedtest_run():
    try:
        result = run_speedtest_internal()
        return jsonify(success=True, result=result)
    except Exception as e:
        logger.error("Manual speedtest failed: %s", e)
        return jsonify(success=False, error=str(e)), 500


def start_background_thread():
    t = threading.Thread(target=probe_loop, daemon=True)
    t.start()


# Start probe loop when imported (gunicorn worker start)
ensure_db()
start_background_thread()


def main():
    # For local dev only
    app.run(host="0.0.0.0", port=WEB_PORT)


if __name__ == "__main__":
    main()
