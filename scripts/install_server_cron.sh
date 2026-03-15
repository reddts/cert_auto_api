#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRON_CMD="/bin/bash ${PROJECT_DIR}/scripts/server_cron.sh >> /var/log/cert_auto_api.log 2>&1"
CRON_LINE="0 3 * * * ${CRON_CMD}"

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

if grep -Fq "$CRON_CMD" "$current_crontab"; then
  echo "server renew cron already exists"
  exit 0
fi

printf "%s\n" "$CRON_LINE" >>"$current_crontab"
crontab "$current_crontab"
echo "server renew cron installed: $CRON_LINE"
