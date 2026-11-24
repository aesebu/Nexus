import http.client
import hmac
import ipaddress
import socket
import ssl
from hashlib import sha256
from urllib.parse import urlsplit

from app.core.config import settings


class WebhookConfigurationError(ValueError):
    pass


class WebhookTransientError(RuntimeError):
    pass


def _normalise_hostname(hostname: str) -> str:
    try:
        return hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise WebhookConfigurationError("Webhook destination hostname is invalid") from exc


def validate_webhook_destination(target_url: str) -> tuple[str, int, str]:
    if any(ord(character) < 32 or ord(character) == 127 for character in target_url):
        raise WebhookConfigurationError("Webhook destination URL contains control characters")
    try:
        parsed = urlsplit(target_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise WebhookConfigurationError("Webhook destination URL is invalid") from exc

    if (
        parsed.scheme.lower() != "https"
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port not in (None, 443)
    ):
        raise WebhookConfigurationError(
            "Webhook destinations must use HTTPS on port 443 without credentials, query, or fragment"
        )

    normalised_hostname = _normalise_hostname(hostname)
    try:
        ipaddress.ip_address(normalised_hostname)
    except ValueError:
        pass
    else:
        raise WebhookConfigurationError("Webhook destinations must use an allowlisted hostname")

    allowed_hosts = {
        _normalise_hostname(host.strip())
        for host in settings.integration_allowed_hosts.split(",")
        if host.strip()
    }
    if not allowed_hosts or normalised_hostname not in allowed_hosts:
        raise WebhookConfigurationError(
            "Webhook destination hostname is not in NEXUS_INTEGRATION_ALLOWED_HOSTS"
        )

    return normalised_hostname, 443, parsed.path or "/"


def _resolve_public_ip(hostname: str, port: int) -> str:
    try:
        addresses = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise WebhookTransientError("Webhook destination could not be resolved") from exc

    unique_addresses = {record[4][0] for record in addresses}
    if not unique_addresses:
        raise WebhookTransientError("Webhook destination did not resolve")
    for address in unique_addresses:
        try:
            is_public = ipaddress.ip_address(address).is_global
        except ValueError as exc:
            raise WebhookConfigurationError(
                "Webhook destination resolved to an invalid IP address"
            ) from exc
        if not is_public:
            raise WebhookConfigurationError(
                "Webhook destination must resolve only to public IP addresses"
            )
    return sorted(unique_addresses)[0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        hostname: str,
        *,
        address: str,
        timeout: float,
    ) -> None:
        super().__init__(
            hostname,
            port=443,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._address = address

    def connect(self) -> None:
        sock = socket.create_connection(
            (self._address, self.port),
            self.timeout,
            self.source_address,
        )
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def send_signed_webhook(
    *,
    target_url: str,
    signing_secret: str,
    body: bytes,
    event_id: str,
    delivery_id: str,
    timeout: float = 10.0,
) -> int:
    hostname, port, path = validate_webhook_destination(target_url)
    address = _resolve_public_ip(hostname, port)
    signature = hmac.new(
        signing_secret.encode("utf-8"),
        body,
        sha256,
    ).hexdigest()
    connection = _PinnedHTTPSConnection(
        hostname,
        address=address,
        timeout=timeout,
    )
    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers={
                "Content-Type": "application/json",
                "X-Nexus-Event-ID": event_id,
                "X-Nexus-Delivery-ID": delivery_id,
                "X-Nexus-Signature": f"sha256={signature}",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        return response.status
    except (OSError, http.client.HTTPException) as exc:
        raise WebhookTransientError("Webhook delivery request failed") from exc
    finally:
        connection.close()
