-- ============================================================================
-- Script: 01-create-user.sql
-- Description: Create dedicated user for HCC Compression Advisor
-- Author: Daniel Moya (copyright), GitHub: github.com/danimoya Website: danielmoya.cv
-- Database: Oracle 23c Free Edition
-- ============================================================================

WHENEVER SQLERROR EXIT SQL.SQLCODE
SET ECHO ON
SET SERVEROUTPUT ON SIZE UNLIMITED

-- Connect to PDB (Pluggable Database)
ALTER SESSION SET CONTAINER = FREEPDB1;

PROMPT ========================================
PROMPT Creating Compression Manager User
PROMPT ========================================

-- Drop user if exists (for re-installation)
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

-- Create dedicated user for compression advisor
CREATE USER COMPRESSION_MGR IDENTIFIED BY "Compress123"
    DEFAULT TABLESPACE USERS
    TEMPORARY TABLESPACE TEMP
    QUOTA UNLIMITED ON USERS
    ACCOUNT UNLOCK
    PASSWORD EXPIRE;

PROMPT User COMPRESSION_MGR created successfully

-- Verify user creation
SELECT username, account_status, default_tablespace, temporary_tablespace
FROM dba_users
WHERE username = 'COMPRESSION_MGR';

PROMPT ========================================
PROMPT User Creation Complete
PROMPT ========================================

EXIT;
