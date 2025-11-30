import os
import time
import threading
import sqlite3
import subprocess
import statistics
from datetime import datetime

from flask import Flask, jsonify, render_template, request
import dns.resolver
import speedtest

# -------------------------
# Config from environment
# -------------------------

WEB_PORT = int(os.getenv("WEB_PORT", "8080"))

DB_PATH = os.getenv("DB_PATH", "/data/netprobe.sqlite")

PROBE_INTERVAL = int(os.getenv("PROBE_INTERVAL", "30"))
PING_COUNT = int(os.getenv("PING_COUNT", "20"))

SITES = [
    s.strip() for s in os.getenv(
        "SITES", "fast.com,google.com,youtube.com,amazon.com"
    ).split(",") if s.strip()
]

ROUTER_IP = os.getenv("ROUTER_IP", "").strip()

DNS_TEST_SITE = os.getenv("DNS_TEST_SITE", "google.com").strip()

DNS_SERVERS = []
for i in range(1, 5):
    ip = os.getenv(f"DNS_NAMESERVER_{i}_IP", "").strip()
    if ip:
        DNS_SERVERS.append(ip)

WEIGHT_LOSS = float(os.getenv("WEIGHT_LOSS", "0.6"))
WEIGHT_LATENCY = float(os.getenv("WEIGHT_LATENCY", "0.15"))
WEIGHT_JITTER = float(os.getenv("WEIGHT_JITTER", "0.2"))
WEIGHT_DNS_LATENCY = float(os.getenv("WEIGHT_DNS_LATENCY", "0.05"))

THRESHOLD_LOSS = float(os.getenv("THRESHOLD_LOSS", "5"))
THRESHOLD_LATENCY = float(os.getenv("THRESHOLD_LATENCY", "100"))
THRESHOLD_JITTER = float(os.getenv("THRESHOLD_JITTER", "30"))
THRESHOLD_DNS_LATENCY = float(os.getenv("THRESHOLD_DNS_LATENCY", "100"))

SPEEDTEST_ENABLED = os.getenv("SPEEDTEST_ENABLED", "True").lower() == "true"
SPEEDTEST_INTERVAL = int(os.getenv("SPEEDTEST_INTERVAL", "14400"))

# -------------------------
# SQLite helpers
# -------------------------

def ensure_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            avg_latency_ms REAL,
            avg_jitter_ms REAL,
            avg_loss_pct REAL,
            avg_dns_latency_ms REAL,
            score REAL
        );
        """
    )
    conn.commit()
    conn.close()


def insert_measurement(ts, avg_latency, avg_jitter, avg_loss, avg_dns, score):
    conn = sqlite3.connect(DB_PATH)
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


def fetch_recent(limit=2880):
    conn = sqlite3.connect(DB_PATH)
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
    rows.reverse()  # chronological
    return rows


def fetch_latest():
    conn = sqlite3.connect(DB_PATH)
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
        return out or None
    except Exception:
        return None


def run_ping(host, count):
    """
    Run ping and return:
      latency (avg ms), jitter (max-min), loss (%).
    On failure, treat as 100% loss and huge latency/jitter.
    """
    try:
        proc = subprocess.run(
            ["ping", "-q", "-c", str(count), host],
            capture_output=True,
            text=True,
            timeout=10,
        )
        out = proc.stdout
        if not out:
            raise RuntimeError("no ping output")

        lines = out.splitlines()
        loss_line = next(l for l in lines if "packet loss" in l)
        rtt_line = next(l for l in lines if "min/avg/max" in l)

        # "5 packets transmitted, 5 received, 0% packet loss, time 4004ms"
        loss_str = loss_line.split("%")[0].split()[-1]
        loss = float(loss_str)

        # "rtt min/avg/max/mdev = 11.123/12.345/13.123/0.567 ms"
        rtt_stats = rtt_line.split("=")[1].split()[0].split("/")
        rtt_min, rtt_avg, rtt_max, _ = map(float, rtt_stats)
        jitter = rtt_max - rtt_min

        return {"host": host, "latency": rtt_avg, "jitter": jitter, "loss": loss}
    except Exception:
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
latest_speedtest = None  # not exposed yet, but we can add API later


def run_speedtest_if_due():
    global last_speedtest_ts, latest_speedtest
    if not SPEEDTEST_ENABLED:
        return
    now = time.time()
    with last_speedtest_lock:
        if now - last_speedtest_ts < SPEEDTEST_INTERVAL:
            return
        last_speedtest_ts = now
    try:
        st = speedtest.Speedtest()
        st.get_best_server()
        down = st.download()
        up = st.upload()
        res = st.results.dict()
        latest_speedtest = {
            "ping_ms": res.get("ping"),
            "download_mbps": down / (1024 * 1024),
            "upload_mbps": up / (1024 * 1024),
            "server": res.get("server", {}),
        }
    except Exception:
        pass


def probe_loop():
    ensure_db()
    gw = get_default_gateway()

    while True:
        ts = int(time.time())

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

        avg_latency = statistics.mean(latencies) if latencies else 0
        avg_jitter = statistics.mean(jitters) if jitters else 0
        avg_loss = statistics.mean(losses) if losses else 0

        dns_times = []
        for server in DNS_SERVERS:
            t = measure_dns_latency(DNS_TEST_SITE, server, count=3)
            if t is not None:
                dns_times.append(t)
        avg_dns = statistics.mean(dns_times) if dns_times else 0

        score = compute_score(avg_loss, avg_latency, avg_jitter, avg_dns)
        insert_measurement(ts, avg_latency, avg_jitter, avg_loss, avg_dns, score)

        if SPEEDTEST_ENABLED:
            threading.Thread(target=run_speedtest_if_due, daemon=True).start()

        time.sleep(PROBE_INTERVAL)

# -------------------------
# Flask web app
# -------------------------

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/score/recent")
def api_recent():
    try:
        limit = int(request.args.get("limit", "2880"))
    except ValueError:
        limit = 2880
    rows = fetch_recent(limit)
    data = [
        {
            "ts": r[0],
            "iso": datetime.utcfromtimestamp(r[0]).isoformat() + "Z",
            "avg_latency_ms": r[1],
            "avg_jitter_ms": r[2],
            "avg_loss_pct": r[3],
            "avg_dns_latency_ms": r[4],
            "score": r[5],
        }
        for r in rows
    ]
    return jsonify(data=data)


@app.route("/api/score/latest")
def api_latest():
    row = fetch_latest()
    if not row:
        return jsonify(data=None)
    r = row
    data = {
        "ts": r[0],
        "iso": datetime.utcfromtimestamp(r[0]).isoformat() + "Z",
        "avg_latency_ms": r[1],
        "avg_jitter_ms": r[2],
        "avg_loss_pct": r[3],
        "avg_dns_latency_ms": r[4],
        "score": r[5],
    }
    return jsonify(data=data)


def main():
    ensure_db()
    t = threading.Thread(target=probe_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=WEB_PORT)


if __name__ == "__main__":
    main()
