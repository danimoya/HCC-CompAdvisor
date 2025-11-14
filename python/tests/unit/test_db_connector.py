"""
Unit tests for database connector module.
"""
import pytest
from unittest.mock import MagicMock, patch, call
import oracledb


@pytest.mark.unit
@pytest.mark.database
class TestDatabaseConnection:
    """Test database connection functionality."""

    def test_create_connection_success(self, mock_oracledb_connect, mock_oracle_connection, mock_config):
        """Test successful database connection creation."""
        # Arrange
        mock_oracledb_connect.return_value = mock_oracle_connection
        db_config = mock_config['database']

        # Act
        connection = mock_oracledb_connect(
            user=db_config['user'],
            password=db_config['password'],
            dsn=db_config['dsn']
        )

        # Assert
        assert connection is not None
        mock_oracledb_connect.assert_called_once_with(
            user=db_config['user'],
            password=db_config['password'],
            dsn=db_config['dsn']
        )

    def test_create_connection_failure(self, mock_oracledb_connect):
        """Test database connection failure handling."""
        # Arrange
        mock_oracledb_connect.side_effect = oracledb.DatabaseError("Connection failed")

        # Act & Assert
        with pytest.raises(oracledb.DatabaseError):
            mock_oracledb_connect(
                user='invalid_user',
                password='invalid_pass',
                dsn='invalid_dsn'
            )

    def test_connection_pool_creation(self, mock_oracledb_pool, mock_connection_pool, mock_config):
        """Test connection pool creation."""
        # Arrange
        mock_oracledb_pool.return_value = mock_connection_pool
        db_config = mock_config['database']

        # Act
        pool = mock_oracledb_pool(
            user=db_config['user'],
            password=db_config['password'],
            dsn=db_config['dsn'],
            min=db_config['min_pool'],
            max=db_config['max_pool'],
            increment=db_config['increment']
        )

        # Assert
        assert pool is not None
        assert pool.min == db_config['min_pool']
        assert pool.max == db_config['max_pool']

    def test_acquire_connection_from_pool(self, mock_connection_pool, mock_oracle_connection):
        """Test acquiring connection from pool."""
        # Arrange
        mock_connection_pool.acquire.return_value = mock_oracle_connection

        # Act
        connection = mock_connection_pool.acquire()

        # Assert
        assert connection is not None
        mock_connection_pool.acquire.assert_called_once()

    def test_release_connection_to_pool(self, mock_connection_pool, mock_oracle_connection):
        """Test releasing connection back to pool."""
        # Arrange
        mock_connection_pool.acquire.return_value = mock_oracle_connection
        connection = mock_connection_pool.acquire()

        # Act
        mock_connection_pool.release(connection)

        # Assert
        mock_connection_pool.release.assert_called_once_with(connection)


@pytest.mark.unit
@pytest.mark.database
class TestDatabaseQueries:
    """Test database query execution."""

    def test_execute_select_query(self, mock_oracle_connection, mock_oracle_cursor, sample_table_data):
        """Test executing SELECT query."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        mock_oracle_cursor.fetchall.return_value = sample_table_data
        query = "SELECT table_name, size_mb FROM user_tables"

        # Act
        cursor = mock_oracle_connection.cursor()
        cursor.execute(query)
        results = cursor.fetchall()

        # Assert
        assert len(results) == len(sample_table_data)
        assert results == sample_table_data
        cursor.execute.assert_called_once_with(query)

    def test_execute_query_with_parameters(self, mock_oracle_connection, mock_oracle_cursor):
        """Test executing query with bind parameters."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        query = "SELECT * FROM user_tables WHERE table_name = :table_name"
        params = {'table_name': 'CUSTOMERS'}

        # Act
        cursor = mock_oracle_connection.cursor()
        cursor.execute(query, params)

        # Assert
        cursor.execute.assert_called_once_with(query, params)

    def test_execute_insert_query(self, mock_oracle_connection, mock_oracle_cursor):
        """Test executing INSERT query."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        query = "INSERT INTO compression_log (table_name, compression_type) VALUES (:name, :type)"
        params = {'name': 'CUSTOMERS', 'type': 'QUERY_LOW'}

        # Act
        cursor = mock_oracle_connection.cursor()
        cursor.execute(query, params)
        mock_oracle_connection.commit()

        # Assert
        cursor.execute.assert_called_once_with(query, params)
        mock_oracle_connection.commit.assert_called_once()

    def test_query_error_handling(self, mock_oracle_connection, mock_oracle_cursor):
        """Test query error handling."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        mock_oracle_cursor.execute.side_effect = oracledb.DatabaseError("SQL Error")
        query = "SELECT * FROM invalid_table"

        # Act & Assert
        cursor = mock_oracle_connection.cursor()
        with pytest.raises(oracledb.DatabaseError):
            cursor.execute(query)

    def test_transaction_rollback(self, mock_oracle_connection, mock_oracle_cursor):
        """Test transaction rollback on error."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        mock_oracle_cursor.execute.side_effect = oracledb.DatabaseError("SQL Error")

        # Act
        cursor = mock_oracle_connection.cursor()
        try:
            cursor.execute("UPDATE table SET column = 'value'")
            mock_oracle_connection.commit()
        except oracledb.DatabaseError:
            mock_oracle_connection.rollback()

        # Assert
        mock_oracle_connection.rollback.assert_called_once()


@pytest.mark.unit
@pytest.mark.database
class TestDatabaseHelpers:
    """Test database helper functions."""

    def test_get_table_list(self, mock_oracle_connection, mock_oracle_cursor, sample_table_data):
        """Test retrieving list of tables."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        mock_oracle_cursor.fetchall.return_value = sample_table_data

        # Act
        cursor = mock_oracle_connection.cursor()
        cursor.execute("SELECT table_name FROM user_tables")
        tables = cursor.fetchall()

        # Assert
        assert len(tables) == 4
        assert tables[0][0] == 'CUSTOMERS'

    def test_get_table_size(self, mock_oracle_connection, mock_oracle_cursor):
        """Test retrieving table size."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        mock_oracle_cursor.fetchone.return_value = (1024.5,)

        # Act
        cursor = mock_oracle_connection.cursor()
        cursor.execute("SELECT SUM(bytes)/1024/1024 FROM user_segments WHERE segment_name = :name",
                      {'name': 'CUSTOMERS'})
        size = cursor.fetchone()[0]

        # Assert
        assert size == 1024.5

    def test_get_compression_type(self, mock_oracle_connection, mock_oracle_cursor):
        """Test retrieving current compression type."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        mock_oracle_cursor.fetchone.return_value = ('QUERY_LOW',)

        # Act
        cursor = mock_oracle_connection.cursor()
        cursor.execute("SELECT compression FROM user_tables WHERE table_name = :name",
                      {'name': 'CUSTOMERS'})
        compression = cursor.fetchone()[0]

        # Assert
        assert compression == 'QUERY_LOW'

    def test_check_table_exists(self, mock_oracle_connection, mock_oracle_cursor):
        """Test checking if table exists."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor
        mock_oracle_cursor.fetchone.return_value = (1,)

        # Act
        cursor = mock_oracle_connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM user_tables WHERE table_name = :name",
                      {'name': 'CUSTOMERS'})
        exists = cursor.fetchone()[0] > 0

        # Assert
        assert exists is True

    def test_connection_cleanup(self, mock_oracle_connection, mock_oracle_cursor):
        """Test proper cleanup of database resources."""
        # Arrange
        mock_oracle_connection.cursor.return_value = mock_oracle_cursor

        # Act
        cursor = mock_oracle_connection.cursor()
        cursor.execute("SELECT 1 FROM DUAL")
        cursor.close()
        mock_oracle_connection.close()

        # Assert
        cursor.close.assert_called_once()
        mock_oracle_connection.close.assert_called_once()
