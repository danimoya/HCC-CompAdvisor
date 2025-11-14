"""
Integration tests for database operations.
"""
import pytest
from unittest.mock import MagicMock, patch
import oracledb
from datetime import datetime


@pytest.mark.integration
@pytest.mark.database
@pytest.mark.slow
class TestDatabaseIntegration:
    """Test end-to-end database operations."""

    def test_full_connection_lifecycle(self, mock_oracledb_connect, mock_oracle_connection,
                                      mock_oracle_cursor, mock_config):
        """Test complete connection lifecycle from create to close."""
        # Arrange
        mock_oracledb_connect.return_value = mock_oracle_connection
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        db_config = mock_config['database']

        # Act
        # 1. Create connection
        connection = mock_oracledb_connect(
            user=db_config['user'],
            password=db_config['password'],
            dsn=db_config['dsn']
        )

        # 2. Execute query
        cursor = connection.cursor()
        cursor.execute("SELECT 1 FROM DUAL")

        # 3. Close resources
        cursor.close()
        connection.close()

        # Assert
        assert connection is not None
        cursor.execute.assert_called_once_with("SELECT 1 FROM DUAL")
        cursor.close.assert_called_once()
        connection.close.assert_called_once()

    def test_connection_pool_workflow(self, mock_oracledb_pool, mock_connection_pool,
                                     mock_oracle_connection, mock_config):
        """Test connection pool workflow."""
        # Arrange
        mock_oracledb_pool.return_value = mock_connection_pool
        mock_connection_pool.acquire.return_value = mock_oracle_connection
        db_config = mock_config['database']

        # Act
        # 1. Create pool
        pool = mock_oracledb_pool(
            user=db_config['user'],
            password=db_config['password'],
            dsn=db_config['dsn'],
            min=db_config['min_pool'],
            max=db_config['max_pool']
        )

        # 2. Acquire connection
        conn = pool.acquire()

        # 3. Use connection
        cursor = conn.cursor()
        cursor.execute("SELECT SYSDATE FROM DUAL")
        cursor.close()

        # 4. Release connection
        pool.release(conn)

        # 5. Close pool
        pool.close()

        # Assert
        pool.acquire.assert_called_once()
        pool.release.assert_called_once_with(conn)
        pool.close.assert_called_once()

    def test_transaction_commit_workflow(self, mock_oracle_connection, mock_oracle_cursor):
        """Test complete transaction with commit."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor

        # Act
        cursor = mock_oracle_connection.cursor()

        # Execute multiple statements
        cursor.execute("INSERT INTO test_table VALUES (1, 'test1')")
        cursor.execute("INSERT INTO test_table VALUES (2, 'test2')")
        cursor.execute("UPDATE test_table SET name = 'updated' WHERE id = 1")

        # Commit transaction
        mock_oracle_connection.commit()
        cursor.close()

        # Assert
        assert cursor.execute.call_count == 3
        mock_oracle_connection.commit.assert_called_once()

    def test_transaction_rollback_workflow(self, mock_oracle_connection, mock_oracle_cursor):
        """Test transaction rollback on error."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        mock_oracle_cursor.execute.side_effect = [None, oracledb.DatabaseError("Error")]

        # Act
        cursor = mock_oracle_connection.cursor()
        try:
            cursor.execute("INSERT INTO test_table VALUES (1, 'test1')")
            cursor.execute("INSERT INTO test_table VALUES (2, 'test2')")  # This will fail
            mock_oracle_connection.commit()
        except oracledb.DatabaseError:
            mock_oracle_connection.rollback()
        finally:
            cursor.close()

        # Assert
        mock_oracle_connection.rollback.assert_called_once()
        mock_oracle_connection.commit.assert_not_called()


@pytest.mark.integration
@pytest.mark.database
class TestCompressionAnalysisWorkflow:
    """Test complete compression analysis workflow."""

    def test_analyze_table_compression(self, mock_oracle_connection, mock_oracle_cursor,
                                      sample_compression_analysis):
        """Test analyzing table for compression recommendations."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        table_name = 'CUSTOMERS'

        # Setup mock responses
        mock_oracle_cursor.fetchone.side_effect = [
            (1024.5,),  # Current size
            (5000000,),  # Row count
            (None,),  # Current compression
        ]

        # Act
        cursor = mock_oracle_connection.cursor()

        # Get table size
        cursor.execute("SELECT SUM(bytes)/1024/1024 FROM user_segments WHERE segment_name = :name",
                      {'name': table_name})
        size_mb = cursor.fetchone()[0]

        # Get row count
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        row_count = cursor.fetchone()[0]

        # Get current compression
        cursor.execute("SELECT compression FROM user_tables WHERE table_name = :name",
                      {'name': table_name})
        current_compression = cursor.fetchone()[0]

        cursor.close()

        # Assert
        assert size_mb == 1024.5
        assert row_count == 5000000
        assert current_compression is None
        assert cursor.execute.call_count == 3

    def test_apply_compression_recommendation(self, mock_oracle_connection, mock_oracle_cursor):
        """Test applying compression to a table."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        table_name = 'CUSTOMERS'
        compression_type = 'QUERY_LOW'

        # Act
        cursor = mock_oracle_connection.cursor()

        # Start compression
        cursor.execute(f"ALTER TABLE {table_name} MOVE COMPRESS FOR {compression_type}")
        mock_oracle_connection.commit()

        # Rebuild indexes
        cursor.execute(f"SELECT index_name FROM user_indexes WHERE table_name = :name",
                      {'name': table_name})
        mock_oracle_cursor.fetchall.return_value = [('IDX_CUST_1',), ('IDX_CUST_2',)]
        indexes = cursor.fetchall()

        for idx in indexes:
            cursor.execute(f"ALTER INDEX {idx[0]} REBUILD")

        mock_oracle_connection.commit()
        cursor.close()

        # Assert
        assert mock_oracle_connection.commit.call_count == 2
        assert cursor.execute.call_count >= 3  # ALTER TABLE + SELECT + REBUILD(s)

    def test_verify_compression_applied(self, mock_oracle_connection, mock_oracle_cursor):
        """Test verifying compression was successfully applied."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        table_name = 'CUSTOMERS'

        # Setup mock responses
        mock_oracle_cursor.fetchone.side_effect = [
            ('QUERY_LOW',),  # Compression type
            (512.25,),  # New size
        ]

        # Act
        cursor = mock_oracle_connection.cursor()

        # Check compression type
        cursor.execute("SELECT compression FROM user_tables WHERE table_name = :name",
                      {'name': table_name})
        compression = cursor.fetchone()[0]

        # Check new size
        cursor.execute("SELECT SUM(bytes)/1024/1024 FROM user_segments WHERE segment_name = :name",
                      {'name': table_name})
        new_size = cursor.fetchone()[0]

        cursor.close()

        # Assert
        assert compression == 'QUERY_LOW'
        assert new_size == 512.25


@pytest.mark.integration
@pytest.mark.database
class TestBatchOperations:
    """Test batch database operations."""

    def test_batch_table_analysis(self, mock_oracle_connection, mock_oracle_cursor,
                                  sample_table_data):
        """Test analyzing multiple tables in batch."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        mock_oracle_cursor.fetchall.return_value = sample_table_data

        # Act
        cursor = mock_oracle_connection.cursor()

        # Get all tables
        cursor.execute("SELECT table_name FROM user_tables")
        tables = cursor.fetchall()

        # Analyze each table
        results = []
        for table in tables:
            table_name = table[0]
            cursor.execute(
                "SELECT SUM(bytes)/1024/1024 FROM user_segments WHERE segment_name = :name",
                {'name': table_name}
            )
            results.append({'table': table_name, 'size': 1024.5})

        cursor.close()

        # Assert
        assert len(results) == len(sample_table_data)
        assert cursor.execute.call_count == len(sample_table_data) + 1

    def test_bulk_insert_compression_log(self, mock_oracle_connection, mock_oracle_cursor):
        """Test bulk inserting compression analysis results."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor

        log_entries = [
            ('CUSTOMERS', 'QUERY_LOW', 1024.5, 512.25, 50.0, datetime.now()),
            ('ORDERS', 'QUERY_HIGH', 2048.75, 512.19, 75.0, datetime.now()),
            ('PRODUCTS', 'ARCHIVE_LOW', 512.25, 256.12, 50.0, datetime.now()),
        ]

        # Act
        cursor = mock_oracle_connection.cursor()

        query = """
        INSERT INTO compression_analysis_log
        (table_name, compression_type, original_size_mb, compressed_size_mb,
         savings_pct, analysis_date)
        VALUES (:1, :2, :3, :4, :5, :6)
        """

        cursor.executemany(query, log_entries)
        mock_oracle_connection.commit()
        cursor.close()

        # Assert
        cursor.executemany.assert_called_once()
        mock_oracle_connection.commit.assert_called_once()


@pytest.mark.integration
@pytest.mark.database
@pytest.mark.slow
class TestPerformanceOperations:
    """Test database performance-related operations."""

    def test_large_result_set_fetch(self, mock_oracle_connection, mock_oracle_cursor):
        """Test fetching large result sets efficiently."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        batch_size = 1000

        # Setup mock to return batches
        mock_oracle_cursor.fetchmany.side_effect = [
            [(i, f'row_{i}') for i in range(batch_size)],
            [(i, f'row_{i}') for i in range(batch_size, batch_size * 2)],
            []  # Empty list indicates no more rows
        ]

        # Act
        cursor = mock_oracle_connection.cursor()
        cursor.execute("SELECT id, name FROM large_table")

        all_rows = []
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            all_rows.extend(rows)

        cursor.close()

        # Assert
        assert len(all_rows) == batch_size * 2
        assert cursor.fetchmany.call_count == 3

    def test_parallel_query_execution(self, mock_connection_pool, mock_oracle_connection,
                                     mock_oracle_cursor):
        """Test executing queries in parallel using connection pool."""
        # Arrange
        mock_connection_pool.acquire.return_value = mock_oracle_connection
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor

        queries = [
            "SELECT COUNT(*) FROM customers",
            "SELECT COUNT(*) FROM orders",
            "SELECT COUNT(*) FROM products"
        ]

        # Act
        results = []
        for query in queries:
            conn = mock_connection_pool.acquire()
            cursor = conn.cursor()
            cursor.execute(query)
            mock_oracle_cursor.fetchone.return_value = (1000,)
            result = cursor.fetchone()[0]
            results.append(result)
            cursor.close()
            mock_connection_pool.release(conn)

        # Assert
        assert len(results) == len(queries)
        assert mock_connection_pool.acquire.call_count == len(queries)
        assert mock_connection_pool.release.call_count == len(queries)
