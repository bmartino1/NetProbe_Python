import os
import time
import threading
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import execute_values
from icmplib import multiping
import dns.resolver
import speedtest

from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "netprobe")
DB_USER = os.getenv("DB_USER", "netprobe")
DB_PASSWORD = os.getenv("DB_PASSWORD", "netprobe_password_change_me")

PING_TARGETS = [h.strip() for h in os.getenv("PING_TARGETS", "1.1.1.1,8.8.8.8").split(",") if h.strip()]
PING_INTERVAL = int(os.getenv("PING_INTERVAL_SECONDS", "60"))
PING_COUNT = int(os.getenv("PING_COUNT", "5"))

DNS_TARGETS = [d.strip() for d in os.getenv("DNS_TARGETS", "google.com,cloudflare.com").split(",") if d.strip()]
DNS_SERVERS = [s.strip() for s in os.getenv("DNS_SERVERS", "1.1.1.1,8.8.8.8").split(",") if s.strip()]
DNS_INTERVAL = int(os.getenv("DNS_INTERVAL_SECONDS", "60"))
DNS_QUERY_COUNT = int(os.getenv("DNS_QUERY_COUNT", "3"))

SPEEDTEST_ENABLED = os.getenv("SPEEDTEST_ENABLED", "False").lower() == "true"
SPEEDTEST_INTERVAL = int(os.getenv("SPEEDTEST_INTERVAL_SECONDS", "3600"))


def db_connect():
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )
    conn.autocommit = True
    return conn


def init_schema():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ping_measurements (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMPTZ NOT NULL,
        target_host TEXT NOT NULL,
        avg_rtt_ms DOUBLE PRECISION,
        min_rtt_ms DOUBLE PRECISION,
        max_rtt_ms DOUBLE PRECISION,
        jitter_ms DOUBLE PRECISION,
        packet_loss_percent DOUBLE PRECISION
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS dns_measurements (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMPTZ NOT NULL,
        domain TEXT NOT NULL,
        dns_server TEXT NOT NULL,
        avg_time_ms DOUBLE PRECISION,
        min_time_ms DOUBLE PRECISION,
        max_time_ms DOUBLE PRECISION,
        success BOOLEAN NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS speedtest_results (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMPTZ NOT NULL,
        ping_ms DOUBLE PRECISION,
        download_mbps DOUBLE PRECISION,
        upload_mbps DOUBLE PRECISION,
        server_id TEXT,
        server_name TEXT
    );
    """)

    cur.close()
    conn.close()


def collect_ping_loop():
    conn = db_connect()
    while True:
        now = datetime.now(timezone.utc)
        try:
            hosts = multiping(PING_TARGETS, count=PING_COUNT, interval=0.2, timeout=2)
            rows = []
            for host in hosts:
                if host.packets_sent == 0:
                    continue
                loss_pct = 100.0 * (1 - host.packets_received / host.packets_sent)
                jitter = host.max_rtt - host.min_rtt if host.packets_received > 1 else 0.0
                rows.append((
                    now,
                    host.address,
                    host.avg_rtt,
                    host.min_rtt,
                    host.max_rtt,
                    jitter,
                    loss_pct
                ))

            if rows:
                with conn.cursor() as cur:
                    execute_values(cur, """
                        INSERT INTO ping_measurements
                        (ts, target_host, avg_rtt_ms, min_rtt_ms, max_rtt_ms, jitter_ms, packet_loss_percent)
                        VALUES %s
                    """, rows)
            print(f"[PING] {now.isoformat()} inserted {len(rows)} rows")
        except Exception as e:
            print(f"[PING] error: {e}")

        time.sleep(PING_INTERVAL)


def collect_dns_loop():
    conn = db_connect()
    resolver = dns.resolver.Resolver(configure=False)

    while True:
        now = datetime.now(timezone.utc)
        rows = []
        try:
            for domain in DNS_TARGETS:
                for server in DNS_SERVERS:
                    resolver.nameservers = [server]
                    times = []
                    success = True
                    for _ in range(DNS_QUERY_COUNT):
                        start = time.perf_counter()
                        try:
                            resolver.resolve(domain, "A", lifetime=5)
                            elapsed = (time.perf_counter() - start) * 1000.0
                            times.append(elapsed)
                        except Exception:
                            success = False
                            # still count timeout as max time
                            elapsed = (time.perf_counter() - start) * 1000.0
                            times.append(elapsed)
                    if times:
                        avg_t = sum(times) / len(times)
                        min_t = min(times)
                        max_t = max(times)
                        rows.append((now, domain, server, avg_t, min_t, max_t, success))

            if rows:
                with conn.cursor() as cur:
                    execute_values(cur, """
                        INSERT INTO dns_measurements
                        (ts, domain, dns_server, avg_time_ms, min_time_ms, max_time_ms, success)
                        VALUES %s
                    """, rows)
            print(f"[DNS] {now.isoformat()} inserted {len(rows)} rows")
        except Exception as e:
            print(f"[DNS] error: {e}")

        time.sleep(DNS_INTERVAL)


def collect_speedtest_loop():
    if not SPEEDTEST_ENABLED:
        print("[SPEEDTEST] disabled, exiting thread")
        return

    conn = db_connect()
    while True:
        now = datetime.now(timezone.utc)
        try:
            print("[SPEEDTEST] running...")
            st = speedtest.Speedtest()
            st.get_best_server()
            download_bps = st.download()
            upload_bps = st.upload()
            results = st.results.dict()

            ping_ms = results.get("ping")
            download_mbps = download_bps / (1024 * 1024)
            upload_mbps = upload_bps / (1024 * 1024)
            server = results.get("server", {}) or {}
            server_id = str(server.get("id")) if server.get("id") is not None else None
            server_name = server.get("name")

            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO speedtest_results
                    (ts, ping_ms, download_mbps, upload_mbps, server_id, server_name)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (now, ping_ms, download_mbps, upload_mbps, server_id, server_name))

            print(f"[SPEEDTEST] {now.isoformat()} ping={ping_ms}ms "
                  f"down={download_mbps:.2f}Mb/s up={upload_mbps:.2f}Mb/s")

        except Exception as e:
            print(f"[SPEEDTEST] error: {e}")

        time.sleep(SPEEDTEST_INTERVAL)


def main():
    print("[INIT] initializing schema...")
    init_schema()
    print("[INIT] starting probe loops")

    threads = [
        threading.Thread(target=collect_ping_loop, daemon=True),
        threading.Thread(target=collect_dns_loop, daemon=True),
        threading.Thread(target=collect_speedtest_loop, daemon=True),
    ]
    for t in threads:
        t.start()

    # Keep main thread alive
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
