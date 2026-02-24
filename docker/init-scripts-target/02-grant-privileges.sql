-- ============================================================================
-- Script: 02-grant-privileges.sql
-- Description: Grant FULL privileges to COMPRESSION_MGR (Target DB)
-- Database: Oracle 23c Free Edition (Target Test Database)
--
-- NOTE: This is a TARGET database where compression analysis is performed.
-- Requires broader privileges than the central DB:
--   - DBMS_COMPRESSION for analysis
--   - DBA views for schema introspection
--   - ALTER TABLE for applying compression
-- ============================================================================

WHENEVER SQLERROR EXIT SQL.SQLCODE
SET ECHO ON
SET SERVEROUTPUT ON SIZE UNLIMITED

ALTER SESSION SET CONTAINER = FREEPDB1;

PROMPT ========================================
PROMPT Granting Privileges to COMPRESSION_MGR
PROMPT (Target DB - Full Privilege Set)
PROMPT ========================================

-- Basic connection
GRANT CREATE SESSION TO COMPRESSION_MGR;
GRANT RESOURCE TO COMPRESSION_MGR;
GRANT CONNECT TO COMPRESSION_MGR;

-- Object creation
GRANT CREATE TABLE TO COMPRESSION_MGR;
GRANT CREATE VIEW TO COMPRESSION_MGR;
GRANT CREATE PROCEDURE TO COMPRESSION_MGR;
GRANT CREATE SEQUENCE TO COMPRESSION_MGR;
GRANT CREATE TRIGGER TO COMPRESSION_MGR;
GRANT CREATE TYPE TO COMPRESSION_MGR;

-- Target-specific: schema introspection
GRANT SELECT ANY DICTIONARY TO COMPRESSION_MGR;
GRANT SELECT ANY TABLE TO COMPRESSION_MGR;
GRANT ANALYZE ANY TO COMPRESSION_MGR;

-- Target-specific: compression operations
GRANT EXECUTE ON DBMS_COMPRESSION TO COMPRESSION_MGR;
GRANT EXECUTE ON DBMS_STATS TO COMPRESSION_MGR;
GRANT EXECUTE ON DBMS_OUTPUT TO COMPRESSION_MGR;
GRANT ALTER ANY TABLE TO COMPRESSION_MGR;

-- V$ views
GRANT SELECT ON V_$DATABASE TO COMPRESSION_MGR;
GRANT SELECT ON V_$INSTANCE TO COMPRESSION_MGR;
GRANT SELECT ON V_$VERSION TO COMPRESSION_MGR;
GRANT SELECT ON V_$SEGMENT_STATISTICS TO COMPRESSION_MGR;
GRANT SELECT ON V_$SESSION TO COMPRESSION_MGR;

PROMPT All target privileges granted

-- Verify
SELECT grantee, privilege
FROM dba_sys_privs
WHERE grantee = 'COMPRESSION_MGR'
ORDER BY privilege;

PROMPT ========================================
PROMPT Privilege Grant Complete (Target DB)
PROMPT ========================================

EXIT;
