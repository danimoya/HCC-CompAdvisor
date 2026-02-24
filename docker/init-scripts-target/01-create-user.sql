-- ============================================================================
-- Script: 01-create-user.sql
-- Description: Create user for HCC Compression Advisor Target Test DB
-- Database: Oracle 23c Free Edition (Target Test Database)
-- ============================================================================

WHENEVER SQLERROR EXIT SQL.SQLCODE
SET ECHO ON
SET SERVEROUTPUT ON SIZE UNLIMITED

ALTER SESSION SET CONTAINER = FREEPDB1;

PROMPT ========================================
PROMPT Creating Compression Manager User
PROMPT (Target Test Database)
PROMPT ========================================

DECLARE
    v_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_count FROM dba_users WHERE username = 'COMPRESSION_MGR';
    IF v_count > 0 THEN
        EXECUTE IMMEDIATE 'DROP USER COMPRESSION_MGR CASCADE';
        DBMS_OUTPUT.PUT_LINE('Existing COMPRESSION_MGR user dropped');
    END IF;
END;
/

CREATE USER COMPRESSION_MGR IDENTIFIED BY "Compress123"
    DEFAULT TABLESPACE USERS
    TEMPORARY TABLESPACE TEMP
    QUOTA UNLIMITED ON USERS
    ACCOUNT UNLOCK;

PROMPT User COMPRESSION_MGR created successfully

EXIT;
