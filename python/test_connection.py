#!/usr/bin/env python3
"""
Connection Test Script for HCC Compression Advisor
Tests database and ORDS API connectivity
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from config import config
from utils.db_connector import DatabaseConnector
from utils.api_client import ORDSClient


def test_database_connection():
    """Test database connection"""
    print("\n" + "="*60)
    print("Testing Database Connection")
    print("="*60)

    try:
        print(f"Host: {config.DB_HOST}")
        print(f"Port: {config.DB_PORT}")
        print(f"Service: {config.DB_SERVICE}")
        print(f"User: {config.DB_USER}")
        print()

        # Initialize connection pool
        DatabaseConnector.initialize_pool()
        print("✓ Connection pool initialized")

        # Test connection
        if DatabaseConnector.test_connection():
            print("✓ Database connection successful")

            # Get version
            query = "SELECT BANNER FROM V$VERSION WHERE ROWNUM = 1"
            df = DatabaseConnector.execute_query(query)

            if not df.empty:
                print(f"✓ Oracle Version: {df.iloc[0]['BANNER']}")

            return True
        else:
            print("✗ Database connection failed")
            return False

    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def test_ords_connection():
    """Test ORDS API connection"""
    print("\n" + "="*60)
    print("Testing ORDS API Connection")
    print("="*60)

    try:
        print(f"Base URL: {config.ORDS_BASE_URL}")
        print(f"Username: {config.ORDS_USERNAME}")
        print()

        client = ORDSClient()

        # Test health endpoint
        if client.health_check():
            print("✓ ORDS API connection successful")

            # Test strategies endpoint
            strategies = client.get_strategies()
            if "items" in strategies:
                print(f"✓ Strategies endpoint working ({len(strategies['items'])} strategies)")

            # Test statistics endpoint
            stats = client.get_compression_statistics()
            if "items" in stats:
                print("✓ Statistics endpoint working")

            return True
        else:
            print("✗ ORDS API connection failed")
            return False

    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def test_ssl_certificates():
    """Test SSL certificate existence"""
    print("\n" + "="*60)
    print("Testing SSL Configuration")
    print("="*60)

    try:
        cert_path = Path(__file__).parent / config.SSL_CERT_FILE
        key_path = Path(__file__).parent / config.SSL_KEY_FILE

        print(f"SSL Enabled: {config.SSL_ENABLED}")
        print(f"Certificate: {cert_path}")
        print(f"Private Key: {key_path}")
        print()

        if config.SSL_ENABLED:
            if cert_path.exists():
                print("✓ SSL certificate found")
            else:
                print("✗ SSL certificate not found")

            if key_path.exists():
                print("✓ SSL private key found")
            else:
                print("✗ SSL private key not found")

            return cert_path.exists() and key_path.exists()
        else:
            print("⚠ SSL is disabled")
            return True

    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def main():
    """Run all connection tests"""
    print("\n" + "="*60)
    print("HCC Compression Advisor - Connection Test")
    print("="*60)

    # Validate configuration
    errors = config.validate_config()
    if errors:
        print("\n⚠ Configuration Errors:")
        for error in errors:
            print(f"  - {error}")
        print()

    # Run tests
    results = {
        "SSL Configuration": test_ssl_certificates(),
        "Database Connection": test_database_connection(),
        "ORDS API Connection": test_ords_connection()
    }

    # Summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)

    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{test_name}: {status}")

    all_passed = all(results.values())

    print()
    if all_passed:
        print("✓ All tests passed! Ready to start the dashboard.")
        print("\nRun: ./start.sh")
    else:
        print("✗ Some tests failed. Please fix the issues above.")

    print()
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
