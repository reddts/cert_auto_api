from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes

from .builtin_acme import BuiltinAcmeEngine
from .config import Settings


ACME_SH_CANDIDATE_PATHS = [
    "/www/server/panel/.acme.sh/acme.sh",
    "/root/.acme.sh/acme.sh",
    "~/.acme.sh/acme.sh",
]

ACME_SH_SEARCH_ROOTS = [
    "/www/server",
    "/root",
    "~",
]


@dataclass(slots=True)
class CertStatus:
    exists: bool
    expires_at: datetime | None
    expires_in_days: int | None
    sha256: str | None
    fingerprint_sha256: str | None


class CertManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_dir = Path(__file__).resolve().parent.parent

    def ensure_ready(self) -> None:
        if not self.settings.api_token:
            raise ValueError("API_TOKEN is required")
        if not self.settings.cf_token:
            raise ValueError("CF_TOKEN is required")
        self.settings.cert_output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def renewal_lock_path(self) -> Path:
        return self.settings.cert_output_dir / ".renew_in_progress"

    @property
    def renewal_status_path(self) -> Path:
        return self.settings.cert_output_dir / ".renew_status.json"

    @property
    def renewal_log_path(self) -> Path:
        return self.settings.cert_output_dir / ".renew.log"

    def get_renewal_status(self) -> dict[str, str | bool | int | None]:
        default_status: dict[str, str | bool | int | None] = {
            "state": "running" if self.is_renewal_running() else "idle",
            "reason": None,
            "started_at": None,
            "finished_at": None,
            "message": None,
        }
        if not self.renewal_status_path.exists():
            return default_status

        try:
            data = json.loads(self.renewal_status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default_status

        if self.is_renewal_running():
            data["state"] = "running"
        return {
            "state": data.get("state") or default_status["state"],
            "reason": data.get("reason"),
            "started_at": data.get("started_at"),
            "finished_at": data.get("finished_at"),
            "message": data.get("message"),
        }

    def update_renewal_status(
        self,
        *,
        state: str,
        reason: str | None = None,
        message: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        current = self.get_renewal_status()
        payload = {
            "state": state,
            "reason": reason,
            "message": message,
            "started_at": started_at if started_at is not None else current.get("started_at"),
            "finished_at": finished_at if finished_at is not None else current.get("finished_at"),
        }
        temp_path = self.renewal_status_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        temp_path.replace(self.renewal_status_path)

    def append_renewal_log(self, message: str) -> None:
        timestamp = datetime.now(UTC).isoformat()
        with self.renewal_log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"[{timestamp}] {message}\n")

    def get_certificate_engine(self) -> tuple[str, str]:
        try:
            return "acme_sh", self.detect_acme_sh()
        except FileNotFoundError:
            return "builtin_acme", "cert_auto_api.builtin_acme"

    def get_acme_sh_candidates(self) -> list[str]:
        # Probe high-probability locations first: BaoTa, root install, then current-user install.
        candidates: list[str] = []
        for path in ACME_SH_CANDIDATE_PATHS:
            expanded = str(Path(path).expanduser())
            if expanded not in candidates:
                candidates.append(expanded)

        # Finally fall back to PATH for environments where acme.sh was installed system-wide.
        which_acme = shutil.which("acme.sh")
        if which_acme and which_acme not in candidates:
            candidates.append(which_acme)

        if any(Path(candidate).is_file() for candidate in candidates):
            return candidates

        # If fixed candidates fail, do a bounded search in common install roots.
        for root in ACME_SH_SEARCH_ROOTS:
            search_root = Path(root).expanduser()
            if not search_root.exists():
                continue

            try:
                for found in search_root.rglob("acme.sh"):
                    found_path = str(found)
                    if found.is_file() and found_path not in candidates:
                        candidates.append(found_path)
            except (OSError, PermissionError):
                continue
        return candidates

    def detect_acme_sh(self) -> str:
        candidates = self.get_acme_sh_candidates()
        for candidate in candidates:
            if Path(candidate).is_file():
                return candidate
        raise FileNotFoundError(
            "acme.sh not found. Tried: "
            + ", ".join(candidates)
            + ". Install BaoTa acme.sh or a self-installed acme.sh in one of these locations, or ensure it is in PATH."
        )

    def get_cert_status(self) -> CertStatus:
        cert_path = self.settings.cert_path
        if not cert_path.exists():
            return CertStatus(False, None, None, None, None)

        try:
            cert_bytes = cert_path.read_bytes()
            cert = x509.load_pem_x509_certificate(cert_bytes)
        except (OSError, ValueError):
            return CertStatus(False, None, None, None, None)

        expires_at = cert.not_valid_after_utc.astimezone(UTC)
        expires_in_days = int((expires_at - datetime.now(UTC)).total_seconds() // 86400)
        sha256 = hashlib.sha256(cert_bytes).hexdigest()
        fingerprint_sha256 = cert.fingerprint(hashes.SHA256()).hex()
        return CertStatus(True, expires_at, expires_in_days, sha256, fingerprint_sha256)

    def has_valid_installed_certificate(self) -> bool:
        if not self.settings.cert_path.exists() or not self.settings.key_path.exists():
            return False
        return self.get_cert_status().exists

    def needs_renewal(self) -> bool:
        if not self.has_valid_installed_certificate():
            return True
        status = self.get_cert_status()
        if status.expires_in_days is None:
            return True
        return status.expires_in_days <= self.settings.renew_threshold_days

    def is_renewal_running(self) -> bool:
        lock_path = self.renewal_lock_path
        if not lock_path.exists():
            return False

        try:
            pid = int(lock_path.read_text().strip())
        except (OSError, ValueError):
            lock_path.unlink(missing_ok=True)
            return False

        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            lock_path.unlink(missing_ok=True)
            return False
        except PermissionError:
            return True
        return True

    def acquire_renewal_lock(self) -> bool:
        self.ensure_ready()
        lock_path = self.renewal_lock_path
        if self.is_renewal_running():
            return False

        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if self.is_renewal_running():
                return False
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)

        with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
            file_obj.write(str(os.getpid()))
        self.update_renewal_status(
            state="running",
            reason="renewal_started",
            message="renewal task is running",
            started_at=datetime.now(UTC).isoformat(),
            finished_at=None,
        )
        self.append_renewal_log("renewal task started")
        return True

    def release_renewal_lock(self) -> None:
        self.renewal_lock_path.unlink(missing_ok=True)

    def check_and_renew(self) -> dict[str, str | int | bool | None]:
        self.ensure_ready()
        engine_name, _ = self.get_certificate_engine()
        before = self.get_cert_status()
        if self.has_valid_installed_certificate() and before.exists and before.expires_in_days is not None:
            if before.expires_in_days > self.settings.renew_threshold_days:
                return {
                    "changed": False,
                    "action": "skip",
                    "engine": engine_name,
                    "expires_at": before.expires_at.isoformat() if before.expires_at else None,
                    "expires_in_days": before.expires_in_days,
                }

        action = "issue" if not self.has_valid_installed_certificate() else "renew"
        if action == "issue":
            self.issue_certificate()
        else:
            self.renew_certificate()

        after = self.get_cert_status()
        return {
            "changed": True,
            "action": action,
            "engine": engine_name,
            "expires_at": after.expires_at.isoformat() if after.expires_at else None,
            "expires_in_days": after.expires_in_days,
        }

    def run_check_and_renew_job(self, lock_already_held: bool = False) -> dict[str, str | int | bool | None]:
        lock_owned = lock_already_held
        if not lock_owned:
            if not self.acquire_renewal_lock():
                status_info = self.get_cert_status()
                return {
                    "changed": False,
                    "action": "running",
                    "expires_at": status_info.expires_at.isoformat() if status_info.expires_at else None,
                    "expires_in_days": status_info.expires_in_days,
                }
            lock_owned = True

        try:
            result = self.check_and_renew()
            self.update_renewal_status(
                state="success",
                reason=str(result.get("action")),
                message="renewal check finished",
                finished_at=datetime.now(UTC).isoformat(),
            )
            self.append_renewal_log(
                f"renewal task finished successfully: action={result.get('action')} expires_at={result.get('expires_at')}"
            )
            return result
        except Exception as exc:
            self.update_renewal_status(
                state="failed",
                reason="error",
                message=str(exc),
                finished_at=datetime.now(UTC).isoformat(),
            )
            self.append_renewal_log(f"renewal task failed: {exc}")
            raise
        finally:
            if lock_owned:
                self.release_renewal_lock()

    def trigger_background_renewal_if_needed(self) -> dict[str, str | int | bool | None]:
        self.ensure_ready()
        status_info = self.get_cert_status()
        if not self.needs_renewal():
            self.update_renewal_status(
                state="idle",
                reason="not_due",
                message="certificate is not due for renewal",
                finished_at=datetime.now(UTC).isoformat(),
            )
            self.append_renewal_log("renewal skipped: certificate is not due")
            return {
                "triggered": False,
                "reason": "not_due",
                "expires_at": status_info.expires_at.isoformat() if status_info.expires_at else None,
                "expires_in_days": status_info.expires_in_days,
            }

        if not self.acquire_renewal_lock():
            status_info = self.get_cert_status()
            self.append_renewal_log("renewal trigger ignored: task already running")
            return {
                "triggered": False,
                "reason": "already_running",
                "expires_at": status_info.expires_at.isoformat() if status_info.expires_at else None,
                "expires_in_days": status_info.expires_in_days,
            }

        env = os.environ.copy()
        env["CERT_AUTO_API_LOCK_OWNED"] = "1"
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{self.base_dir}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(self.base_dir)
        )

        try:
            log_file = self.renewal_log_path.open("a", encoding="utf-8")
            subprocess.Popen(
                [sys.executable, "-m", "cert_auto_api.cli", "check-renew"],
                cwd=str(self.base_dir),
                env=env,
                stdout=log_file,
                stderr=log_file,
                start_new_session=True,
            )
        except Exception:
            self.release_renewal_lock()
            raise
        finally:
            if 'log_file' in locals():
                log_file.close()

        return {
            "triggered": True,
            "reason": "started",
            "expires_at": status_info.expires_at.isoformat() if status_info.expires_at else None,
            "expires_in_days": status_info.expires_in_days,
        }

    def issue_certificate(self) -> None:
        engine_name, engine_path = self.get_certificate_engine()
        if engine_name == "builtin_acme":
            self.append_renewal_log("running builtin ACME engine with Cloudflare API Token")
            BuiltinAcmeEngine(self.settings, log_callback=self.append_renewal_log).issue()
            return

        acme_sh = engine_path
        cmd = [acme_sh, "--issue"]
        for domain in self.settings.cert_domains:
            cmd.extend(["-d", domain])
        cmd.extend(
            [
                "--dns",
                self.settings.acme_dns_provider,
                "--keylength",
                self.settings.acme_keylength,
            ]
        )
        self._run_acme(cmd)
        self.install_certificate()

    def renew_certificate(self) -> None:
        engine_name, engine_path = self.get_certificate_engine()
        if engine_name == "builtin_acme":
            self.append_renewal_log("running builtin ACME engine with Cloudflare API Token")
            BuiltinAcmeEngine(self.settings, log_callback=self.append_renewal_log).issue()
            return

        acme_sh = engine_path
        cmd = [acme_sh, "--renew", "-d", self.settings.primary_domain]
        if self.settings.use_ecc:
            cmd.append("--ecc")
        try:
            self._run_acme(cmd)
        except subprocess.CalledProcessError:
            self.issue_certificate()
            return
        self.install_certificate()

    def install_certificate(self) -> None:
        engine_name, engine_path = self.get_certificate_engine()
        if engine_name == "builtin_acme":
            return

        acme_sh = engine_path
        cert_path = self.settings.cert_path
        key_path = self.settings.key_path
        cert_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            acme_sh,
            "--install-cert",
            "-d",
            self.settings.primary_domain,
        ]
        if self.settings.use_ecc:
            cmd.append("--ecc")
        cmd.extend(
            [
                "--fullchain-file",
                str(cert_path),
                "--key-file",
                str(key_path),
            ]
        )
        self._run_acme(cmd)
        os.chmod(cert_path, 0o644)
        os.chmod(key_path, 0o600)

    def create_archive(self) -> Path:
        self.ensure_ready()
        if not self.settings.cert_path.exists() or not self.settings.key_path.exists():
            raise FileNotFoundError("certificate files not found")

        temp_dir = Path(tempfile.mkdtemp(prefix="cert-bundle-"))
        archive_path = temp_dir / "certificate_bundle.tgz"
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(self.settings.cert_path, arcname=self.settings.cert_file_name)
            tar.add(self.settings.key_path, arcname=self.settings.key_file_name)
        return archive_path

    def _run_acme(self, cmd: list[str]) -> None:
        env = os.environ.copy()
        env["CF_Token"] = self.settings.cf_token
        subprocess.run(cmd, check=True, env=env, cwd=str(self.settings.cert_output_dir))
