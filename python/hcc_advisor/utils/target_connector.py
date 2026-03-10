"""
Target Database Connector for HCC Compression Advisor
Manages connection pools to remote Oracle target databases.
Supports multiple simultaneous connections keyed by database_id.
"""

import oracledb
import pandas as pd
import time
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
import streamlit as st
from hcc_advisor.config import config
from hcc_advisor.utils.logger import log_db_error, log_info, log_debug, log_error
from hcc_advisor.utils.sql_debug import capture_sql, is_debug_enabled


class TargetConnector:
    """Oracle connection pool manager for target databases"""

    _pools: Dict[int, oracledb.ConnectionPool] = {}
    _pool_configs: Dict[int, Dict[str, Any]] = {}

    @classmethod
    def get_pool(cls, database_id: int, conn_config: Dict[str, Any]) -> oracledb.ConnectionPool:
        """
        Get or create connection pool for a specific target database

        Args:
            database_id: Unique identifier for the target database
            conn_config: Connection configuration dict with keys:
                         username, password, host, port, service

        Returns:
            oracledb.ConnectionPool: Connection pool for the target database
        """
        if database_id in cls._pools:
            return cls._pools[database_id]

        try:
            pool = oracledb.create_pool(
                user=conn_config['username'],
                password=conn_config['password'],
                dsn=f"{conn_config['host']}:{conn_config['port']}/{conn_config['service']}",
                min=config.TARGET_POOL_MIN,
                max=config.TARGET_POOL_MAX,
                increment=1
            )
            cls._pools[database_id] = pool
            cls._pool_configs[database_id] = conn_config
            log_info(f"Target pool created for database_id={database_id}")
            return pool
        except oracledb.Error as e:
            log_error(e, f"TargetConnector.get_pool(database_id={database_id})")
            raise

    @classmethod
    @contextmanager
    def get_connection(cls, database_id: int, conn_config: Optional[Dict[str, Any]] = None):
        """
        Get connection to a specific target database

        If no conn_config is provided, fetches connection details from the
        central database using CentralQueries.

        Args:
            database_id: Unique identifier for the target database
            conn_config: Optional connection configuration dict

        Yields:
            oracledb.Connection: Database connection to the target
        """
        if conn_config is None:
            from hcc_advisor.utils.central_queries import CentralQueries
            db_info = CentralQueries.get_target_database(database_id)
            if not db_info:
                raise ValueError(f"Target database {database_id} not found in central registry")
            conn_config = db_info

        pool = cls.get_pool(database_id, conn_config)
        connection = None
        try:
            connection = pool.acquire()
            yield connection
        except oracledb.Error as e:
            log_error(e, f"TargetConnector.get_connection(db_id={database_id})")
            raise
        finally:
            if connection:
                pool.release(connection)

    @classmethod
    def execute_query(
        cls,
        database_id: int,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        conn_config: Optional[Dict[str, Any]] = None
    ) -> pd.DataFrame:
        """
        Execute SELECT query on a target database and return results as DataFrame

        Args:
            database_id: Unique identifier for the target database
            query: SQL SELECT statement
            params: Query parameters
            conn_config: Optional connection configuration dict

        Returns:
            pd.DataFrame: Query results
        """
        _t0 = time.perf_counter() if is_debug_enabled() else None
        try:
            log_debug(f"[Target db_id={database_id}] Executing query", query_preview=query[:200])
            with cls.get_connection(database_id, conn_config) as conn:
                cursor = conn.cursor()

                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)

                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                df = pd.DataFrame(rows, columns=columns)

                cursor.close()
                log_debug(f"[Target db_id={database_id}] Query returned {len(df)} rows")
                if _t0 is not None:
                    capture_sql(f'target(id={database_id})', 'SELECT', query, params,
                                rows_affected=len(df), duration_ms=(time.perf_counter() - _t0) * 1000)
                return df

        except oracledb.Error as e:
            if _t0 is not None:
                capture_sql(f'target(id={database_id})', 'SELECT', query, params,
                            status='ERROR', error=str(e), duration_ms=(time.perf_counter() - _t0) * 1000)
            log_db_error(e, query, params)
            st.error(f"Target database (id={database_id}) query error: {e}")
            return pd.DataFrame()

    @classmethod
    def execute_dml(
        cls,
        database_id: int,
        statement: str,
        params: Optional[Dict[str, Any]] = None,
        commit: bool = True,
        conn_config: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Execute DML statement (INSERT, UPDATE, DELETE) on a target database

        Args:
            database_id: Unique identifier for the target database
            statement: SQL DML statement
            params: Statement parameters
            commit: Whether to commit transaction
            conn_config: Optional connection configuration dict

        Returns:
            int: Number of rows affected
        """
        _t0 = time.perf_counter() if is_debug_enabled() else None
        try:
            log_debug(f"[Target db_id={database_id}] Executing DML", statement_preview=statement[:200])
            with cls.get_connection(database_id, conn_config) as conn:
                cursor = conn.cursor()

                if params:
                    cursor.execute(statement, params)
                else:
                    cursor.execute(statement)

                rows_affected = cursor.rowcount

                if commit:
                    conn.commit()

                cursor.close()
                log_debug(f"[Target db_id={database_id}] DML affected {rows_affected} rows")
                if _t0 is not None:
                    capture_sql(f'target(id={database_id})', 'DML', statement, params,
                                rows_affected=rows_affected, duration_ms=(time.perf_counter() - _t0) * 1000)
                return rows_affected

        except oracledb.Error as e:
            if _t0 is not None:
                capture_sql(f'target(id={database_id})', 'DML', statement, params,
                            status='ERROR', error=str(e), duration_ms=(time.perf_counter() - _t0) * 1000)
            log_db_error(e, statement, params)
            st.error(f"Target database (id={database_id}) DML error: {e}")
            return 0

    @classmethod
    def execute_plsql(
        cls,
        database_id: int,
        plsql_block: str,
        params: Optional[Dict[str, Any]] = None,
        commit: bool = True,
        conn_config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Execute a PL/SQL anonymous block on a target database

        Args:
            database_id: Unique identifier for the target database
            plsql_block: PL/SQL code to execute
            params: Optional bind parameters
            commit: Whether to commit after execution
            conn_config: Optional connection configuration dict

        Returns:
            bool: True if successful
        """
        _t0 = time.perf_counter() if is_debug_enabled() else None
        try:
            log_debug(f"[Target db_id={database_id}] Executing PL/SQL block", block_preview=plsql_block[:200])
            with cls.get_connection(database_id, conn_config) as conn:
                cursor = conn.cursor()

                if params:
                    cursor.execute(plsql_block, params)
                else:
                    cursor.execute(plsql_block)

                if commit:
                    conn.commit()

                cursor.close()
                log_info(f"[Target db_id={database_id}] PL/SQL block executed successfully")
                if _t0 is not None:
                    capture_sql(f'target(id={database_id})', 'PLSQL', plsql_block, params,
                                duration_ms=(time.perf_counter() - _t0) * 1000)
                return True

        except oracledb.Error as e:
            if _t0 is not None:
                capture_sql(f'target(id={database_id})', 'PLSQL', plsql_block, params,
                            status='ERROR', error=str(e), duration_ms=(time.perf_counter() - _t0) * 1000)
            log_db_error(e, plsql_block, params)
            st.error(f"Target database (id={database_id}) PL/SQL execution error: {e}")
            return False

    @classmethod
    def execute_procedure(
        cls,
        database_id: int,
        procedure_name: str,
        params: Optional[List[Any]] = None,
        conn_config: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Execute stored procedure on a target database

        Args:
            database_id: Unique identifier for the target database
            procedure_name: Name of stored procedure
            params: Procedure parameters
            conn_config: Optional connection configuration dict

        Returns:
            Any: Procedure result
        """
        _t0 = time.perf_counter() if is_debug_enabled() else None
        try:
            log_debug(f"[Target db_id={database_id}] Executing procedure: {procedure_name}")
            with cls.get_connection(database_id, conn_config) as conn:
                cursor = conn.cursor()

                if params:
                    result = cursor.callproc(procedure_name, params)
                else:
                    result = cursor.callproc(procedure_name)

                conn.commit()
                cursor.close()

                log_info(f"[Target db_id={database_id}] Procedure {procedure_name} executed successfully")
                if _t0 is not None:
                    capture_sql(f'target(id={database_id})', 'PROCEDURE', f"CALL {procedure_name}",
                                duration_ms=(time.perf_counter() - _t0) * 1000)
                return result

        except oracledb.Error as e:
            if _t0 is not None:
                capture_sql(f'target(id={database_id})', 'PROCEDURE', f"CALL {procedure_name}",
                            status='ERROR', error=str(e), duration_ms=(time.perf_counter() - _t0) * 1000)
            log_error(e, f"TargetConnector.execute_procedure(db_id={database_id}, proc={procedure_name})")
            st.error(f"Target database (id={database_id}) procedure execution error: {e}")
            return None

    @classmethod
    def execute_procedure_with_output(
        cls,
        database_id: int,
        plsql_block: str,
        in_params: Optional[Dict[str, Any]] = None,
        out_params: Optional[Dict[str, type]] = None,
        conn_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute PL/SQL block with input and output parameters on a target database

        Args:
            database_id: Unique identifier for the target database
            plsql_block: PL/SQL anonymous block with bind variables
            in_params: Input parameters dictionary
            out_params: Output parameters with their types (e.g., {'result': int, 'message': str})
            conn_config: Optional connection configuration dict

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
            result = TargetConnector.execute_procedure_with_output(
                database_id=1,
                plsql_block=plsql,
                in_params={'input_val': 100},
                out_params={'output_val': int}
            )
        """
        _t0 = time.perf_counter() if is_debug_enabled() else None
        try:
            log_debug(f"[Target db_id={database_id}] Executing PL/SQL with output", block_preview=plsql_block[:200])
            with cls.get_connection(database_id, conn_config) as conn:
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
                    if out_params.get(param_name) == int and value is not None:
                        result[param_name] = int(value)
                    elif out_params.get(param_name) == float and value is not None:
                        result[param_name] = float(value)
                    else:
                        result[param_name] = value

                cursor.close()
                log_debug(f"[Target db_id={database_id}] PL/SQL with output returned: {list(result.keys())}")
                if _t0 is not None:
                    capture_sql(f'target(id={database_id})', 'PLSQL', plsql_block, in_params,
                                duration_ms=(time.perf_counter() - _t0) * 1000)
                return result

        except oracledb.Error as e:
            if _t0 is not None:
                capture_sql(f'target(id={database_id})', 'PLSQL', plsql_block, in_params,
                            status='ERROR', error=str(e), duration_ms=(time.perf_counter() - _t0) * 1000)
            log_db_error(e, plsql_block, in_params)
            st.error(f"Target database (id={database_id}) PL/SQL execution error: {e}")
            raise

    @classmethod
    def call_function_cursor(
        cls,
        database_id: int,
        function_call: str,
        params: Optional[Dict[str, Any]] = None,
        conn_config: Optional[Dict[str, Any]] = None
    ) -> pd.DataFrame:
        """
        Call a function that returns a REF CURSOR on a target database and return results as DataFrame

        Args:
            database_id: Unique identifier for the target database
            function_call: Function call expression (e.g., 'pkg_name.func_name(:param1)')
            params: Function parameters
            conn_config: Optional connection configuration dict

        Returns:
            pd.DataFrame: Query results from the cursor

        Example:
            df = TargetConnector.call_function_cursor(
                database_id=1,
                function_call='my_pkg.get_data(:owner)',
                params={'owner': 'HR'}
            )
        """
        _t0 = time.perf_counter() if is_debug_enabled() else None
        try:
            log_debug(f"[Target db_id={database_id}] Calling function cursor: {function_call}")
            with cls.get_connection(database_id, conn_config) as conn:
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

                log_debug(f"[Target db_id={database_id}] Function cursor returned {len(rows)} rows")
                if _t0 is not None:
                    capture_sql(f'target(id={database_id})', 'FUNCTION', f"CURSOR: {function_call}", params,
                                rows_affected=len(rows), duration_ms=(time.perf_counter() - _t0) * 1000)
                return pd.DataFrame(rows, columns=columns)

        except oracledb.Error as e:
            if _t0 is not None:
                capture_sql(f'target(id={database_id})', 'FUNCTION', f"CURSOR: {function_call}", params,
                            status='ERROR', error=str(e), duration_ms=(time.perf_counter() - _t0) * 1000)
            log_error(e, f"TargetConnector.call_function_cursor(db_id={database_id}, func={function_call})")
            st.error(f"Target database (id={database_id}) function cursor execution error: {e}")
            return pd.DataFrame()

    @classmethod
    def test_connection_by_id(cls, database_id: int) -> bool:
        """
        Test connection to a target database by its registered database_id.
        Fetches connection config from the central database.

        Args:
            database_id: Unique identifier for the target database

        Returns:
            bool: True if connection successful
        """
        try:
            with cls.get_connection(database_id) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM DUAL")
                cursor.fetchone()
                cursor.close()
                log_info(f"[Target db_id={database_id}] Connection test successful")
                return True
        except Exception as e:
            log_error(e, f"TargetConnector.test_connection_by_id(db_id={database_id})")
            st.error(f"Target database (id={database_id}) connection test failed: {e}")
            return False

    @classmethod
    def test_connection_direct(cls, conn_config: Dict[str, Any]) -> bool:
        """
        Test connection to a target database using provided config directly.
        Useful for testing connectivity before saving a new database registration.

        Does NOT create a persistent pool -- uses a temporary standalone connection.

        Args:
            conn_config: Connection configuration dict with keys:
                         username, password, host, port, service

        Returns:
            bool: True if connection successful
        """
        connection = None
        try:
            dsn = f"{conn_config['host']}:{conn_config['port']}/{conn_config['service']}"
            connection = oracledb.connect(
                user=conn_config['username'],
                password=conn_config['password'],
                dsn=dsn
            )
            cursor = connection.cursor()
            cursor.execute("SELECT 1 FROM DUAL")
            cursor.fetchone()
            cursor.close()
            log_info(f"[Target direct] Connection test successful to {conn_config['host']}:{conn_config['port']}/{conn_config['service']}")
            return True
        except oracledb.Error as e:
            log_error(e, f"TargetConnector.test_connection_direct(host={conn_config.get('host', '?')})")
            st.error(f"Target database connection test failed: {e}")
            return False
        finally:
            if connection:
                try:
                    connection.close()
                except:
                    pass

    @classmethod
    def close_pool(cls, database_id: int):
        """
        Close connection pool for a specific target database

        Args:
            database_id: Unique identifier for the target database
        """
        if database_id in cls._pools:
            try:
                cls._pools[database_id].close()
                log_info(f"[Target db_id={database_id}] Connection pool closed")
            except oracledb.Error as e:
                log_error(e, f"TargetConnector.close_pool(db_id={database_id})")
            del cls._pools[database_id]
            cls._pool_configs.pop(database_id, None)

    @classmethod
    def close_all_pools(cls):
        """Close all target database connection pools"""
        db_ids = list(cls._pools.keys())
        for database_id in db_ids:
            cls.close_pool(database_id)
        log_info(f"[Target] All connection pools closed ({len(db_ids)} pools)")
