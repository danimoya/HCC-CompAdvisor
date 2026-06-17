"""
SSRF guard for admin-configurable outbound URLs (Ollama, notification webhooks).

The admin panel lets an operator persist an Ollama base URL and a webhook URL
and then makes server-side HTTP requests to them. Without validation, those
requests can be aimed at internal-only addresses (cloud metadata, the central
DB, the proxy, loopback admin ports) — classic SSRF. This module centralises
scheme + host allowlisting and resolves the destination to reject loopback,
link-local, private and otherwise non-global IP literals (and the IPs a
hostname resolves to), so every call site validates the same way.

Use validate_outbound_url(url, kind) before issuing the request. It raises
UrlNotAllowed (a ValueError subclass) on rejection. Callers should also disable
redirects so a permitted host cannot 30x-bounce to an internal target.
"""

import ipaddress
import socket
from fnmatch import fnmatch
from typing import List
from urllib.parse import urlsplit

from hcc_advisor.config import config


class UrlNotAllowed(ValueError):
    """Raised when an outbound URL fails the SSRF allowlist checks."""


def _split_allowlist(raw: str) -> List[str]:
    return [h.strip().lower() for h in (raw or '').split(',') if h.strip()]


def _host_allowed(host: str, patterns: List[str]) -> bool:
    host = host.lower()
    return any(fnmatch(host, p) for p in patterns)


def _is_global_ip(ip_str: str) -> bool:
    """True only for normal, globally-routable addresses."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_loopback or ip.is_link_local or ip.is_private
        or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def _resolve_ips(host: str) -> List[str]:
    """Resolve host to all A/AAAA addresses (raises on failure)."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return list({info[4][0] for info in infos})


def validate_outbound_url(url: str, kind: str) -> str:
    """
    Validate an admin-supplied URL before a server-side request.

    kind: 'webhook' (must be https, host in WEBHOOK_HOST_ALLOWLIST) or
          'ollama'  (http/https, host in OLLAMA_HOST_ALLOWLIST).

    Returns the URL unchanged if allowed; raises UrlNotAllowed otherwise.
    Destination IPs (including those a hostname resolves to) must be globally
    routable unless config.SSRF_ALLOW_PRIVATE is set.
    """
    if not url or not isinstance(url, str):
        raise UrlNotAllowed("Empty URL")

    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = parts.hostname

    if not host:
        raise UrlNotAllowed("URL has no host")

    if kind == 'webhook':
        allowed_schemes = {'https'}
        allowlist = _split_allowlist(config.WEBHOOK_HOST_ALLOWLIST)
    elif kind == 'ollama':
        allowed_schemes = {'http', 'https'}
        allowlist = _split_allowlist(config.OLLAMA_HOST_ALLOWLIST)
    else:
        raise UrlNotAllowed(f"Unknown URL kind: {kind}")

    if scheme not in allowed_schemes:
        raise UrlNotAllowed(
            f"Scheme {scheme!r} not allowed for {kind} (need {sorted(allowed_schemes)})")

    # Host allowlist. If no allowlist is configured for a kind, fail closed
    # rather than allowing arbitrary hosts.
    if not allowlist:
        raise UrlNotAllowed(
            f"No host allowlist configured for {kind}; set the corresponding "
            f"*_HOST_ALLOWLIST env var to permit destinations.")
    if not _host_allowed(host, allowlist):
        raise UrlNotAllowed(f"Host {host!r} is not in the {kind} allowlist")

    # Resolve and reject non-global destinations (blocks IP literals like
    # 169.254.169.254 / 127.0.0.1 / 10.x and DNS names pointing at them),
    # unless private destinations are explicitly permitted.
    if not config.SSRF_ALLOW_PRIVATE:
        try:
            resolved = _resolve_ips(host)
        except socket.gaierror as exc:
            raise UrlNotAllowed(f"Could not resolve host {host!r}: {exc}")
        if not resolved:
            raise UrlNotAllowed(f"Host {host!r} did not resolve")
        for ip_str in resolved:
            if not _is_global_ip(ip_str):
                raise UrlNotAllowed(
                    f"Host {host!r} resolves to non-global address {ip_str}; "
                    f"set SSRF_ALLOW_PRIVATE=true to permit internal targets.")

    return url
