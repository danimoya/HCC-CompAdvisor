"""
Unit tests for the SSRF guard on admin-configured outbound URLs
(hcc_advisor.utils.url_guard.validate_outbound_url).

- Webhooks must be https to a host in WEBHOOK_HOST_ALLOWLIST; Ollama may be
  http or https to a host in OLLAMA_HOST_ALLOWLIST; an empty allowlist fails
  closed.
- Every address the host resolves to must be globally routable (no loopback,
  link-local / cloud metadata, private, multicast, reserved) unless
  SSRF_ALLOW_PRIVATE is set.

No network: DNS resolution is mocked.
"""
import socket

import pytest

from hcc_advisor.config import Config
from hcc_advisor.utils import url_guard
from hcc_advisor.utils.url_guard import UrlNotAllowed, validate_outbound_url

PUBLIC_IP = '93.184.216.34'


@pytest.fixture
def dns(monkeypatch):
    """Allowlists as shipped (webhooks: Slack/Teams) plus an Ollama host, and
    a fake resolver: host -> list of IPs (default: one public address)."""
    monkeypatch.setattr(Config, 'WEBHOOK_HOST_ALLOWLIST', 'hooks.slack.com,*.webhook.office.com')
    monkeypatch.setattr(Config, 'OLLAMA_HOST_ALLOWLIST', 'ollama.example.com, 127.0.0.1')
    monkeypatch.setattr(Config, 'SSRF_ALLOW_PRIVATE', False)
    table = {}
    calls = []

    def resolve(host):
        calls.append(host)
        result = table.get(host, [PUBLIC_IP])
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(url_guard, '_resolve_ips', resolve)
    return table, calls


def _rejected(url, kind) -> str:
    with pytest.raises(UrlNotAllowed) as exc:
        validate_outbound_url(url, kind)
    return str(exc.value)


@pytest.mark.unit
class TestSchemeAndHost:

    def test_allowed_webhook_is_returned_unchanged(self, dns):
        url = 'https://hooks.slack.com/services/T000/B000/XXXX'
        assert validate_outbound_url(url, 'webhook') == url

    def test_wildcard_and_case_insensitive_hosts(self, dns):
        assert validate_outbound_url('https://ACME.webhook.office.com/x', 'webhook')
        assert 'not in the webhook allowlist' in _rejected(
            'https://webhook.office.com.evil.example/x', 'webhook')

    @pytest.mark.parametrize('url', [None, '', 42])
    def test_empty_url(self, dns, url):
        assert _rejected(url, 'webhook') == 'Empty URL'

    def test_url_without_host(self, dns):
        assert _rejected('https:///path-only', 'webhook') == 'URL has no host'

    def test_unknown_kind(self, dns):
        assert 'Unknown URL kind' in _rejected('https://hooks.slack.com/x', 'smtp')

    def test_webhook_requires_https(self, dns):
        assert "Scheme 'http' not allowed for webhook" in _rejected(
            'http://hooks.slack.com/x', 'webhook')

    def test_ollama_accepts_http_but_not_other_schemes(self, dns):
        assert validate_outbound_url('http://ollama.example.com:11434', 'ollama')
        assert "Scheme 'ftp' not allowed" in _rejected('ftp://ollama.example.com/', 'ollama')

    def test_empty_allowlist_fails_closed(self, dns, monkeypatch):
        monkeypatch.setattr(Config, 'OLLAMA_HOST_ALLOWLIST', ' , ')
        assert 'No host allowlist configured for ollama' in _rejected(
            'http://ollama.example.com', 'ollama')

    def test_userinfo_does_not_fool_the_host_check(self, dns):
        assert "'evil.example' is not in the webhook allowlist" in _rejected(
            'https://hooks.slack.com@evil.example/x', 'webhook')


@pytest.mark.unit
class TestDestinationAddress:

    @pytest.mark.parametrize('ip', [
        '127.0.0.1', '169.254.169.254', '10.1.2.3', '192.168.0.10', '172.16.5.4',
        '0.0.0.0', '224.0.0.1', '::1', 'fe80::1', 'fd00::1',
    ])
    def test_non_global_resolution_is_rejected(self, dns, ip):
        table, _ = dns
        table['hooks.slack.com'] = [ip]
        message = _rejected('https://hooks.slack.com/x', 'webhook')
        assert f'non-global address {ip}' in message

    def test_one_private_address_among_several_is_enough(self, dns):
        table, _ = dns
        table['hooks.slack.com'] = [PUBLIC_IP, '10.0.0.8']
        assert 'non-global address 10.0.0.8' in _rejected('https://hooks.slack.com/x', 'webhook')

    def test_allowlisted_ip_literal_is_still_checked(self, dns):
        table, _ = dns
        table['127.0.0.1'] = ['127.0.0.1']
        assert 'non-global address 127.0.0.1' in _rejected('http://127.0.0.1:11434', 'ollama')

    def test_unresolvable_host(self, dns):
        table, _ = dns
        table['hooks.slack.com'] = socket.gaierror(-2, 'Name or service not known')
        assert "Could not resolve host 'hooks.slack.com'" in _rejected(
            'https://hooks.slack.com/x', 'webhook')

    def test_host_without_addresses(self, dns):
        table, _ = dns
        table['hooks.slack.com'] = []
        assert 'did not resolve' in _rejected('https://hooks.slack.com/x', 'webhook')

    def test_allow_private_skips_resolution(self, dns, monkeypatch):
        table, calls = dns
        monkeypatch.setattr(Config, 'SSRF_ALLOW_PRIVATE', True)
        table['127.0.0.1'] = ['127.0.0.1']
        assert validate_outbound_url('http://127.0.0.1:11434', 'ollama') == 'http://127.0.0.1:11434'
        assert calls == []

    def test_allow_private_keeps_the_allowlist(self, dns, monkeypatch):
        monkeypatch.setattr(Config, 'SSRF_ALLOW_PRIVATE', True)
        assert 'not in the ollama allowlist' in _rejected('http://10.0.0.5:11434', 'ollama')


@pytest.mark.unit
class TestHelpers:

    @pytest.mark.parametrize('ip, is_global', [
        (PUBLIC_IP, True), ('2606:4700:4700::1111', True),
        ('127.0.0.1', False), ('240.0.0.1', False), ('not-an-ip', False), ('', False),
    ])
    def test_is_global_ip(self, ip, is_global):
        assert url_guard._is_global_ip(ip) is is_global

    def test_resolve_ips_deduplicates(self, monkeypatch):
        infos = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', (PUBLIC_IP, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', (PUBLIC_IP, 0)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('2606:4700:4700::1111', 0, 0, 0)),
        ]
        monkeypatch.setattr(url_guard.socket, 'getaddrinfo', lambda host, port, proto: infos)
        assert sorted(url_guard._resolve_ips('example.com')) == sorted(
            [PUBLIC_IP, '2606:4700:4700::1111'])

    def test_split_allowlist(self):
        assert url_guard._split_allowlist(' A.example , ,b.example ') == ['a.example', 'b.example']
        assert url_guard._split_allowlist(None) == []
