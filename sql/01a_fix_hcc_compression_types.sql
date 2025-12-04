-- ===========================================================================
-- Migration Script: Add HCC Compression Types to Check Constraints
-- File: 01a_fix_hcc_compression_types.sql
-- Description: Updates check constraints to support HCC compression types
-- Version: 1.0.0
-- Date: 2025-12-04
-- ===========================================================================

SET ECHO ON
SET FEEDBACK ON
SET SERVEROUTPUT ON SIZE UNLIMITED

PROMPT ================================================================================
PROMPT Updating Compression Type Check Constraints for HCC Support
PROMPT ================================================================================

-- Drop existing constraints
PROMPT Dropping existing check constraints...

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE T_STRATEGY_RULES DROP CONSTRAINT CHK_RULE_COMPRESSION_TYPE';
  DBMS_OUTPUT.PUT_LINE('✓ Dropped CHK_RULE_COMPRESSION_TYPE');
EXCEPTION
  WHEN OTHERS THEN
    DBMS_OUTPUT.PUT_LINE('! CHK_RULE_COMPRESSION_TYPE - ' || SQLERRM);
END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE T_COMPRESSION_HISTORY DROP CONSTRAINT CHK_HISTORY_COMPRESSION_TYPE';
  DBMS_OUTPUT.PUT_LINE('✓ Dropped CHK_HISTORY_COMPRESSION_TYPE');
EXCEPTION
  WHEN OTHERS THEN
    DBMS_OUTPUT.PUT_LINE('! CHK_HISTORY_COMPRESSION_TYPE - ' || SQLERRM);
END;
/

PROMPT Adding updated check constraints with HCC compression types...
/

-- Add updated constraints with HCC types
ALTER TABLE T_STRATEGY_RULES ADD CONSTRAINT CHK_RULE_COMPRESSION_TYPE CHECK (
    COMPRESSION_TYPE IN ('NONE', 'BASIC', 'OLTP', 'ADV_LOW', 'ADV_HIGH', 'QUERY LOW', 'QUERY HIGH', 'ARCHIVE LOW', 'ARCHIVE HIGH')
);

ALTER TABLE T_COMPRESSION_HISTORY ADD CONSTRAINT CHK_HISTORY_COMPRESSION_TYPE CHECK (
    COMPRESSION_TYPE_APPLIED IN ('NONE', 'BASIC', 'OLTP', 'ADV_LOW', 'ADV_HIGH',
                                  'QUERY LOW', 'QUERY HIGH', 'ARCHIVE LOW', 'ARCHIVE HIGH',
                                  'PREFIX', 'ADVANCED_LOW', 'ADVANCED_HIGH',
                                  'LOW', 'MEDIUM', 'HIGH')
);

PROMPT
PROMPT ================================================================================
PROMPT Constraint Migration Complete!
PROMPT ================================================================================
PROMPT Updated constraints now support:
PROMPT   - NONE (No compression for LOBs)
PROMPT   - BASIC, OLTP (Standard compression)
PROMPT   - ADV_LOW, ADV_HIGH (Advanced compression)
PROMPT   - QUERY LOW, QUERY HIGH (HCC - Exadata)
PROMPT   - ARCHIVE LOW, ARCHIVE HIGH (HCC - Exadata)
PROMPT
PROMPT Verification:
PROMPT

SELECT
    CONSTRAINT_NAME,
    SEARCH_CONDITION
FROM USER_CONSTRAINTS
WHERE TABLE_NAME IN ('T_STRATEGY_RULES', 'T_COMPRESSION_HISTORY')
  AND CONSTRAINT_NAME IN ('CHK_RULE_COMPRESSION_TYPE', 'CHK_HISTORY_COMPRESSION_TYPE')
ORDER BY TABLE_NAME, CONSTRAINT_NAME;

PROMPT
SET ECHO OFF
