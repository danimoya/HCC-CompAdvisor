"""
Oracle Database Connector for HCC Compression Advisor
Handles database connections and query execution using oracledb
"""

import oracledb
import pandas as pd
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
import streamlit as st
from config import config


class DatabaseConnector:
    """Oracle Database connection manager with connection pooling"""

    _pool: Optional[oracledb.ConnectionPool] = None

    @classmethod
    def initialize_pool(cls):
        """Initialize connection pool"""
        if cls._pool is None:
            try:
                cls._pool = oracledb.create_pool(
                    user=config.DB_USER,
                    password=config.DB_PASSWORD,
                    dsn=f"{config.DB_HOST}:{config.DB_PORT}/{config.DB_SERVICE}",
                    min=config.POOL_MIN,
                    max=config.POOL_MAX,
                    increment=config.POOL_INCREMENT,
                    threaded=True
                )
            except oracledb.Error as e:
                st.error(f"Failed to create connection pool: {e}")
                raise

    @classmethod
    @contextmanager
    def get_connection(cls):
        """
        Get database connection from pool

        Yields:
            oracledb.Connection: Database connection
        """
        if cls._pool is None:
            cls.initialize_pool()

        connection = None
        try:
            connection = cls._pool.acquire()
            yield connection
        except oracledb.Error as e:
            st.error(f"Database connection error: {e}")
            raise
        finally:
            if connection:
                cls._pool.release(connection)

    @classmethod
    def execute_query(cls, query: str, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        """
        Execute SELECT query and return results as DataFrame

        Args:
            query: SQL SELECT statement
            params: Query parameters

        Returns:
            pd.DataFrame: Query results
        """
        try:
            with cls.get_connection() as conn:
                cursor = conn.cursor()

                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)

                # Fetch all rows
                rows = cursor.fetchall()

                # Get column names
                columns = [desc[0] for desc in cursor.description]

                # Create DataFrame
                df = pd.DataFrame(rows, columns=columns)

                cursor.close()
                return df

        except oracledb.Error as e:
            st.error(f"Query execution error: {e}")
            return pd.DataFrame()

    @classmethod
    def execute_dml(cls, statement: str, params: Optional[Dict[str, Any]] = None, commit: bool = True) -> int:
        """
        Execute DML statement (INSERT, UPDATE, DELETE)

        Args:
            statement: SQL DML statement
            params: Statement parameters
            commit: Whether to commit transaction

        Returns:
            int: Number of rows affected
        """
        try:
            with cls.get_connection() as conn:
                cursor = conn.cursor()

                if params:
                    cursor.execute(statement, params)
                else:
                    cursor.execute(statement)

                rows_affected = cursor.rowcount

                if commit:
                    conn.commit()

                cursor.close()
                return rows_affected

        except oracledb.Error as e:
            st.error(f"DML execution error: {e}")
            return 0

    @classmethod
    def execute_procedure(cls, procedure_name: str, params: Optional[List[Any]] = None) -> Any:
        """
        Execute stored procedure

        Args:
            procedure_name: Name of stored procedure
            params: Procedure parameters

        Returns:
            Any: Procedure result
        """
        try:
            with cls.get_connection() as conn:
                cursor = conn.cursor()

                if params:
                    result = cursor.callproc(procedure_name, params)
                else:
                    result = cursor.callproc(procedure_name)

                conn.commit()
                cursor.close()

                return result

        except oracledb.Error as e:
            st.error(f"Procedure execution error: {e}")
            return None

    @classmethod
    def test_connection(cls) -> bool:
        """
        Test database connection

        Returns:
            bool: True if connection successful
        """
        try:
            with cls.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM DUAL")
                cursor.fetchone()
                cursor.close()
                return True
        except oracledb.Error as e:
            st.error(f"Connection test failed: {e}")
            return False

    @classmethod
    def get_table_statistics(cls, owner: str, table_name: str) -> Dict[str, Any]:
        """
        Get table statistics

        Args:
            owner: Schema owner
            table_name: Table name

        Returns:
            dict: Table statistics
        """
        query = """
            SELECT
                num_rows,
                blocks,
                avg_row_len,
                compress_for,
                compression,
                ROUND(blocks * 8192 / 1024 / 1024, 2) as size_mb
            FROM all_tables
            WHERE owner = :owner
            AND table_name = :table_name
        """

        df = cls.execute_query(query, {'owner': owner, 'table_name': table_name})

        if not df.empty:
            return df.iloc[0].to_dict()
        return {}

    @classmethod
    def close_pool(cls):
        """Close connection pool"""
        if cls._pool:
            cls._pool.close()
            cls._pool = None


# Initialize connection pool when module is imported
@st.cache_resource
def get_db_connector():
    """Get cached database connector instance"""
    return DatabaseConnector()
