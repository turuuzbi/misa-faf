import asyncio
import ipaddress
import re
import socket
from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import get_settings


_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "instance-data",
}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_BUILTIN_MEDIA_HOSTS = {
    "cdn.discordapp.com",
    "media.discordapp.net",
    "lh3.googleusercontent.com",
    "t.me",
}


def _normalized_host(value: str) -> str:
    host = (value or "").strip().rstrip(".").lower()
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return ""


def _host_is_public(host: str) -> bool:
    normalized = _normalized_host(host)
    if not normalized or normalized in _BLOCKED_HOSTS or normalized.endswith(_BLOCKED_SUFFIXES):
        return False
    try:
        return ipaddress.ip_address(normalized).is_global
    except ValueError:
        # Browsers accept several legacy numeric-IP spellings that ipaddress rejects.
        if re.fullmatch(r"[0-9.]+", normalized) or re.fullmatch(r"0x[0-9a-f]+", normalized):
            return False
        # Single-label names are local/service-discovery names, never public web hosts.
        return "." in normalized


def safe_public_url(
    value: object,
    *,
    allowed_hosts: Iterable[str] | None = None,
    https_only: bool = False,
) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > 2000:
        return None
    try:
        parsed = urlparse(text)
        port = parsed.port
    except ValueError:
        return None
    schemes = {"https"} if https_only else {"http", "https"}
    if parsed.scheme.lower() not in schemes or not parsed.netloc or parsed.username or parsed.password:
        return None
    host = _normalized_host(parsed.hostname or "")
    if not _host_is_public(host):
        return None
    expected_port = 443 if parsed.scheme.lower() == "https" else 80
    if port is not None and port != expected_port:
        return None
    if allowed_hosts is not None:
        normalized_allowed = {_normalized_host(item) for item in allowed_hosts if _normalized_host(item)}
        if host not in normalized_allowed:
            return None
    return text


def configured_media_hosts() -> set[str]:
    settings = get_settings()
    hosts = set(_BUILTIN_MEDIA_HOSTS)
    for raw_url in (settings.r2_public_base_url, settings.supabase_url):
        host = _normalized_host(urlparse(raw_url).hostname or "")
        if host:
            hosts.add(host)
    hosts.update(_normalized_host(item) for item in settings.media_fetch_host_list)
    return {host for host in hosts if host}


def safe_media_url(value: object) -> str | None:
    return safe_public_url(value, allowed_hosts=configured_media_hosts(), https_only=True)


async def _resolved_url(value: str, allowed_hosts: Iterable[str] | None, *, https_only: bool = True) -> str | None:
    safe = safe_public_url(value, allowed_hosts=allowed_hosts, https_only=https_only)
    if not safe:
        return None
    parsed = urlparse(safe)
    try:
        records = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except (OSError, UnicodeError):
        return None
    addresses = {record[4][0].split("%", 1)[0] for record in records if record[4]}
    if not addresses:
        return None
    try:
        if any(not ipaddress.ip_address(address).is_global for address in addresses):
            return None
    except ValueError:
        return None
    return safe


async def fetch_public_image_bytes(url: object, *, max_bytes: int, max_redirects: int = 3) -> bytes | None:
    allowed_hosts = configured_media_hosts()
    current = str(url or "").strip()
    headers = {"Accept": "image/*", "User-Agent": "misa.lol media renderer"}
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False, trust_env=False) as client:
            for redirect_count in range(max_redirects + 1):
                safe = await _resolved_url(current, allowed_hosts)
                if not safe:
                    return None
                async with client.stream("GET", safe, headers=headers) as response:
                    if response.status_code in _REDIRECT_CODES:
                        location = response.headers.get("location")
                        if not location or redirect_count >= max_redirects:
                            return None
                        current = urljoin(safe, location)
                        continue
                    if response.status_code != 200:
                        return None
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type and not content_type.startswith("image/"):
                        return None
                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            if int(content_length) > max_bytes:
                                return None
                        except ValueError:
                            return None
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            return None
                    return bytes(body)
    except (httpx.HTTPError, OSError, ValueError):
        return None
    return None


async def probe_public_url(url: object, *, max_redirects: int = 3, timeout: float = 8.0) -> tuple[bool, str]:
    """Check whether a user-supplied web link answers, without reaching private networks.

    Every hop (including redirects) must be http(s) on a standard port and resolve
    only to public addresses, so a profile link cannot be used to probe the
    data-api, Dragonfly, cloud metadata or anything else on the internal network.
    Returns (ok, note) for display in the dashboard.
    """
    current = str(url or "").strip()
    headers = {"User-Agent": "Mozilla/5.0 (misa.lol link check)"}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            for redirect_count in range(max_redirects + 1):
                safe = await _resolved_url(current, None, https_only=False)
                if not safe:
                    return False, "not a public web address"
                async with client.stream("GET", safe, headers=headers) as response:
                    if response.status_code in _REDIRECT_CODES:
                        location = response.headers.get("location")
                        if not location or redirect_count >= max_redirects:
                            return False, "too many redirects"
                        current = urljoin(safe, location)
                        continue
                    if response.status_code < 400:
                        return True, "ok"
                    return False, f"returns {response.status_code}"
    except (httpx.HTTPError, OSError, ValueError):
        return False, "could not reach it"
    return False, "could not reach it"
