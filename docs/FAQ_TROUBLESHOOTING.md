# FAQ and troubleshooting — NetProbe 2.1 (development)

This guide covers the **new NetProbe 2.1 single-container image** with Nginx HTTPS, Flask/Gunicorn, WebUI-managed settings and a single application `/config` mount. It updates the [original NetProbe troubleshooting notes](https://github.com/bmartino1/NetProbe_Python#troubleshooting). Commands assume the container is named `netprobe`; for the PostgreSQL stack add `-f compose-postgress.yaml` to Compose commands.

> Start with `docker compose ps` and `docker compose logs --tail=150 netprobe`. On Debian/Proxmox LXC, verify Docker nesting and host networking before troubleshooting the probe itself.

## FAQ: bridge networking, macvlan and ipvlan

**Do I need macvlan/ipvlan?** No. Docker bridge with `NET_RAW` is the supported first-test configuration. It uses NAT and the container's own bridge gateway, which may **not** be your physical LAN router. Don't interpret a fast ping to the Docker bridge gateway as a measurement of your actual LAN router. Set the router target under Settings to monitor the intended LAN gateway.

**Will bridge networking reduce Speedtest results?** NAT/virtual networking can affect measurements, but do not assume a throughput problem is caused by bridge mode. Compare repeated host and container tests using the **same backend, protocol and server**, during comparable periods. Check CPU limits, LXC networking, DNS, host firewall and offloading before changing network mode.

**Can I use macvlan/ipvlan?** Yes, as an advanced Docker host-side override, with a suitable LAN subnet/gateway and a free IP. This repo does not ship a ready-to-run macvlan setup because those values are deployment-specific. The Docker host may not communicate directly with macvlan containers without extra routing. Do **not** enable `privileged`, `SYS_ADMIN`, or `NET_ADMIN` simply to make ICMP monitoring work; start with `NET_RAW` and increase privileges only for a demonstrated need. Proxmox LXC must also permit the selected Docker networking driver.

## WebUI inaccessible, setup code missing, or HTTPS warning

```sh
docker compose ps
docker compose logs --tail=150 netprobe
docker exec netprobe nginx -t
docker exec netprobe sh -c 'ls -ld /config /config/tls /config/data && ls -l /config/tls'
```

Open `https://HOST_IP:8443/setup` on first boot. Nginx redirects container port 80 to HTTPS 8443; with a different published HTTPS port, the redirect configuration must be adjusted. The generated certificate is self-signed, so browser warnings are expected for local testing. The entrypoint creates a fallback pair only when both files are missing; an incomplete or mismatched certificate/key pair stops startup. Inspect entrypoint logs rather than deleting TLS keys blindly. The one-time setup code appears in the container logs; keep those logs private.

## Charts show 100% packet loss or high latency

Allow several probe cycles before judging the graph; the old recommendation was about five minutes. Then check from inside the container:

```sh
docker exec netprobe ping -c 3 8.8.8.8
docker exec netprobe ping -c 3 google.com
docker exec netprobe ip route
docker inspect netprobe --format '{{json .HostConfig.CapAdd}}'
```

If IP ping fails, investigate Docker/LXC ICMP permission, network route and host firewall. If IP ping works but hostname ping fails, troubleshoot DNS. Review the configured router IP and targets in **Settings**, and check whether ICMP is intentionally blocked by a remote host. A target that refuses ping should not automatically be treated as proof the internet connection is down. The default Compose grants `NET_RAW`; extra elevated capabilities are not a default requirement.

## DNS chart empty or flat

```sh
docker exec netprobe nslookup google.com 8.8.8.8
docker exec netprobe cat /etc/resolv.conf
docker compose logs --tail=150 netprobe
```

Check the nameserver IPs under **Settings**, the test domain, and that outbound UDP/TCP 53 is permitted. DNS servers may decline external queries. Use **Show Current Configuration** to confirm which settings the application reports; the old **Show Config / Env** label was renamed.

## Speedtest is disabled, slow, failing, or selecting the wrong server

Open **Settings → Speedtest backend readiness** first. Check whether the selected client is installed, terms are acknowledged for Ookla, and whether a database or backend selection restart is pending. Check the current interval and enable toggle in the WebUI; the factory automatic interval is **14,400 seconds (4 hours)**. A manual run is useful to verify behavior without waiting four hours.

```sh
docker compose logs --tail=200 netprobe
docker exec netprobe speedtest-cli --version
docker exec netprobe sh -c 'command -v speedtest || true'
```

Python `speedtest-cli` and official Ookla `speedtest` are **different programs**. The open-source Python backend is installed in the image; the separate official Ookla binary is **not bundled** and requires administrator acceptance/installation. Read [OOKLA_BACKEND_NOTICE.md](OOKLA_BACKEND_NOTICE.md) before enabling the official backend.

**A preferred server ID disappears / reports NoMatchedServers:** The Python client's `--secure --list` and `--list` can return different server catalogs. IDs from a modern Ookla embed API may not be discoverable using the older Python client. Only list servers when diagnosing an issue—rapid repeated requests may be rate-limited with HTTP 403.

```sh
docker exec netprobe speedtest-cli --secure --list
# Wait before requesting another list; this uses non-secure discovery:
docker exec netprobe speedtest-cli --list
```

Use an ID found through the **same protocol** as the manual run, or use **Force auto**, the candidate pool or server exclusions from Settings. If comparing host vs container, keep the backend and selected server the same. See [original issue #4](https://github.com/bmartino1/NetProbe_Python/issues/4); the detailed regression checklist is retained in the private engineering archive.

## Manual tests versus scheduled monitoring

Use **Controls & diagnostics → Manual test** to run a temporary ICMP ping or DNS A lookup. Pick a target from configured monitoring settings, or type a different hostname/IP without changing the ongoing probe. Choose a configured DNS resolver for one-off DNS tests. The result and its UTC timestamp are stored separately in `/config/data/manual_tests.sqlite` (inside the one optional `/config` mount).

Authenticated JSON endpoints:

- `GET /api/manual/targets` — current configured ping targets, DNS domains and resolvers.
- `POST /api/manual/run` — one-off test; JSON body `{"kind":"ping","target":"example.com","count":3}` or `{"kind":"dns","target":"example.com","resolver":"1.1.1.1"}`.
- `GET /api/manual/history?limit=50` — up to 500 most recent manual ping/DNS results, distinct from scheduled monitoring.

The read-only bearer token used for Grafana-style access can retrieve `/api/manual/history`, but cannot trigger tests. Manual test failures are retained as records too. Scheduled history and its quality score remain independent. The existing `/api/speedtest/run` and `/api/speedtest/history` are separate Speedtest endpoints; do not assume the latter contains only scheduled runs.

## PostgreSQL cannot connect or data seems missing

For the integrated PostgreSQL stack:

```sh
docker compose -f compose-postgress.yaml ps
docker compose -f compose-postgress.yaml logs --tail=150 postgres
docker compose -f compose-postgress.yaml logs --tail=150 netprobe
docker compose -f compose-postgress.yaml exec postgres pg_isready -U netprobe -d netprobe
```

Use **Settings → Database connection → Test PostgreSQL Connection** for a read-only connection test when the WebUI is accessible. A healthy database process does not guarantee credentials or the requested database are correct. External PostgreSQL hosts must be reachable from the Docker container—not simply from the browser or the Docker host.

NetProbe retains `/config/data/netprobe.sqlite` as a local fallback. Switching engines **does not copy history**; missing old records after a switch may simply belong to the other database. Back up both stores before changing engines. Do not run both Compose variants concurrently. For PostgreSQL, keep the local `.env` containing `POSTGRES_PASSWORD` private.

## Docker environment differs from WebUI settings

**The saved WebUI configuration is the source of truth.** Values in Docker `-e`, Compose `environment:`, Unraid template variables or optional `env_file` only seed monitoring settings when `/config/settings.json` is first created. After that, changing or restarting with Docker variables does **not** override saved monitoring choices.

The Settings page warns about differing Docker variables by **name only**. If you changed a setting in the WebUI, remove the stale Docker/Unraid environment entry or update it to match your saved preference. Do not delete `/config/settings.json` just to silence the warning; that would reset your saved configuration. Database deployment controls such as `DB_ENGINE` and the initial `POSTGRES_*` connection values are separate infrastructure options, not WebUI monitoring overrides. Never paste database passwords into support logs.

Check saved configuration and environment cautiously:

```sh
docker exec netprobe sh -c 'ls -l /config/settings.json'
docker compose config --no-interpolate
```

The second command can reveal secrets in your Compose file; review locally and **do not post its unredacted output**.

## Settings changes, persistence, and backup

Monitoring/DNS/quality/Speedtest settings are saved to `/config/settings.json` and applied live. A **database engine change still requires a controlled restart**. PostgreSQL credentials are stored separately under `/config/database.json`. Runtime files live under a single optional `/config` mount, including `/config/data/netprobe.sqlite` and TLS keys. A mount-free `docker run` works for disposable testing, but deleting/recreating the container loses its writable-layer data. Back up `/config` plus the **separate PostgreSQL server data** when using PostgreSQL; never copy a live SQLite file as your only verified backup.

```sh
docker exec netprobe sh -c 'ls -la /config /config/data /config/tls'
docker inspect netprobe --format '{{json .Mounts}}'
```

## First LXC test: quick diagnostic collection

```sh
docker version
docker compose version
docker compose config
docker compose ps
docker compose logs --tail=150 netprobe
docker exec netprobe sh -c 'python --version; command -v ping; command -v speedtest-cli'
```

When requesting support, include the exact image commit, Docker/Compose versions, selected database backend, network mode, symptom, and relevant **redacted** logs. Never share `.env`, `/config/database.json`, `session.key`, administrator hashes, the setup code, or an unredacted configuration dump.
