# Netprobe 2.0 – Internet Quality Dashboard

Netprobe 2.0 is a lightweight, container-friendly network probe and web UI for
home / lab internet monitoring.

It periodically:

- Pings your gateway, router and a list of “anchor” sites.
- Measures packet loss, latency and jitter.
- Measures DNS lookup latency **per DNS server**.
- Runs scheduled and manual Speedtest.net tests.
- Stores everything in SQLite and renders a dark-mode dashboard with Chart.js.

The goal is a simple “drop in and forget it” quality monitor that you can
run on Unraid, Proxmox, Docker, etc.

---

## Features

- **Internet Quality Score (0–100)**  
  Weighted composite of loss, latency, jitter and DNS response time.

- **Per-metric panels**
  - Packet Loss
  - Latency to anchors
  - Jitter
  - DNS Response Time (with lines + checkboxes for each configured DNS server)
  - Bandwidth (download / upload history from speedtest)

- **History controls**  
  Time selector on each chart (seconds → months).

- **Panel toggles**  
  Checkboxes to show/hide sections (Internet Quality, Loss, Latency, Jitter,
  DNS, Bandwidth). Preference is saved in `localStorage` per browser.

- **Speedtest integration**
  - Automatic periodic runs (`SPEEDTEST_INTERVAL`).
  - “Run Speedtest Now” button in UI.
  - Last result summary in the top status bar.
  - Download / upload charts.

- **SQLite storage**
  - `measurements` – aggregate probe results.
  - `dns_measurements` – per-DNS-server latency per probe.
  - `speedtests` – speedtest history.

- **Single-container deployment**
  - Flask + Gunicorn backend
  - Chart.js frontend
  - Works nicely with Docker Compose and Unraid templates.

---

## How it works

Every `PROBE_INTERVAL` seconds the probe loop:

1. Detects the container’s default gateway.
2. Pings:
   - Default gateway (inside Docker network)
   - Optional `ROUTER_IP` (your LAN router)
   - Each hostname in `SITES`
3. Computes average latency, jitter (max–min) and packet loss across all ping
   targets.
4. For each configured DNS server (`DNS_NAMESERVER_X_IP`), it measures the
   time to resolve `DNS_TEST_SITE` several times and averages the result.
5. Computes an **Internet Quality Score** using weighted, threshold-normalized
   metrics.
6. Stores:
   - Aggregate metrics in `measurements`
   - Per-server DNS results in `dns_measurements`

Separately, a periodic task runs `speedtest` when at least
`SPEEDTEST_INTERVAL` seconds have passed since the last run and stores the
result in `speedtests`.

The frontend polls the APIs (JSON) and renders gauges + history charts.

---

## Quick start (Docker Compose)

```yaml
# docker-compose.yml
services:
  netprobe:
    build: ./probe
    container_name: netprobe
    restart: unless-stopped

    # Optional: use a separate env file instead of inline vars
    # env_file:
    #   - ./probe/config.env

    environment:
      WEB_PORT: 8080
      DB_PATH: /data/netprobe.sqlite
      PROBE_INTERVAL: 60
      PING_COUNT: 4

      SITES: fast.com,google.com,youtube.com
      ROUTER_IP: 192.168.2.1

      DNS_TEST_SITE: google.com
      DNS_NAMESERVER_1: Google_DNS
      DNS_NAMESERVER_1_IP: 8.8.8.8
      DNS_NAMESERVER_2: Quad9_DNS
      DNS_NAMESERVER_2_IP: 9.9.9.9
      DNS_NAMESERVER_3: CloudFlare_DNS
      DNS_NAMESERVER_3_IP: 1.1.1.1
      DNS_NAMESERVER_4: My_DNS_Server
      DNS_NAMESERVER_4_IP: 192.168.2.3

      WEIGHT_LOSS: 0.6
      WEIGHT_LATENCY: 0.15
      WEIGHT_JITTER: 0.2
      WEIGHT_DNS_LATENCY: 0.05

      THRESHOLD_LOSS: 5
      THRESHOLD_LATENCY: 100
      THRESHOLD_JITTER: 30
      THRESHOLD_DNS_LATENCY: 100

      SPEEDTEST_ENABLED: "True"
      SPEEDTEST_INTERVAL: 14400   # 4 hours
      APP_TIMEZONE: UTC

    ports:
      - "8080:8080"

    volumes:
      - netprobe_data:/data

    cap_add:
      - NET_RAW
      - NET_ADMIN
      - SYS_ADMIN

volumes:
  netprobe_data:
```

---
## Environment variables

| Variable                    | Default                                      | Description                                                  |
|----------------------------|----------------------------------------------|--------------------------------------------------------------|
| `WEB_PORT`                 | `8080`                                       | Port inside container for the web UI / API.                 |
| `DB_PATH`                  | `/data/netprobe.sqlite`                      | SQLite DB path.                                             |
| `PROBE_INTERVAL`           | `30`                                         | Seconds between probe runs.                                 |
| `PING_COUNT`               | `20`                                         | ICMP packets per target per probe.                          |
| `APP_TIMEZONE`             | `UTC`                                        | Label shown in UI (no TZ conversion yet).                   |
| `SITES`                    | `fast.com,google.com,youtube.com,amazon.com` | Comma-separated ping targets.                               |
| `ROUTER_IP`                | *(empty)*                                    | Optional LAN router IP.                                     |
| `DNS_TEST_SITE`            | `google.com`                                 | Domain for DNS latency tests.                               |
| `DNS_NAMESERVER_1..4`      | *(labels)*                                   | Human-readable DNS names for UI.                            |
| `DNS_NAMESERVER_1..4_IP`   | *(IPs)*                                      | DNS IPs to probe.                                           |
| `WEIGHT_LOSS`              | `0.6`                                        | Weight of packet loss in score (0–1, sum = 1).              |
| `WEIGHT_LATENCY`           | `0.15`                                       | Weight of latency.                                          |
| `WEIGHT_JITTER`            | `0.2`                                        | Weight of jitter.                                           |
| `WEIGHT_DNS_LATENCY`       | `0.05`                                       | Weight of DNS latency.                                      |
| `THRESHOLD_LOSS`           | `5`                                          | Loss % considered “max bad” for scoring.                    |
| `THRESHOLD_LATENCY`        | `100`                                        | Latency ms considered “max bad”.                            |
| `THRESHOLD_JITTER`         | `30`                                         | Jitter ms considered “max bad”.                             |
| `THRESHOLD_DNS_LATENCY`    | `100`                                        | DNS ms considered “max bad”.                                |
| `SPEEDTEST_ENABLED`        | `True`                                       | Enable periodic speedtests.                                 |
| `SPEEDTEST_INTERVAL`       | `14400`                                      | Seconds between automatic speedtests.                       |

You can also put these in `config.env` and uncomment `env_file` in the
Compose file.

---

## API code overview...

The frontend uses these JSON endpoints (you can also query them yourself by calling the python venv...):

- `GET /` – main UI.
- `GET /api/score/recent?limit=N`  
  Recent aggregate data. Each row includes:
  - `ts`, `iso`
  - `avg_latency_ms`, `avg_jitter_ms`, `avg_loss_pct`
  - `avg_dns_latency_ms`
  - `score` (0–100)
  - `dns_per_server` – optional `{ "<dns_ip>": latency_ms }` map.

- `GET /api/score/latest`  
  Most recent probe (same fields as above).

- `GET /api/config`  
  Effective configuration (after env overrides), including:
  - probe interval, ping count, timezone label
  - resolved gateway IP
  - router IP
  - sites
  - DNS test site
  - `dns_servers_detail` – list of `{ name, ip }`
  - weights / thresholds
  - speedtest settings.

- `GET /api/speedtest/history?limit=N`  
  Speedtest history, newest → oldest, each with:
  - `ts`, `iso`
  - `ping_ms`
  - `download_mbps`, `upload_mbps`
  - `server_name`, `server_host`, `server_country`.

- `GET /api/speedtest/latest`  
  Most recent speedtest result.

- `POST /api/speedtest/run`  
  Trigger an immediate speedtest. Returns:
  ```json
  {
    "success": true,
    "result": {
      "timestamp": 1234567890,
      "ping_ms": 6.1,
      "download_mbps": 100.0,
      "upload_mbps": 20.0,
      "server": {
        "name": "Example ISP",
        "host": "speed.example.com",
        "country": "US"
      }
    }
  }

---

## Troubleshooting

### Charts all show 100% loss / very high latency

- Let it run for 5 min... internet average takes time to build per defualt weights...
- Ensure the container has the needed capabilities:
  - `NET_RAW`, `NET_ADMIN`, `SYS_ADMIN`
- From the host, verify basic connectivity from inside the container:
  ```bash
  docker exec -it netprobe ping -c 3 8.8.8.8
  ```
  
- If this fails, fix host networking / firewall before debugging Netprobe.

---

### DNS panel is flat or empty

- Confirm `DNS_TEST_SITE` resolves inside the container:

  ```bash
  docker exec -it netprobe nslookup google.com 8.8.8.8
  ```


- Verify that `DNS_NAMESERVER_X_IP` values are correct and reachable.
- Click **Show Config / Env** in the UI to confirm DNS servers are parsed as expected.

### Speedtest never runs

- Check that:

```bash
echo $SPEEDTEST_ENABLED
# should be: True
```

- Look at logs:

```bash
docker logs netprobe
```

- You should see lines like:
  ```
  You should see lines like:
  ```

- Remember automatic runs only happen every SPEEDTEST_INTERVAL seconds. (by default every 4 hours) you can manuly run or set this interval in the docker env...)(
- Use the Run Speedtest Now button in the UI to verify it works on demand
