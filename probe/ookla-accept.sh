#!/usr/bin/env bash
set -euo pipefail

ACCEPTANCE_FILE="${SPEEDTEST_OOKLA_ACCEPTANCE_FILE:-/data/ookla-eula-accepted.txt}"
EULA_URL="https://www.speedtest.net/about/eula"
TERMS_URL="https://www.speedtest.net/about/terms"
PRIVACY_URL="https://www.speedtest.net/about/privacy"

env_acknowledged() {
  local value="${SPEEDTEST_OOKLA_ACCEPT_LICENSE:-}"
  local upper lower
  upper="$(printf '%s' "${value}" | tr '[:lower:]' '[:upper:]')"
  lower="$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]')"
  [[ "${upper}" == "I_ACCEPT" || "${upper}" == "I ACCEPT" ||      "${lower}" == "1" || "${lower}" == "true" ||      "${lower}" == "yes" || "${lower}" == "on" ]]
}

show_notice() {
  cat <<NOTICE
NetProbe optional Ookla Speedtest CLI acknowledgement

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
NOTICE
}

case "${1:-}" in
  --status)
    if env_acknowledged; then
      echo "Ookla terms acknowledgement is provided by SPEEDTEST_OOKLA_ACCEPT_LICENSE."
      exit 0
    fi
    if [[ -f "${ACCEPTANCE_FILE}" ]] && grep -qx 'I_ACCEPT' "${ACCEPTANCE_FILE}"; then
      echo "Ookla terms acknowledgement is recorded at ${ACCEPTANCE_FILE}."
      exit 0
    fi
    echo "Ookla terms acknowledgement is not recorded."
    exit 1
    ;;
  --revoke)
    rm -f "${ACCEPTANCE_FILE}"
    echo "Removed persisted Ookla terms acknowledgement from ${ACCEPTANCE_FILE}."
    if env_acknowledged; then
      echo "SPEEDTEST_OOKLA_ACCEPT_LICENSE is still set; remove it from the container configuration to fully revoke acknowledgement."
    fi
    exit 0
    ;;
  --help|-h)
    cat <<USAGE
Usage:
  netprobe-ookla-accept           Review and record acknowledgement interactively
  netprobe-ookla-accept --status  Show acknowledgement status
  netprobe-ookla-accept --revoke  Remove the persisted acknowledgement
USAGE
    exit 0
    ;;
  "")
    ;;
  *)
    echo "Unknown option: $1" >&2
    exit 2
    ;;
esac

show_notice

if [[ ! -t 0 ]]; then
  cat >&2 <<ERROR

An interactive terminal is required. Run:
  docker exec -it <container-name> netprobe-ookla-accept

For a non-interactive Unraid deployment, the administrator may instead set:
  SPEEDTEST_OOKLA_ACCEPT_LICENSE=I_ACCEPT
ERROR
  exit 2
fi

printf '\nType exactly I ACCEPT to record your acknowledgement: '
IFS= read -r response
if [[ "${response}" != "I ACCEPT" ]]; then
  echo "Acknowledgement was not recorded."
  exit 1
fi

umask 077
mkdir -p "$(dirname "${ACCEPTANCE_FILE}")"
tmp_file="${ACCEPTANCE_FILE}.tmp.$$"
{
  echo 'I_ACCEPT'
  echo "accepted_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "eula=${EULA_URL}"
  echo "terms=${TERMS_URL}"
  echo "privacy=${PRIVACY_URL}"
} > "${tmp_file}"
mv -f "${tmp_file}" "${ACCEPTANCE_FILE}"

echo "Acknowledgement recorded at ${ACCEPTANCE_FILE}."
echo "Reload NetProbe's web page or run the Ookla test again."
