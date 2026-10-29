# NetProbe 2.1

**Self-hosted network quality monitoring with a browser dashboard, live diagnostics, historical charts, and optional Speedtest.**

[![Docker Hub](https://img.shields.io/badge/Docker%20Hub-bmmbmm01%2Fnetprobe-blue?logo=docker)](https://hub.docker.com/r/bmmbmm01/netprobe)
[![GitHub](https://img.shields.io/badge/Source-bmartino1%2FNetProbe__Python-181717?logo=github)](https://github.com/bmartino1/NetProbe_Python)

NetProbe monitors connectivity with scheduled **Ping/ICMP, DNS lookup timing, packet loss, latency, jitter, and an overall connection quality score**. It can also measure upload/download speeds using Python `speedtest-cli` or the separately installed official Ookla Speedtest CLI. Results are available in a responsive HTTPS WebUI with guest read-only access and administrator controls.

> **Release note:** This README describes the tested NetProbe **2.1** implementation. Publish the matching 2.1 application files and Docker image **before** presenting this documentation as the active `latest` release. The legacy `latest` image might not have these features until it is replaced.

## Features

- **First-run WebUI setup:** create an administrator account, sign in, then select monitoring targets and defaults. Scheduled probes stay paused until monitoring setup is completed.
- **Read-only guest dashboard:** Overview, Metrics, Speedtest, History, Customize Display, and Current Configuration without administrator privileges.
- **Administrator tools:** run manual Ping/DNS diagnostics, inspect live logs, edit monitoring settings, select a database, manage the password policy, and restart the application worker.
- **History and customization:** trend charts for quality, packet loss, latency, jitter, DNS, and bandwidth; show or hide summary cards and charts locally in each browser.
- **Speedtest backends:** Python `speedtest-cli` included by default. Optional official Ookla CLI requires explicit terms acknowledgement and an administrator-triggered runtime install; the proprietary binary is not bundled.
- **SQLite or PostgreSQL:** SQLite works out of the box. An alternative Compose file starts PostgreSQL 16 and NetProbe together; external PostgreSQL is also supported.
- **Single NetProbe configuration mount:** persist application settings, credentials, TLS certificates, and SQLite data at `/config`.
- **HTTPS interface:** Nginx reverse proxy in front of Flask/Gunicorn with a self-signed fallback certificate for trusted local use.

## Screenshots

<!-- Add screenshots to docs/screenshots/ when ready. Suggested names:
01-setup-account.png, 02-login.png, 03-monitoring-setup.png,
04-guest-overview.png, 05-metrics.png, 06-speedtest.png,
07-history.png, 08-customize-display.png, 09-admin-settings.png.
Replace this comment with a compact screenshot gallery, e.g.:
![NetProbe Overview](docs/screenshots/04-guest-overview.png)
![NetProbe Metrics](docs/screenshots/05-metrics.png)
Do not expose passwords, authentication tokens, or sensitive hostnames/IP addresses.
-->

## Quick start — SQLite (recommended)

The repository provides `compose.yaml` for a local SQLite deployment. **No `.env` file is required.**

```bash
git clone https://github.com/bmartino1/NetProbe_Python.git
cd NetProbe_Python

docker compose -f compose.yaml up -d --build
docker compose -f compose.yaml ps
```

Open `https://YOUR_SERVER_IP:8443/setup` and follow the two setup stages:

1. Create your administrator username and password (factory minimum: **8 characters**).
2. Sign in and configure sites, router IP, Ping count, DNS tests, scoring thresholds, and Speedtest options.

The monitoring engine does not begin scheduled probes until the configuration wizard completes. Visit `https://YOUR_SERVER_IP:8443/` afterward to use the dashboard. The default certificate is self-signed, so browsers may warn until you install a certificate they trust.

By default, Compose exposes **HTTPS on host port 8443** and an **HTTP redirect on host port 8080**. Both can be changed through `NETPROBE_HTTPS_PORT` and `NETPROBE_HTTP_PORT` in an untracked `.env` file.

To check startup and health:

```bash
docker compose -f compose.yaml ps
docker compose -f compose.yaml logs --tail=100 netprobe
```

### Docker Hub image

When the matching 2.1 image has been published, you can run it without building from source:

```bash
docker run -d \
  --name netprobe \
  --restart unless-stopped \
  --init \
  --cap-add NET_RAW \
  -p 8080:80 -p 8443:8443 \
  -v netprobe_config:/config \
  bmmbmm01/netprobe:latest
```

**Check that `bmmbmm01/netprobe:latest` actually points to the 2.1 release before using this command.** For reproducible deployments, prefer a published version tag (for example, `:2.1.0`) once available. A persistent `/config` mount is strongly recommended; omitting it loses settings and measurement history when the container is recreated.

## WebUI access

| Area | Guest (read-only) | Administrator |
| --- | :---: | :---: |
| Overview and connection quality | Yes | Yes |
| Ping/DNS Metrics | Yes | Yes |
| Speedtest results and history | Yes | Yes |
| Monitoring history and charts | Yes | Yes |
| Customize display | Yes | Yes |
| Current configuration | Yes | Yes |
| Run manual diagnostics / Speedtest | No | Yes |
| Live Logs & Diagnostics | No | Yes |
| Change settings, database profile, password policy | No | Yes |

Display customization is stored in the current browser and does **not** change collection settings or delete historical measurements. For unattended installs with known-good settings, `NETPROBE_AUTOSTART_CONFIGURED=true` explicitly permits starting monitoring before completing the wizard; leave it disabled for interactive first-run setup.

## Speedtest backends

**Python `speedtest-cli`** is included and requires no separate license acknowledgement in the WebUI. **Official Ookla CLI** is optional: the administrator selects it during setup or in Settings, reviews [Ookla EULA](https://www.speedtest.net/about/eula), [Terms](https://www.speedtest.net/about/terms), and [Privacy Policy](https://www.speedtest.net/about/privacy), and explicitly acknowledges the terms before installation. Acknowledgement accepts `I ACCEPT`, `i accept`, or `i_accept`.

The official executable is installed into the *running container*, **not distributed in the NetProbe Docker image**. The acknowledgement persists in `/config`, but a container/image recreation can remove the executable; use Settings to reinstall it after such a change. Speedtest selection and scheduling can be managed through the WebUI. Bandwidth tests may consume substantial data and temporarily saturate your connection.

## PostgreSQL (optional)

The provided file is intentionally named **`compose-postgress.yaml`**. It starts a separate PostgreSQL 16 container on a private Compose network and retains data in the `netprobe_pgdata` volume. Do **not** run it alongside `compose.yaml` or combine the files: they use the same NetProbe service, name, and ports.

Create a private `.env` file with a strong database password, then deploy:

```bash
cd NetProbe_Python
umask 077
printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 32)" > .env
chmod 600 .env

docker compose -f compose-postgress.yaml config --quiet
docker compose -f compose-postgress.yaml up -d --build
docker compose -f compose-postgress.yaml ps
```

In **Settings → Database connection**, review the active database, test the saved PostgreSQL connection, then validate and save the PostgreSQL profile if switching from an existing SQLite setup. An **application worker restart** is required to activate a saved database-engine change. A running PostgreSQL container does not by itself mean that NetProbe has switched away from an existing saved SQLite profile.

**Switching database engines does not migrate historical records.** Keep the `/config` volume (including `data/netprobe.sqlite`) when switching backends; PostgreSQL has its own persistent database volume. Back up both volumes before migration or significant upgrades. PostgreSQL port 5432 is not exposed publicly by the included Compose file.

For an existing SQLite install, stop the active stack before starting the PostgreSQL stack:

```bash
docker compose -f compose.yaml down
# Never use `down -v` if you want to preserve SQLite settings/history.
```

## Configuration and persistence

| Setting / path | Meaning |
| --- | --- |
| `/config/settings.json` | Authoritative saved monitoring settings |
| `/config/database.json` | Database selection and private PostgreSQL profile |
| `/config/security-policy.json` | Administrator password minimum after editing in Settings |
| `/config/data/netprobe.sqlite` | SQLite monitoring data, retained if PostgreSQL is selected |
| `/config/data/ookla-eula-accepted.txt` | Official Ookla terms acknowledgement |
| `/config/tls/` | HTTPS certificate and key |
| `/config/setup.complete` | First-run monitoring completion marker |
| `/config/` | Other private application/authentication files |

Docker/Compose environment variables can seed initial settings, but **saved WebUI settings take precedence** afterward. The Settings page can show genuine differences between explicit Docker-provided values and saved WebUI values. Modifying Docker environment variables alone will not overwrite the existing saved monitoring configuration.

Optional deployment variables include:

| Variable | Default | Use |
| --- | --- | --- |
| `NETPROBE_HTTP_PORT` | `8080` | Host HTTP redirect port (Compose) |
| `NETPROBE_HTTPS_PORT` | `8443` | Host HTTPS port (Compose) |
| `NETPROBE_MIN_PASSWORD_LENGTH` | `8` | Initial password minimum; can be set as low as `6` |
| `NETPROBE_AUTOSTART_CONFIGURED` | `false` | Allow monitoring before wizard completion when explicitly provisioned |
| `DB_ENGINE` | `sqlite` | Initial database engine seed; saved profile can take precedence |
| `POSTGRES_PASSWORD` | Required for PostgreSQL Compose | PostgreSQL server credential; keep out of Git |

The minimum password length can subsequently be set from **Settings → Administrator password policy**, using a 6–32-character slider. Existing administrator passwords remain valid when the minimum is changed.

### Updating an existing installation

Update the image/source while keeping your persistent data:

```bash
git pull --ff-only origin main
docker compose -f compose.yaml build --pull
docker compose -f compose.yaml up -d --no-build
docker compose -f compose.yaml ps
```

Back up `/config` first. **Do not use** `docker compose down -v`, `docker volume rm`, or indiscriminate Docker prune commands during an ordinary update. If you use PostgreSQL, use its respective Compose file for updates and back up the PostgreSQL volume too.

## Troubleshooting

- **Health or startup:** `docker compose -f compose.yaml ps` and `docker compose -f compose.yaml logs --tail=150 netprobe`.
- **No measurements immediately after first boot:** finish the monitoring wizard; probes intentionally wait for the `/config/setup.complete` marker.
- **Self-signed certificate warning:** expected for the bundled fallback certificate on a trusted local network.
- **False or low quality score:** review target availability and packet loss (some internet hosts may reject ICMP). Confirm the router address and DNS servers in Settings.
- **Ookla missing after update:** the binary lives in the writable container layer and may require reinstallation; the acceptance file can remain in `/config`.
- **PostgreSQL connection error:** verify the PostgreSQL container is healthy, database credentials match, and the selected engine is activated after the application worker restart.
- **Environment mismatch warning:** saved WebUI values are authoritative; review actual Docker-provided overrides and remove obsolete Compose/Unraid seeds if desired.

## Security and licenses

Keep unclaimed `/setup` accessible only on a trusted network. Do not publish the admin interface directly to the internet without additional access controls, trusted TLS, and appropriate reverse-proxy/network protections. Back up authentication material and database credentials securely. The NetProbe image does not need a Docker socket mount.

Official Ookla CLI is proprietary third-party software with its own terms, installed separately only after administrator acknowledgement. See [LICENSE](LICENSE) and the repository's `docs/` directory for the project license, architecture, troubleshooting, and third-party dependency notices.

---

**Project:** [GitHub](https://github.com/bmartino1/NetProbe_Python) · **Image:** [Docker Hub](https://hub.docker.com/r/bmmbmm01/netprobe)
