--------------------------------------------------------------------------------
-- Master Test Runner for HCC Compression Advisor
-- Executes all test suites and generates comprehensive report
--------------------------------------------------------------------------------

SET SERVEROUTPUT ON SIZE UNLIMITED
SET FEEDBACK OFF
SET VERIFY OFF
SET TIMING ON

PROMPT
PROMPT ================================================================================
PROMPT HCC COMPRESSION ADVISOR - COMPREHENSIVE TEST SUITE
PROMPT ================================================================================
PROMPT

-- Set session parameters for testing
ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD HH24:MI:SS';
ALTER SESSION SET NLS_TIMESTAMP_FORMAT = 'YYYY-MM-DD HH24:MI:SS.FF';

PROMPT Creating test framework...
@@test_framework.sql

PROMPT
PROMPT Clearing previous test results...
EXEC test_framework.clear_results();

PROMPT
PROMPT ================================================================================
PROMPT UNIT TESTS
PROMPT ================================================================================

PROMPT
PROMPT [1/4] Running ADVISOR_PKG unit tests...
@@unit/test_advisor_pkg.sql

PROMPT
PROMPT [2/4] Running EXECUTOR_PKG unit tests...
@@unit/test_executor_pkg.sql

PROMPT
PROMPT [3/4] Running LOGGING_PKG unit tests...
@@unit/test_logging_pkg.sql

PROMPT
PROMPT ================================================================================
PROMPT INTEGRATION TESTS
PROMPT ================================================================================

PROMPT
PROMPT [4/4] Running full workflow integration tests...
@@integration/test_full_workflow.sql

PROMPT
PROMPT ================================================================================
PROMPT TEST EXECUTION COMPLETE
PROMPT ================================================================================

-- Generate detailed test report
PROMPT
PROMPT Generating detailed test report...
PROMPT

SET PAGESIZE 1000
SET LINESIZE 200

COL test_suite FORMAT A30
COL test_name FORMAT A50
COL test_status FORMAT A10
COL test_message FORMAT A60
COL test_duration FORMAT 999.99

PROMPT
PROMPT ──────────────────────────────────────────────────────────────────────────────
PROMPT DETAILED TEST RESULTS
PROMPT ──────────────────────────────────────────────────────────────────────────────

SELECT test_suite,
       test_name,
       test_status,
       test_message,
       test_duration
FROM test_results
ORDER BY test_id;

PROMPT
PROMPT ──────────────────────────────────────────────────────────────────────────────
PROMPT SUMMARY BY TEST SUITE
PROMPT ──────────────────────────────────────────────────────────────────────────────

SELECT test_suite,
       COUNT(*) as total_tests,
       SUM(CASE WHEN test_status = 'PASS' THEN 1 ELSE 0 END) as passed,
       SUM(CASE WHEN test_status = 'FAIL' THEN 1 ELSE 0 END) as failed,
       SUM(CASE WHEN test_status = 'ERROR' THEN 1 ELSE 0 END) as errors,
       ROUND(AVG(test_duration), 2) as avg_duration_sec,
       ROUND(SUM(test_duration), 2) as total_duration_sec
FROM test_results
GROUP BY test_suite
ORDER BY test_suite;

PROMPT
PROMPT ──────────────────────────────────────────────────────────────────────────────
PROMPT OVERALL TEST STATISTICS
PROMPT ──────────────────────────────────────────────────────────────────────────────

SELECT COUNT(*) as total_tests,
       SUM(CASE WHEN test_status = 'PASS' THEN 1 ELSE 0 END) as passed,
       SUM(CASE WHEN test_status = 'FAIL' THEN 1 ELSE 0 END) as failed,
       SUM(CASE WHEN test_status = 'ERROR' THEN 1 ELSE 0 END) as errors,
       ROUND(SUM(CASE WHEN test_status = 'PASS' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) || '%' as pass_rate,
       ROUND(SUM(test_duration), 2) as total_duration_sec
FROM test_results;

PROMPT
PROMPT ──────────────────────────────────────────────────────────────────────────────
PROMPT FAILED/ERROR TESTS (if any)
PROMPT ──────────────────────────────────────────────────────────────────────────────

SELECT test_suite,
       test_name,
       test_status,
       test_message
FROM test_results
WHERE test_status IN ('FAIL', 'ERROR')
ORDER BY test_suite, test_name;

PROMPT
PROMPT ──────────────────────────────────────────────────────────────────────────────
PROMPT SLOWEST TESTS
PROMPT ──────────────────────────────────────────────────────────────────────────────

SELECT test_suite,
       test_name,
       test_duration
FROM (
    SELECT test_suite,
           test_name,
           test_duration,
           RANK() OVER (ORDER BY test_duration DESC) as rnk
    FROM test_results
)
WHERE rnk <= 10
ORDER BY test_duration DESC;

PROMPT
PROMPT ──────────────────────────────────────────────────────────────────────────────
PROMPT TEST COVERAGE BY CATEGORY
PROMPT ──────────────────────────────────────────────────────────────────────────────

SELECT
    CASE
        WHEN UPPER(test_name) LIKE '%CANDIDATE%' OR UPPER(test_name) LIKE '%IDENTIFY%' THEN 'Candidate Identification'
        WHEN UPPER(test_name) LIKE '%RECOMMEND%' THEN 'Recommendation Logic'
        WHEN UPPER(test_name) LIKE '%DDL%' THEN 'DDL Generation'
        WHEN UPPER(test_name) LIKE '%EXECUT%' OR UPPER(test_name) LIKE '%SAFETY%' THEN 'Execution Safety'
        WHEN UPPER(test_name) LIKE '%ERROR%' OR UPPER(test_name) LIKE '%HANDLE%' THEN 'Error Handling'
        WHEN UPPER(test_name) LIKE '%ROLLBACK%' OR UPPER(test_name) LIKE '%RECOVERY%' THEN 'Rollback & Recovery'
        WHEN UPPER(test_name) LIKE '%TABLESPACE%' THEN 'Tablespace Management'
        WHEN UPPER(test_name) LIKE '%EXADATA%' OR UPPER(test_name) LIKE '%PLATFORM%' THEN 'Platform Detection'
        WHEN UPPER(test_name) LIKE '%LOG%' THEN 'Logging'
        WHEN UPPER(test_name) LIKE '%WORKFLOW%' OR UPPER(test_name) LIKE '%INTEGRATION%' THEN 'Integration'
        ELSE 'Other'
    END as test_category,
    COUNT(*) as test_count,
    SUM(CASE WHEN test_status = 'PASS' THEN 1 ELSE 0 END) as passed,
    SUM(CASE WHEN test_status = 'FAIL' THEN 1 ELSE 0 END) as failed
FROM test_results
GROUP BY
    CASE
        WHEN UPPER(test_name) LIKE '%CANDIDATE%' OR UPPER(test_name) LIKE '%IDENTIFY%' THEN 'Candidate Identification'
        WHEN UPPER(test_name) LIKE '%RECOMMEND%' THEN 'Recommendation Logic'
        WHEN UPPER(test_name) LIKE '%DDL%' THEN 'DDL Generation'
        WHEN UPPER(test_name) LIKE '%EXECUT%' OR UPPER(test_name) LIKE '%SAFETY%' THEN 'Execution Safety'
        WHEN UPPER(test_name) LIKE '%ERROR%' OR UPPER(test_name) LIKE '%HANDLE%' THEN 'Error Handling'
        WHEN UPPER(test_name) LIKE '%ROLLBACK%' OR UPPER(test_name) LIKE '%RECOVERY%' THEN 'Rollback & Recovery'
        WHEN UPPER(test_name) LIKE '%TABLESPACE%' THEN 'Tablespace Management'
        WHEN UPPER(test_name) LIKE '%EXADATA%' OR UPPER(test_name) LIKE '%PLATFORM%' THEN 'Platform Detection'
        WHEN UPPER(test_name) LIKE '%LOG%' THEN 'Logging'
        WHEN UPPER(test_name) LIKE '%WORKFLOW%' OR UPPER(test_name) LIKE '%INTEGRATION%' THEN 'Integration'
        ELSE 'Other'
    END
ORDER BY test_count DESC;

PROMPT
PROMPT ================================================================================
PROMPT TEST EXECUTION SUMMARY
PROMPT ================================================================================

DECLARE
    v_total NUMBER;
    v_passed NUMBER;
    v_failed NUMBER;
    v_errors NUMBER;
    v_pass_rate NUMBER;
BEGIN
    SELECT COUNT(*),
           SUM(CASE WHEN test_status = 'PASS' THEN 1 ELSE 0 END),
           SUM(CASE WHEN test_status = 'FAIL' THEN 1 ELSE 0 END),
           SUM(CASE WHEN test_status = 'ERROR' THEN 1 ELSE 0 END)
    INTO v_total, v_passed, v_failed, v_errors
    FROM test_results;

    v_pass_rate := ROUND((v_passed * 100.0) / v_total, 2);

    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE('Total Tests Run:     ' || v_total);
    DBMS_OUTPUT.PUT_LINE('Tests Passed:        ' || v_passed || ' (' || v_pass_rate || '%)');
    DBMS_OUTPUT.PUT_LINE('Tests Failed:        ' || v_failed);
    DBMS_OUTPUT.PUT_LINE('Tests with Errors:   ' || v_errors);
    DBMS_OUTPUT.PUT_LINE('');

    IF v_failed = 0 AND v_errors = 0 THEN
        DBMS_OUTPUT.PUT_LINE('✓ ALL TESTS PASSED SUCCESSFULLY!');
    ELSE
        DBMS_OUTPUT.PUT_LINE('✗ SOME TESTS FAILED - REVIEW RESULTS ABOVE');
    END IF;

    DBMS_OUTPUT.PUT_LINE('');
END;
/

PROMPT
PROMPT ================================================================================
PROMPT Test results saved to TEST_RESULTS table
PROMPT ================================================================================
PROMPT
PROMPT To view results later, query:
PROMPT   SELECT * FROM test_results ORDER BY test_id;
PROMPT
PROMPT To clear results:
PROMPT   EXEC test_framework.clear_results();
PROMPT
PROMPT ================================================================================

SET TIMING OFF
SET FEEDBACK ON
SET VERIFY ON
