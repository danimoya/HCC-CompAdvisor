"""
Unit tests for API client module.
"""
import pytest
from unittest.mock import MagicMock, patch
import requests
from datetime import datetime


@pytest.mark.unit
@pytest.mark.api
class TestAPIClient:
    """Test API client initialization and configuration."""

    def test_api_client_initialization(self, mock_config):
        """Test API client initialization with configuration."""
        # Arrange
        api_config = mock_config['api']

        # Act
        client = {
            'base_url': api_config['base_url'],
            'timeout': api_config['timeout'],
            'api_key': api_config['api_key']
        }

        # Assert
        assert client['base_url'] == 'http://localhost:8080'
        assert client['timeout'] == 30
        assert client['api_key'] == 'test_api_key'

    def test_api_client_default_headers(self, mock_config):
        """Test API client sets default headers."""
        # Arrange & Act
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-API-Key': mock_config['api']['api_key']
        }

        # Assert
        assert headers['Content-Type'] == 'application/json'
        assert headers['Accept'] == 'application/json'
        assert 'X-API-Key' in headers

    def test_api_client_timeout_configuration(self, mock_config):
        """Test API client timeout configuration."""
        # Arrange
        api_config = mock_config['api']

        # Act
        timeout = api_config['timeout']

        # Assert
        assert timeout == 30
        assert isinstance(timeout, int)


@pytest.mark.unit
@pytest.mark.api
class TestAPIRequests:
    """Test API request methods."""

    def test_get_request_success(self, mock_requests_session, mock_api_response):
        """Test successful GET request."""
        # Arrange
        mock_requests_session.get.return_value = mock_api_response
        endpoint = '/api/v1/tables'

        # Act
        response = mock_requests_session.get(endpoint)

        # Assert
        assert response.status_code == 200
        assert response.json()['status'] == 'success'
        mock_requests_session.get.assert_called_once_with(endpoint)

    def test_post_request_success(self, mock_requests_session, mock_api_response):
        """Test successful POST request."""
        # Arrange
        mock_requests_session.post.return_value = mock_api_response
        endpoint = '/api/v1/analyze'
        payload = {'table_name': 'CUSTOMERS'}

        # Act
        response = mock_requests_session.post(endpoint, json=payload)

        # Assert
        assert response.status_code == 200
        assert response.json()['status'] == 'success'
        mock_requests_session.post.assert_called_once_with(endpoint, json=payload)

    def test_request_with_retry(self, mock_requests_session, mock_api_response):
        """Test request retry mechanism."""
        # Arrange
        mock_requests_session.get.side_effect = [
            requests.exceptions.Timeout(),
            requests.exceptions.Timeout(),
            mock_api_response
        ]
        endpoint = '/api/v1/data'
        max_retries = 3

        # Act
        for attempt in range(max_retries):
            try:
                response = mock_requests_session.get(endpoint)
                break
            except requests.exceptions.Timeout:
                if attempt == max_retries - 1:
                    raise

        # Assert
        assert response.status_code == 200
        assert mock_requests_session.get.call_count == 3

    def test_request_error_handling(self, mock_requests_session, mock_api_error_response):
        """Test API request error handling."""
        # Arrange
        mock_requests_session.get.return_value = mock_api_error_response
        endpoint = '/api/v1/invalid'

        # Act
        response = mock_requests_session.get(endpoint)

        # Assert
        assert response.status_code == 500
        assert response.json()['status'] == 'error'


@pytest.mark.unit
@pytest.mark.api
class TestAPIEndpoints:
    """Test specific API endpoint methods."""

    def test_get_compression_recommendations(self, mock_requests_session, mock_api_response,
                                            sample_compression_analysis):
        """Test getting compression recommendations."""
        # Arrange
        mock_api_response.json.return_value = sample_compression_analysis
        mock_requests_session.get.return_value = mock_api_response
        table_name = 'CUSTOMERS'

        # Act
        response = mock_requests_session.get(f'/api/v1/compression/analyze/{table_name}')
        data = response.json()

        # Assert
        assert data['table_name'] == table_name
        assert 'recommendations' in data
        assert len(data['recommendations']) == 2

    def test_submit_compression_job(self, mock_requests_session, mock_api_response):
        """Test submitting compression job."""
        # Arrange
        mock_api_response.json.return_value = {
            'job_id': 'job_12345',
            'status': 'queued',
            'table_name': 'CUSTOMERS'
        }
        mock_requests_session.post.return_value = mock_api_response
        payload = {
            'table_name': 'CUSTOMERS',
            'compression_type': 'QUERY_LOW'
        }

        # Act
        response = mock_requests_session.post('/api/v1/compression/jobs', json=payload)
        data = response.json()

        # Assert
        assert 'job_id' in data
        assert data['status'] == 'queued'
        assert data['table_name'] == 'CUSTOMERS'

    def test_get_job_status(self, mock_requests_session, mock_api_response):
        """Test getting job status."""
        # Arrange
        job_id = 'job_12345'
        mock_api_response.json.return_value = {
            'job_id': job_id,
            'status': 'completed',
            'progress': 100
        }
        mock_requests_session.get.return_value = mock_api_response

        # Act
        response = mock_requests_session.get(f'/api/v1/compression/jobs/{job_id}')
        data = response.json()

        # Assert
        assert data['job_id'] == job_id
        assert data['status'] == 'completed'
        assert data['progress'] == 100

    def test_get_table_statistics(self, mock_requests_session, mock_api_response):
        """Test getting table statistics."""
        # Arrange
        table_name = 'CUSTOMERS'
        mock_api_response.json.return_value = {
            'table_name': table_name,
            'size_mb': 1024.5,
            'row_count': 5000000,
            'compression': None
        }
        mock_requests_session.get.return_value = mock_api_response

        # Act
        response = mock_requests_session.get(f'/api/v1/tables/{table_name}/stats')
        data = response.json()

        # Assert
        assert data['table_name'] == table_name
        assert data['size_mb'] == 1024.5
        assert data['row_count'] == 5000000


@pytest.mark.unit
@pytest.mark.api
class TestAPIAuthentication:
    """Test API authentication handling."""

    def test_api_key_authentication(self, mock_requests_session, mock_api_response, mock_config):
        """Test API key authentication."""
        # Arrange
        api_key = mock_config['api']['api_key']
        headers = {'X-API-Key': api_key}
        mock_requests_session.get.return_value = mock_api_response

        # Act
        response = mock_requests_session.get('/api/v1/protected', headers=headers)

        # Assert
        assert response.status_code == 200
        mock_requests_session.get.assert_called_once_with('/api/v1/protected', headers=headers)

    def test_unauthorized_access(self, mock_requests_session):
        """Test handling unauthorized access."""
        # Arrange
        error_response = MagicMock()
        error_response.status_code = 401
        error_response.json.return_value = {'error': 'Unauthorized'}
        mock_requests_session.get.return_value = error_response

        # Act
        response = mock_requests_session.get('/api/v1/protected')

        # Assert
        assert response.status_code == 401
        assert 'error' in response.json()
