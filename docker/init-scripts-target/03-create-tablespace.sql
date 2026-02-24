-- ============================================================================
-- Script: 03-create-tablespace.sql
-- Description: Create tablespace for target test data (~1GB)
-- Database: Oracle 23c Free Edition (Target Test Database)
-- ============================================================================

WHENEVER SQLERROR EXIT SQL.SQLCODE
SET ECHO ON
SET SERVEROUTPUT ON SIZE UNLIMITED

ALTER SESSION SET CONTAINER = FREEPDB1;

PROMPT ========================================
PROMPT Creating TEST_DATA Tablespace
PROMPT (Target DB - 2GB max for test data)
PROMPT ========================================

DECLARE
    v_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM dba_tablespaces
    WHERE tablespace_name = 'TEST_DATA_TS';
    IF v_count > 0 THEN
        EXECUTE IMMEDIATE 'DROP TABLESPACE TEST_DATA_TS INCLUDING CONTENTS AND DATAFILES CASCADE CONSTRAINTS';
        DBMS_OUTPUT.PUT_LINE('Existing TEST_DATA_TS tablespace dropped');
    END IF;
END;
/

CREATE TABLESPACE TEST_DATA_TS
    DATAFILE '/opt/oracle/oradata/FREE/FREEPDB1/testdata01.dbf'
    SIZE 512M
    AUTOEXTEND ON
    NEXT 256M
    MAXSIZE 3G
    EXTENT MANAGEMENT LOCAL
    UNIFORM SIZE 1M
    SEGMENT SPACE MANAGEMENT AUTO
    ONLINE;

ALTER USER COMPRESSION_MGR QUOTA UNLIMITED ON TEST_DATA_TS;

PROMPT TEST_DATA_TS tablespace created

EXIT;
