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
## Screenshots
Config and live data:

* Python Default backend build and Docker Hub distrubuted image
<img width="1704" height="399" alt="image" src="https://github.com/user-attachments/assets/9b3dd3ae-bee2-4f3f-9cf8-e5f0d249d65a" />

* Ookla Backend Admin/User EULA must be accepted
<img width="1687" height="444" alt="image" src="https://github.com/user-attachments/assets/38538c10-24b5-4b52-8927-fd140aefb070" />

Internet Quality Score
<img width="1690" height="896" alt="image" src="https://github.com/user-attachments/assets/df1bbcad-aa2f-4182-ae4a-4b8c02d83249" />
Packet Loss (Avg)
<img width="1689" height="880" alt="image" src="https://github.com/user-attachments/assets/8105d9ad-dc49-4358-8be9-05679924f6db" />
Latency to Anchors (Avg)
<img width="1694" height="887" alt="image" src="https://github.com/user-attachments/assets/02b9afa7-badf-494d-8366-a78a9dddc2bc" />
Jitter (Avg)
<img width="1696" height="893" alt="image" src="https://github.com/user-attachments/assets/46ebbc41-370b-493b-8d4a-5ced3f44a41c" />
DNS Response Time (Avg)
<img width="1690" height="931" alt="image" src="https://github.com/user-attachments/assets/1a24db04-73c0-458a-97c1-e33902f4d586" />
Internet Bandwidth (Speedtest)
<img width="1700" height="923" alt="image" src="https://github.com/user-attachments/assets/e2f2a88e-3731-4e03-971f-ebe2b4daf357" />



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
  - Selectable backend: legacy Python `speedtest-cli` or official Ookla CLI.
  - Selectable HTTPS/secure or HTTP/non-secure discovery for the Python backend.
  - Automatic, single-server, or multi-server CSV-pool selection.
  - Global server exclusion list.
  - One-off manual “Force auto” control and friendly server-list mismatch errors.
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

## Quick start (Docker Run)

```bash
docker run -d \
  --name netprobe \
  --restart unless-stopped \
  -p 8080:8080 \
  -v /mnt/user/appdata/netprobe/database:/data \
  -e DB_ENGINE=sqlite \
  -e USE_POSTGRES=false \
  -e ROUTER_IP=192.168.1.1 \
  -e DNS_NAMESERVER_4="LAN_DNS" \
  -e DNS_NAMESERVER_4_IP=192.168.1.1 \
  bmmbmm01/netprobe
```

## Quick start (Docker Compose)

```yaml
# docker-compose.yml
services:
  netprobe:
    image: bmmbmm01/netprobe:latest
    #build: ./probe #github clone and build run your own...
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
      ROUTER_IP: 192.168.1.1

      DNS_TEST_SITE: google.com
      DNS_NAMESERVER_1: Google_DNS
      DNS_NAMESERVER_1_IP: 8.8.8.8
      DNS_NAMESERVER_2: Quad9_DNS
      DNS_NAMESERVER_2_IP: 9.9.9.9
      DNS_NAMESERVER_3: CloudFlare_DNS
      DNS_NAMESERVER_3_IP: 1.1.1.1
      DNS_NAMESERVER_4: My_DNS_Server
      DNS_NAMESERVER_4_IP: 192.168.1.1

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
      SPEEDTEST_BACKEND: python   # python or ookla
      # Required only when SPEEDTEST_BACKEND=ookla after reviewing and
      # accepting Ookla's EULA, Terms of Use, and Privacy Policy:
      SPEEDTEST_OOKLA_ACCEPT_LICENSE: ""  # set I_ACCEPT after review
      SPEEDTEST_OOKLA_ACCEPTANCE_FILE: /data/ookla-eula-accepted.txt
      SPEEDTEST_SECURE: "True"    # Python backend only: HTTPS vs HTTP list
      SPEEDTEST_SERVER: ""        # optional legacy single-server ID
      SPEEDTEST_CSV: "False"      # true = use SPEEDTEST_CSV_SERVERS
      SPEEDTEST_CSV_SERVERS: ""   # example: 2,12345,23456
      SPEEDTEST_EXCLUDE: ""       # example: 46408,4392
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

** Both Quick Starts use the sqlfile option for longterm persitent data... Postgres backend changeover is available via additional docker options later

---
## Environment variables

| Variable                  | Default                                      | Description                                                                   |
|---------------------------|----------------------------------------------|-------------------------------------------------------------------------------|
| `WEB_PORT`                | `8080`                                       | Port inside container for the web UI / API.                                   |
| `DB_PATH`                 | `/data/netprobe.sqlite`                      | SQLite DB path (used when `DB_ENGINE=sqlite`).                                |
| `DB_ENGINE`               | `sqlite`                                     | Database backend: `sqlite` or `postgres`.                                     |
| `USE_POSTGRES`            | *(empty)*                                    | Legacy flag; if `true`, forces Postgres unless `DB_ENGINE` is set.            |
| `POSTGRES_HOST`           | `postgres`                                   | Postgres host when `DB_ENGINE=postgres` or `USE_POSTGRES=true`.               |
| `POSTGRES_PORT`           | `5432`                                       | Postgres TCP port.                                                            |
| `POSTGRES_DB`             | `netprobe`                                   | Postgres database name.                                                       |
| `POSTGRES_USER`           | `netprobe`                                   | Postgres username.                                                            |
| `POSTGRES_PASSWORD`       | `netprobe`                                   | Postgres password.                                                            |
| `PROBE_INTERVAL`          | `30`                                         | Seconds between probe runs.                                                   |
| `PING_COUNT`              | `20`                                         | ICMP packets per target per probe.                                            |
| `APP_TIMEZONE`            | `UTC`                                        | Label shown in UI (no TZ conversion yet).                                     |
| `SITES`                   | `fast.com,google.com,youtube.com,amazon.com` | Comma-separated ping targets.                                                 |
| `ROUTER_IP`               | *(empty)*                                    | Optional LAN router IP.                                                       |
| `DNS_TEST_SITE`           | `google.com`                                 | Domain for DNS latency tests.                                                 |
| `DNS_NAMESERVER_1..4`     | *(labels)*                                   | Human-readable DNS names for UI.                                              |
| `DNS_NAMESERVER_1..4_IP`  | *(IPs)*                                      | DNS IPs to probe.                                                             |
| `WEIGHT_LOSS`             | `0.6`                                        | Weight of packet loss in score (0–1, sum = 1).                                |
| `WEIGHT_LATENCY`          | `0.15`                                       | Weight of latency.                                                            |
| `WEIGHT_JITTER`           | `0.2`                                        | Weight of jitter.                                                             |
| `WEIGHT_DNS_LATENCY`      | `0.05`                                       | Weight of DNS latency.                                                        |
| `THRESHOLD_LOSS`          | `5`                                          | Loss % considered “max bad” for scoring.                                      |
| `THRESHOLD_LATENCY`       | `100`                                        | Latency ms considered “max bad”.                                              |
| `THRESHOLD_JITTER`        | `30`                                         | Jitter ms considered “max bad”.                                               |
| `THRESHOLD_DNS_LATENCY`   | `100`                                        | DNS ms considered “max bad”.                                                  |
| `SPEEDTEST_ENABLED`       | `True`                                       | Enable periodic speedtests.                                                   |
| `SPEEDTEST_INTERVAL`      | `14400`                                      | Seconds between automatic speedtests.                                         |
| `SPEEDTEST_BACKEND`       | `python`                                     | `python` for the legacy Python client or `ookla` for the official CLI.        |
| `SPEEDTEST_OOKLA_ACCEPT_LICENSE` | `""`                                | Runtime acknowledgement. Set `I_ACCEPT` only after the end user reviews Ookla's documents. |
| `SPEEDTEST_OOKLA_ACCEPTANCE_FILE` | `/data/ookla-eula-accepted.txt`      | Persistent marker written by the interactive acknowledgement helper.          |
| `SPEEDTEST_OOKLA_PATH`    | `/usr/bin/speedtest`                         | Path to the official Ookla CLI binary.                                        |
| `SPEEDTEST_OOKLA_TIMEOUT` | `180`                                        | Timeout in seconds for an official Ookla CLI process.                         |
| `SPEEDTEST_SECURE`        | `True`                                       | Python backend only: use HTTPS discovery; HTTP can return different IDs.      |
| `SPEEDTEST_SERVER`        | `""`                                         | Optional Speedtest server ID. Leave blank to use automatic server selection.  |
| `SPEEDTEST_CSV`           | `False`                                      | When true, use the multi-server CSV pool instead of `SPEEDTEST_SERVER`.       |
| `SPEEDTEST_CSV_SERVERS`   | `""`                                         | Candidate server pool. Accepts `12345,23456` or `2,12345,23456`.              |
| `SPEEDTEST_EXCLUDE`       | `""`                                         | Comma-separated server IDs excluded from every Speedtest selection mode.      |
| `LIVE_LOG_POLL_SECONDS`   | `2`                                          | Seconds between live log viewer refreshes in the web UI.                      |

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
  - speedtest backend, mode, candidate pool, exclusions, and Ookla availability.

- `GET /api/speedtest/history?limit=N`
  Speedtest history, newest → oldest, each with:
  - `ts`, `iso`
  - `ping_ms`
  - `download_mbps`, `upload_mbps`
  - `server_id`, `server_name`, `server_host`, `server_country`
  - `requested_server_id`, `requested_server_ids`, and `backend`.

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
      "backend": "ookla",
      "protocol": "ookla",
      "selection_mode": "csv",
      "requested_server_id": "12345,23456",
      "requested_server_ids": ["12345", "23456"],
      "excluded_server_ids": ["46408"],
      "server": {
        "id": "23456",
        "name": "Example ISP",
        "host": "speed.example.com",
        "country": "US"
      }
    }
  }
  ```

---

## Find a Speedtest Server ID

NetProbe contains two different clients, and each client can expose a different
server catalog.

### Python backend

```bash
docker exec -it netprobe speedtest-cli --secure --list
```

Use IDs from this list when `SPEEDTEST_BACKEND=python`. The Python client's HTTP
and HTTPS catalogs may also differ, so match the list command to
`SPEEDTEST_SECURE`.

### Official Ookla backend

```bash
docker exec -it netprobe speedtest \
  --accept-license \
  --accept-gdpr \
  --servers
```

Use IDs from this list when `SPEEDTEST_BACKEND=ookla`. Modern IDs obtained from
Ookla web/embed configurations are more likely to work with this backend than
with the archived Python client.

The two binaries are intentionally separate:

```text
/opt/venv/bin/speedtest-cli   Python implementation
/usr/bin/speedtest            Official Ookla CLI
```

### Speedtest server-selection modes

The web UI includes a backend selector for one-off manual tests. Scheduled tests
use `SPEEDTEST_BACKEND`.

- **Python backend:** preserves the existing secure/HTTP selector, native CSV
  candidate filtering, and native exclusion filtering.
- **Ookla backend:** uses Ookla's native protocol. The Secure / HTTPS checkbox
  is disabled. Fixed IDs use `--server-id`. CSV mode tries official candidates
  in nearest-list order and falls back through the configured IDs. Automatic
  mode with exclusions selects the first allowed server from `speedtest --servers`.

Netprobe resolves the server mode in this order:

1. “Force auto” checked in the web UI for a one-off automatic run.
2. A server ID typed into the web UI for a one-off manual run.
3. `SPEEDTEST_CSV=True` and the IDs in `SPEEDTEST_CSV_SERVERS`.
4. The legacy single ID in `SPEEDTEST_SERVER`.
5. Automatic best-server selection.

`SPEEDTEST_SECURE=True` applies only to the Python backend and uses its
HTTPS/secure server list. Set it to `False` to use that client's legacy HTTP
list. The official Ookla backend uses its native protocol and ignores this
setting. The web UI can override the backend and Python protocol for a single
manual run, plus **Force auto** can ignore the configured server or pool.

`SPEEDTEST_EXCLUDE` is applied in every mode. If an ID is both selected and
excluded, the test stops with a clear configuration error instead of silently
using a different server.

#### Automatic selection with exclusions

```env
SPEEDTEST_CSV=False
SPEEDTEST_SERVER=
SPEEDTEST_EXCLUDE=46408,4392
```
* Exaggerated examples, they may not be real server IDs

#### Force one server

```env
SPEEDTEST_CSV=False
SPEEDTEST_SERVER=12345
SPEEDTEST_EXCLUDE=
```
* Exaggerated examples, they may not be real server IDs

#### Use a fallback pool of servers

The counted CSV format starts with the number of server IDs:

```env
SPEEDTEST_CSV=True
SPEEDTEST_CSV_SERVERS=2,12345,23456
SPEEDTEST_EXCLUDE=46408
```
* meaning set the number of servers and comma-separate the speedtest id
* Exaggerated examples, they may not be real server IDs

The plain CSV form is also accepted:

```env
SPEEDTEST_CSV_SERVERS=12345,23456
```
* Exaggerated examples, they may not be real server IDs

With the Python backend, the library retrieves the configured candidates and
tests latency to the available matches before selecting the best one. With the
Ookla backend, NetProbe orders matching candidates from the official
`speedtest --servers` result and tries configured fallbacks if necessary.

## Official Ookla terms and acceptance

NetProbe remains MIT licensed, but the optional official Ookla CLI is separate
third-party proprietary software. Before enabling the Ookla backend, review the
current official documents:

- Ookla EULA: https://www.speedtest.net/about/eula
- Speedtest Terms of Use: https://www.speedtest.net/about/terms
- Ookla Privacy Policy: https://www.speedtest.net/about/privacy

The backend stays disabled by default through `SPEEDTEST_BACKEND=python`.
The Docker build never runs the Ookla executable and never pre-accepts its
terms. Before NetProbe invokes the official CLI, the end user must acknowledge
the current documents at runtime using either method below.

Non-interactive Unraid/Docker environment:

```env
SPEEDTEST_OOKLA_ACCEPT_LICENSE=I_ACCEPT
```

Interactive acknowledgement stored in the persistent `/data` volume:

```bash
docker exec -it netprobe netprobe-ookla-accept
```

The helper displays the EULA, Terms, and Privacy links and requires the user to
type `I ACCEPT`. NetProbe then passes the official CLI's `--accept-license` and
`--accept-gdpr` flags when a test is actually run. The acknowledgement can be
removed with `netprobe-ookla-accept --revoke`.

## Enable the official Ookla backend

The Dockerfile can install Ookla's official package on supported Debian
architectures, but the build option defaults to `false`. This path is intended
for a local/private personal home-lab build. Do not push an image containing the
Ookla executable to a public registry unless you have separate written
permission that allows redistribution.

Build a private local image with the official binary:

```bash
DOCKER_BUILDKIT=1 docker build --pull --no-cache \
  --build-arg INSTALL_OOKLA_SPEEDTEST=true \
  -t bmmbmm01/netprobe:ookla-test ./probe
```

Then enable the backend at runtime only after accepting Ookla's current EULA,
Terms of Use, and Privacy Policy:

```env
SPEEDTEST_BACKEND=ookla
SPEEDTEST_OOKLA_ACCEPT_LICENSE=I_ACCEPT
SPEEDTEST_SERVER=23151
```

The runtime acknowledgement allows NetProbe to pass both `--accept-license`
and `--accept-gdpr` to the official CLI for that deployment. It does not
relicense the Ookla binary or grant redistribution or commercial-use rights.

Verify both clients inside the container:

```bash
docker exec -it netprobe speedtest-cli --version
docker exec -it netprobe speedtest --version
```

See `OOKLA_BACKEND_NOTICE.md` and `THIRD_PARTY_NOTICES.md` for the licensing
boundary, official terms links, runtime acceptance behavior, and distribution
notes.

## Troubleshooting

### Charts all show 100% loss / very high latency

- Let it run for 5 min... internet average takes time to build per default weights...
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
  Speedtest: ping=… down=… up=…
  ```

- Remember automatic runs only happen every SPEEDTEST_INTERVAL seconds. (by default every 4 hours) you can manuly run or set this interval in the docker env...)
- Use the Run Speedtest Now button in the UI to verify it works on demand

---

## License

NetProbe source code is licensed under the MIT License. The official Ookla
`speedtest` binary, when installed in the image, is third-party proprietary
software governed by Ookla's separate terms and is not relicensed under MIT.
See `THIRD_PARTY_NOTICES.md`.
