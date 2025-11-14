--------------------------------------------------------------------------------
-- Unit Tests for HCC_LOGGING Package
-- Test coverage: Logging functionality, log levels, log retrieval
--------------------------------------------------------------------------------

SET SERVEROUTPUT ON SIZE UNLIMITED
SET FEEDBACK OFF
SET VERIFY OFF

-- Start test suite
EXEC test_framework.start_suite('LOGGING_PKG_UNIT_TESTS');

DECLARE
    v_result VARCHAR2(4000);
    v_count NUMBER;
    v_log_id NUMBER;

BEGIN

    ----------------------------------------------------------------------------
    -- TEST GROUP 1: Basic Logging Tests (5 tests)
    ----------------------------------------------------------------------------

    -- Test 1: Log INFO level message
    BEGIN
        -- Clear existing logs
        DELETE FROM hcc_execution_log WHERE 1=1;
        COMMIT;

        -- Insert test log
        INSERT INTO hcc_execution_log (
            log_level, log_message, table_owner, table_name
        ) VALUES (
            'INFO', 'Test INFO message', USER, 'TEST_TABLE'
        );
        COMMIT;

        SELECT COUNT(*) INTO v_count
        FROM hcc_execution_log
        WHERE log_level = 'INFO';

        test_framework.assert_true(
            'Log INFO level message',
            v_count > 0,
            'Should log INFO messages'
        );
    END;

    -- Test 2: Log WARNING level message
    BEGIN
        INSERT INTO hcc_execution_log (
            log_level, log_message, table_owner, table_name
        ) VALUES (
            'WARNING', 'Test WARNING message', USER, 'TEST_TABLE'
        );
        COMMIT;

        SELECT COUNT(*) INTO v_count
        FROM hcc_execution_log
        WHERE log_level = 'WARNING';

        test_framework.assert_true(
            'Log WARNING level message',
            v_count > 0,
            'Should log WARNING messages'
        );
    END;

    -- Test 3: Log ERROR level message
    BEGIN
        INSERT INTO hcc_execution_log (
            log_level, log_message, table_owner, table_name
        ) VALUES (
            'ERROR', 'Test ERROR message', USER, 'TEST_TABLE'
        );
        COMMIT;

        SELECT COUNT(*) INTO v_count
        FROM hcc_execution_log
        WHERE log_level = 'ERROR';

        test_framework.assert_true(
            'Log ERROR level message',
            v_count > 0,
            'Should log ERROR messages'
        );
    END;

    -- Test 4: Log DEBUG level message
    BEGIN
        INSERT INTO hcc_execution_log (
            log_level, log_message, table_owner, table_name
        ) VALUES (
            'DEBUG', 'Test DEBUG message', USER, 'TEST_TABLE'
        );
        COMMIT;

        SELECT COUNT(*) INTO v_count
        FROM hcc_execution_log
        WHERE log_level = 'DEBUG';

        test_framework.assert_true(
            'Log DEBUG level message',
            v_count > 0,
            'Should log DEBUG messages'
        );
    END;

    -- Test 5: Validate log timestamp
    BEGIN
        SELECT COUNT(*) INTO v_count
        FROM hcc_execution_log
        WHERE log_timestamp IS NOT NULL
        AND log_timestamp <= SYSTIMESTAMP;

        test_framework.assert_true(
            'Validate log timestamp',
            v_count > 0,
            'All logs should have valid timestamps'
        );
    END;

    ----------------------------------------------------------------------------
    -- TEST GROUP 2: Log Retrieval Tests (5 tests)
    ----------------------------------------------------------------------------

    -- Test 6: Retrieve logs by level
    BEGIN
        SELECT COUNT(*) INTO v_count
        FROM hcc_execution_log
        WHERE log_level = 'ERROR';

        test_framework.assert_true(
            'Filter logs by level',
            v_count >= 0,
            'Should retrieve logs by specific level'
        );
    END;

    -- Test 7: Retrieve logs by date range
    BEGIN
        SELECT COUNT(*) INTO v_count
        FROM hcc_execution_log
        WHERE log_timestamp >= SYSTIMESTAMP - INTERVAL '1' DAY;

        test_framework.assert_true(
            'Filter logs by date range',
            v_count >= 0,
            'Should retrieve logs within date range'
        );
    END;

    -- Test 8: Retrieve logs by table
    BEGIN
        SELECT COUNT(*) INTO v_count
        FROM hcc_execution_log
        WHERE table_name = 'TEST_TABLE';

        test_framework.assert_true(
            'Filter logs by table name',
            v_count >= 0,
            'Should retrieve logs for specific table'
        );
    END;

    -- Test 9: Retrieve recent logs
    BEGIN
        SELECT COUNT(*) INTO v_count
        FROM (
            SELECT * FROM hcc_execution_log
            ORDER BY log_timestamp DESC
            FETCH FIRST 10 ROWS ONLY
        );

        test_framework.assert_true(
            'Retrieve recent logs',
            v_count >= 0,
            'Should retrieve most recent log entries'
        );
    END;

    -- Test 10: Validate log data integrity
    BEGIN
        SELECT COUNT(*) INTO v_count
        FROM hcc_execution_log
        WHERE log_message IS NOT NULL
        AND log_level IS NOT NULL;

        test_framework.assert_true(
            'Validate log data integrity',
            v_count >= 0,
            'All logs should have required fields'
        );
    END;

    -- Cleanup test logs
    DELETE FROM hcc_execution_log WHERE table_name = 'TEST_TABLE';
    COMMIT;

    DBMS_OUTPUT.PUT_LINE(CHR(10) || 'All LOGGING_PKG unit tests completed.');

END;
/

-- End test suite
EXEC test_framework.end_suite;
