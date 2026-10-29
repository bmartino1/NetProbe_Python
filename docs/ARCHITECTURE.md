# NetProbe 2.1 architecture (development)

```text
Host :8080 → container :80  ─┐
                             ├→ Nginx :8443 (HTTPS) → Gunicorn 127.0.0.1:8080 → Flask API
Host :8443 → container :8443 ┘                                       │
                                                                     ├→ /config/settings.json
                                                                     └→ /config/data/netprobe.sqlite
```

## Single image

The root `Dockerfile` installs Python, Gunicorn, Nginx and utilities. The root `compose.yaml` builds **only this image** for SQLite; `compose-postgress.yaml` adds a separate PostgreSQL 16 service. `container/scripts/entrypoint.sh` starts both services, forwards shutdown signals and ends the container if either service dies. No PHP or separate Nginx container is required.

## Source directories

- `probe/`: existing Python monitors, Flask routes, views, CSS/JS, and factory defaults.
- `container/nginx/`: reverse proxy config, self-signed HTTPS handling.
- `container/scripts/`: lifecycle logic.
- `docs/`: design and test notes.

## Runtime settings

Factory values ship under `/opt/netprobe/defaults`, with settings initialized once under `/config/settings.json`. Optional environment values only seed initial creation. WebUI edits persist in `/config`; monitoring changes are applied live. Database engine selection requires restart. Mounting one `/config` volume is recommended for persistence; PostgreSQL keeps its own separate server data volume.

## Existing-install migration

Earlier Compose files used `netprobe_data`, `netprobe_config`, `netprobe_tls` project-scoped named volumes and a separate PostgreSQL container. The new Compose file keeps data/config volume keys, but Docker Compose volume names depend on the project name. Confirm names with `docker volume ls` and `docker compose config`; do **not** remove previous volumes. TLS will be generated fresh under `/config/tls` if absent. PostgreSQL is now external/optional; do not expect PostgreSQL data to be automatically copied into SQLite.

## Testing

```bash
docker compose config
docker compose build --no-cache
docker compose up -d
docker compose ps
docker compose logs netprobe --tail 100
curl -kI https://localhost:8443/login
```

Verify setup code, account creation, wizard saves, chart refresh, persistence, manual Speedtest, Ookla install and restart. Test only in an isolated lab.

## Python application/runtime dependency separation

The Python backend remains a single `probe/app.py` during initial Docker testing. Internally, it contains collection/scheduling, database adapters, optional Speedtest backends, authentication/setup, and Flask JSON/HTML endpoints. The Python 3.15.2 base-image refresh does **not** remove Flask: Nginx acts only as the HTTPS proxy and the existing WebUI calls the Flask API. Gunicorn provides the local WSGI server. See commented `probe/requirements.txt` for package roles. SQLite is in the standard library; PostgreSQL needs `psycopg2-binary` when selected. Splitting `app.py` into modules should follow API regression tests rather than happen in the same change as the interpreter upgrade.
