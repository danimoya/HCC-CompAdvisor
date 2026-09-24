"""
Unit tests for the optional ORDS REST client (hcc_advisor.utils.api_client).

- Settings: base URL, basic auth, timeout; TLS verification is on by default,
  ORDS_CA_BUNDLE replaces it with a bundle path, ORDS_VERIFY_SSL=false turns it
  off with a logged warning.
- Requests: URL joining, parameters and JSON bodies of the endpoint helpers;
  204 is a success without a body; a request error is shown with st.error and
  returned as {'error': ...} instead of raising.

No network: requests.request / requests.get are mocked.
"""
import logging
from unittest.mock import MagicMock

import pytest
import requests
from requests.auth import HTTPBasicAuth

from hcc_advisor.config import Config
from hcc_advisor.utils import api_client
from hcc_advisor.utils.api_client import ORDSClient


def _response(status=200, payload=None, text=''):
    resp = MagicMock(name='response')
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {}
    resp.text = text
    resp.raise_for_status.return_value = None
    return resp


@pytest.fixture
def ords(monkeypatch):
    """ORDS settings, a mocked requests module entry point and st."""
    monkeypatch.setattr(Config, 'ORDS_BASE_URL', 'https://ords.example/ords/hcc/')
    monkeypatch.setattr(Config, 'ORDS_USERNAME', 'hcc_advisor')
    monkeypatch.setattr(Config, 'ORDS_PASSWORD', 'ords-pw')
    monkeypatch.setattr(Config, 'ORDS_VERIFY_SSL', True)
    monkeypatch.setattr(Config, 'ORDS_CA_BUNDLE', '')
    request = MagicMock(name='requests.request', return_value=_response(payload={'ok': 1}))
    monkeypatch.setattr(api_client.requests, 'request', request)
    st = MagicMock(name='st')
    monkeypatch.setattr(api_client, 'st', st)
    return request, st


def _call(request):
    """(method, url, kwargs) of the single requests.request call."""
    kwargs = request.call_args.kwargs
    return kwargs['method'], kwargs['url'], kwargs


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.api
class TestAPIClient:

    def test_settings_from_config(self, ords):
        client = ORDSClient()
        assert client.base_url == 'https://ords.example/ords/hcc'
        assert client.auth == HTTPBasicAuth('hcc_advisor', 'ords-pw')
        assert client.timeout == Config.API_TIMEOUT
        assert client.verify_ssl is True

    def test_ca_bundle_replaces_default_verification(self, ords, monkeypatch):
        monkeypatch.setattr(Config, 'ORDS_CA_BUNDLE', '/etc/ssl/internal-ca.pem')
        monkeypatch.setattr(Config, 'ORDS_VERIFY_SSL', False)
        assert ORDSClient().verify_ssl == '/etc/ssl/internal-ca.pem'

    def test_disabled_verification_is_logged(self, ords, monkeypatch, caplog):
        monkeypatch.setattr(Config, 'ORDS_VERIFY_SSL', False)
        with caplog.at_level(logging.WARNING, logger=api_client.logger.name):
            client = ORDSClient()
        assert client.verify_ssl is False
        assert 'verification is DISABLED' in caplog.text

    def test_verify_setting_is_passed_to_requests(self, ords, monkeypatch):
        request, _ = ords
        monkeypatch.setattr(Config, 'ORDS_CA_BUNDLE', '/etc/ssl/internal-ca.pem')
        ORDSClient().get('health')
        assert _call(request)[2]['verify'] == '/etc/ssl/internal-ca.pem'


# ---------------------------------------------------------------------------
# Request handling
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.api
class TestAPIRequests:

    def test_get_joins_url_and_returns_json(self, ords):
        request, _ = ords
        result = ORDSClient().get('/analysis/latest', params={'a': 1})
        method, url, kwargs = _call(request)
        assert (method, url) == ('GET', 'https://ords.example/ords/hcc/analysis/latest')
        assert kwargs['params'] == {'a': 1}
        assert kwargs['json'] is None
        assert kwargs['timeout'] == Config.API_TIMEOUT
        assert kwargs['auth'] == HTTPBasicAuth('hcc_advisor', 'ords-pw')
        assert result == {'ok': 1}

    @pytest.mark.parametrize('verb', ['post', 'put'])
    def test_post_and_put_send_json(self, ords, verb):
        request, _ = ords
        getattr(ORDSClient(), verb)('strategies', {'name': 'X'})
        method, _, kwargs = _call(request)
        assert method == verb.upper()
        assert kwargs['json'] == {'name': 'X'}

    def test_delete(self, ords):
        request, _ = ords
        ORDSClient().delete('strategies/X')
        assert _call(request)[:2] == ('DELETE', 'https://ords.example/ords/hcc/strategies/X')

    def test_no_content_is_success(self, ords):
        request, _ = ords
        request.return_value = _response(status=204)
        assert ORDSClient().delete('strategies/X') == {'success': True}

    @pytest.mark.parametrize('exc', [
        requests.exceptions.ConnectionError('connection refused'),
        requests.exceptions.Timeout('timed out'),
    ])
    def test_request_error_is_reported_not_raised(self, ords, exc):
        request, st = ords
        request.side_effect = exc
        result = ORDSClient().get('health')
        assert result == {'error': str(exc)}
        assert 'API request failed' in st.error.call_args.args[0]

    def test_http_error_status_is_reported(self, ords):
        request, st = ords
        resp = _response(status=500)
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError('500 Server Error')
        request.return_value = resp
        assert ORDSClient().get('recommendations') == {'error': '500 Server Error'}
        st.error.assert_called_once()


# ---------------------------------------------------------------------------
# Endpoint helpers
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.api
class TestAPIEndpoints:

    @pytest.mark.parametrize('call, method, path, params, body', [
        (lambda c: c.start_analysis(250.0), 'POST', 'analysis/start', None,
         {'min_size_mb': 250.0}),
        (lambda c: c.get_analysis_status(7), 'GET', 'analysis/7/status', None, None),
        (lambda c: c.get_latest_analysis(), 'GET', 'analysis/latest', None, None),
        (lambda c: c.get_recommendations(), 'GET', 'recommendations',
         {'min_savings_pct': 10.0, 'limit': 100}, None),
        (lambda c: c.get_recommendations('BALANCED', 25.0, 5), 'GET', 'recommendations',
         {'min_savings_pct': 25.0, 'limit': 5, 'strategy': 'BALANCED'}, None),
        (lambda c: c.get_recommendation_details(3), 'GET', 'recommendations/3', None, None),
        (lambda c: c.execute_compression(3), 'POST', 'compression/execute', None,
         {'recommendation_id': 3, 'dry_run': True, 'parallel_degree': 4}),
        (lambda c: c.get_execution_status(9), 'GET', 'compression/execution/9', None, None),
        (lambda c: c.get_execution_history(), 'GET', 'compression/history', {'limit': 100}, None),
        (lambda c: c.get_execution_history('2026-01-01', '2026-02-01', 10), 'GET',
         'compression/history',
         {'limit': 10, 'start_date': '2026-01-01', 'end_date': '2026-02-01'}, None),
        (lambda c: c.get_compression_statistics(), 'GET', 'statistics/compression', None, None),
        (lambda c: c.get_savings_by_strategy(), 'GET', 'statistics/savings-by-strategy',
         None, None),
        (lambda c: c.get_table_statistics('HR', 'EMP'), 'GET', 'statistics/table/HR/EMP',
         None, None),
        (lambda c: c.get_strategies(), 'GET', 'strategies', None, None),
        (lambda c: c.get_strategy_details('BALANCED'), 'GET', 'strategies/BALANCED', None, None),
        (lambda c: c.compare_strategies('HR', 'EMP'), 'GET', 'strategies/compare/HR/EMP',
         None, None),
        (lambda c: c.batch_execute([1, 2], dry_run=False, parallel_degree=8), 'POST',
         'compression/batch', None,
         {'recommendation_ids': [1, 2], 'dry_run': False, 'parallel_degree': 8}),
    ])
    def test_endpoint(self, ords, call, method, path, params, body):
        request, _ = ords
        call(ORDSClient())
        got_method, url, kwargs = _call(request)
        assert got_method == method
        assert url == f'https://ords.example/ords/hcc/{path}'
        assert kwargs['params'] == params
        assert kwargs['json'] == body

    @pytest.mark.parametrize('payload, healthy', [
        ({'status': 'healthy'}, True),
        ({'status': 'degraded'}, False),
        ({}, False),
    ])
    def test_health_check(self, ords, payload, healthy):
        request, _ = ords
        request.return_value = _response(payload=payload)
        assert ORDSClient().health_check() is healthy

    def test_health_check_is_false_when_unreachable(self, ords):
        request, _ = ords
        request.side_effect = requests.exceptions.ConnectionError('refused')
        assert ORDSClient().health_check() is False

    def test_export_csv(self, ords, monkeypatch):
        get = MagicMock(return_value=_response(text='owner,table\nHR,EMP\n'))
        monkeypatch.setattr(api_client.requests, 'get', get)
        assert ORDSClient().export_recommendations_csv('BALANCED') == 'owner,table\nHR,EMP\n'
        assert get.call_args.args[0] == 'https://ords.example/ords/hcc/export/recommendations/csv'
        assert get.call_args.kwargs['params'] == {'strategy': 'BALANCED'}
        assert get.call_args.kwargs['verify'] is True

    def test_export_csv_failure_returns_empty(self, ords, monkeypatch):
        _, st = ords
        monkeypatch.setattr(api_client.requests, 'get',
                            MagicMock(side_effect=requests.exceptions.Timeout('slow')))
        assert ORDSClient().export_recommendations_csv() == ''
        assert 'Export failed' in st.error.call_args.args[0]
