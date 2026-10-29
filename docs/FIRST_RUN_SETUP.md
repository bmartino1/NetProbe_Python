# NetProbe 2.1 first-run setup (development)

Persistent user configuration: `/config/settings.json`; credentials: `/config/admin.hash`; session signing key: `/config/session.key`. SQLite measurement history lives at `/config/data/netprobe.sqlite`, under the single optional application volume.

On a fresh install, open `/setup` over HTTPS and create the administrator password directly; no log-based code is required. After registration, sign in as admin; the monitoring setup wizard then presents factory defaults. Save or skip; later configuration is available via the existing settings API/UI. Monitoring and Speedtest settings apply live; database engine switching requires a controlled restart.

Factory defaults are packaged at `/opt/netprobe/defaults/settings.json`. The working config is initialized once, with environment variables used only for first-run seeding. Existing `/data/config/settings.json` is migrated if `/config/settings.json` does not exist; the old copy is retained. Damaged configuration is moved to an invalid timestamped file and the most recent valid backup is restored, or factory defaults used.

**Security:** Safeguard the config volume (it holds a password hash and signing key). The unclaimed first-run setup screen can be reached by anyone with network access until an admin account is created. Restrict access to a trusted LAN and complete setup immediately. Guests can view dashboard/history after setup but cannot edit settings or run diagnostics. This is a testing build: do not expose setup to the public Internet; terminate HTTPS with the supplied Nginx reverse proxy. No container can change Docker host port mappings through these settings.

**Migration:** Preserve both the old data volume and the new config volume; do not delete `/data/config` until you have verified recovery. Existing v0.2 authentication files (`admin.hash` and `session.key`) are copied automatically into `/config` if absent there. Existing `/config` credentials are never overwritten. Preserve the original volume and confirm successful login before deleting old files.

## Test checklist: setup and official Ookla CLI

1. Deploy to isolated test volumes with `docker compose up -d --build`; do not use production database or credentials.
2. Visit HTTPS `/setup`, create an admin password, and sign in on `/login`. No setup code is used.
3. Save probe settings through the wizard; verify the browser reaches the dashboard without a CSRF error. Restart `netprobe` and verify settings remain in `/config/settings.json`.
4. Open Settings → Official Ookla Speedtest CLI. Review the linked EULA, Terms and Privacy Policy. Type exactly `I ACCEPT` and start installation. A successful installation depends on supported CPU architecture, apt repositories and external package availability.
5. Refresh status and check that the binary is installed. Only then choose `ookla` as the Speedtest backend and run a manual test. No license acceptance or installation occurs automatically.
6. Recreating the container may remove the installed CLI even when its acceptance marker persists; repeat installation if needed.

**Deployment note:** The current development Compose uses separate Nginx and Flask services. The envisioned single-container `docker run` appliance is not implemented yet. Never expose setup or administrative installer endpoints directly to the public Internet until deployment hardening has been completed.


## First-run scheduler and password controls (October 2026)

On a new installation, **the container, HTTPS WebUI, and database initialization may start**, but scheduled Ping, DNS, scoring and automatic Speedtests do **not** start until the administrator completes the monitoring wizard. Completion is recorded by `/config/setup.complete`. Merely creating the administrator account does not release the scheduler. An explicitly chosen **Use defaults and open dashboard** also counts as completion.

An unattended deployment with targets and configuration intentionally provisioned by Docker may opt into starting before the wizard by setting `NETPROBE_AUTOSTART_CONFIGURED=true`. Keep it `false` (the default) for regular WebUI-driven setup.

The default administrator password minimum is **8 characters**, configurable through `NETPROBE_MIN_PASSWORD_LENGTH` (allowed 6–128, clamped to this range). For example, set `NETPROBE_MIN_PASSWORD_LENGTH=6` in a project's untracked `.env` before creating the administrator; both Compose files pass this variable into NetProbe. Changing the variable later affects future password changes, not existing passwords. After setup, Settings → Administrator password policy provides a slider (6–32) that saves to `/config/security-policy.json` and overrides the initial Docker minimum.

The first-run Speedtest backend field is a dropdown. Selecting **Official Ookla** exposes links to Ookla's EULA, Terms and Privacy Policy, an explicit consent field, an install button, and a status refresh button. Confirmation is case-insensitive: `I ACCEPT`, `i accept`, and `i_accept` work. When scheduled Speedtests are enabled and the backend is Ookla, setup completion requires its binary and acknowledgement to be present. Binary installation remains a separate, explicitly requested action and may be lost when the container is recreated.

Administrators can inspect Docker-vs-saved-Settings differences using the **actual nonsecret Docker-supplied values** (captured before WebUI settings are loaded into the process environment) (Docker seed, saved value, and applied source). WebUI monitoring changes apply live; a database engine change needs an application worker reload, available from Settings when running under Gunicorn. This reload does not restart Nginx or Docker; use `docker compose restart netprobe` for the entire container.
