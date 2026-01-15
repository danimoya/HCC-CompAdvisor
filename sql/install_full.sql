--------------------------------------------------------------------------------
-- HCC Compression Advisor - Full Installation Script
--------------------------------------------------------------------------------
-- Description: Master installation script for HCC Compression Advisor
-- Version:     1.0.0
-- Author:      Daniel Moya (copyright), GitHub: github.com/danimoya Website: danielmoya.cv
--
-- Prerequisites:
--   - Oracle Database 19c or later
--   - SYSDBA or schema owner privileges
--   - ORDS installed (for REST API installation)
--   - Minimum 100MB tablespace quota
--
-- Installation:
--   SQL> @install_full.sql
--
-- Notes:
--   - Review prerequisites before running
--   - Installation takes approximately 2-5 minutes
--   - Check install_full.log for detailed results
--------------------------------------------------------------------------------

--------------------------------------------------------------------------------
-- SECTION 1: Environment Setup
--------------------------------------------------------------------------------

-- Set SQL*Plus environment
SET ECHO ON
SET FEEDBACK ON
SET HEADING ON
SET LINESIZE 200
SET PAGESIZE 1000
SET SERVEROUTPUT ON SIZE UNLIMITED
SET VERIFY OFF
SET TRIMSPOOL ON
SET TRIMOUT ON
SET DEFINE '&'
SET CONCAT '.'
SET TIMING ON

-- Start logging
SPOOL install_full.log

PROMPT ================================================================================
PROMPT HCC Compression Advisor - Installation Starting
PROMPT ================================================================================
PROMPT Installation Time: &_DATE
PROMPT Database: &_CONNECT_IDENTIFIER
PROMPT User: &_USER
PROMPT ================================================================================
PROMPT
PROMPT Installation Components:
PROMPT   - Core Schema Objects (tables, sequences, indexes)
PROMPT   - Schema Fixes and Enhancements
PROMPT   - Compression Strategies Reference Data
PROMPT   - Logging Package (foundation)
PROMPT   - Exadata Detection Package
PROMPT   - HCC Advisor Package (main logic)
PROMPT   - Compression Executor Package
PROMPT   - Reporting Views
PROMPT   - REST API Modules (if ORDS available)
PROMPT   - Installation Validation
PROMPT
PROMPT Estimated Installation Time: 2-5 minutes
PROMPT ================================================================================

--------------------------------------------------------------------------------
-- SECTION 2: Pre-Installation Checks
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT STEP 1: Pre-Installation Validation
PROMPT ================================================================================

-- Variable declarations for validation
VARIABLE v_db_version VARCHAR2(100)
VARIABLE v_hcc_support VARCHAR2(10)
VARIABLE v_username VARCHAR2(128)
VARIABLE v_quota NUMBER
VARIABLE v_privs_ok NUMBER
VARIABLE v_errors NUMBER

-- Initialize error counter
BEGIN
    :v_errors := 0;
END;
/

-- Check Oracle Database Version
PROMPT
PROMPT [1.1] Checking Oracle Database Version...
DECLARE
    v_version VARCHAR2(100);
    v_major NUMBER;
    v_minor NUMBER;
BEGIN
    SELECT version INTO v_version FROM v$instance;
    :v_db_version := v_version;

    -- Extract major version
    v_major := TO_NUMBER(SUBSTR(v_version, 1, INSTR(v_version, '.') - 1));

    IF v_major < 19 THEN
        DBMS_OUTPUT.PUT_LINE('ERROR: Oracle Database 19c or later required. Current version: ' || v_version);
        :v_errors := :v_errors + 1;
    ELSE
        DBMS_OUTPUT.PUT_LINE('SUCCESS: Oracle Database version ' || v_version || ' detected.');
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('ERROR: Unable to determine database version: ' || SQLERRM);
        :v_errors := :v_errors + 1;
END;
/

-- Check HCC Support
PROMPT
PROMPT [1.2] Checking HCC (Hybrid Columnar Compression) Support...
DECLARE
    v_hcc VARCHAR2(10);
BEGIN
    SELECT VALUE INTO v_hcc
    FROM v$parameter
    WHERE name = 'compatible';

    :v_hcc_support := v_hcc;
    DBMS_OUTPUT.PUT_LINE('SUCCESS: Database compatibility set to ' || v_hcc);
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('WARNING: Unable to verify HCC support: ' || SQLERRM);
END;
/

-- Check Current User and Privileges
PROMPT
PROMPT [1.3] Checking User Privileges...
DECLARE
    v_priv_count NUMBER := 0;
BEGIN
    SELECT user INTO :v_username FROM dual;

    DBMS_OUTPUT.PUT_LINE('Current user: ' || :v_username);

    -- Check for required privileges
    SELECT COUNT(*) INTO v_priv_count
    FROM (
        SELECT privilege FROM user_sys_privs WHERE privilege IN ('CREATE TABLE', 'CREATE PROCEDURE', 'CREATE VIEW', 'CREATE SEQUENCE')
        UNION ALL
        SELECT privilege FROM session_privs WHERE privilege IN ('CREATE TABLE', 'CREATE PROCEDURE', 'CREATE VIEW', 'CREATE SEQUENCE')
    );

    IF v_priv_count >= 4 THEN
        DBMS_OUTPUT.PUT_LINE('SUCCESS: Required privileges detected.');
        :v_privs_ok := 1;
    ELSE
        DBMS_OUTPUT.PUT_LINE('ERROR: Missing required privileges. Need CREATE TABLE, PROCEDURE, VIEW, SEQUENCE.');
        :v_errors := :v_errors + 1;
        :v_privs_ok := 0;
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('ERROR: Unable to verify privileges: ' || SQLERRM);
        :v_errors := :v_errors + 1;
END;
/

-- Check Tablespace Quota
PROMPT
PROMPT [1.4] Checking Tablespace Quota...
DECLARE
    v_quota NUMBER;
BEGIN
    SELECT NVL(SUM(DECODE(max_bytes, -1, 104857600, max_bytes)), 0) / 1048576
    INTO v_quota
    FROM user_ts_quotas;

    :v_quota := v_quota;

    IF v_quota >= 100 OR v_quota = -1 THEN
        DBMS_OUTPUT.PUT_LINE('SUCCESS: Sufficient tablespace quota available (' ||
            CASE WHEN v_quota = -1 THEN 'UNLIMITED' ELSE TO_CHAR(ROUND(v_quota, 2)) || ' MB' END || ')');
    ELSE
        DBMS_OUTPUT.PUT_LINE('WARNING: Limited tablespace quota (' || ROUND(v_quota, 2) || ' MB). Recommended: 100+ MB');
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('WARNING: Unable to verify tablespace quota: ' || SQLERRM);
END;
/

-- Validation Summary
PROMPT
PROMPT ================================================================================
PROMPT Pre-Installation Validation Summary
PROMPT ================================================================================
PROMPT Database Version:    &v_db_version
PROMPT Current User:        &v_username
PROMPT Validation Errors:   &v_errors
PROMPT ================================================================================

-- Exit if validation failed
WHENEVER SQLERROR EXIT SQL.SQLCODE

BEGIN
    IF :v_errors > 0 THEN
        RAISE_APPLICATION_ERROR(-20001, 'Pre-installation validation failed. Please review errors above.');
    END IF;
    DBMS_OUTPUT.PUT_LINE('Pre-installation validation completed successfully.');
    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE('Progress: [####################] 10% Complete');
END;
/

WHENEVER SQLERROR CONTINUE

--------------------------------------------------------------------------------
-- SECTION 3: Core Schema Installation
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT STEP 2: Installing Core Schema Objects
PROMPT ================================================================================
PROMPT [2.1] Creating tables, sequences, and indexes...

@@01_schema.sql

PROMPT
PROMPT [2.2] Applying schema fixes and enhancements...
@@01a_schema_fixes.sql

WHENEVER SQLERROR EXIT FAILURE

-- Verify schema objects
DECLARE
    v_table_count NUMBER;
    v_seq_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_table_count
    FROM user_tables
    WHERE table_name IN ('HCC_COMPRESSION_STRATEGIES', 'HCC_ANALYSIS_HISTORY',
                         'HCC_SEGMENT_ANALYSIS', 'HCC_ADVISOR_CONFIG');

    SELECT COUNT(*) INTO v_seq_count
    FROM user_sequences
    WHERE sequence_name IN ('HCC_ANALYSIS_SEQ', 'HCC_SEGMENT_SEQ');

    DBMS_OUTPUT.PUT_LINE('Tables created: ' || v_table_count || '/4');
    DBMS_OUTPUT.PUT_LINE('Sequences created: ' || v_seq_count || '/2');

    IF v_table_count < 4 OR v_seq_count < 2 THEN
        RAISE_APPLICATION_ERROR(-20002, 'Schema object creation incomplete.');
    END IF;

    DBMS_OUTPUT.PUT_LINE('SUCCESS: Core schema objects created successfully.');
    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE('Progress: [########------------] 30% Complete');
END;
/

WHENEVER SQLERROR CONTINUE

--------------------------------------------------------------------------------
-- SECTION 4: Reference Data Installation
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT STEP 3: Loading Reference Data
PROMPT ================================================================================
PROMPT [3.1] Loading compression strategies...

@@02_strategies.sql

-- Verify strategies loaded
DECLARE
    v_strategy_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_strategy_count FROM HCC_COMPRESSION_STRATEGIES;

    DBMS_OUTPUT.PUT_LINE('Compression strategies loaded: ' || v_strategy_count);

    IF v_strategy_count = 0 THEN
        RAISE_APPLICATION_ERROR(-20003, 'No compression strategies loaded.');
    END IF;

    DBMS_OUTPUT.PUT_LINE('SUCCESS: Reference data loaded successfully.');
    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE('Progress: [##########----------] 40% Complete');
END;
/

COMMIT;

--------------------------------------------------------------------------------
-- SECTION 5: PL/SQL Package Installation
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT STEP 4: Installing PL/SQL Packages
PROMPT ================================================================================

PROMPT [4.1] Installing HCC_LOGGING_PKG package (foundation)...
@@02a_logging_pkg.sql

PROMPT
PROMPT [4.2] Installing HCC_EXADATA_PKG package (Exadata detection)...
@@02b_exadata_detection.sql

PROMPT
PROMPT [4.3] Installing HCC_ADVISOR_PKG package (main advisor)...
@@03_advisor_pkg.sql

PROMPT
PROMPT [4.4] Installing HCC_EXECUTOR_PKG package (compression execution)...
@@04_executor_pkg.sql

-- Verify packages compiled
WHENEVER SQLERROR EXIT FAILURE

DECLARE
    v_pkg_count NUMBER;
    v_invalid_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_pkg_count
    FROM user_objects
    WHERE object_type IN ('PACKAGE', 'PACKAGE BODY')
      AND object_name IN ('HCC_LOGGING_PKG', 'HCC_EXADATA_PKG', 'HCC_ADVISOR_PKG', 'HCC_EXECUTOR_PKG')
      AND status = 'VALID';

    SELECT COUNT(*) INTO v_invalid_count
    FROM user_objects
    WHERE object_type IN ('PACKAGE', 'PACKAGE BODY')
      AND object_name IN ('HCC_LOGGING_PKG', 'HCC_EXADATA_PKG', 'HCC_ADVISOR_PKG', 'HCC_EXECUTOR_PKG')
      AND status = 'INVALID';

    DBMS_OUTPUT.PUT_LINE('Valid packages: ' || v_pkg_count || '/8');
    DBMS_OUTPUT.PUT_LINE('Invalid objects: ' || v_invalid_count);

    IF v_invalid_count > 0 THEN
        RAISE_APPLICATION_ERROR(-20004, 'Package compilation failed. Check compilation errors.');
    END IF;

    DBMS_OUTPUT.PUT_LINE('SUCCESS: All packages compiled successfully.');
    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE('Progress: [##############------] 60% Complete');
END;
/

WHENEVER SQLERROR CONTINUE

--------------------------------------------------------------------------------
-- SECTION 6: Views Installation
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT STEP 5: Installing Views
PROMPT ================================================================================
PROMPT [5.1] Creating reporting and summary views...

@@05_views.sql

-- Verify views created
DECLARE
    v_view_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_view_count
    FROM user_views
    WHERE view_name LIKE 'HCC_%';

    DBMS_OUTPUT.PUT_LINE('Views created: ' || v_view_count);

    IF v_view_count = 0 THEN
        RAISE_APPLICATION_ERROR(-20005, 'No views created.');
    END IF;

    DBMS_OUTPUT.PUT_LINE('SUCCESS: Views created successfully.');
    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE('Progress: [################----] 70% Complete');
END;
/

--------------------------------------------------------------------------------
-- SECTION 7: ORDS REST API Installation
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT STEP 6: Installing ORDS REST API (Optional)
PROMPT ================================================================================
PROMPT [6.1] Installing REST API modules...
PROMPT NOTE: This step requires ORDS to be installed and configured.
PROMPT

BEGIN
    -- Check if ORDS is available
    DECLARE
        v_ords_installed NUMBER := 0;
    BEGIN
        SELECT COUNT(*) INTO v_ords_installed
        FROM all_objects
        WHERE object_name = 'ORDS' AND object_type = 'PACKAGE';

        IF v_ords_installed > 0 THEN
            DBMS_OUTPUT.PUT_LINE('ORDS detected. Installing REST API modules...');
        ELSE
            DBMS_OUTPUT.PUT_LINE('WARNING: ORDS not detected. Skipping REST API installation.');
            DBMS_OUTPUT.PUT_LINE('Run 06_ords.sql manually after installing ORDS.');
        END IF;
    END;
END;
/

-- Attempt ORDS installation (will skip if not available)
WHENEVER SQLERROR CONTINUE
@@06_ords.sql
WHENEVER SQLERROR CONTINUE

--------------------------------------------------------------------------------
-- SECTION 8: Post-Installation Tasks
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT STEP 7: Post-Installation Tasks
PROMPT ================================================================================

PROMPT [7.1] Recompiling invalid objects...
BEGIN
    DBMS_UTILITY.COMPILE_SCHEMA(
        schema => USER,
        compile_all => FALSE
    );
    DBMS_OUTPUT.PUT_LINE('Schema recompilation completed.');
END;
/

PROMPT
PROMPT [7.2] Gathering object statistics...
BEGIN
    FOR rec IN (SELECT table_name FROM user_tables WHERE table_name LIKE 'HCC_%') LOOP
        DBMS_STATS.GATHER_TABLE_STATS(
            ownname => USER,
            tabname => rec.table_name,
            estimate_percent => DBMS_STATS.AUTO_SAMPLE_SIZE,
            cascade => TRUE
        );
    END LOOP;
    DBMS_OUTPUT.PUT_LINE('Statistics gathered successfully.');
END;
/

PROMPT
PROMPT [7.3] Running installation validation...
@@validate_installation.sql

PROMPT
PROMPT Progress: [###################-] 90% Complete

--------------------------------------------------------------------------------
-- SECTION 9: Installation Summary
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT Installation Summary
PROMPT ================================================================================

-- Object counts
PROMPT
PROMPT Object Inventory:
PROMPT ----------------
SELECT object_type, COUNT(*) as count,
       SUM(CASE WHEN status = 'VALID' THEN 1 ELSE 0 END) as valid,
       SUM(CASE WHEN status = 'INVALID' THEN 1 ELSE 0 END) as invalid
FROM user_objects
WHERE object_name LIKE 'HCC_%'
GROUP BY object_type
ORDER BY object_type;

-- Invalid objects check
PROMPT
PROMPT Invalid Objects (if any):
PROMPT ------------------------
SELECT object_type, object_name, status
FROM user_objects
WHERE object_name LIKE 'HCC_%'
  AND status = 'INVALID'
ORDER BY object_type, object_name;

-- Final validation
DECLARE
    v_invalid_count NUMBER;
    v_total_objects NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_invalid_count
    FROM user_objects
    WHERE object_name LIKE 'HCC_%' AND status = 'INVALID';

    SELECT COUNT(*) INTO v_total_objects
    FROM user_objects
    WHERE object_name LIKE 'HCC_%';

    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE('================================================================================');
    DBMS_OUTPUT.PUT_LINE('Installation Status');
    DBMS_OUTPUT.PUT_LINE('================================================================================');
    DBMS_OUTPUT.PUT_LINE('Total objects created: ' || v_total_objects);
    DBMS_OUTPUT.PUT_LINE('Invalid objects:       ' || v_invalid_count);

    IF v_invalid_count > 0 THEN
        DBMS_OUTPUT.PUT_LINE('');
        DBMS_OUTPUT.PUT_LINE('WARNING: Installation completed with errors.');
        DBMS_OUTPUT.PUT_LINE('Please review invalid objects above and check install_full.log');
        DBMS_OUTPUT.PUT_LINE('');
        DBMS_OUTPUT.PUT_LINE('Progress: [####################] 100% Complete (WITH ERRORS)');
    ELSE
        DBMS_OUTPUT.PUT_LINE('');
        DBMS_OUTPUT.PUT_LINE('SUCCESS: Installation completed successfully!');
        DBMS_OUTPUT.PUT_LINE('');
        DBMS_OUTPUT.PUT_LINE('Progress: [####################] 100% Complete');
    END IF;
END;
/

PROMPT
PROMPT ================================================================================
PROMPT Next Steps
PROMPT ================================================================================
PROMPT
PROMPT 1. Review installation log: install_full.log
PROMPT
PROMPT 2. Test the installation:
PROMPT    SQL> SELECT HCC_ADVISOR_PKG.get_version FROM dual;
PROMPT
PROMPT 3. Analyze a table:
PROMPT    SQL> BEGIN
PROMPT           HCC_ADVISOR_PKG.analyze_table(
PROMPT               p_table_name => 'YOUR_TABLE_NAME'
PROMPT           );
PROMPT         END;
PROMPT         /
PROMPT
PROMPT 4. View recommendations:
PROMPT    SQL> SELECT * FROM HCC_COMPRESSION_RECOMMENDATIONS;
PROMPT
PROMPT 5. Access REST API (if ORDS installed):
PROMPT    https://your-ords-server/ords/schema/hcc/analyze
PROMPT
PROMPT 6. Review documentation:
PROMPT    - README.md for usage guide
PROMPT    - docs/API_REFERENCE.md for API documentation
PROMPT    - docs/TROUBLESHOOTING.md for common issues
PROMPT
PROMPT ================================================================================
PROMPT Rollback Instructions (If Installation Failed)
PROMPT ================================================================================
PROMPT
PROMPT If the installation failed or you need to remove the HCC Compression Advisor:
PROMPT
PROMPT 1. Run the uninstall script:
PROMPT    SQL> @uninstall.sql
PROMPT
PROMPT 2. Manual rollback (if uninstall script is unavailable):
PROMPT    SQL> DROP PACKAGE HCC_EXECUTOR_PKG;
PROMPT    SQL> DROP PACKAGE HCC_ADVISOR_PKG;
PROMPT    SQL> DROP PACKAGE HCC_EXADATA_PKG;
PROMPT    SQL> DROP PACKAGE HCC_LOGGING_PKG;
PROMPT    SQL> DROP VIEW HCC_COMPRESSION_RECOMMENDATIONS;
PROMPT    SQL> DROP VIEW HCC_SEGMENT_SUMMARY;
PROMPT    SQL> DROP TABLE HCC_SEGMENT_ANALYSIS CASCADE CONSTRAINTS;
PROMPT    SQL> DROP TABLE HCC_ANALYSIS_HISTORY CASCADE CONSTRAINTS;
PROMPT    SQL> DROP TABLE HCC_ADVISOR_CONFIG CASCADE CONSTRAINTS;
PROMPT    SQL> DROP TABLE HCC_COMPRESSION_STRATEGIES CASCADE CONSTRAINTS;
PROMPT    SQL> DROP SEQUENCE HCC_SEGMENT_SEQ;
PROMPT    SQL> DROP SEQUENCE HCC_ANALYSIS_SEQ;
PROMPT
PROMPT 3. Remove ORDS modules (if installed):
PROMPT    SQL> BEGIN
PROMPT           ORDS.DELETE_MODULE(p_module_name => 'hcc.advisor');
PROMPT           COMMIT;
PROMPT         END;
PROMPT         /
PROMPT
PROMPT 4. Verify cleanup:
PROMPT    SQL> SELECT object_type, object_name, status
PROMPT         FROM user_objects
PROMPT         WHERE object_name LIKE 'HCC_%';
PROMPT
PROMPT ================================================================================
PROMPT Installation Complete
PROMPT ================================================================================
PROMPT Installation Time: &_DATE
PROMPT Log File: install_full.log
PROMPT ================================================================================

SPOOL OFF
SET ECHO OFF
SET FEEDBACK OFF
SET TIMING OFF

-- Exit with appropriate code
WHENEVER SQLERROR EXIT SQL.SQLCODE
WHENEVER OSERROR EXIT FAILURE

EXIT SUCCESS
