#!/usr/bin/env bash
set -euo pipefail

umask 077

# Default configuration values. Override them with environment variables when needed.
DEFAULT_API_BASE_URL="http://127.0.0.1:8080/api/v1"
DEFAULT_API_TOKEN=""
DEFAULT_CERT_DEST_DIR="/etc/XrayR/cert"
DEFAULT_XRAYR_SERVICE_NAME="XrayR"
DEFAULT_CERT_FILE_NAME="certificate.cert"
DEFAULT_KEY_FILE_NAME="private.key"

# Runtime configuration.
API_BASE_URL="${API_BASE_URL:-$DEFAULT_API_BASE_URL}"
API_TOKEN="${API_TOKEN:-$DEFAULT_API_TOKEN}"
CERT_DEST_DIR="${CERT_DEST_DIR:-$DEFAULT_CERT_DEST_DIR}"
XRAYR_SERVICE_NAME="${XRAYR_SERVICE_NAME:-$DEFAULT_XRAYR_SERVICE_NAME}"
CERT_FILE_NAME="${CERT_FILE_NAME:-$DEFAULT_CERT_FILE_NAME}"
KEY_FILE_NAME="${KEY_FILE_NAME:-$DEFAULT_KEY_FILE_NAME}"

if [[ -z "$API_TOKEN" ]]; then
  echo "API_TOKEN is required" >&2
  exit 1
fi

python3_bin="${PYTHON3_BIN:-python3}"
tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

auth_header=("Authorization: Bearer ${API_TOKEN}")
info_json="$tmp_dir/info.json"

curl -fsS -H "${auth_header[0]}" "${API_BASE_URL}/certificate/info" -o "$info_json"

remote_expires_at="$("$python3_bin" - "$info_json" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
print(data.get("expires_at") or "")
PY
)"

remote_fingerprint="$("$python3_bin" - "$info_json" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
print(data.get("fingerprint_sha256") or "")
PY
)"

local_cert_path="${CERT_DEST_DIR}/${CERT_FILE_NAME}"

local_expires_at=""
local_fingerprint=""
if [[ -f "$local_cert_path" ]]; then
  local_expires_at="$("$python3_bin" - "$local_cert_path" <<'PY'
from datetime import datetime
import subprocess
import sys

output = subprocess.check_output(
    ["openssl", "x509", "-in", sys.argv[1], "-noout", "-enddate"],
    text=True,
).strip()
value = output.split("=", 1)[1]
print(datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").isoformat() + "+00:00")
PY
)"
  local_fingerprint="$(openssl x509 -in "$local_cert_path" -noout -fingerprint -sha256 | awk -F= '{print tolower($2)}' | tr -d ':')"
fi

if [[ -n "$remote_expires_at" && "$remote_expires_at" == "$local_expires_at" && "$remote_fingerprint" == "$local_fingerprint" ]]; then
  exit 0
fi

archive_path="$tmp_dir/certificate_bundle.tgz"
curl -fsS -H "${auth_header[0]}" "${API_BASE_URL}/certificate/download" -o "$archive_path"

mkdir -p "$CERT_DEST_DIR"
tar -xzf "$archive_path" -C "$CERT_DEST_DIR"
chmod 644 "${CERT_DEST_DIR}/${CERT_FILE_NAME}"
chmod 600 "${CERT_DEST_DIR}/${KEY_FILE_NAME}"

if command -v systemctl >/dev/null 2>&1; then
  systemctl restart "$XRAYR_SERVICE_NAME"
else
  service "$XRAYR_SERVICE_NAME" restart
fi
