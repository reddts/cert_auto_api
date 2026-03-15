from __future__ import annotations

import ipaddress
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import josepy as jose
from acme import challenges, client, errors, messages
import certifi
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID
import dns.resolver

from .config import Settings


CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"
PUBLIC_DNS_RESOLVERS = [
    "1.1.1.1",
    "8.8.8.8",
]


@dataclass(slots=True)
class DnsRecordRef:
    zone_id: str
    record_id: str
    name: str
    value: str


class CloudflareTokenDnsClient:
    def __init__(self, token: str) -> None:
        self.token = token
        self._zone_cache: dict[str, tuple[str, str]] = {}
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        url = f"{CLOUDFLARE_API_BASE}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "cert_auto_api/1.0",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, context=self.ssl_context) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Cloudflare API request failed: {exc.code} {body}") from exc

        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Cloudflare API returned invalid JSON: {body}") from exc

        if not result.get("success"):
            raise RuntimeError(f"Cloudflare API error: {result}")
        return result

    def _zone_candidates(self, fqdn: str) -> list[str]:
        hostname = fqdn.rstrip(".")
        labels = hostname.split(".")
        candidates: list[str] = []
        for index in range(len(labels) - 1):
            candidate = ".".join(labels[index:])
            try:
                ipaddress.ip_address(candidate)
                continue
            except ValueError:
                pass
            if candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def get_zone(self, fqdn: str) -> tuple[str, str]:
        for candidate in self._zone_candidates(fqdn):
            cached = self._zone_cache.get(candidate)
            if cached:
                return cached

            result = self._request("GET", "/zones", query={"name": candidate, "status": "active", "per_page": "1"})
            zones = result.get("result") or []
            if zones:
                zone = zones[0]
                zone_info = (str(zone["id"]), candidate)
                self._zone_cache[candidate] = zone_info
                return zone_info

        raise RuntimeError(f"Cloudflare zone not found for {fqdn}")

    def create_txt_record(self, fqdn: str, value: str) -> DnsRecordRef:
        zone_id, _ = self.get_zone(fqdn)
        result = self._request(
            "POST",
            f"/zones/{zone_id}/dns_records",
            payload={
                "type": "TXT",
                "name": fqdn.rstrip("."),
                "content": value,
                "ttl": 60,
            },
        )
        record = result["result"]
        return DnsRecordRef(
            zone_id=zone_id,
            record_id=str(record["id"]),
            name=fqdn.rstrip("."),
            value=value,
        )

    def delete_record(self, record: DnsRecordRef) -> None:
        try:
            self._request("DELETE", f"/zones/{record.zone_id}/dns_records/{record.record_id}")
        except RuntimeError:
            # Cleanup is best-effort and should not hide the original ACME result.
            return


class BuiltinAcmeEngine:
    def __init__(self, settings: Settings, log_callback: Callable[[str], None] | None = None) -> None:
        self.settings = settings
        self.state_dir = self.settings.cert_output_dir / ".engine_state"
        self.account_key_path = self.state_dir / "account.key.pem"
        self.dns_client = CloudflareTokenDnsClient(self.settings.cf_token)
        self.log_callback = log_callback

    def issue(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._log("builtin ACME engine started")
        account_key = self._load_or_create_account_key()
        acme_client = self._create_client(account_key)
        self._ensure_account(acme_client)

        domain_key = self._generate_domain_private_key()
        csr_pem = self._build_csr(domain_key)
        self._log("creating ACME order")
        order = acme_client.new_order(csr_pem)

        created_records: list[DnsRecordRef] = []
        try:
            for authorization in order.authorizations:
                domain_name = authorization.body.identifier.value
                dns_name = domain_name[2:] if domain_name.startswith("*.") else domain_name
                challenge_body = self._get_dns_challenge(authorization)
                validation_name = challenge_body.chall.validation_domain_name(dns_name)
                validation_value = challenge_body.chall.validation(acme_client.net.key)
                self._log(f"creating Cloudflare TXT record for {validation_name}")
                created_records.append(self.dns_client.create_txt_record(validation_name, validation_value))

            self._log("waiting for DNS propagation")
            self._wait_for_dns(created_records)

            for authorization in order.authorizations:
                challenge_body = self._get_dns_challenge(authorization)
                response = challenge_body.chall.response(acme_client.net.key)
                acme_client.answer_challenge(challenge_body, response)

            self._log("polling ACME order until finalized")
            finalized_order = acme_client.poll_and_finalize(
                order,
                deadline=datetime.now() + timedelta(seconds=self.settings.dns_propagation_timeout + 300),
            )
        finally:
            for record in created_records:
                self.dns_client.delete_record(record)

        if not finalized_order.fullchain_pem:
            raise RuntimeError("ACME finalize succeeded but no fullchain certificate was returned")

        self.settings.cert_output_dir.mkdir(parents=True, exist_ok=True)
        self.settings.cert_path.write_text(finalized_order.fullchain_pem, encoding="utf-8")
        self.settings.key_path.write_bytes(
            domain_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        self.settings.cert_path.chmod(0o644)
        self.settings.key_path.chmod(0o600)
        self._log("builtin ACME engine finished successfully")

    def _load_or_create_account_key(self) -> rsa.RSAPrivateKey:
        if self.account_key_path.exists():
            return serialization.load_pem_private_key(
                self.account_key_path.read_bytes(),
                password=None,
            )

        account_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.account_key_path.write_bytes(
            account_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        return account_key

    def _create_client(self, account_key: rsa.RSAPrivateKey) -> client.ClientV2:
        jwk = jose.JWKRSA(key=account_key)
        net = client.ClientNetwork(jwk, user_agent="cert_auto_api/1.0")
        directory = client.ClientV2.get_directory(self.settings.acme_directory_url, net)
        return client.ClientV2(directory, net=net)

    def _ensure_account(self, acme_client: client.ClientV2) -> None:
        registration = messages.NewRegistration.from_data(
            email=self.settings.acme_contact_email or None,
            terms_of_service_agreed=True,
        )
        try:
            acme_client.new_account(registration)
        except errors.ConflictError as exc:
            existing = messages.RegistrationResource(
                body=messages.Registration(),
                uri=getattr(exc, "location", exc.args[0]),
            )
            acme_client.query_registration(existing)

    def _generate_domain_private_key(self) -> rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey:
        keylength = self.settings.acme_keylength.lower()
        if keylength == "ec-256":
            return ec.generate_private_key(ec.SECP256R1())
        if keylength == "ec-384":
            return ec.generate_private_key(ec.SECP384R1())

        key_size = 2048
        if "-" in keylength:
            _, _, size = keylength.partition("-")
            if size.isdigit():
                key_size = int(size)
        return rsa.generate_private_key(public_exponent=65537, key_size=key_size)

    def _build_csr(self, private_key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey) -> bytes:
        common_name = self.settings.primary_domain
        san_names = [x509.DNSName(domain) for domain in self.settings.cert_domains]
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(
                x509.Name(
                    [
                        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
                    ]
                )
            )
            .add_extension(x509.SubjectAlternativeName(san_names), critical=False)
            .sign(private_key, hashes.SHA256())
        )
        return csr.public_bytes(serialization.Encoding.PEM)

    def _get_dns_challenge(self, authorization: messages.AuthorizationResource) -> messages.ChallengeBody:
        for challenge_body in authorization.body.challenges:
            if isinstance(challenge_body.chall, challenges.DNS01):
                return challenge_body
        raise RuntimeError(
            f"No DNS-01 challenge available for {authorization.body.identifier.value}"
        )

    def _wait_for_dns(self, records: list[DnsRecordRef]) -> None:
        deadline = time.time() + self.settings.dns_propagation_timeout
        while time.time() < deadline:
            if all(self._record_visible(record) for record in records):
                return
            time.sleep(max(self.settings.dns_poll_interval, 1))
        unresolved = ", ".join(record.name for record in records if not self._record_visible(record))
        raise RuntimeError(f"DNS propagation timeout for TXT records: {unresolved}")

    def _record_visible(self, record: DnsRecordRef) -> bool:
        for resolver_ip in PUBLIC_DNS_RESOLVERS:
            resolver = dns.resolver.Resolver(configure=False)
            resolver.nameservers = [resolver_ip]
            resolver.lifetime = 5
            resolver.timeout = 5
            try:
                answers = resolver.resolve(record.name, "TXT")
            except Exception:
                return False

            values = {
                b"".join(item.strings).decode("utf-8")
                for item in answers
            }
            if record.value not in values:
                return False
        return True

    def _log(self, message: str) -> None:
        if self.log_callback:
            self.log_callback(message)
