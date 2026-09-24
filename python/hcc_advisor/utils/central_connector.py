"""
Central Database Connector for HCC Compression Advisor
Manages connection pool to the centralized Oracle database that stores
all analysis results, strategies, and target database registrations.
"""

import oracledb
import pandas as pd
import threading
import time
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
import streamlit as st
from hcc_advisor.config import config
from hcc_advisor.utils.logger import log_db_error, log_info, log_debug, log_error
from hcc_advisor.utils.sql_debug import capture_sql, is_debug_enabled
from hcc_advisor.utils.db_timeouts import (
    connection_call_timeout, describe_db_error, pool_timeout_kwargs, read_call_timeout_ms,
)


class CentralConnector:
    """Oracle connection pool manager for the central metadata database"""

    _pool: Optional[oracledb.ConnectionPool] = None
    # Serializes pool creation/replacement: concurrent first callers (several
    # sessions, worker threads) share one pool instead of each creating one.
    _pool_lock = threading.RLock()

    @classmethod
    def initialize_pool(cls, force_reinit: bool = False):
        """Initialize connection pool to central database"""
        with cls._pool_lock:
            if cls._pool is not None and not force_reinit:
                return

            if cls._pool is not None:
                try:
                    cls._pool.close()
                except:
                    pass
                cls._pool = None

            try:
                cls._pool = oracledb.create_pool(
                    user=config.CENTRAL_DB_USER,
                    password=config.CENTRAL_DB_PASSWORD,
                    dsn=f"{config.CENTRAL_DB_HOST}:{config.CENTRAL_DB_PORT}/{config.CENTRAL_DB_SERVICE}",
                    min=config.CENTRAL_POOL_MIN,
                    max=config.CENTRAL_POOL_MAX,
                    increment=1,
                    **pool_timeout_kwargs(config.CENTRAL_CONNECT_TIMEOUT),
                )
                log_info("Central database connection pool initialized")
            except oracledb.Error as e:
                log_error(e, "CentralConnector.initialize_pool")
                st.error(f"Failed to create central DB connection pool: {describe_db_error(e)}")
                raise

    @classmethod
    @contextmanager
    def get_connection(cls):
        """
        Get database connection from central pool

        Yields:
            oracledb.Connection: Database connection to central database
        """
        pool = cls._pool
        if pool is None:
            cls.initialize_pool()
            pool = cls._pool

        connection = None
        try:
            connection = pool.acquire()
            yield connection
        except oracledb.Error as e:
            log_error(e, "CentralConnector.get_connection")
            # Only a failed acquire is a connection error. Errors raised by the
            # caller's statements are the caller's to report (execute_* show
            # their own st.error unless raise_on_error=True).
            if connection is None:
                st.error(f"Central database connection error: {describe_db_error(e)}")
            raise
        finally:
            if connection:
                pool.release(connection)

    @classmethod
    def execute_query(cls, query: str, params: Optional[Dict[str, Any]] = None,
                      raise_on_error: bool = False,
                      call_timeout: Optional[float] = None) -> pd.DataFrame:
        """
        Execute SELECT query on central database and return results as DataFrame

        Args:
            query: SQL SELECT statement
            params: Query parameters
            raise_on_error: Re-raise database errors to the caller instead of
                showing st.error and returning an empty DataFrame
            call_timeout: Per-round-trip limit in seconds (0 = none); None =
                DB_CALL_TIMEOUT, or none inside db_timeouts.long_operation()

        Returns:
            pd.DataFrame: Query results
        """
        _t0 = time.perf_counter() if is_debug_enabled() else None
        try:
            log_debug(f"[Central] Executing query", query_preview=query[:200])
            with cls.get_connection() as conn, \
                    connection_call_timeout(conn, read_call_timeout_ms(call_timeout)):
                cursor = conn.cursor()

                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)

                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                df = pd.DataFrame(rows, columns=columns)

                cursor.close()
                log_debug(f"[Central] Query returned {len(df)} rows")
                if _t0 is not None:
                    capture_sql('central', 'SELECT', query, params,
                                rows_affected=len(df), duration_ms=(time.perf_counter() - _t0) * 1000)
                return df

        except oracledb.Error as e:
            if _t0 is not None:
                capture_sql('central', 'SELECT', query, params,
                            status='ERROR', error=str(e), duration_ms=(time.perf_counter() - _t0) * 1000)
            log_db_error(e, query, params)
            if raise_on_error:
                raise
            st.error(f"Central database query error: {describe_db_error(e)}")
            return pd.DataFrame()

    @classmethod
    def execute_dml(cls, statement: str, params: Optional[Dict[str, Any]] = None, commit: bool = True,
                    raise_on_error: bool = False) -> int:
        """
        Execute DML statement (INSERT, UPDATE, DELETE) on central database

        Args:
            statement: SQL DML statement
            params: Statement parameters
            commit: Whether to commit transaction
            raise_on_error: Re-raise database errors to the caller instead of
                showing st.error and returning 0

        Returns:
            int: Number of rows affected
        """
        _t0 = time.perf_counter() if is_debug_enabled() else None
        try:
            log_debug(f"[Central] Executing DML", statement_preview=statement[:200])
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
                log_debug(f"[Central] DML affected {rows_affected} rows")
                if _t0 is not None:
                    capture_sql('central', 'DML', statement, params,
                                rows_affected=rows_affected, duration_ms=(time.perf_counter() - _t0) * 1000)
                return rows_affected

        except oracledb.Error as e:
            if _t0 is not None:
                capture_sql('central', 'DML', statement, params,
                            status='ERROR', error=str(e), duration_ms=(time.perf_counter() - _t0) * 1000)
            log_db_error(e, statement, params)
            if raise_on_error:
                raise
            st.error(f"Central database DML error: {describe_db_error(e)}")
            return 0

    @classmethod
    def execute_plsql(cls, plsql_block: str, params: Optional[Dict[str, Any]] = None, commit: bool = True,
                      raise_on_error: bool = False) -> bool:
        """
        Execute a PL/SQL anonymous block on central database

        Args:
            plsql_block: PL/SQL code to execute
            params: Optional bind parameters
            commit: Whether to commit after execution
            raise_on_error: Re-raise database errors to the caller instead of
                showing st.error and returning False

        Returns:
            bool: True if successful
        """
        _t0 = time.perf_counter() if is_debug_enabled() else None
        try:
            log_debug(f"[Central] Executing PL/SQL block", block_preview=plsql_block[:200])
            with cls.get_connection() as conn:
                cursor = conn.cursor()

                if params:
                    cursor.execute(plsql_block, params)
                else:
                    cursor.execute(plsql_block)

                if commit:
                    conn.commit()

                cursor.close()
                log_info("[Central] PL/SQL block executed successfully")
                if _t0 is not None:
                    capture_sql('central', 'PLSQL', plsql_block, params,
                                duration_ms=(time.perf_counter() - _t0) * 1000)
                return True

        except oracledb.Error as e:
            if _t0 is not None:
                capture_sql('central', 'PLSQL', plsql_block, params,
                            status='ERROR', error=str(e), duration_ms=(time.perf_counter() - _t0) * 1000)
            log_db_error(e, plsql_block, params)
            if raise_on_error:
                raise
            st.error(f"Central database PL/SQL execution error: {describe_db_error(e)}")
            return False

    @classmethod
    def execute_procedure(cls, procedure_name: str, params: Optional[List[Any]] = None) -> Any:
        """
        Execute stored procedure on central database

        Args:
            procedure_name: Name of stored procedure
            params: Procedure parameters

        Returns:
            Any: Procedure result
        """
        _t0 = time.perf_counter() if is_debug_enabled() else None
        try:
            log_debug(f"[Central] Executing procedure: {procedure_name}")
            with cls.get_connection() as conn:
                cursor = conn.cursor()

                if params:
                    result = cursor.callproc(procedure_name, params)
                else:
                    result = cursor.callproc(procedure_name)

                conn.commit()
                cursor.close()

                log_info(f"[Central] Procedure {procedure_name} executed successfully")
                if _t0 is not None:
                    capture_sql('central', 'PROCEDURE', f"CALL {procedure_name}",
                                duration_ms=(time.perf_counter() - _t0) * 1000)
                return result

        except oracledb.Error as e:
            if _t0 is not None:
                capture_sql('central', 'PROCEDURE', f"CALL {procedure_name}",
                            status='ERROR', error=str(e), duration_ms=(time.perf_counter() - _t0) * 1000)
            log_error(e, f"CentralConnector.execute_procedure({procedure_name})")
            st.error(f"Central database procedure execution error: {describe_db_error(e)}")
            return None

    @classmethod
    def execute_procedure_with_output(
        cls,
        plsql_block: str,
        in_params: Optional[Dict[str, Any]] = None,
        out_params: Optional[Dict[str, type]] = None
    ) -> Dict[str, Any]:
        """
        Execute PL/SQL block with input and output parameters on central database

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
            result = CentralConnector.execute_procedure_with_output(
                plsql,
                in_params={'input_val': 100},
                out_params={'output_val': int}
            )
        """
        _t0 = time.perf_counter() if is_debug_enabled() else None
        try:
            log_debug(f"[Central] Executing PL/SQL with output", block_preview=plsql_block[:200])
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
                    if out_params.get(param_name) == int and value is not None:
                        result[param_name] = int(value)
                    elif out_params.get(param_name) == float and value is not None:
                        result[param_name] = float(value)
                    else:
                        result[param_name] = value

                cursor.close()
                log_debug(f"[Central] PL/SQL with output returned: {list(result.keys())}")
                if _t0 is not None:
                    capture_sql('central', 'PLSQL', plsql_block, in_params,
                                duration_ms=(time.perf_counter() - _t0) * 1000)
                return result

        except oracledb.Error as e:
            if _t0 is not None:
                capture_sql('central', 'PLSQL', plsql_block, in_params,
                            status='ERROR', error=str(e), duration_ms=(time.perf_counter() - _t0) * 1000)
            log_db_error(e, plsql_block, in_params)
            st.error(f"Central database PL/SQL execution error: {describe_db_error(e)}")
            raise

    @classmethod
    def call_function_cursor(cls, function_call: str, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        """
        Call a function that returns a REF CURSOR on central database and return results as DataFrame

        Args:
            function_call: Function call expression (e.g., 'pkg_name.func_name(:param1)')
            params: Function parameters

        Returns:
            pd.DataFrame: Query results from the cursor

        Example:
            df = CentralConnector.call_function_cursor(
                'my_pkg.get_data(:owner)',
                {'owner': 'HR'}
            )
        """
        _t0 = time.perf_counter() if is_debug_enabled() else None
        try:
            log_debug(f"[Central] Calling function cursor: {function_call}")
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

                log_debug(f"[Central] Function cursor returned {len(rows)} rows")
                if _t0 is not None:
                    capture_sql('central', 'FUNCTION', f"CURSOR: {function_call}", params,
                                rows_affected=len(rows), duration_ms=(time.perf_counter() - _t0) * 1000)
                return pd.DataFrame(rows, columns=columns)

        except oracledb.Error as e:
            if _t0 is not None:
                capture_sql('central', 'FUNCTION', f"CURSOR: {function_call}", params,
                            status='ERROR', error=str(e), duration_ms=(time.perf_counter() - _t0) * 1000)
            log_error(e, f"CentralConnector.call_function_cursor({function_call})")
            st.error(f"Central database function cursor execution error: {describe_db_error(e)}")
            return pd.DataFrame()

    @classmethod
    def test_connection(cls) -> bool:
        """
        Test central database connection

        Returns:
            bool: True if connection successful
        """
        try:
            with cls.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM DUAL")
                cursor.fetchone()
                cursor.close()
                log_info("[Central] Connection test successful")
                return True
        except oracledb.Error as e:
            log_error(e, "CentralConnector.test_connection")
            st.error(f"Central database connection test failed: {describe_db_error(e)}")
            return False

    @classmethod
    def close_pool(cls):
        """Close central database connection pool"""
        with cls._pool_lock:
            if cls._pool:
                try:
                    cls._pool.close()
                    log_info("[Central] Connection pool closed")
                except oracledb.Error as e:
                    log_error(e, "CentralConnector.close_pool")
                cls._pool = None

    @classmethod
    def execute_dml_returning(
        cls,
        statement: str,
        params: Optional[Dict[str, Any]] = None,
        out_bind: str = 'new_id',
        commit: bool = True,
        raise_on_error: bool = False
    ) -> Optional[Any]:
        """
        Execute a single-row DML statement with a RETURNING ... INTO clause on
        the central database and return the returned value (typically the
        generated identity key of an INSERT).

        Use this instead of re-selecting the key afterwards (SELECT MAX(id) ...),
        which races with concurrent inserts.

        Args:
            statement: DML ending in "RETURNING <column> INTO :<out_bind>"
            params: Input bind parameters (must not contain out_bind)
            out_bind: Name of the RETURNING INTO bind variable
            commit: Whether to commit transaction
            raise_on_error: Re-raise database errors to the caller instead of
                showing st.error and returning None

        Returns:
            The returned value (int for integral numbers), or None if no row
            was affected or the statement failed

        Example:
            new_id = CentralConnector.execute_dml_returning(
                "INSERT INTO t_foo (name) VALUES (:name) RETURNING foo_id INTO :new_id",
                {'name': 'x'}
            )
        """
        _t0 = time.perf_counter() if is_debug_enabled() else None
        try:
            log_debug("[Central] Executing DML returning", statement_preview=statement[:200])
            with cls.get_connection() as conn:
                cursor = conn.cursor()

                out_var = cursor.var(oracledb.NUMBER)
                all_params = dict(params or {})
                all_params[out_bind] = out_var

                cursor.execute(statement, all_params)
                rows_affected = cursor.rowcount

                if commit:
                    conn.commit()

                # For DML returning, getvalue() is a list with one entry per
                # affected row.
                values = out_var.getvalue()
                cursor.close()

                if isinstance(values, list):
                    value = values[0] if values else None
                else:
                    value = values
                if isinstance(value, float) and value.is_integer():
                    value = int(value)

                log_debug(f"[Central] DML affected {rows_affected} rows, returned {out_bind}={value}")
                if _t0 is not None:
                    capture_sql('central', 'DML', statement, params,
                                rows_affected=rows_affected, duration_ms=(time.perf_counter() - _t0) * 1000)
                return value

        except oracledb.Error as e:
            if _t0 is not None:
                capture_sql('central', 'DML', statement, params,
                            status='ERROR', error=str(e), duration_ms=(time.perf_counter() - _t0) * 1000)
            log_db_error(e, statement, params)
            if raise_on_error:
                raise
            st.error(f"Central database DML error: {describe_db_error(e)}")
            return None


@st.cache_resource
def get_central_connector():
    """Get cached central database connector"""
    return CentralConnector()
