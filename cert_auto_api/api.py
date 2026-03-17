from __future__ import annotations

import logging
import subprocess
from datetime import UTC, datetime
import shutil
from pathlib import Path
from contextlib import asynccontextmanager
import time
import tarfile
import tempfile

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .cert_manager import CertManager
from .config import load_settings


settings = load_settings()
manager = CertManager(settings)
logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent
INSTALL_SERVER_CRON_SCRIPT = BASE_DIR / "scripts" / "install_server_cron.sh"
CLIENT_DIR = BASE_DIR / "client"
_CRON_CHECK_TTL_SECONDS = 300.0
_last_cron_check_at = 0.0


def cleanup_archive(path: str) -> None:
    shutil.rmtree(str(Path(path).parent), ignore_errors=True)


def create_client_template_archive() -> Path:
    sync_script = (CLIENT_DIR / "sync_cert.sh").read_text(encoding="utf-8")
    sync_script = sync_script.replace(
        'DEFAULT_API_BASE_URL="http://127.0.0.1:8080/api/v1"',
        'DEFAULT_API_BASE_URL="https://your-api-host/api/v1"',
    )
    sync_script = sync_script.replace(
        'DEFAULT_API_TOKEN=""',
        'DEFAULT_API_TOKEN="replace_with_your_api_token"',
    )
    sync_script = sync_script.replace(
        'DEFAULT_CERT_DEST_DIR="/etc/XrayR/cert"',
        'DEFAULT_CERT_DEST_DIR="/etc/XrayR/cert"',
    )
    sync_script = sync_script.replace(
        'DEFAULT_XRAYR_SERVICE_NAME="XrayR"',
        'DEFAULT_XRAYR_SERVICE_NAME="XrayR"',
    )

    install_script = (CLIENT_DIR / "install_client_cron.sh").read_text(encoding="utf-8")
    guide_text = """Client template package

1. Put sync_cert.sh and install_client_cron.sh in a stable directory, for example:
   /etc/cert_auto_api_client/
2. Edit sync_cert.sh and set your real DEFAULT_API_BASE_URL and DEFAULT_API_TOKEN.
3. Run as root:
   chmod 700 sync_cert.sh install_client_cron.sh
   /bin/bash install_client_cron.sh
"""

    temp_dir = Path(tempfile.mkdtemp(prefix="client-template-"))
    archive_path = temp_dir / "cert_auto_api_client.tgz"
    export_dir = temp_dir / "client"
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "sync_cert.sh").write_text(sync_script, encoding="utf-8")
    (export_dir / "install_client_cron.sh").write_text(install_script, encoding="utf-8")
    (export_dir / "README.txt").write_text(guide_text, encoding="utf-8")

    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(export_dir / "sync_cert.sh", arcname="sync_cert.sh")
        tar.add(export_dir / "install_client_cron.sh", arcname="install_client_cron.sh")
        tar.add(export_dir / "README.txt", arcname="README.txt")

    return archive_path


def ensure_server_cron_installed(force: bool = False) -> None:
    global _last_cron_check_at

    now = time.monotonic()
    if not force and now - _last_cron_check_at < _CRON_CHECK_TTL_SECONDS:
        return

    if not INSTALL_SERVER_CRON_SCRIPT.is_file():
        logger.warning("cron installer script not found: %s", INSTALL_SERVER_CRON_SCRIPT)
        return

    try:
        subprocess.run(
            ["/bin/bash", str(INSTALL_SERVER_CRON_SCRIPT)],
            check=True,
            capture_output=True,
            text=True,
        )
        _last_cron_check_at = now
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else ""
        logger.warning("failed to ensure renew cron is installed: %s", stderr or exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_server_cron_installed(force=True)
    yield


app = FastAPI(title="Certificate Auto API", version="1.0.0", lifespan=lifespan)


def verify_token(
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
) -> None:
    expected = settings.api_token
    bearer = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()

    provided = x_api_token or bearer
    if not expected or provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
        )


def ensure_renew_cron() -> None:
    ensure_server_cron_installed()


def trigger_certificate_renewal_if_needed() -> None:
    try:
        manager.trigger_background_renewal_if_needed()
    except Exception as exc:
        logger.warning("failed to trigger certificate renewal: %s", exc)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root_info() -> dict[str, str]:
    return {"status": "ok", "message": "cert_auto_api"}


@app.get(f"{settings.api_prefix}/client/download")
def download_client_scripts() -> FileResponse:
    archive_path = create_client_template_archive()
    return FileResponse(
        archive_path,
        media_type="application/gzip",
        filename="cert_auto_api_client.tgz",
        background=BackgroundTask(cleanup_archive, str(archive_path)),
    )


@app.get(
    f"{settings.api_prefix}/certificate/info",
    dependencies=[Depends(verify_token), Depends(ensure_renew_cron)],
)
def certificate_info(background_tasks: BackgroundTasks) -> dict[str, object]:
    background_tasks.add_task(trigger_certificate_renewal_if_needed)
    status_info = manager.get_cert_status()
    renewal_status = manager.get_renewal_status()
    try:
        engine_name, _ = manager.get_certificate_engine()
    except Exception as exc:
        engine_name = f"unavailable: {exc}"
    return {
        "domains": settings.cert_domains,
        "primary_domain": settings.primary_domain,
        "engine": engine_name,
        "exists": status_info.exists,
        "expires_at": status_info.expires_at.isoformat() if status_info.expires_at else None,
        "expires_in_days": status_info.expires_in_days,
        "sha256": status_info.sha256,
        "fingerprint_sha256": status_info.fingerprint_sha256,
        "renewal_running": manager.is_renewal_running(),
        "renewal_status": renewal_status,
        "renewal_log_file": str(manager.renewal_log_path),
        "checked_at": datetime.now(UTC).isoformat(),
    }


@app.post(
    f"{settings.api_prefix}/certificate/check-renew",
    dependencies=[Depends(verify_token), Depends(ensure_renew_cron)],
)
def check_renew() -> dict[str, str | int | bool | None]:
    return manager.trigger_background_renewal_if_needed()


@app.get(
    f"{settings.api_prefix}/certificate/download",
    dependencies=[Depends(verify_token), Depends(ensure_renew_cron)],
)
def download_certificate() -> FileResponse:
    if not settings.cert_path.exists() or not settings.key_path.exists():
        trigger_certificate_renewal_if_needed()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="certificate is missing or renewal is in progress; retry later",
        )
    archive_path = manager.create_archive()
    return FileResponse(
        archive_path,
        media_type="application/gzip",
        filename="certificate_bundle.tgz",
        background=BackgroundTask(cleanup_archive, str(archive_path)),
    )
