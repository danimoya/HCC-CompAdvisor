-- ============================================================================
-- Script: 02-grant-privileges.sql
-- Description: Grant REDUCED privileges to COMPRESSION_MGR user (Central DB)
-- Author: Daniel Moya (copyright), GitHub: github.com/danimoya Website: danimoya.com
-- Database: Oracle 23c Free Edition (Central Metadata Server)
--
-- NOTE: This is the CENTRAL database that stores metadata and results.
-- Privileges are REDUCED compared to the target DB version because:
--   - No target schema introspection (no DBA_TABLES, DBA_TAB_COLUMNS, DBA_SEGMENTS)
--   - No compression analysis (no DBMS_COMPRESSION)
--   - No target operations (no SELECT ANY TABLE, ALTER ANY TABLE, ANALYZE ANY)
-- ============================================================================

WHENEVER SQLERROR EXIT SQL.SQLCODE
SET ECHO ON
SET SERVEROUTPUT ON SIZE UNLIMITED

-- Connect to PDB
ALTER SESSION SET CONTAINER = FREEPDB1;

PROMPT ========================================
PROMPT Granting Privileges to COMPRESSION_MGR
PROMPT (Central DB - Reduced Privilege Set)
PROMPT ========================================

-- Basic connection and resource privileges
GRANT CREATE SESSION TO COMPRESSION_MGR;
GRANT RESOURCE TO COMPRESSION_MGR;
GRANT CONNECT TO COMPRESSION_MGR;

PROMPT Basic privileges granted

-- Object creation privileges
GRANT CREATE TABLE TO COMPRESSION_MGR;
GRANT CREATE VIEW TO COMPRESSION_MGR;
GRANT CREATE PROCEDURE TO COMPRESSION_MGR;
GRANT CREATE SEQUENCE TO COMPRESSION_MGR;
GRANT CREATE TRIGGER TO COMPRESSION_MGR;
GRANT CREATE TYPE TO COMPRESSION_MGR;

PROMPT Object creation privileges granted

-- V$ views for health checks and monitoring
GRANT SELECT ON V_$DATABASE TO COMPRESSION_MGR;
GRANT SELECT ON V_$INSTANCE TO COMPRESSION_MGR;
GRANT SELECT ON V_$VERSION TO COMPRESSION_MGR;

PROMPT V$ health check views granted

-- DBMS packages required for central operations
GRANT EXECUTE ON DBMS_STATS TO COMPRESSION_MGR;
GRANT EXECUTE ON DBMS_OUTPUT TO COMPRESSION_MGR;

PROMPT DBMS package privileges granted

-- Create synonyms for easier access
CREATE OR REPLACE SYNONYM COMPRESSION_MGR.DBMS_STATS FOR SYS.DBMS_STATS;

PROMPT Synonyms created

-- Verify privileges
PROMPT Verifying privileges...
SELECT grantee, privilege, admin_option
FROM dba_sys_privs
WHERE grantee = 'COMPRESSION_MGR'
ORDER BY privilege;

PROMPT ========================================
PROMPT Privilege Grant Complete (Central DB)
PROMPT ========================================

EXIT;
