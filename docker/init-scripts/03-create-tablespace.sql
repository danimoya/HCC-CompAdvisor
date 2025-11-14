-- ============================================================================
-- Script: 03-create-tablespace.sql
-- Description: Create SCRATCH tablespace for compression analysis
-- Author: Daniel Moya (copyright), GitHub: github.com/danimoya Website: danielmoya.cv
-- Database: Oracle 23c Free Edition
-- ============================================================================

WHENEVER SQLERROR EXIT SQL.SQLCODE
SET ECHO ON
SET SERVEROUTPUT ON SIZE UNLIMITED

-- Connect to PDB
ALTER SESSION SET CONTAINER = FREEPDB1;

PROMPT ========================================
PROMPT Creating SCRATCH Tablespace
PROMPT ========================================

-- Drop tablespace if exists (for re-installation)
DECLARE
    v_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM dba_tablespaces
    WHERE tablespace_name = 'SCRATCH_TS';

    IF v_count > 0 THEN
        EXECUTE IMMEDIATE 'DROP TABLESPACE SCRATCH_TS INCLUDING CONTENTS AND DATAFILES CASCADE CONSTRAINTS';
        DBMS_OUTPUT.PUT_LINE('Existing SCRATCH_TS tablespace dropped');
    END IF;
END;
/

-- Create SCRATCH tablespace for compression analysis
-- This tablespace will be used for temporary tables during compression testing
CREATE TABLESPACE SCRATCH_TS
    DATAFILE '/opt/oracle/oradata/FREE/FREEPDB1/scratch01.dbf'
    SIZE 1G
    AUTOEXTEND ON
    NEXT 256M
    MAXSIZE 10G
    EXTENT MANAGEMENT LOCAL
    UNIFORM SIZE 1M
    SEGMENT SPACE MANAGEMENT AUTO
    ONLINE;

PROMPT SCRATCH_TS tablespace created successfully

-- Grant quota on SCRATCH tablespace to COMPRESSION_MGR
ALTER USER COMPRESSION_MGR QUOTA UNLIMITED ON SCRATCH_TS;

PROMPT Quota granted to COMPRESSION_MGR

-- Verify tablespace creation
SELECT
    tablespace_name,
    block_size,
    status,
    contents,
    extent_management,
    allocation_type,
    segment_space_management
FROM dba_tablespaces
WHERE tablespace_name = 'SCRATCH_TS';

-- Verify datafile
SELECT
    file_name,
    tablespace_name,
    bytes/1024/1024 AS size_mb,
    maxbytes/1024/1024 AS max_size_mb,
    autoextensible,
    status
FROM dba_data_files
WHERE tablespace_name = 'SCRATCH_TS';

-- Verify user quota
SELECT
    username,
    tablespace_name,
    bytes/1024/1024 AS used_mb,
    max_bytes/1024/1024 AS quota_mb
FROM dba_ts_quotas
WHERE username = 'COMPRESSION_MGR'
AND tablespace_name = 'SCRATCH_TS';

PROMPT ========================================
PROMPT Tablespace Creation Complete
PROMPT ========================================

-- Additional configuration for optimal compression testing
ALTER TABLESPACE SCRATCH_TS ADD DATAFILE
    '/opt/oracle/oradata/FREE/FREEPDB1/scratch02.dbf'
    SIZE 512M
    AUTOEXTEND ON
    NEXT 128M
    MAXSIZE 5G;

PROMPT Additional datafile added to SCRATCH_TS

-- Create directory for external tables and export operations
CREATE OR REPLACE DIRECTORY COMPRESSION_DIR AS '/opt/oracle/compression_advisor';
GRANT READ, WRITE ON DIRECTORY COMPRESSION_DIR TO COMPRESSION_MGR;

PROMPT Directory created and privileges granted

-- Set tablespace group for parallel operations
ALTER TABLESPACE SCRATCH_TS TABLESPACE GROUP compression_group;

PROMPT Tablespace group configured

EXIT;
