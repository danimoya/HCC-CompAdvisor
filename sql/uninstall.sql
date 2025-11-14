--------------------------------------------------------------------------------
-- HCC Compression Advisor - Uninstallation Script
--------------------------------------------------------------------------------
-- Description: Removes all HCC Compression Advisor objects
-- Version:     1.0.0
-- Author:      Daniel Moya (copyright), GitHub: github.com/danimoya Website: danielmoya.cv
--
-- WARNING:     This script will DROP all HCC Compression Advisor objects
--              including tables, packages, views, and sequences.
--              ALL DATA WILL BE LOST!
--
-- Usage:
--   SQL> @uninstall.sql
--
-- Notes:
--   - Requires schema owner privileges
--   - User confirmation required before execution
--   - Review uninstall.log for detailed results
--   - Backup data before running if needed
--------------------------------------------------------------------------------

--------------------------------------------------------------------------------
-- SECTION 1: Environment Setup
--------------------------------------------------------------------------------

SET ECHO ON
SET FEEDBACK ON
SET HEADING ON
SET LINESIZE 200
SET PAGESIZE 1000
SET SERVEROUTPUT ON SIZE UNLIMITED
SET VERIFY OFF
SET TRIMSPOOL ON
SET TRIMOUT ON
SET TIMING ON

SPOOL uninstall.log

PROMPT ================================================================================
PROMPT HCC Compression Advisor - Uninstallation
PROMPT ================================================================================
PROMPT WARNING: This will remove ALL HCC Compression Advisor objects!
PROMPT WARNING: All analysis data and history will be PERMANENTLY DELETED!
PROMPT ================================================================================
PROMPT Uninstall Time: &_DATE
PROMPT Database: &_CONNECT_IDENTIFIER
PROMPT User: &_USER
PROMPT ================================================================================

--------------------------------------------------------------------------------
-- SECTION 2: Pre-Uninstall Inventory
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT Current Object Inventory (Before Uninstall)
PROMPT ================================================================================

SELECT object_type, COUNT(*) as count
FROM user_objects
WHERE object_name LIKE 'HCC_%'
GROUP BY object_type
ORDER BY object_type;

PROMPT
PROMPT Data Inventory:
PROMPT ----------------

DECLARE
    v_analysis_count NUMBER;
    v_segment_count NUMBER;
    v_strategy_count NUMBER;
BEGIN
    -- Count existing data
    BEGIN
        SELECT COUNT(*) INTO v_analysis_count FROM HCC_ANALYSIS_HISTORY;
        DBMS_OUTPUT.PUT_LINE('Analysis history records: ' || v_analysis_count);
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('Analysis history table not found or not accessible');
    END;

    BEGIN
        SELECT COUNT(*) INTO v_segment_count FROM HCC_SEGMENT_ANALYSIS;
        DBMS_OUTPUT.PUT_LINE('Segment analysis records: ' || v_segment_count);
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('Segment analysis table not found or not accessible');
    END;

    BEGIN
        SELECT COUNT(*) INTO v_strategy_count FROM HCC_COMPRESSION_STRATEGIES;
        DBMS_OUTPUT.PUT_LINE('Compression strategies:   ' || v_strategy_count);
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('Compression strategies table not found or not accessible');
    END;
END;
/

--------------------------------------------------------------------------------
-- SECTION 3: User Confirmation
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT CONFIRMATION REQUIRED
PROMPT ================================================================================
PROMPT
PROMPT This operation will permanently delete:
PROMPT   - All analysis history and recommendations
PROMPT   - All segment analysis data
PROMPT   - All configuration settings
PROMPT   - All PL/SQL packages and views
PROMPT   - All ORDS REST API modules
PROMPT
PROMPT THIS CANNOT BE UNDONE!
PROMPT
PROMPT If you have important data, press Ctrl+C NOW to cancel
PROMPT and export data before proceeding.
PROMPT
PROMPT ================================================================================

ACCEPT v_confirm CHAR PROMPT 'Type YES (in uppercase) to confirm uninstallation: '

-- Validate confirmation
DECLARE
    v_user_input VARCHAR2(10) := '&v_confirm';
BEGIN
    IF v_user_input != 'YES' THEN
        RAISE_APPLICATION_ERROR(-20001, 'Uninstallation cancelled by user.');
    END IF;
    DBMS_OUTPUT.PUT_LINE('User confirmation received. Proceeding with uninstallation...');
END;
/

PROMPT
PROMPT ================================================================================
PROMPT Starting Uninstallation Process
PROMPT ================================================================================

--------------------------------------------------------------------------------
-- SECTION 4: Drop ORDS Modules
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT STEP 1: Removing ORDS REST API Modules
PROMPT ================================================================================

DECLARE
    v_ords_installed NUMBER := 0;
    v_module_count NUMBER := 0;
BEGIN
    -- Check if ORDS is available
    SELECT COUNT(*) INTO v_ords_installed
    FROM all_objects
    WHERE object_name = 'ORDS' AND object_type = 'PACKAGE';

    IF v_ords_installed > 0 THEN
        DBMS_OUTPUT.PUT_LINE('[1.1] ORDS detected. Removing REST modules...');

        -- Drop HCC Advisor module
        BEGIN
            ORDS.DELETE_MODULE(p_module_name => 'hcc.advisor');
            DBMS_OUTPUT.PUT_LINE('SUCCESS: ORDS module "hcc.advisor" removed.');
        EXCEPTION
            WHEN OTHERS THEN
                IF SQLCODE = -20987 THEN
                    DBMS_OUTPUT.PUT_LINE('INFO: ORDS module "hcc.advisor" not found.');
                ELSE
                    DBMS_OUTPUT.PUT_LINE('WARNING: Error removing ORDS module: ' || SQLERRM);
                END IF;
        END;

        COMMIT;
    ELSE
        DBMS_OUTPUT.PUT_LINE('[1.1] ORDS not detected. Skipping REST API cleanup.');
    END IF;
END;
/

--------------------------------------------------------------------------------
-- SECTION 5: Drop Views
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT STEP 2: Dropping Views
PROMPT ================================================================================
PROMPT [2.1] Dropping reporting and summary views...

DECLARE
    TYPE view_array IS TABLE OF VARCHAR2(128);
    v_views view_array;
    v_sql VARCHAR2(500);
BEGIN
    -- Get all HCC views
    SELECT view_name
    BULK COLLECT INTO v_views
    FROM user_views
    WHERE view_name LIKE 'HCC_%'
    ORDER BY view_name;

    IF v_views.COUNT > 0 THEN
        FOR i IN 1..v_views.COUNT LOOP
            v_sql := 'DROP VIEW ' || v_views(i);
            BEGIN
                EXECUTE IMMEDIATE v_sql;
                DBMS_OUTPUT.PUT_LINE('Dropped view: ' || v_views(i));
            EXCEPTION
                WHEN OTHERS THEN
                    DBMS_OUTPUT.PUT_LINE('ERROR dropping view ' || v_views(i) || ': ' || SQLERRM);
            END;
        END LOOP;
        DBMS_OUTPUT.PUT_LINE('SUCCESS: ' || v_views.COUNT || ' views dropped.');
    ELSE
        DBMS_OUTPUT.PUT_LINE('INFO: No HCC views found to drop.');
    END IF;
END;
/

--------------------------------------------------------------------------------
-- SECTION 6: Drop Packages
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT STEP 3: Dropping PL/SQL Packages
PROMPT ================================================================================
PROMPT [3.1] Dropping package bodies...

DECLARE
    TYPE package_array IS TABLE OF VARCHAR2(128);
    v_packages package_array;
    v_sql VARCHAR2(500);
BEGIN
    -- Drop package bodies first
    SELECT object_name
    BULK COLLECT INTO v_packages
    FROM user_objects
    WHERE object_type = 'PACKAGE BODY'
      AND object_name LIKE 'HCC_%'
    ORDER BY object_name;

    IF v_packages.COUNT > 0 THEN
        FOR i IN 1..v_packages.COUNT LOOP
            v_sql := 'DROP PACKAGE BODY ' || v_packages(i);
            BEGIN
                EXECUTE IMMEDIATE v_sql;
                DBMS_OUTPUT.PUT_LINE('Dropped package body: ' || v_packages(i));
            EXCEPTION
                WHEN OTHERS THEN
                    DBMS_OUTPUT.PUT_LINE('ERROR dropping package body ' || v_packages(i) || ': ' || SQLERRM);
            END;
        END LOOP;
    END IF;
END;
/

PROMPT [3.2] Dropping package specifications...

DECLARE
    TYPE package_array IS TABLE OF VARCHAR2(128);
    v_packages package_array;
    v_sql VARCHAR2(500);
BEGIN
    -- Drop package specifications
    SELECT object_name
    BULK COLLECT INTO v_packages
    FROM user_objects
    WHERE object_type = 'PACKAGE'
      AND object_name LIKE 'HCC_%'
    ORDER BY object_name;

    IF v_packages.COUNT > 0 THEN
        FOR i IN 1..v_packages.COUNT LOOP
            v_sql := 'DROP PACKAGE ' || v_packages(i);
            BEGIN
                EXECUTE IMMEDIATE v_sql;
                DBMS_OUTPUT.PUT_LINE('Dropped package: ' || v_packages(i));
            EXCEPTION
                WHEN OTHERS THEN
                    DBMS_OUTPUT.PUT_LINE('ERROR dropping package ' || v_packages(i) || ': ' || SQLERRM);
            END;
        END LOOP;
        DBMS_OUTPUT.PUT_LINE('SUCCESS: ' || v_packages.COUNT || ' packages dropped.');
    ELSE
        DBMS_OUTPUT.PUT_LINE('INFO: No HCC packages found to drop.');
    END IF;
END;
/

--------------------------------------------------------------------------------
-- SECTION 7: Drop Tables
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT STEP 4: Dropping Tables
PROMPT ================================================================================
PROMPT [4.1] Dropping tables with CASCADE CONSTRAINTS...

DECLARE
    TYPE table_array IS TABLE OF VARCHAR2(128);
    v_tables table_array;
    v_sql VARCHAR2(500);
BEGIN
    -- Get all HCC tables in reverse dependency order
    SELECT table_name
    BULK COLLECT INTO v_tables
    FROM user_tables
    WHERE table_name LIKE 'HCC_%'
    ORDER BY
        CASE table_name
            WHEN 'HCC_SEGMENT_ANALYSIS' THEN 1
            WHEN 'HCC_ANALYSIS_HISTORY' THEN 2
            WHEN 'HCC_ADVISOR_CONFIG' THEN 3
            WHEN 'HCC_COMPRESSION_STRATEGIES' THEN 4
            ELSE 5
        END;

    IF v_tables.COUNT > 0 THEN
        FOR i IN 1..v_tables.COUNT LOOP
            v_sql := 'DROP TABLE ' || v_tables(i) || ' CASCADE CONSTRAINTS PURGE';
            BEGIN
                EXECUTE IMMEDIATE v_sql;
                DBMS_OUTPUT.PUT_LINE('Dropped table: ' || v_tables(i));
            EXCEPTION
                WHEN OTHERS THEN
                    DBMS_OUTPUT.PUT_LINE('ERROR dropping table ' || v_tables(i) || ': ' || SQLERRM);
            END;
        END LOOP;
        DBMS_OUTPUT.PUT_LINE('SUCCESS: ' || v_tables.COUNT || ' tables dropped.');
    ELSE
        DBMS_OUTPUT.PUT_LINE('INFO: No HCC tables found to drop.');
    END IF;
END;
/

--------------------------------------------------------------------------------
-- SECTION 8: Drop Sequences
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT STEP 5: Dropping Sequences
PROMPT ================================================================================
PROMPT [5.1] Dropping sequences...

DECLARE
    TYPE sequence_array IS TABLE OF VARCHAR2(128);
    v_sequences sequence_array;
    v_sql VARCHAR2(500);
BEGIN
    -- Get all HCC sequences
    SELECT sequence_name
    BULK COLLECT INTO v_sequences
    FROM user_sequences
    WHERE sequence_name LIKE 'HCC_%'
    ORDER BY sequence_name;

    IF v_sequences.COUNT > 0 THEN
        FOR i IN 1..v_sequences.COUNT LOOP
            v_sql := 'DROP SEQUENCE ' || v_sequences(i);
            BEGIN
                EXECUTE IMMEDIATE v_sql;
                DBMS_OUTPUT.PUT_LINE('Dropped sequence: ' || v_sequences(i));
            EXCEPTION
                WHEN OTHERS THEN
                    DBMS_OUTPUT.PUT_LINE('ERROR dropping sequence ' || v_sequences(i) || ': ' || SQLERRM);
            END;
        END LOOP;
        DBMS_OUTPUT.PUT_LINE('SUCCESS: ' || v_sequences.COUNT || ' sequences dropped.');
    ELSE
        DBMS_OUTPUT.PUT_LINE('INFO: No HCC sequences found to drop.');
    END IF;
END;
/

--------------------------------------------------------------------------------
-- SECTION 9: Cleanup Recyclebin
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT STEP 6: Cleaning Up Recyclebin
PROMPT ================================================================================
PROMPT [6.1] Purging recyclebin...

BEGIN
    EXECUTE IMMEDIATE 'PURGE RECYCLEBIN';
    DBMS_OUTPUT.PUT_LINE('SUCCESS: Recyclebin purged.');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('WARNING: Error purging recyclebin: ' || SQLERRM);
END;
/

--------------------------------------------------------------------------------
-- SECTION 10: Drop Any Remaining Objects
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT STEP 7: Checking for Remaining Objects
PROMPT ================================================================================

DECLARE
    v_remaining_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_remaining_count
    FROM user_objects
    WHERE object_name LIKE 'HCC_%';

    IF v_remaining_count > 0 THEN
        DBMS_OUTPUT.PUT_LINE('WARNING: ' || v_remaining_count || ' HCC objects still exist:');

        FOR rec IN (SELECT object_type, object_name, status
                    FROM user_objects
                    WHERE object_name LIKE 'HCC_%'
                    ORDER BY object_type, object_name) LOOP
            DBMS_OUTPUT.PUT_LINE('  - ' || rec.object_type || ': ' || rec.object_name || ' (' || rec.status || ')');
        END LOOP;

        DBMS_OUTPUT.PUT_LINE('');
        DBMS_OUTPUT.PUT_LINE('Manual cleanup may be required for these objects.');
    ELSE
        DBMS_OUTPUT.PUT_LINE('SUCCESS: All HCC objects have been removed.');
    END IF;
END;
/

--------------------------------------------------------------------------------
-- SECTION 11: Uninstall Summary
--------------------------------------------------------------------------------

PROMPT
PROMPT ================================================================================
PROMPT Uninstallation Summary
PROMPT ================================================================================

PROMPT
PROMPT Final Object Count:
PROMPT -------------------

SELECT object_type, COUNT(*) as remaining_count
FROM user_objects
WHERE object_name LIKE 'HCC_%'
GROUP BY object_type
ORDER BY object_type;

DECLARE
    v_total_remaining NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_total_remaining
    FROM user_objects
    WHERE object_name LIKE 'HCC_%';

    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE('================================================================================');
    DBMS_OUTPUT.PUT_LINE('Uninstallation Status');
    DBMS_OUTPUT.PUT_LINE('================================================================================');
    DBMS_OUTPUT.PUT_LINE('Remaining HCC objects: ' || v_total_remaining);

    IF v_total_remaining = 0 THEN
        DBMS_OUTPUT.PUT_LINE('');
        DBMS_OUTPUT.PUT_LINE('SUCCESS: HCC Compression Advisor uninstalled successfully!');
        DBMS_OUTPUT.PUT_LINE('');
        DBMS_OUTPUT.PUT_LINE('All objects have been removed from the database.');
    ELSE
        DBMS_OUTPUT.PUT_LINE('');
        DBMS_OUTPUT.PUT_LINE('WARNING: Uninstallation completed with remaining objects.');
        DBMS_OUTPUT.PUT_LINE('Please review the object list above and remove manually if needed.');
    END IF;
END;
/

PROMPT
PROMPT ================================================================================
PROMPT Post-Uninstall Notes
PROMPT ================================================================================
PROMPT
PROMPT 1. Review uninstall log: uninstall.log
PROMPT
PROMPT 2. Verify no HCC objects remain:
PROMPT    SQL> SELECT object_type, object_name
PROMPT         FROM user_objects
PROMPT         WHERE object_name LIKE 'HCC_%';
PROMPT
PROMPT 3. If reinstalling:
PROMPT    SQL> @install_full.sql
PROMPT
PROMPT 4. To restore from backup (if available):
PROMPT    - Restore schema backup
PROMPT    - Import data using Data Pump
PROMPT    - Recompile invalid objects
PROMPT
PROMPT ================================================================================
PROMPT Uninstallation Complete
PROMPT ================================================================================
PROMPT Uninstall Time: &_DATE
PROMPT Log File: uninstall.log
PROMPT ================================================================================

SPOOL OFF
SET ECHO OFF
SET FEEDBACK OFF
SET TIMING OFF

EXIT SUCCESS
