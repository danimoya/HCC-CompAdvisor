"""
Oracle Database Connector for HCC Compression Advisor
Handles database connections and query execution using oracledb
Supports dynamic connection switching via Connection Manager
"""

import oracledb
import pandas as pd
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
import streamlit as st
from config import config
from utils.logger import log_db_error, log_info, log_debug, log_error


def get_active_connection_config() -> Dict[str, Any]:
    """Get active connection configuration from Connection Manager or fallback to config"""
    try:
        from views.page_06_connections import get_active_connection
        active = get_active_connection()
        if active:
            return {
                'host': active.get('host', config.DB_HOST),
                'port': active.get('port', config.DB_PORT),
                'service': active.get('service', config.DB_SERVICE),
                'user': active.get('username', config.DB_USER),
                'password': active.get('password', config.DB_PASSWORD)
            }
    except ImportError:
        pass

    # Fallback to config
    return {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'service': config.DB_SERVICE,
        'user': config.DB_USER,
        'password': config.DB_PASSWORD
    }


class DatabaseConnector:
    """Oracle Database connection manager with connection pooling"""

    _pool: Optional[oracledb.ConnectionPool] = None

    @classmethod
    def initialize_pool(cls, force_reinit: bool = False):
        """Initialize connection pool using active connection from Connection Manager"""
        if cls._pool is not None and not force_reinit:
            return

        # Close existing pool if reinitializing
        if cls._pool is not None:
            try:
                cls._pool.close()
            except:
                pass
            cls._pool = None

        try:
            conn_config = get_active_connection_config()
            cls._pool = oracledb.create_pool(
                user=conn_config['user'],
                password=conn_config['password'],
                dsn=f"{conn_config['host']}:{conn_config['port']}/{conn_config['service']}",
                min=config.POOL_MIN,
                max=config.POOL_MAX,
                increment=config.POOL_INCREMENT
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
            log_debug(f"Executing query", query_preview=query[:200])
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
                log_debug(f"Query returned {len(df)} rows")
                return df

        except oracledb.Error as e:
            log_db_error(e, query, params)
            st.error(f"Database connection error: {e}")
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
    def execute_procedure_with_output(
        cls,
        plsql_block: str,
        in_params: Optional[Dict[str, Any]] = None,
        out_params: Optional[Dict[str, type]] = None
    ) -> Dict[str, Any]:
        """
        Execute PL/SQL block with input and output parameters

        Args:
            plsql_block: PL/SQL anonymous block with bind variables
            in_params: Input parameters dictionary
            out_params: Output parameters with their types (e.g., {'result': int, 'message': str})

        Returns:
            dict: Output parameter values

        Example:
            plsql = '''
            DECLARE
                v_result NUMBER;
            BEGIN
                my_proc(:input_val, v_result);
                :output_val := v_result;
            END;
            '''
            result = execute_procedure_with_output(
                plsql,
                in_params={'input_val': 100},
                out_params={'output_val': int}
            )
        """
        try:
            with cls.get_connection() as conn:
                cursor = conn.cursor()

                # Prepare all parameters
                all_params = {}

                # Add input parameters
                if in_params:
                    all_params.update(in_params)

                # Create output variables
                out_vars = {}
                if out_params:
                    for param_name, param_type in out_params.items():
                        if param_type == int:
                            out_vars[param_name] = cursor.var(oracledb.NUMBER)
                        elif param_type == float:
                            out_vars[param_name] = cursor.var(oracledb.NUMBER)
                        elif param_type == str:
                            out_vars[param_name] = cursor.var(oracledb.STRING, 4000)
                        else:
                            out_vars[param_name] = cursor.var(oracledb.STRING, 4000)
                        all_params[param_name] = out_vars[param_name]

                # Execute the PL/SQL block
                cursor.execute(plsql_block, all_params)
                conn.commit()

                # Extract output values
                result = {}
                for param_name, var in out_vars.items():
                    value = var.getvalue()
                    # Convert to appropriate Python type
                    if out_params.get(param_name) == int and value is not None:
                        result[param_name] = int(value)
                    elif out_params.get(param_name) == float and value is not None:
                        result[param_name] = float(value)
                    else:
                        result[param_name] = value

                cursor.close()
                return result

        except oracledb.Error as e:
            st.error(f"PL/SQL execution error: {e}")
            raise

    @classmethod
    def call_function_cursor(cls, function_call: str, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        """
        Call a function that returns a REF CURSOR and return results as DataFrame

        Args:
            function_call: Function call expression (e.g., 'pkg_name.func_name(:param1)')
            params: Function parameters

        Returns:
            pd.DataFrame: Query results from the cursor

        Example:
            df = call_function_cursor(
                'my_pkg.get_data(:owner)',
                {'owner': 'HR'}
            )
        """
        try:
            with cls.get_connection() as conn:
                cursor = conn.cursor()

                # Create a ref cursor variable
                ref_cursor = cursor.var(oracledb.CURSOR)

                # Build the PL/SQL block
                plsql = f"""
                BEGIN
                    :result_cursor := {function_call};
                END;
                """

                # Prepare parameters
                all_params = {'result_cursor': ref_cursor}
                if params:
                    all_params.update(params)

                # Execute
                cursor.execute(plsql, all_params)

                # Fetch results from ref cursor
                result_cursor = ref_cursor.getvalue()
                rows = result_cursor.fetchall()
                columns = [desc[0] for desc in result_cursor.description]

                result_cursor.close()
                cursor.close()

                return pd.DataFrame(rows, columns=columns)

        except oracledb.Error as e:
            st.error(f"Function cursor execution error: {e}")
            return pd.DataFrame()

    @classmethod
    def execute_plsql(cls, plsql_block: str, params: Optional[Dict[str, Any]] = None, commit: bool = True) -> bool:
        """
        Execute a PL/SQL anonymous block

        Args:
            plsql_block: PL/SQL code to execute
            params: Optional bind parameters
            commit: Whether to commit after execution

        Returns:
            bool: True if successful
        """
        try:
            log_debug(f"Executing PL/SQL block", block_preview=plsql_block[:200])
            with cls.get_connection() as conn:
                cursor = conn.cursor()

                if params:
                    cursor.execute(plsql_block, params)
                else:
                    cursor.execute(plsql_block)

                if commit:
                    conn.commit()

                cursor.close()
                log_info("PL/SQL block executed successfully")
                return True

        except oracledb.Error as e:
            log_db_error(e, plsql_block, params)
            st.error(f"PL/SQL execution error: {e}")
            return False

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
