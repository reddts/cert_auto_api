#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIENT_SCRIPT="${PROJECT_DIR}/client/sync_cert.sh"
CRON_TAG="# cert_auto_api_client_sync"
SCHEDULE_FILE="${PROJECT_DIR}/client/.client_sync_schedule"

# Pick one fixed random time per client in the 03:00-05:59 window and persist it locally.
if [[ -f "$SCHEDULE_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$SCHEDULE_FILE"
else
  minute="$(shuf -i 0-59 -n 1)"
  hour="$(shuf -i 3-5 -n 1)"
  cat >"$SCHEDULE_FILE" <<EOF
hour=${hour}
minute=${minute}
EOF
  chmod 600 "$SCHEDULE_FILE"
fi

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8080/api/v1}"
API_TOKEN="${API_TOKEN:-}"
CERT_DEST_DIR="${CERT_DEST_DIR:-/etc/XrayR/cert}"
XRAYR_SERVICE_NAME="${XRAYR_SERVICE_NAME:-XrayR}"
CRON_LOG_FILE="${CRON_LOG_FILE:-/var/log/cert_sync.log}"

if [[ -z "$API_TOKEN" ]]; then
  echo "API_TOKEN is required" >&2
  exit 1
fi

cron_command="API_BASE_URL=\"${API_BASE_URL}\" API_TOKEN=\"${API_TOKEN}\" CERT_DEST_DIR=\"${CERT_DEST_DIR}\" XRAYR_SERVICE_NAME=\"${XRAYR_SERVICE_NAME}\" /bin/bash ${CLIENT_SCRIPT} >> ${CRON_LOG_FILE} 2>&1"
cron_line="${minute} ${hour} * * * ${cron_command} ${CRON_TAG}"

current_crontab="$(mktemp)"
cleanup() {
  rm -f "$current_crontab"
}
trap cleanup EXIT

if crontab -l >"$current_crontab" 2>/dev/null; then
  :
else
  : >"$current_crontab"
fi

if grep -Fq "$CRON_TAG" "$current_crontab"; then
  echo "client sync cron already exists"
  exit 0
fi

printf "%s\n" "$cron_line" >>"$current_crontab"
crontab "$current_crontab"
echo "client sync cron installed at ${hour}:$(printf '%02d' "$minute")"
