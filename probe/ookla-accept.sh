#!/usr/bin/env bash
# Runtime installer for the OFFICIAL, separately licensed Ookla CLI.
# This is not Python's open-source speedtest-cli pip package.
# No automatic acceptance: a user must explicitly consent in the WebUI or
# interactive shell. Installation modifies the container writable layer,
# so a recreated image may require reinstallation.
# --install is designed for authenticated WebUI requests after consent;
# --status and --revoke support administrator diagnostics.
set -euo pipefail

ACCEPTANCE_FILE="${SPEEDTEST_OOKLA_ACCEPTANCE_FILE:-/config/data/ookla-eula-accepted.txt}"
OOKLA_BINARY="${SPEEDTEST_OOKLA_PATH:-/usr/bin/speedtest}"
OOKLA_REPOSITORY_INSTALLER="https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh"
EULA_URL="https://www.speedtest.net/about/eula"
TERMS_URL="https://www.speedtest.net/about/terms"
PRIVACY_URL="https://www.speedtest.net/about/privacy"
INSTALL_LOCK_DIR="/tmp/netprobe-ookla-install.lock"

cleanup() {
  rmdir "${INSTALL_LOCK_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

env_acknowledged() {
  local value="${SPEEDTEST_OOKLA_ACCEPT_LICENSE:-}"
  local upper lower
  upper="$(printf '%s' "${value}" | tr '[:lower:]' '[:upper:]')"
  lower="$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]')"
  [[ "${upper}" == "I_ACCEPT" || "${upper}" == "I ACCEPT" || \
     "${lower}" == "1" || "${lower}" == "true" || \
     "${lower}" == "yes" || "${lower}" == "on" ]]
}

file_acknowledged() {
  # The marker is on the FIRST line; following lines record date/terms for audit.
  # grep -qx over the whole file would reject our own multi-line receipt.
  [[ -f "${ACCEPTANCE_FILE}" ]] && [[ "$(head -n 1 "${ACCEPTANCE_FILE}")" == "I_ACCEPT" ]]
}

acknowledgement_source() {
  if env_acknowledged; then
    printf '%s\n' "environment"
    return 0
  fi
  if file_acknowledged; then
    printf '%s\n' "persistent-file"
    return 0
  fi
  return 1
}

binary_installed() {
  [[ -x "${OOKLA_BINARY}" ]]
}

show_binary_status() {
  if binary_installed; then
    echo "Official Ookla Speedtest CLI is installed at ${OOKLA_BINARY}."
    "${OOKLA_BINARY}" --version 2>/dev/null | head -n 1 || true
    return 0
  fi
  echo "Official Ookla Speedtest CLI is not installed at ${OOKLA_BINARY}."
  return 1
}

show_notice() {
  cat <<NOTICE
NetProbe optional Ookla Speedtest CLI acknowledgement and installer

The official Ookla Speedtest CLI is separate third-party software and is not
covered by NetProbe's MIT License. It is described by Ookla as being for
personal, non-commercial use.

Review the current documents before accepting:
  EULA:          ${EULA_URL}
  Terms of Use:  ${TERMS_URL}
  Privacy:       ${PRIVACY_URL}

NetProbe is independent software and is not affiliated with or endorsed by
Ookla, LLC. This acknowledgement does not grant redistribution or commercial-use
rights.

When you continue, this helper downloads and installs the official Debian
package directly from Ookla's Packagecloud repository into this running
container. NetProbe's distributed image does not contain that binary.
NOTICE
}

supported_architecture() {
  case "$(dpkg --print-architecture 2>/dev/null || true)" in
    amd64|arm64|armhf|armel|i386) return 0 ;;
    *) return 1 ;;
  esac
}

require_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    cat >&2 <<ERROR
Installing the Ookla package requires root inside the container.
Run:
  docker exec -it --user root <container-name> netprobe-ookla-accept
ERROR
    exit 3
  fi
}

record_acknowledgement() {
  umask 077
  mkdir -p "$(dirname "${ACCEPTANCE_FILE}")"
  local tmp_file="${ACCEPTANCE_FILE}.tmp.$$"
  {
    echo 'I_ACCEPT'
    echo "accepted_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "eula=${EULA_URL}"
    echo "terms=${TERMS_URL}"
    echo "privacy=${PRIVACY_URL}"
  } > "${tmp_file}"
  mv -f "${tmp_file}" "${ACCEPTANCE_FILE}"
  echo "Acknowledgement recorded at ${ACCEPTANCE_FILE}."
}

ensure_acknowledged_interactively() {
  local source
  if source="$(acknowledgement_source)"; then
    echo "Ookla terms acknowledgement is already present via ${source}."
    return 0
  fi

  show_notice

  if [[ ! -t 0 ]]; then
    cat >&2 <<ERROR

An interactive terminal is required to record acknowledgement. Run:
  docker exec -it <container-name> netprobe-ookla-accept

For a non-interactive Unraid deployment, the administrator may instead set:
  SPEEDTEST_OOKLA_ACCEPT_LICENSE=I_ACCEPT
Then run:
  docker exec <container-name> netprobe-ookla-accept --install
ERROR
    exit 2
  fi

  printf '\nType I ACCEPT (case-insensitive; i_accept also accepted): '
  IFS= read -r response
  # Same consent spelling rules as the WebUI: case-insensitive; underscore or space.
  response="$(printf '%s' "${response}" | tr '[:lower:]' '[:upper:]' | tr '_' ' ')"
  if [[ "${response}" != "I ACCEPT" ]]; then
    echo "Acknowledgement was not recorded."
    exit 1
  fi

  record_acknowledgement
}

install_ookla_cli() {
  if binary_installed; then
    show_binary_status
    return 0
  fi

  if ! acknowledgement_source >/dev/null; then
    cat >&2 <<ERROR
Ookla terms acknowledgement is required before installation.
Run interactively:
  docker exec -it <container-name> netprobe-ookla-accept
Or set SPEEDTEST_OOKLA_ACCEPT_LICENSE=I_ACCEPT and run this helper again.
ERROR
    exit 2
  fi

  require_root

  if ! supported_architecture; then
    echo "Ookla Speedtest CLI is not published for architecture $(dpkg --print-architecture 2>/dev/null || echo unknown)." >&2
    exit 4
  fi

  if ! command -v apt-get >/dev/null 2>&1 || ! command -v dpkg >/dev/null 2>&1; then
    echo "This runtime installer requires a Debian-based container with apt-get and dpkg." >&2
    exit 4
  fi

  if ! mkdir "${INSTALL_LOCK_DIR}" 2>/dev/null; then
    echo "Another Ookla installation appears to be running. Try again shortly." >&2
    exit 5
  fi

  echo "Installing the official Ookla Speedtest CLI from Ookla's Packagecloud repository..."
  export DEBIAN_FRONTEND=noninteractive

  # Hide routine apt progress from the WebUI. On failure preserve the logfile
  # inside the running container and print a useful excerpt.
  local install_log="/tmp/netprobe-ookla-install.$.log"
  local installer_file="/tmp/netprobe-ookla-repository.$.sh"
  touch "${install_log}"
  chmod 0600 "${install_log}"
  run_install_step() {
    if ! "$@" >> "${install_log}" 2>&1; then
      echo "Ookla installation failed during: $1" >&2
      echo "Last installer output (full log: ${install_log}):" >&2
      tail -n 25 "${install_log}" >&2 || true
      return 1
    fi
  }
  echo "[1/5] Preparing Debian package metadata..."
  run_install_step apt-get update
  echo "[2/5] Installing repository prerequisites..."
  run_install_step apt-get install -y --no-install-recommends ca-certificates curl gnupg bash
  echo "[3/5] Configuring Ookla Packagecloud repository..."
  run_install_step curl -fsSL "${OOKLA_REPOSITORY_INSTALLER}" -o "${installer_file}"
  run_install_step bash "${installer_file}"
  rm -f "${installer_file}"
  echo "[4/5] Updating package metadata..."
  run_install_step apt-get update
  echo "[5/5] Installing official Ookla CLI..."
  run_install_step apt-get install -y --no-install-recommends speedtest
  rm -rf /var/lib/apt/lists/*
  rm -f "${install_log}"
  hash -r

  if ! binary_installed; then
    echo "Installation completed, but ${OOKLA_BINARY} was not found or is not executable." >&2
    exit 6
  fi

  echo "Official Ookla Speedtest CLI installation completed."
  show_binary_status
  cat <<NOTICE

The package was installed into this container's writable layer. Docker image
updates or container recreation remove runtime-installed packages. Your
acknowledgement remains in the persistent /config volume; rerun
netprobe-ookla-accept after an update if the binary is missing.
NOTICE
}

show_status() {
  local result=0 source
  if source="$(acknowledgement_source)"; then
    echo "Ookla terms acknowledgement is present via ${source}."
    if [[ "${source}" == "persistent-file" ]]; then
      echo "Acknowledgement file: ${ACCEPTANCE_FILE}"
    fi
  else
    echo "Ookla terms acknowledgement is not recorded."
    result=1
  fi

  if ! show_binary_status; then
    result=1
  fi
  return "${result}"
}

case "${1:-}" in
  --status)
    show_status
    exit $?
    ;;
  --install)
    install_ookla_cli
    exit 0
    ;;
  --revoke)
    rm -f "${ACCEPTANCE_FILE}"
    echo "Removed persisted Ookla terms acknowledgement from ${ACCEPTANCE_FILE}."
    if env_acknowledged; then
      echo "SPEEDTEST_OOKLA_ACCEPT_LICENSE is still set; remove it from the container configuration to fully revoke acknowledgement."
    fi
    if binary_installed; then
      echo "The Ookla CLI remains installed, but NetProbe will not use it without acknowledgement."
    fi
    exit 0
    ;;
  --help|-h)
    cat <<USAGE
Usage:
  netprobe-ookla-accept            Review/record acknowledgement and install if missing
  netprobe-ookla-accept --install  Install if acknowledgement already exists
  netprobe-ookla-accept --status   Show acknowledgement and binary status
  netprobe-ookla-accept --revoke   Remove persisted acknowledgement
USAGE
    exit 0
    ;;
  "")
    ensure_acknowledged_interactively
    install_ookla_cli
    echo "Reload NetProbe's web page or run the Ookla test again."
    ;;
  *)
    echo "Unknown option: $1" >&2
    exit 2
    ;;
esac
