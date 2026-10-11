import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit


class UnsafeUrlError(ValueError):
    pass


Resolver = Callable[[str, int], Awaitable[list[str]]]


BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "instance-data",
}


async def system_resolver(hostname: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return list({record[4][0] for record in records})


class PublicUrlGuard:
    def __init__(self, resolver: Resolver = system_resolver):
        self.resolver = resolver

    async def validate(self, url: str) -> str:
        await self.resolve_public(url)
        return url

    async def resolve_public(self, url: str) -> list[str]:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise UnsafeUrlError("Only HTTP and HTTPS URLs are allowed")
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise UnsafeUrlError("URL host or credentials are invalid")
        hostname = parsed.hostname.lower().rstrip(".")
        if hostname in BLOCKED_HOSTS or hostname.endswith(".localhost") or hostname.endswith(".internal"):
            raise UnsafeUrlError("Local and metadata hosts are blocked")
        try:
            port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        except ValueError as exc:
            raise UnsafeUrlError("URL port is invalid") from exc
        try:
            literal = ipaddress.ip_address(hostname)
            addresses = [literal]
        except ValueError:
            try:
                addresses = [ipaddress.ip_address(value) for value in await self.resolver(hostname, port)]
            except (OSError, ValueError) as exc:
                raise UnsafeUrlError("URL host could not be resolved") from exc
        if not addresses or any(not address.is_global for address in addresses):
            raise UnsafeUrlError("Private, local, reserved, and metadata addresses are blocked")
        return [str(address) for address in addresses]
