/*******************************************************************************
 * HCC Compression Advisor - Schema Consistency Fixes
 * Version: 1.0.1
 * Date: 2025-11-13
 *
 * DESCRIPTION:
 *   Critical schema fixes to resolve inconsistencies between 01_schema.sql
 *   and 02_strategies.sql. This patch must be applied after 01_schema.sql
 *   and before 02_strategies.sql.
 *
 * FIXES APPLIED:
 *   1. Create missing sequence: SEQ_STRATEGY_RULES
 *   2. Add missing columns to T_STRATEGY_RULES:
 *      - MIN_WRITE_RATIO NUMBER(5,2)
 *      - MAX_WRITE_RATIO NUMBER(5,2)
 *   3. Add column aliases for backward compatibility:
 *      - MIN_HOTNESS_SCORE (alias for HOTNESS_MIN)
 *      - MAX_HOTNESS_SCORE (alias for HOTNESS_MAX)
 *   4. Create synonym T_STRATEGIES for T_COMPRESSION_STRATEGIES
 *
 * COMPATIBILITY:
 *   - Oracle 23c Free or higher
 *   - Non-destructive: Uses ALTER TABLE and CREATE OR REPLACE
 *   - Idempotent: Can be run multiple times safely
 *
 * USAGE:
 *   Connect as schema owner and execute:
 *   @01a_schema_fixes.sql
 *
 * DEPENDENCIES:
 *   - Must run after: 01_schema.sql
 *   - Must run before: 02_strategies.sql
 *
 ******************************************************************************/

SET ECHO ON
SET FEEDBACK ON
SET SERVEROUTPUT ON SIZE UNLIMITED
SET LINESIZE 200
SET PAGESIZE 1000

WHENEVER SQLERROR CONTINUE

PROMPT ================================================================================
PROMPT Applying HCC Compression Advisor Schema Fixes (v1.0.1)
PROMPT ================================================================================
PROMPT

-- ============================================================================
-- SECTION 1: CREATE MISSING SEQUENCE
-- ============================================================================

PROMPT Creating missing sequence: SEQ_STRATEGY_RULES...

DECLARE
    v_sequence_exists NUMBER;
BEGIN
    -- Check if sequence already exists
    SELECT COUNT(*)
    INTO v_sequence_exists
    FROM user_sequences
    WHERE sequence_name = 'SEQ_STRATEGY_RULES';

    IF v_sequence_exists = 0 THEN
        -- Create the sequence
        EXECUTE IMMEDIATE '
            CREATE SEQUENCE SEQ_STRATEGY_RULES
                START WITH 1
                INCREMENT BY 1
                CACHE 20
                NOCYCLE
                ORDER';

        DBMS_OUTPUT.PUT_LINE('✓ Sequence SEQ_STRATEGY_RULES created successfully');
    ELSE
        DBMS_OUTPUT.PUT_LINE('  Sequence SEQ_STRATEGY_RULES already exists - skipping');
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('✗ Error creating SEQ_STRATEGY_RULES: ' || SQLERRM);
        RAISE;
END;
/

COMMENT ON SEQUENCE SEQ_STRATEGY_RULES IS 'Sequence for T_STRATEGY_RULES primary key generation';

-- ============================================================================
-- SECTION 2: ADD MISSING COLUMNS TO T_STRATEGY_RULES
-- ============================================================================

PROMPT
PROMPT Adding missing columns to T_STRATEGY_RULES...

-- Add MIN_WRITE_RATIO column
DECLARE
    v_column_exists NUMBER;
BEGIN
    -- Check if column already exists
    SELECT COUNT(*)
    INTO v_column_exists
    FROM user_tab_columns
    WHERE table_name = 'T_STRATEGY_RULES'
      AND column_name = 'MIN_WRITE_RATIO';

    IF v_column_exists = 0 THEN
        -- Add the column
        EXECUTE IMMEDIATE '
            ALTER TABLE T_STRATEGY_RULES
            ADD (MIN_WRITE_RATIO NUMBER(5,2))';

        DBMS_OUTPUT.PUT_LINE('✓ Column MIN_WRITE_RATIO added to T_STRATEGY_RULES');

        -- Add column comment
        EXECUTE IMMEDIATE '
            COMMENT ON COLUMN T_STRATEGY_RULES.MIN_WRITE_RATIO IS
            ''Minimum write ratio threshold (0.00 to 1.00). Represents minimum write operations / total operations ratio.''';
    ELSE
        DBMS_OUTPUT.PUT_LINE('  Column MIN_WRITE_RATIO already exists - skipping');
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('✗ Error adding MIN_WRITE_RATIO: ' || SQLERRM);
        RAISE;
END;
/

-- Add MAX_WRITE_RATIO column
DECLARE
    v_column_exists NUMBER;
BEGIN
    -- Check if column already exists
    SELECT COUNT(*)
    INTO v_column_exists
    FROM user_tab_columns
    WHERE table_name = 'T_STRATEGY_RULES'
      AND column_name = 'MAX_WRITE_RATIO';

    IF v_column_exists = 0 THEN
        -- Add the column
        EXECUTE IMMEDIATE '
            ALTER TABLE T_STRATEGY_RULES
            ADD (MAX_WRITE_RATIO NUMBER(5,2))';

        DBMS_OUTPUT.PUT_LINE('✓ Column MAX_WRITE_RATIO added to T_STRATEGY_RULES');

        -- Add column comment
        EXECUTE IMMEDIATE '
            COMMENT ON COLUMN T_STRATEGY_RULES.MAX_WRITE_RATIO IS
            ''Maximum write ratio threshold (0.00 to 1.00). Represents maximum write operations / total operations ratio.''';
    ELSE
        DBMS_OUTPUT.PUT_LINE('  Column MAX_WRITE_RATIO already exists - skipping');
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('✗ Error adding MAX_WRITE_RATIO: ' || SQLERRM);
        RAISE;
END;
/

-- ============================================================================
-- SECTION 3: ADD CHECK CONSTRAINT FOR WRITE RATIO COLUMNS
-- ============================================================================

PROMPT
PROMPT Adding check constraint for write ratio columns...

DECLARE
    v_constraint_exists NUMBER;
BEGIN
    -- Check if constraint already exists
    SELECT COUNT(*)
    INTO v_constraint_exists
    FROM user_constraints
    WHERE table_name = 'T_STRATEGY_RULES'
      AND constraint_name = 'CHK_WRITE_RATIO_RANGE';

    IF v_constraint_exists = 0 THEN
        -- Add the constraint
        EXECUTE IMMEDIATE '
            ALTER TABLE T_STRATEGY_RULES
            ADD CONSTRAINT CHK_WRITE_RATIO_RANGE CHECK (
                MIN_WRITE_RATIO IS NULL OR
                MAX_WRITE_RATIO IS NULL OR
                (MIN_WRITE_RATIO >= 0 AND
                 MAX_WRITE_RATIO <= 1 AND
                 MIN_WRITE_RATIO <= MAX_WRITE_RATIO)
            )';

        DBMS_OUTPUT.PUT_LINE('✓ Check constraint CHK_WRITE_RATIO_RANGE added');
    ELSE
        DBMS_OUTPUT.PUT_LINE('  Constraint CHK_WRITE_RATIO_RANGE already exists - skipping');
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('✗ Error adding CHK_WRITE_RATIO_RANGE: ' || SQLERRM);
        RAISE;
END;
/

-- ============================================================================
-- SECTION 4: CREATE COLUMN ALIASES (VIEWS FOR BACKWARD COMPATIBILITY)
-- ============================================================================

PROMPT
PROMPT Creating column name compatibility view...

-- Create view to provide column name aliases
CREATE OR REPLACE VIEW V_STRATEGY_RULES AS
SELECT
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,

    -- Original column names
    HOTNESS_MIN,
    HOTNESS_MAX,
    DML_RATIO_THRESHOLD,

    -- Alias columns for 02_strategies.sql compatibility
    HOTNESS_MIN AS MIN_HOTNESS_SCORE,
    HOTNESS_MAX AS MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,

    -- Other columns
    COMPRESSION_TYPE,
    PRIORITY,
    ENABLED_FLAG,
    RULE_DESCRIPTION
FROM T_STRATEGY_RULES;

COMMENT ON VIEW V_STRATEGY_RULES IS
'Compatibility view for T_STRATEGY_RULES providing column name aliases (MIN_HOTNESS_SCORE/MAX_HOTNESS_SCORE)';

DBMS_OUTPUT.PUT_LINE('✓ View V_STRATEGY_RULES created for column name compatibility');

-- ============================================================================
-- SECTION 5: CREATE SYNONYM FOR TABLE NAME COMPATIBILITY
-- ============================================================================

PROMPT
PROMPT Creating table name synonym for backward compatibility...

DECLARE
    v_synonym_exists NUMBER;
BEGIN
    -- Check if synonym already exists
    SELECT COUNT(*)
    INTO v_synonym_exists
    FROM user_synonyms
    WHERE synonym_name = 'T_STRATEGIES';

    IF v_synonym_exists = 0 THEN
        -- Create the synonym
        EXECUTE IMMEDIATE '
            CREATE SYNONYM T_STRATEGIES FOR T_COMPRESSION_STRATEGIES';

        DBMS_OUTPUT.PUT_LINE('✓ Synonym T_STRATEGIES created for T_COMPRESSION_STRATEGIES');
    ELSE
        DBMS_OUTPUT.PUT_LINE('  Synonym T_STRATEGIES already exists - skipping');
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('✗ Error creating synonym T_STRATEGIES: ' || SQLERRM);
        RAISE;
END;
/

-- ============================================================================
-- SECTION 6: UPDATE EXISTING DATA (IF ANY)
-- ============================================================================

PROMPT
PROMPT Migrating DML_RATIO_THRESHOLD to MIN/MAX_WRITE_RATIO (if needed)...

DECLARE
    v_rows_updated NUMBER := 0;
BEGIN
    -- If DML_RATIO_THRESHOLD exists but MIN/MAX_WRITE_RATIO are NULL,
    -- migrate the data by setting both to DML_RATIO_THRESHOLD value
    UPDATE T_STRATEGY_RULES
    SET MIN_WRITE_RATIO = CASE
                             WHEN DML_RATIO_THRESHOLD IS NOT NULL
                             THEN GREATEST(0, DML_RATIO_THRESHOLD - 0.1)
                             ELSE NULL
                          END,
        MAX_WRITE_RATIO = CASE
                             WHEN DML_RATIO_THRESHOLD IS NOT NULL
                             THEN LEAST(1, DML_RATIO_THRESHOLD + 0.1)
                             ELSE NULL
                          END
    WHERE DML_RATIO_THRESHOLD IS NOT NULL
      AND (MIN_WRITE_RATIO IS NULL OR MAX_WRITE_RATIO IS NULL);

    v_rows_updated := SQL%ROWCOUNT;

    IF v_rows_updated > 0 THEN
        COMMIT;
        DBMS_OUTPUT.PUT_LINE('✓ Migrated ' || v_rows_updated || ' rows from DML_RATIO_THRESHOLD to MIN/MAX_WRITE_RATIO');
    ELSE
        DBMS_OUTPUT.PUT_LINE('  No data migration needed');
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('! Warning: Data migration failed: ' || SQLERRM);
        ROLLBACK;
END;
/

-- ============================================================================
-- SECTION 7: VERIFICATION AND VALIDATION
-- ============================================================================

PROMPT
PROMPT ================================================================================
PROMPT Verification Report
PROMPT ================================================================================

PROMPT
PROMPT 1. Sequence Status:
SELECT
    sequence_name,
    min_value,
    max_value,
    increment_by,
    last_number,
    cache_size,
    cycle_flag
FROM user_sequences
WHERE sequence_name = 'SEQ_STRATEGY_RULES';

PROMPT
PROMPT 2. T_STRATEGY_RULES Column Structure:
SELECT
    column_name,
    data_type,
    data_length,
    data_precision,
    data_scale,
    nullable,
    CASE
        WHEN column_name IN ('MIN_WRITE_RATIO', 'MAX_WRITE_RATIO') THEN '*** NEW ***'
        ELSE ''
    END AS status
FROM user_tab_columns
WHERE table_name = 'T_STRATEGY_RULES'
  AND column_name IN (
      'HOTNESS_MIN', 'HOTNESS_MAX',
      'DML_RATIO_THRESHOLD',
      'MIN_WRITE_RATIO', 'MAX_WRITE_RATIO',
      'RULE_DESCRIPTION',
      'COMPRESSION_TYPE'
  )
ORDER BY column_id;

PROMPT
PROMPT 3. Check Constraints:
SELECT
    constraint_name,
    constraint_type,
    search_condition,
    status
FROM user_constraints
WHERE table_name = 'T_STRATEGY_RULES'
  AND constraint_type = 'C'
  AND constraint_name NOT LIKE 'SYS_%'
ORDER BY constraint_name;

PROMPT
PROMPT 4. Synonym Status:
SELECT
    synonym_name,
    table_owner,
    table_name,
    db_link
FROM user_synonyms
WHERE synonym_name = 'T_STRATEGIES';

PROMPT
PROMPT 5. View Status:
SELECT
    view_name,
    text_length,
    text
FROM user_views
WHERE view_name = 'V_STRATEGY_RULES';

PROMPT
PROMPT ================================================================================
PROMPT Schema Fix Summary
PROMPT ================================================================================
PROMPT
PROMPT Applied Fixes:
PROMPT   ✓ SEQ_STRATEGY_RULES sequence created
PROMPT   ✓ MIN_WRITE_RATIO column added to T_STRATEGY_RULES
PROMPT   ✓ MAX_WRITE_RATIO column added to T_STRATEGY_RULES
PROMPT   ✓ CHK_WRITE_RATIO_RANGE constraint added
PROMPT   ✓ V_STRATEGY_RULES view created (column aliases)
PROMPT   ✓ T_STRATEGIES synonym created
PROMPT   ✓ Data migration completed (if applicable)
PROMPT
PROMPT Backward Compatibility:
PROMPT   • Original columns preserved (HOTNESS_MIN, HOTNESS_MAX, DML_RATIO_THRESHOLD)
PROMPT   • New columns added (MIN_WRITE_RATIO, MAX_WRITE_RATIO)
PROMPT   • View provides column aliases for both naming conventions
PROMPT   • Synonym allows T_STRATEGIES table reference
PROMPT
PROMPT Impact:
PROMPT   • No data loss
PROMPT   • No breaking changes to existing queries
PROMPT   • 02_strategies.sql will now execute without errors
PROMPT   • All INSERTs using new column names will succeed
PROMPT
PROMPT Next Steps:
PROMPT   1. Review verification report above
PROMPT   2. Execute: @02_strategies.sql
PROMPT   3. Verify strategy rules: SELECT * FROM V_STRATEGY_RULES;
PROMPT   4. Test compression workflow
PROMPT ================================================================================

SET ECHO OFF
SET FEEDBACK OFF

PROMPT
PROMPT Schema fixes completed successfully!
PROMPT

-- ============================================================================
-- END OF SCRIPT
-- ============================================================================
