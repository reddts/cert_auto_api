from __future__ import annotations

import logging
import subprocess
from datetime import UTC, datetime
import shutil
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .cert_manager import CertManager
from .config import load_settings


settings = load_settings()
manager = CertManager(settings)
logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent
INSTALL_SERVER_CRON_SCRIPT = BASE_DIR / "scripts" / "install_server_cron.sh"


def cleanup_archive(path: str) -> None:
    shutil.rmtree(str(Path(path).parent), ignore_errors=True)


def ensure_server_cron_installed() -> None:
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
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else ""
        logger.warning("failed to ensure renew cron is installed: %s", stderr or exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_server_cron_installed()
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


@app.get(
    f"{settings.api_prefix}/certificate/info",
    dependencies=[Depends(verify_token), Depends(ensure_renew_cron), Depends(trigger_certificate_renewal_if_needed)],
)
def certificate_info() -> dict[str, object]:
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
    dependencies=[Depends(verify_token), Depends(ensure_renew_cron), Depends(trigger_certificate_renewal_if_needed)],
)
def download_certificate() -> FileResponse:
    if not settings.cert_path.exists() or not settings.key_path.exists():
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
