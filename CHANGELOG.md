# Changelog

## 2026-03-15

- Added root-level entry point `main.py`.
- Added support for two certificate engines:
  - BaoTa `acme_v2.py`
  - self-installed `acme.sh`
- Added automatic fallback search for `acme_v2.py` when the default BaoTa path is not accessible.
- Added automatic fallback search for `acme.sh` in common install roots.
- Changed engine selection to prefer `acme.sh` whenever it is available, using BaoTa `acme_v2.py` only as a fallback.
- Added explicit BaoTa Cloudflare compatibility error handling for legacy `X-Auth-Key` header flows.
- Added a built-in Python ACME engine for Cloudflare API Token issuance when `acme.sh` is unavailable.
- Removed BaoTa `acme_v2.py` from the main issuance path in favor of `acme.sh` or the built-in engine.
- Renamed the built-in engine state directory from `.builtin_acme` to `.engine_state`.
- Added a client-side `SKIP_RESTART=1` option for safe certificate sync testing without restarting `xrayr`.
- Cached certificate engine detection and cron self-checks to reduce request latency.
- Changed `certificate/info` renewal triggering to run after the response is sent instead of inside the synchronous request path.
- Added a public `client/download` endpoint that returns a sanitized client template tgz package without requiring an API token.
- Updated the client cron installer to work from a standalone client directory such as `/etc/cert_auto_api_client/`.
- Changed the client cron installer to remove old client sync cron entries and keep exactly one current entry.
- Changed the client cron installer to run `sync_cert.sh` once immediately after installation for first-run validation.
- Changed the client sync script to restart `XrayR` only when the certificate actually changes.
- Added a dedicated client restart log file for `XrayR` restart failures.
- Added background renewal status tracking and log file output.
- Added `renewal_status`, `renewal_running`, `renewal_log_file`, and `engine` fields to certificate info responses.
- Added root path `/` to avoid repeated `404 Not Found` noise from probes.
- Added client cron installer with a persisted per-client randomized execution window.
- Added Cloudflare wildcard DNS preparation documentation.
- Added server-side deployment documentation for BaoTa and standalone Linux environments.
- Added known issues and future work documentation, including the recommendation to build a minimal self-maintained BT-compatible ACME engine in a future iteration.
