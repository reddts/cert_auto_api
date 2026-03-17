#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CLIENT_SCRIPT="${SCRIPT_DIR}/sync_cert.sh"
if [[ ! -f "$CLIENT_SCRIPT" ]]; then
  CLIENT_SCRIPT="${PROJECT_DIR}/client/sync_cert.sh"
fi
CRON_TAG="# cert_auto_api_client_sync"
SCHEDULE_FILE="${SCRIPT_DIR}/.client_sync_schedule"
if [[ ! -f "$CLIENT_SCRIPT" && -f "${PROJECT_DIR}/client/sync_cert.sh" ]]; then
  SCHEDULE_FILE="${PROJECT_DIR}/client/.client_sync_schedule"
fi
CRON_LOG_FILE="/var/log/cert_sync.log"
SYNC_SCRIPT_BASENAME="$(basename "$CLIENT_SCRIPT")"

if [[ ! -f "$CLIENT_SCRIPT" ]]; then
  echo "sync_cert.sh not found next to install_client_cron.sh or in project client/ directory" >&2
  exit 1
fi

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

# This installer only writes a cron entry. Runtime settings must be configured
# directly in client/sync_cert.sh before installing the cron job.
cron_command="/bin/bash ${CLIENT_SCRIPT} >> ${CRON_LOG_FILE} 2>&1"
cron_line="${minute} ${hour} * * * ${cron_command} ${CRON_TAG}"

current_crontab="$(mktemp)"
filtered_crontab="$(mktemp)"
cleanup() {
  rm -f "$current_crontab" "$filtered_crontab"
}
trap cleanup EXIT

if crontab -l >"$current_crontab" 2>/dev/null; then
  :
else
  : >"$current_crontab"
fi

# Keep the cron clean: remove any previously installed client sync entries,
# even if they point to an old path, then write exactly one current entry.
awk -v tag="$CRON_TAG" -v script_name="$SYNC_SCRIPT_BASENAME" '
  index($0, tag) == 0 && index($0, script_name) == 0 { print }
' "$current_crontab" >"$filtered_crontab"

printf "%s\n" "$cron_line" >>"$filtered_crontab"
crontab "$filtered_crontab"
echo "client sync cron installed at ${hour}:$(printf '%02d' "$minute")"

echo "running initial sync check..."
/bin/bash "$CLIENT_SCRIPT"
