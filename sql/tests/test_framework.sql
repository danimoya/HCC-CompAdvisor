--------------------------------------------------------------------------------
-- Test Framework for HCC Compression Advisor
-- Simple PL/SQL testing framework with assertions and reporting
--------------------------------------------------------------------------------

-- Test tracking table
CREATE TABLE IF NOT EXISTS test_results (
    test_id NUMBER GENERATED ALWAYS AS IDENTITY,
    test_suite VARCHAR2(100),
    test_name VARCHAR2(200),
    test_status VARCHAR2(20), -- PASS, FAIL, ERROR
    test_message VARCHAR2(4000),
    test_duration NUMBER,
    test_timestamp TIMESTAMP DEFAULT SYSTIMESTAMP,
    CONSTRAINT pk_test_results PRIMARY KEY (test_id)
);

CREATE OR REPLACE PACKAGE test_framework AS
    -- Test tracking
    g_current_suite VARCHAR2(100);
    g_test_count NUMBER := 0;
    g_pass_count NUMBER := 0;
    g_fail_count NUMBER := 0;
    g_error_count NUMBER := 0;
    g_start_time TIMESTAMP;

    -- Initialize test suite
    PROCEDURE start_suite(p_suite_name VARCHAR2);

    -- Finalize test suite
    PROCEDURE end_suite;

    -- Assertion procedures
    PROCEDURE assert_true(
        p_test_name VARCHAR2,
        p_condition BOOLEAN,
        p_message VARCHAR2 DEFAULT NULL
    );

    PROCEDURE assert_false(
        p_test_name VARCHAR2,
        p_condition BOOLEAN,
        p_message VARCHAR2 DEFAULT NULL
    );

    PROCEDURE assert_equals(
        p_test_name VARCHAR2,
        p_expected VARCHAR2,
        p_actual VARCHAR2,
        p_message VARCHAR2 DEFAULT NULL
    );

    PROCEDURE assert_equals_number(
        p_test_name VARCHAR2,
        p_expected NUMBER,
        p_actual NUMBER,
        p_message VARCHAR2 DEFAULT NULL
    );

    PROCEDURE assert_not_null(
        p_test_name VARCHAR2,
        p_value VARCHAR2,
        p_message VARCHAR2 DEFAULT NULL
    );

    PROCEDURE assert_null(
        p_test_name VARCHAR2,
        p_value VARCHAR2,
        p_message VARCHAR2 DEFAULT NULL
    );

    PROCEDURE assert_contains(
        p_test_name VARCHAR2,
        p_haystack VARCHAR2,
        p_needle VARCHAR2,
        p_message VARCHAR2 DEFAULT NULL
    );

    -- Print test summary
    PROCEDURE print_summary;

    -- Clear test results
    PROCEDURE clear_results(p_suite_name VARCHAR2 DEFAULT NULL);

END test_framework;
/

CREATE OR REPLACE PACKAGE BODY test_framework AS

    PROCEDURE log_result(
        p_test_name VARCHAR2,
        p_status VARCHAR2,
        p_message VARCHAR2
    ) IS
        PRAGMA AUTONOMOUS_TRANSACTION;
        v_duration NUMBER;
    BEGIN
        v_duration := EXTRACT(SECOND FROM (SYSTIMESTAMP - g_start_time));

        INSERT INTO test_results (
            test_suite,
            test_name,
            test_status,
            test_message,
            test_duration
        ) VALUES (
            g_current_suite,
            p_test_name,
            p_status,
            p_message,
            v_duration
        );

        COMMIT;

        g_test_count := g_test_count + 1;

        CASE p_status
            WHEN 'PASS' THEN
                g_pass_count := g_pass_count + 1;
                DBMS_OUTPUT.PUT_LINE('  ✓ ' || p_test_name);
            WHEN 'FAIL' THEN
                g_fail_count := g_fail_count + 1;
                DBMS_OUTPUT.PUT_LINE('  ✗ ' || p_test_name || ': ' || p_message);
            WHEN 'ERROR' THEN
                g_error_count := g_error_count + 1;
                DBMS_OUTPUT.PUT_LINE('  ⚠ ' || p_test_name || ': ' || p_message);
        END CASE;

    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('Error logging result: ' || SQLERRM);
            ROLLBACK;
    END log_result;

    PROCEDURE start_suite(p_suite_name VARCHAR2) IS
    BEGIN
        g_current_suite := p_suite_name;
        g_test_count := 0;
        g_pass_count := 0;
        g_fail_count := 0;
        g_error_count := 0;
        g_start_time := SYSTIMESTAMP;

        DBMS_OUTPUT.PUT_LINE(CHR(10) || '═══════════════════════════════════════════════════════');
        DBMS_OUTPUT.PUT_LINE('Test Suite: ' || p_suite_name);
        DBMS_OUTPUT.PUT_LINE('═══════════════════════════════════════════════════════');
    END start_suite;

    PROCEDURE end_suite IS
        v_duration NUMBER;
    BEGIN
        v_duration := EXTRACT(SECOND FROM (SYSTIMESTAMP - g_start_time));

        DBMS_OUTPUT.PUT_LINE('───────────────────────────────────────────────────────');
        DBMS_OUTPUT.PUT_LINE('Results: ' || g_pass_count || ' passed, ' ||
                           g_fail_count || ' failed, ' ||
                           g_error_count || ' errors');
        DBMS_OUTPUT.PUT_LINE('Duration: ' || ROUND(v_duration, 2) || ' seconds');
        DBMS_OUTPUT.PUT_LINE('═══════════════════════════════════════════════════════' || CHR(10));
    END end_suite;

    PROCEDURE assert_true(
        p_test_name VARCHAR2,
        p_condition BOOLEAN,
        p_message VARCHAR2 DEFAULT NULL
    ) IS
    BEGIN
        IF p_condition THEN
            log_result(p_test_name, 'PASS', NULL);
        ELSE
            log_result(p_test_name, 'FAIL',
                NVL(p_message, 'Expected TRUE but got FALSE'));
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            log_result(p_test_name, 'ERROR', SQLERRM);
    END assert_true;

    PROCEDURE assert_false(
        p_test_name VARCHAR2,
        p_condition BOOLEAN,
        p_message VARCHAR2 DEFAULT NULL
    ) IS
    BEGIN
        IF NOT p_condition THEN
            log_result(p_test_name, 'PASS', NULL);
        ELSE
            log_result(p_test_name, 'FAIL',
                NVL(p_message, 'Expected FALSE but got TRUE'));
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            log_result(p_test_name, 'ERROR', SQLERRM);
    END assert_false;

    PROCEDURE assert_equals(
        p_test_name VARCHAR2,
        p_expected VARCHAR2,
        p_actual VARCHAR2,
        p_message VARCHAR2 DEFAULT NULL
    ) IS
    BEGIN
        IF p_expected = p_actual OR (p_expected IS NULL AND p_actual IS NULL) THEN
            log_result(p_test_name, 'PASS', NULL);
        ELSE
            log_result(p_test_name, 'FAIL',
                NVL(p_message, 'Expected "' || p_expected || '" but got "' || p_actual || '"'));
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            log_result(p_test_name, 'ERROR', SQLERRM);
    END assert_equals;

    PROCEDURE assert_equals_number(
        p_test_name VARCHAR2,
        p_expected NUMBER,
        p_actual NUMBER,
        p_message VARCHAR2 DEFAULT NULL
    ) IS
    BEGIN
        IF p_expected = p_actual OR (p_expected IS NULL AND p_actual IS NULL) THEN
            log_result(p_test_name, 'PASS', NULL);
        ELSE
            log_result(p_test_name, 'FAIL',
                NVL(p_message, 'Expected ' || p_expected || ' but got ' || p_actual));
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            log_result(p_test_name, 'ERROR', SQLERRM);
    END assert_equals_number;

    PROCEDURE assert_not_null(
        p_test_name VARCHAR2,
        p_value VARCHAR2,
        p_message VARCHAR2 DEFAULT NULL
    ) IS
    BEGIN
        IF p_value IS NOT NULL THEN
            log_result(p_test_name, 'PASS', NULL);
        ELSE
            log_result(p_test_name, 'FAIL',
                NVL(p_message, 'Expected non-NULL value but got NULL'));
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            log_result(p_test_name, 'ERROR', SQLERRM);
    END assert_not_null;

    PROCEDURE assert_null(
        p_test_name VARCHAR2,
        p_value VARCHAR2,
        p_message VARCHAR2 DEFAULT NULL
    ) IS
    BEGIN
        IF p_value IS NULL THEN
            log_result(p_test_name, 'PASS', NULL);
        ELSE
            log_result(p_test_name, 'FAIL',
                NVL(p_message, 'Expected NULL but got "' || p_value || '"'));
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            log_result(p_test_name, 'ERROR', SQLERRM);
    END assert_null;

    PROCEDURE assert_contains(
        p_test_name VARCHAR2,
        p_haystack VARCHAR2,
        p_needle VARCHAR2,
        p_message VARCHAR2 DEFAULT NULL
    ) IS
    BEGIN
        IF INSTR(p_haystack, p_needle) > 0 THEN
            log_result(p_test_name, 'PASS', NULL);
        ELSE
            log_result(p_test_name, 'FAIL',
                NVL(p_message, 'Expected to find "' || p_needle || '" in "' || p_haystack || '"'));
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            log_result(p_test_name, 'ERROR', SQLERRM);
    END assert_contains;

    PROCEDURE print_summary IS
        CURSOR c_results IS
            SELECT test_suite,
                   COUNT(*) as total_tests,
                   SUM(CASE WHEN test_status = 'PASS' THEN 1 ELSE 0 END) as passed,
                   SUM(CASE WHEN test_status = 'FAIL' THEN 1 ELSE 0 END) as failed,
                   SUM(CASE WHEN test_status = 'ERROR' THEN 1 ELSE 0 END) as errors,
                   ROUND(AVG(test_duration), 2) as avg_duration
            FROM test_results
            GROUP BY test_suite
            ORDER BY test_suite;
    BEGIN
        DBMS_OUTPUT.PUT_LINE(CHR(10) || '═══════════════════════════════════════════════════════');
        DBMS_OUTPUT.PUT_LINE('OVERALL TEST SUMMARY');
        DBMS_OUTPUT.PUT_LINE('═══════════════════════════════════════════════════════');

        FOR rec IN c_results LOOP
            DBMS_OUTPUT.PUT_LINE(CHR(10) || 'Suite: ' || rec.test_suite);
            DBMS_OUTPUT.PUT_LINE('  Total: ' || rec.total_tests);
            DBMS_OUTPUT.PUT_LINE('  Passed: ' || rec.passed);
            DBMS_OUTPUT.PUT_LINE('  Failed: ' || rec.failed);
            DBMS_OUTPUT.PUT_LINE('  Errors: ' || rec.errors);
            DBMS_OUTPUT.PUT_LINE('  Avg Duration: ' || rec.avg_duration || 's');
        END LOOP;

        DBMS_OUTPUT.PUT_LINE('═══════════════════════════════════════════════════════' || CHR(10));
    END print_summary;

    PROCEDURE clear_results(p_suite_name VARCHAR2 DEFAULT NULL) IS
        PRAGMA AUTONOMOUS_TRANSACTION;
    BEGIN
        IF p_suite_name IS NULL THEN
            DELETE FROM test_results;
        ELSE
            DELETE FROM test_results WHERE test_suite = p_suite_name;
        END IF;
        COMMIT;
        DBMS_OUTPUT.PUT_LINE('Test results cleared.');
    END clear_results;

END test_framework;
/
