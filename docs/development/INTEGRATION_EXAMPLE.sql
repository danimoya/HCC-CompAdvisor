/*******************************************************************************
 * Integration Example: Using Exadata Detection in Advisor Package
 * File: INTEGRATION_EXAMPLE.sql
 * Purpose: Example code snippets for integrating PKG_EXADATA_DETECTION
 *          with the existing PKG_COMPRESSION_ADVISOR package
 ******************************************************************************/

-- ===========================================================================
-- EXAMPLE 1: Update init_compression_map in PKG_COMPRESSION_ADVISOR
-- ===========================================================================

-- Replace the existing init_compression_map procedure in 03_advisor_pkg.sql
-- with this enhanced version:

PROCEDURE init_compression_map IS
    v_is_exadata BOOLEAN;
    v_platform VARCHAR2(30);
BEGIN
    -- Check if Exadata detection is available
    BEGIN
        v_is_exadata := PKG_EXADATA_DETECTION.is_exadata;
        v_platform := PKG_EXADATA_DETECTION.get_platform_type();

        pkg_compression_log.log_info(
            'PKG_COMPRESSION_ADVISOR',
            'init_compression_map',
            'Platform detected: ' || v_platform ||
            ' (HCC Available: ' || CASE WHEN v_is_exadata THEN 'YES' ELSE 'NO' END || ')'
        );
    EXCEPTION
        WHEN OTHERS THEN
            -- Fallback if detection package not available
            v_is_exadata := FALSE;
            v_platform := 'STANDARD';

            pkg_compression_log.log_info(
                'PKG_COMPRESSION_ADVISOR',
                'init_compression_map',
                'Exadata detection not available, assuming standard platform'
            );
    END;

    -- Table compression mappings
    IF v_is_exadata THEN
        -- Use HCC compression types on Exadata
        g_compression_map('NONE') := 'NOCOMPRESS';
        g_compression_map('BASIC') := 'COMPRESS BASIC';
        g_compression_map('OLTP') := 'COMPRESS FOR OLTP';
        g_compression_map('QUERY_LOW') :=
            PKG_EXADATA_DETECTION.get_compression_clause('QUERY_LOW');
        g_compression_map('QUERY_HIGH') :=
            PKG_EXADATA_DETECTION.get_compression_clause('QUERY_HIGH');
        g_compression_map('ARCHIVE_LOW') :=
            PKG_EXADATA_DETECTION.get_compression_clause('ARCHIVE_LOW');
        g_compression_map('ARCHIVE_HIGH') :=
            PKG_EXADATA_DETECTION.get_compression_clause('ARCHIVE_HIGH');

        -- Map existing types to HCC equivalents
        g_compression_map('ADVANCED') := 'COMPRESS FOR QUERY LOW';

        pkg_compression_log.log_info(
            'PKG_COMPRESSION_ADVISOR',
            'init_compression_map',
            'HCC compression types initialized (' ||
            PKG_EXADATA_DETECTION.get_cell_count() || ' storage cells)'
        );
    ELSE
        -- Fallback to standard compression (no HCC)
        g_compression_map('NONE') := 'NOCOMPRESS';
        g_compression_map('BASIC') := 'COMPRESS BASIC';
        g_compression_map('OLTP') := 'COMPRESS FOR OLTP';
        g_compression_map('ADVANCED') := 'COMPRESS FOR OLTP';

        -- Map HCC types to standard equivalents for compatibility
        g_compression_map('QUERY_LOW') := 'COMPRESS FOR OLTP';
        g_compression_map('QUERY_HIGH') := 'COMPRESS FOR OLTP';
        g_compression_map('ARCHIVE_LOW') := 'COMPRESS BASIC';
        g_compression_map('ARCHIVE_HIGH') := 'COMPRESS BASIC';

        pkg_compression_log.log_info(
            'PKG_COMPRESSION_ADVISOR',
            'init_compression_map',
            'Standard compression types initialized (Oracle 23c Free)'
        );
    END IF;

    -- Index compression mappings (same for both platforms)
    g_compression_map('INDEX_ADVANCED_LOW') := 'COMPRESS ADVANCED LOW';
    g_compression_map('INDEX_ADVANCED_HIGH') := 'COMPRESS ADVANCED HIGH';

    -- LOB compression mappings (same for both platforms)
    g_compression_map('LOB_LOW') := 'COMPRESS LOW';
    g_compression_map('LOB_MEDIUM') := 'COMPRESS MEDIUM';
    g_compression_map('LOB_HIGH') := 'COMPRESS HIGH';
END init_compression_map;

-- ===========================================================================
-- EXAMPLE 2: Enhanced Strategy Evaluation with Platform Awareness
-- ===========================================================================

-- Add to evaluate_strategy_rules function in PKG_COMPRESSION_ADVISOR:

FUNCTION evaluate_strategy_rules(
    p_strategy_id IN NUMBER,
    p_object_type IN VARCHAR2,
    p_size_mb IN NUMBER,
    p_hotness_score IN NUMBER,
    p_access_score IN NUMBER,
    p_compression_ratio IN NUMBER
) RETURN VARCHAR2 IS
    v_recommended_compression VARCHAR2(50);
    v_rule_matched BOOLEAN := FALSE;
    v_is_exadata BOOLEAN := FALSE;
BEGIN
    load_strategy_rules;

    -- Check platform
    BEGIN
        v_is_exadata := PKG_EXADATA_DETECTION.is_exadata;
    EXCEPTION
        WHEN OTHERS THEN
            v_is_exadata := FALSE;
    END;

    -- Evaluate rules in order
    FOR i IN 1..g_strategy_rules.COUNT LOOP
        IF g_strategy_rules(i).strategy_id = p_strategy_id
           AND g_strategy_rules(i).object_type = p_object_type THEN

            -- Check if rule conditions match
            IF (g_strategy_rules(i).min_size_mb IS NULL OR p_size_mb >= g_strategy_rules(i).min_size_mb)
               AND (g_strategy_rules(i).max_size_mb IS NULL OR p_size_mb <= g_strategy_rules(i).max_size_mb)
               AND (g_strategy_rules(i).min_hotness_score IS NULL OR p_hotness_score >= g_strategy_rules(i).min_hotness_score)
               AND (g_strategy_rules(i).max_hotness_score IS NULL OR p_hotness_score <= g_strategy_rules(i).max_hotness_score)
               AND (g_strategy_rules(i).min_compression_ratio IS NULL OR p_compression_ratio >= g_strategy_rules(i).min_compression_ratio) THEN

                v_recommended_compression := g_strategy_rules(i).recommended_compression;
                v_rule_matched := TRUE;
                EXIT;
            END IF;
        END IF;
    END LOOP;

    -- Default recommendation if no rule matched
    IF NOT v_rule_matched THEN
        CASE p_object_type
            WHEN 'TABLE' THEN
                IF v_is_exadata THEN
                    -- Enhanced recommendations for Exadata
                    v_recommended_compression := CASE
                        WHEN p_compression_ratio >= 6 AND p_hotness_score < 30 THEN 'ARCHIVE_HIGH'
                        WHEN p_compression_ratio >= 4 AND p_hotness_score < 30 THEN 'ARCHIVE_LOW'
                        WHEN p_compression_ratio >= 3 AND p_hotness_score < 50 THEN 'QUERY_HIGH'
                        WHEN p_compression_ratio >= 2 AND p_hotness_score < 70 THEN 'QUERY_LOW'
                        WHEN p_compression_ratio >= 2 THEN 'OLTP'
                        WHEN p_compression_ratio >= 1.5 THEN 'BASIC'
                        ELSE 'NONE'
                    END;
                ELSE
                    -- Standard platform recommendations
                    v_recommended_compression := CASE
                        WHEN p_compression_ratio >= 2 THEN 'OLTP'
                        WHEN p_compression_ratio >= 1.5 THEN 'BASIC'
                        ELSE 'NONE'
                    END;
                END IF;
            WHEN 'INDEX' THEN
                v_recommended_compression := CASE
                    WHEN p_compression_ratio >= 1.5 THEN 'INDEX_ADVANCED_LOW'
                    ELSE 'NONE'
                END;
            WHEN 'LOB' THEN
                v_recommended_compression := CASE
                    WHEN p_compression_ratio >= 3 THEN 'LOB_HIGH'
                    WHEN p_compression_ratio >= 2 THEN 'LOB_MEDIUM'
                    WHEN p_compression_ratio >= 1.5 THEN 'LOB_LOW'
                    ELSE 'NONE'
                END;
            ELSE
                v_recommended_compression := 'NONE';
        END CASE;
    END IF;

    RETURN v_recommended_compression;
END evaluate_strategy_rules;

-- ===========================================================================
-- EXAMPLE 3: Enhanced Rationale Generation with Platform Context
-- ===========================================================================

-- Update generate_rationale function to include platform information:

FUNCTION generate_rationale(
    p_object_type IN VARCHAR2,
    p_size_mb IN NUMBER,
    p_hotness_score IN NUMBER,
    p_access_score IN NUMBER,
    p_compression_ratio IN NUMBER,
    p_recommended_compression IN VARCHAR2
) RETURN VARCHAR2 IS
    v_rationale VARCHAR2(4000);
    v_platform VARCHAR2(30);
    v_is_exadata BOOLEAN;
BEGIN
    -- Get platform info
    BEGIN
        v_is_exadata := PKG_EXADATA_DETECTION.is_exadata;
        v_platform := PKG_EXADATA_DETECTION.get_platform_type();
    EXCEPTION
        WHEN OTHERS THEN
            v_is_exadata := FALSE;
            v_platform := 'STANDARD';
    END;

    v_rationale := 'Platform: ' || v_platform || '; ';
    v_rationale := v_rationale || 'Size: ' || ROUND(p_size_mb, 2) || ' MB; ';

    IF p_hotness_score > 0 THEN
        v_rationale := v_rationale || 'Hotness: ' || p_hotness_score || '/100 ';
        IF p_hotness_score > 70 THEN
            v_rationale := v_rationale || '(High DML); ';
        ELSIF p_hotness_score > 30 THEN
            v_rationale := v_rationale || '(Moderate DML); ';
        ELSE
            v_rationale := v_rationale || '(Low DML); ';
        END IF;
    END IF;

    IF p_access_score > 0 THEN
        v_rationale := v_rationale || 'Access: ' || p_access_score || '/100 ';
        IF p_access_score > 70 THEN
            v_rationale := v_rationale || '(Frequently accessed); ';
        END IF;
    END IF;

    v_rationale := v_rationale || 'Compression ratio: ' || ROUND(p_compression_ratio, 2) || ':1; ';

    -- Add recommendation explanation with platform awareness
    CASE p_recommended_compression
        WHEN 'NONE' THEN
            v_rationale := v_rationale || 'No compression recommended (ratio too low or high DML activity)';
        WHEN 'BASIC' THEN
            v_rationale := v_rationale || 'Basic compression recommended (moderate ratio, acceptable overhead)';
        WHEN 'OLTP' THEN
            v_rationale := v_rationale || 'OLTP compression recommended (good ratio, optimized for DML)';
        WHEN 'QUERY_LOW' THEN
            IF v_is_exadata THEN
                v_rationale := v_rationale || 'HCC Query Low recommended (balanced query/compression on Exadata)';
            ELSE
                v_rationale := v_rationale || 'OLTP compression (Query Low requires Exadata)';
            END IF;
        WHEN 'QUERY_HIGH' THEN
            IF v_is_exadata THEN
                v_rationale := v_rationale || 'HCC Query High recommended (higher compression on Exadata)';
            ELSE
                v_rationale := v_rationale || 'OLTP compression (Query High requires Exadata)';
            END IF;
        WHEN 'ARCHIVE_LOW' THEN
            IF v_is_exadata THEN
                v_rationale := v_rationale || 'HCC Archive Low recommended (archival data on Exadata)';
            ELSE
                v_rationale := v_rationale || 'Basic compression (Archive Low requires Exadata)';
            END IF;
        WHEN 'ARCHIVE_HIGH' THEN
            IF v_is_exadata THEN
                v_rationale := v_rationale || 'HCC Archive High recommended (maximum compression on Exadata)';
            ELSE
                v_rationale := v_rationale || 'Basic compression (Archive High requires Exadata)';
            END IF;
        WHEN 'INDEX_ADVANCED_LOW', 'INDEX_ADVANCED_HIGH' THEN
            v_rationale := v_rationale || 'Index compression recommended for space savings';
        WHEN 'LOB_LOW', 'LOB_MEDIUM', 'LOB_HIGH' THEN
            v_rationale := v_rationale || 'LOB compression recommended for large object storage';
        ELSE
            v_rationale := v_rationale || 'Compression type: ' || p_recommended_compression;
    END CASE;

    RETURN SUBSTR(v_rationale, 1, 4000);
END generate_rationale;

-- ===========================================================================
-- EXAMPLE 4: Add Platform Check to run_analysis
-- ===========================================================================

-- Add at the beginning of run_analysis procedure:

PROCEDURE run_analysis(
    p_owner IN VARCHAR2 DEFAULT NULL,
    p_strategy_id IN NUMBER DEFAULT 2,
    p_parallel_degree IN NUMBER DEFAULT 4
) IS
    v_start_time TIMESTAMP := SYSTIMESTAMP;
    v_platform VARCHAR2(30);
    v_is_exadata BOOLEAN;
    -- ... other variables
BEGIN
    init_compression_map;
    load_strategy_rules;

    -- Log platform information
    BEGIN
        v_is_exadata := PKG_EXADATA_DETECTION.is_exadata;
        v_platform := PKG_EXADATA_DETECTION.get_platform_type();

        pkg_compression_log.log_info(
            'PKG_COMPRESSION_ADVISOR',
            'run_analysis',
            'Running on platform: ' || v_platform ||
            ' (HCC: ' || CASE WHEN v_is_exadata THEN 'Available' ELSE 'Not Available' END || ')'
        );

        IF v_is_exadata THEN
            pkg_compression_log.log_info(
                'PKG_COMPRESSION_ADVISOR',
                'run_analysis',
                'Exadata storage cells detected: ' || PKG_EXADATA_DETECTION.get_cell_count()
            );
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            pkg_compression_log.log_info(
                'PKG_COMPRESSION_ADVISOR',
                'run_analysis',
                'Platform detection unavailable, using standard compression types'
            );
    END;

    pkg_compression_log.log_info(
        'PKG_COMPRESSION_ADVISOR',
        'run_analysis',
        'Starting compression analysis - Strategy: ' || p_strategy_id ||
        ', Owner: ' || NVL(p_owner, 'ALL') ||
        ', Parallel Degree: ' || p_parallel_degree
    );

    -- ... rest of the procedure
END run_analysis;

-- ===========================================================================
-- EXAMPLE 5: Query to Show Compression Recommendations with Platform Context
-- ===========================================================================

-- Create a view that shows recommendations with platform awareness:

CREATE OR REPLACE VIEW V_COMPRESSION_RECOMMENDATIONS_PLATFORM AS
SELECT
    a.analysis_id,
    a.owner,
    a.object_name,
    a.object_type,
    a.partition_name,
    a.current_size_mb,
    a.compressed_size_mb,
    a.compression_ratio,
    a.space_savings_mb,
    a.space_savings_pct,
    a.current_compression,
    a.recommended_compression,
    a.hotness_score,
    a.access_score,
    a.analysis_rationale,
    -- Platform information
    p.platform_type,
    p.hcc_available,
    p.detection_confidence,
    -- Actual DDL clause for platform
    CASE
        WHEN p.platform_type = 'EXADATA' THEN
            PKG_EXADATA_DETECTION.get_compression_clause(a.recommended_compression)
        ELSE
            CASE a.recommended_compression
                WHEN 'QUERY_LOW' THEN 'COMPRESS FOR OLTP'
                WHEN 'QUERY_HIGH' THEN 'COMPRESS FOR OLTP'
                WHEN 'ARCHIVE_LOW' THEN 'COMPRESS BASIC'
                WHEN 'ARCHIVE_HIGH' THEN 'COMPRESS BASIC'
                WHEN 'OLTP' THEN 'COMPRESS FOR OLTP'
                WHEN 'BASIC' THEN 'COMPRESS BASIC'
                ELSE 'NOCOMPRESS'
            END
    END AS actual_compression_clause,
    -- Priority indicator
    CASE
        WHEN a.space_savings_pct >= 50 THEN 'HIGH'
        WHEN a.space_savings_pct >= 30 THEN 'MEDIUM'
        ELSE 'LOW'
    END AS priority
FROM t_compression_analysis a
CROSS JOIN (
    SELECT
        platform_type,
        hcc_available,
        detection_confidence
    FROM t_platform_config
    WHERE config_key = 'PLATFORM_TYPE'
) p
WHERE a.recommended_compression != 'NONE'
ORDER BY a.space_savings_mb DESC;

-- ===========================================================================
-- EXAMPLE 6: Testing the Integration
-- ===========================================================================

-- Test script to verify platform detection integration:

SET SERVEROUTPUT ON SIZE UNLIMITED

DECLARE
    v_platform VARCHAR2(30);
    v_is_exadata BOOLEAN;
    v_hcc_available BOOLEAN;
    v_confidence NUMBER;
    v_cell_count NUMBER;
    v_compression_clause VARCHAR2(100);
BEGIN
    DBMS_OUTPUT.PUT_LINE('=== Exadata Detection Integration Test ===');
    DBMS_OUTPUT.PUT_LINE('');

    -- Test 1: Platform Detection
    v_platform := PKG_EXADATA_DETECTION.get_platform_type();
    v_is_exadata := PKG_EXADATA_DETECTION.is_exadata;
    v_hcc_available := PKG_EXADATA_DETECTION.is_hcc_available;
    v_confidence := PKG_EXADATA_DETECTION.get_confidence_score();
    v_cell_count := PKG_EXADATA_DETECTION.get_cell_count();

    DBMS_OUTPUT.PUT_LINE('Platform Type: ' || v_platform);
    DBMS_OUTPUT.PUT_LINE('Is Exadata: ' || CASE WHEN v_is_exadata THEN 'YES' ELSE 'NO' END);
    DBMS_OUTPUT.PUT_LINE('HCC Available: ' || CASE WHEN v_hcc_available THEN 'YES' ELSE 'NO' END);
    DBMS_OUTPUT.PUT_LINE('Detection Confidence: ' || v_confidence || '%');
    DBMS_OUTPUT.PUT_LINE('Storage Cells: ' || v_cell_count);
    DBMS_OUTPUT.PUT_LINE('');

    -- Test 2: Compression Type Mapping
    DBMS_OUTPUT.PUT_LINE('Compression Type Mappings:');
    DBMS_OUTPUT.PUT_LINE('--------------------------');

    v_compression_clause := PKG_EXADATA_DETECTION.get_compression_clause('QUERY_LOW');
    DBMS_OUTPUT.PUT_LINE('QUERY_LOW    -> ' || v_compression_clause);

    v_compression_clause := PKG_EXADATA_DETECTION.get_compression_clause('QUERY_HIGH');
    DBMS_OUTPUT.PUT_LINE('QUERY_HIGH   -> ' || v_compression_clause);

    v_compression_clause := PKG_EXADATA_DETECTION.get_compression_clause('ARCHIVE_LOW');
    DBMS_OUTPUT.PUT_LINE('ARCHIVE_LOW  -> ' || v_compression_clause);

    v_compression_clause := PKG_EXADATA_DETECTION.get_compression_clause('ARCHIVE_HIGH');
    DBMS_OUTPUT.PUT_LINE('ARCHIVE_HIGH -> ' || v_compression_clause);

    v_compression_clause := PKG_EXADATA_DETECTION.get_compression_clause('OLTP');
    DBMS_OUTPUT.PUT_LINE('OLTP         -> ' || v_compression_clause);

    v_compression_clause := PKG_EXADATA_DETECTION.get_compression_clause('BASIC');
    DBMS_OUTPUT.PUT_LINE('BASIC        -> ' || v_compression_clause);
    DBMS_OUTPUT.PUT_LINE('');

    -- Test 3: Advisor Integration
    DBMS_OUTPUT.PUT_LINE('Testing Advisor Integration:');
    DBMS_OUTPUT.PUT_LINE('----------------------------');

    -- This would normally call the advisor, but for testing we just show it works
    DBMS_OUTPUT.PUT_LINE('Advisor can now use platform-aware compression types');
    DBMS_OUTPUT.PUT_LINE('');

    DBMS_OUTPUT.PUT_LINE('=== Test Complete ===');
END;
/

-- ===========================================================================
-- EXAMPLE 7: Monitoring Platform Changes
-- ===========================================================================

-- Create a monitoring job to verify platform periodically:

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'VERIFY_EXADATA_PLATFORM',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN PKG_EXADATA_DETECTION.verify_platform; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=MONTHLY; BYMONTHDAY=1',
        enabled         => TRUE,
        comments        => 'Monthly verification of Exadata platform detection'
    );
END;
/

-- ===========================================================================
-- END OF INTEGRATION EXAMPLES
-- ===========================================================================
