"""
ORDS REST API Client for HCC Compression Advisor
Handles all REST API interactions with Oracle REST Data Services
"""

import requests
import streamlit as st
from typing import Dict, Any, Optional, List
from requests.auth import HTTPBasicAuth
from config import config
import urllib3

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ORDSClient:
    """REST API client for HCC Compression Advisor ORDS endpoints"""

    def __init__(self):
        self.base_url = config.ORDS_BASE_URL.rstrip('/')
        self.auth = HTTPBasicAuth(config.ORDS_USERNAME, config.ORDS_PASSWORD)
        self.timeout = config.API_TIMEOUT
        self.verify_ssl = False  # Use False for self-signed certificates

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Make HTTP request to ORDS API

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path
            params: Query parameters
            json_data: JSON request body

        Returns:
            dict: JSON response
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        try:
            response = requests.request(
                method=method,
                url=url,
                auth=self.auth,
                params=params,
                json=json_data,
                timeout=self.timeout,
                verify=self.verify_ssl
            )

            response.raise_for_status()

            # Handle empty response
            if response.status_code == 204:
                return {"success": True}

            return response.json()

        except requests.exceptions.RequestException as e:
            st.error(f"API request failed: {e}")
            return {"error": str(e)}

    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make GET request"""
        return self._make_request("GET", endpoint, params=params)

    def post(self, endpoint: str, json_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make POST request"""
        return self._make_request("POST", endpoint, json_data=json_data)

    def put(self, endpoint: str, json_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make PUT request"""
        return self._make_request("PUT", endpoint, json_data=json_data)

    def delete(self, endpoint: str) -> Dict[str, Any]:
        """Make DELETE request"""
        return self._make_request("DELETE", endpoint)

    # Analysis Endpoints
    def start_analysis(self, min_size_mb: float = 100.0) -> Dict[str, Any]:
        """Start compression analysis"""
        return self.post("analysis/start", {"min_size_mb": min_size_mb})

    def get_analysis_status(self, analysis_id: int) -> Dict[str, Any]:
        """Get analysis status"""
        return self.get(f"analysis/{analysis_id}/status")

    def get_latest_analysis(self) -> Dict[str, Any]:
        """Get latest analysis results"""
        return self.get("analysis/latest")

    # Recommendations Endpoints
    def get_recommendations(
        self,
        strategy: Optional[str] = None,
        min_savings_pct: float = 10.0,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Get compression recommendations"""
        params = {
            "min_savings_pct": min_savings_pct,
            "limit": limit
        }
        if strategy:
            params["strategy"] = strategy

        return self.get("recommendations", params)

    def get_recommendation_details(self, recommendation_id: int) -> Dict[str, Any]:
        """Get detailed recommendation"""
        return self.get(f"recommendations/{recommendation_id}")

    # Execution Endpoints
    def execute_compression(
        self,
        recommendation_id: int,
        dry_run: bool = True,
        parallel_degree: int = 4
    ) -> Dict[str, Any]:
        """Execute compression for recommendation"""
        return self.post("compression/execute", {
            "recommendation_id": recommendation_id,
            "dry_run": dry_run,
            "parallel_degree": parallel_degree
        })

    def get_execution_status(self, execution_id: int) -> Dict[str, Any]:
        """Get execution status"""
        return self.get(f"compression/execution/{execution_id}")

    def get_execution_history(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Get execution history"""
        params = {"limit": limit}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        return self.get("compression/history", params)

    # Statistics Endpoints
    def get_compression_statistics(self) -> Dict[str, Any]:
        """Get overall compression statistics"""
        return self.get("statistics/compression")

    def get_savings_by_strategy(self) -> Dict[str, Any]:
        """Get savings breakdown by strategy"""
        return self.get("statistics/savings-by-strategy")

    def get_table_statistics(self, owner: str, table_name: str) -> Dict[str, Any]:
        """Get statistics for specific table"""
        return self.get(f"statistics/table/{owner}/{table_name}")

    # Strategy Endpoints
    def get_strategies(self) -> Dict[str, Any]:
        """Get all compression strategies"""
        return self.get("strategies")

    def get_strategy_details(self, strategy_name: str) -> Dict[str, Any]:
        """Get strategy details"""
        return self.get(f"strategies/{strategy_name}")

    def compare_strategies(self, owner: str, table_name: str) -> Dict[str, Any]:
        """Compare all strategies for a table"""
        return self.get(f"strategies/compare/{owner}/{table_name}")

    # Health Check
    def health_check(self) -> bool:
        """Check API health"""
        try:
            response = self.get("health")
            return response.get("status") == "healthy"
        except Exception:
            return False

    # Batch Operations
    def batch_execute(
        self,
        recommendation_ids: List[int],
        dry_run: bool = True,
        parallel_degree: int = 4
    ) -> Dict[str, Any]:
        """Execute multiple compressions in batch"""
        return self.post("compression/batch", {
            "recommendation_ids": recommendation_ids,
            "dry_run": dry_run,
            "parallel_degree": parallel_degree
        })

    # Export Endpoints
    def export_recommendations_csv(self, strategy: Optional[str] = None) -> str:
        """Export recommendations to CSV"""
        params = {}
        if strategy:
            params["strategy"] = strategy

        endpoint = "export/recommendations/csv"
        url = f"{self.base_url}/{endpoint}"

        try:
            response = requests.get(
                url,
                auth=self.auth,
                params=params,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            st.error(f"Export failed: {e}")
            return ""


# Create singleton instance
@st.cache_resource
def get_api_client() -> ORDSClient:
    """Get cached API client instance"""
    return ORDSClient()
