from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _split_domains(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(slots=True)
class Settings:
    api_host: str
    api_port: int
    api_token: str
    api_prefix: str
    cert_domains: list[str]
    cf_token: str
    ali_key: str
    ali_secret: str
    dp_id: str
    dp_key: str
    cert_output_dir: Path
    renew_threshold_days: int
    acme_dns_provider: str
    acme_keylength: str
    acme_directory_url: str
    acme_contact_email: str
    dns_propagation_timeout: int
    dns_poll_interval: int
    cert_file_name: str = "certificate.cert"
    key_file_name: str = "private.key"

    @property
    def cert_path(self) -> Path:
        return self.cert_output_dir / self.cert_file_name

    @property
    def key_path(self) -> Path:
        return self.cert_output_dir / self.key_file_name

    @property
    def use_ecc(self) -> bool:
        return self.acme_keylength.lower().startswith("ec-")

    @property
    def primary_domain(self) -> str:
        return next(
            (domain for domain in self.cert_domains if not domain.startswith("*.")),
            self.cert_domains[0].lstrip("*."),
        )


def load_settings() -> Settings:
    domains = _split_domains(os.getenv("CERT_DOMAINS", ""))
    if not domains:
        raise ValueError("CERT_DOMAINS is required")

    cert_output_dir = Path(os.getenv("CERT_OUTPUT_DIR", str(BASE_DIR / "certs"))).expanduser()
    if not cert_output_dir.is_absolute():
        cert_output_dir = (BASE_DIR / cert_output_dir).resolve()

    return Settings(
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=int(os.getenv("API_PORT", "8080")),
        api_token=os.getenv("API_TOKEN", "").strip(),
        api_prefix=os.getenv("API_PREFIX", "/api/v1").rstrip("/"),
        cert_domains=domains,
        cf_token=os.getenv("CF_TOKEN", "").strip(),
        ali_key=os.getenv("ALI_KEY", "").strip(),
        ali_secret=os.getenv("ALI_SECRET", "").strip(),
        dp_id=os.getenv("DP_ID", "").strip(),
        dp_key=os.getenv("DP_KEY", "").strip(),
        cert_output_dir=cert_output_dir,
        renew_threshold_days=int(os.getenv("RENEW_THRESHOLD_DAYS", "15")),
        acme_dns_provider=os.getenv("ACME_DNS_PROVIDER", "dns_cf").strip(),
        acme_keylength=os.getenv("ACME_KEYLENGTH", "ec-256").strip(),
        acme_directory_url=os.getenv(
            "ACME_DIRECTORY_URL",
            "https://acme-v02.api.letsencrypt.org/directory",
        ).strip(),
        acme_contact_email=os.getenv("ACME_CONTACT_EMAIL", "").strip(),
        dns_propagation_timeout=int(os.getenv("DNS_PROPAGATION_TIMEOUT", "180")),
        dns_poll_interval=int(os.getenv("DNS_POLL_INTERVAL", "10")),
    )
