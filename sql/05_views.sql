-- ============================================================================
-- HCC Compression Advisor - Reporting Views
-- ============================================================================
-- Purpose: Comprehensive views for analyzing compression recommendations,
--          monitoring execution status, and tracking space savings
-- Author: Daniel Moya (copyright), GitHub: github.com/danimoya Website: danielmoya.cv
-- Version: 1.0.0
-- ============================================================================

PROMPT Creating Compression Advisor Reporting Views...

-- ============================================================================
-- View: V_COMPRESSION_CANDIDATES
-- Purpose: All objects with compression recommendations, ordered by potential savings
-- ============================================================================
CREATE OR REPLACE VIEW v_compression_candidates AS
SELECT
    r.owner,
    r.object_name,
    r.object_type,
    ROUND(r.current_size_mb, 2) AS current_size_mb,
    ROUND(r.potential_savings_mb, 2) AS potential_savings_mb,
    ROUND(r.savings_pct, 1) AS savings_pct,
    r.hotness_score,
    r.advisable_compression,
    r.rationale,
    r.current_compression,
    r.io_pattern,
    r.last_analyzed,
    r.recommendation_id,
    a.strategy_name,
    a.analysis_date
FROM
    hcc_recommendations r
    JOIN hcc_analysis_runs a ON r.run_id = a.run_id
WHERE
    r.advisable_compression IS NOT NULL
    AND r.advisable_compression != 'NONE'
    AND r.potential_savings_mb > 0
ORDER BY
    r.potential_savings_mb DESC,
    r.savings_pct DESC;

COMMENT ON TABLE v_compression_candidates IS 'All objects with actionable compression recommendations, prioritized by potential space savings';
-- ============================================================================
-- View: V_COMPRESSION_SUMMARY
-- Purpose: Aggregate statistics by owner and object type
-- ============================================================================
CREATE OR REPLACE VIEW v_compression_summary AS
SELECT
    r.owner,
    r.object_type,
    COUNT(*) AS total_objects_analyzed,
    COUNT(CASE WHEN r.advisable_compression IS NOT NULL
               AND r.advisable_compression != 'NONE'
               THEN 1 END) AS compression_candidates,
    ROUND(SUM(r.current_size_mb), 2) AS total_current_size_mb,
    ROUND(SUM(r.potential_savings_mb), 2) AS total_potential_savings_mb,
    ROUND(AVG(r.savings_pct), 1) AS avg_savings_pct,
    ROUND(AVG(CASE WHEN r.advisable_compression IS NOT NULL
                   AND r.advisable_compression != 'NONE'
                   THEN r.hotness_score END), 1) AS avg_hotness_score,
    COUNT(CASE WHEN r.advisable_compression = 'HCC_QUERY_HIGH' THEN 1 END) AS hcc_query_high_count,
    COUNT(CASE WHEN r.advisable_compression = 'HCC_QUERY_LOW' THEN 1 END) AS hcc_query_low_count,
    COUNT(CASE WHEN r.advisable_compression = 'HCC_ARCHIVE_HIGH' THEN 1 END) AS hcc_archive_high_count,
    COUNT(CASE WHEN r.advisable_compression = 'HCC_ARCHIVE_LOW' THEN 1 END) AS hcc_archive_low_count,
    COUNT(CASE WHEN r.advisable_compression = 'BASIC' THEN 1 END) AS basic_compression_count,
    COUNT(CASE WHEN r.advisable_compression = 'OLTP' THEN 1 END) AS oltp_compression_count,
    COUNT(CASE WHEN r.advisable_compression = 'NONE' THEN 1 END) AS no_compression_count,
    MAX(a.analysis_date) AS last_analysis_date
FROM
    hcc_recommendations r
    JOIN hcc_analysis_runs a ON r.run_id = a.run_id
GROUP BY
    r.owner,
    r.object_type
ORDER BY
    total_potential_savings_mb DESC;

COMMENT ON TABLE v_compression_summary IS 'Aggregated compression statistics by owner and object type';
-- ============================================================================
-- View: V_COMPRESSION_HISTORY
-- Purpose: Complete execution history of compression operations
-- ============================================================================
CREATE OR REPLACE VIEW v_compression_history AS
SELECT
    h.execution_id,
    h.start_time,
    h.end_time,
    ROUND((h.end_time - h.start_time) * 24 * 60, 2) AS execution_time_minutes,
    h.owner,
    h.object_name,
    h.object_type,
    h.compression_type,
    ROUND(h.original_size_mb, 2) AS original_size_mb,
    ROUND(h.compressed_size_mb, 2) AS compressed_size_mb,
    ROUND(h.space_saved_mb, 2) AS space_saved_mb,
    ROUND(h.compression_ratio, 2) AS compression_ratio,
    h.status,
    h.error_message,
    h.ddl_statement,
    CASE
        WHEN h.status = 'COMPLETED' THEN 'SUCCESS'
        WHEN h.status = 'FAILED' THEN 'FAILED'
        WHEN h.status = 'IN_PROGRESS' THEN 'RUNNING'
        ELSE 'PENDING'
    END AS execution_status
FROM
    hcc_execution_history h
ORDER BY
    h.start_time DESC;

COMMENT ON TABLE v_compression_history IS 'Historical record of all compression execution operations';
-- ============================================================================
-- View: V_HOT_OBJECTS
-- Purpose: Write-intensive objects requiring OLTP or no compression
-- ============================================================================
CREATE OR REPLACE VIEW v_hot_objects AS
SELECT
    r.owner,
    r.object_name,
    r.object_type,
    ROUND(r.current_size_mb, 2) AS current_size_mb,
    r.hotness_score,
    r.current_compression,
    r.advisable_compression,
    r.io_pattern,
    r.rationale,
    s.num_rows,
    s.avg_row_len,
    s.blocks,
    s.last_analyzed
FROM
    hcc_recommendations r
    LEFT JOIN dba_tables s ON r.owner = s.owner
                           AND r.object_name = s.table_name
                           AND r.object_type = 'TABLE'
WHERE
    r.hotness_score >= 70
    AND r.advisable_compression IN ('OLTP', 'NONE')
ORDER BY
    r.hotness_score DESC,
    r.current_size_mb DESC;

COMMENT ON TABLE v_hot_objects IS 'Write-intensive objects with high hotness scores requiring OLTP or no compression';
-- ============================================================================
-- View: V_COLD_OBJECTS
-- Purpose: Rarely accessed objects ideal for aggressive compression
-- ============================================================================
CREATE OR REPLACE VIEW v_cold_objects AS
SELECT
    r.owner,
    r.object_name,
    r.object_type,
    ROUND(r.current_size_mb, 2) AS current_size_mb,
    ROUND(r.potential_savings_mb, 2) AS potential_savings_mb,
    ROUND(r.savings_pct, 1) AS savings_pct,
    r.hotness_score,
    r.current_compression,
    r.advisable_compression,
    r.io_pattern,
    r.rationale,
    s.num_rows,
    s.last_analyzed,
    ROUND(MONTHS_BETWEEN(SYSDATE, s.last_analyzed), 1) AS months_since_analyzed
FROM
    hcc_recommendations r
    LEFT JOIN dba_tables s ON r.owner = s.owner
                           AND r.object_name = s.table_name
                           AND r.object_type = 'TABLE'
WHERE
    r.hotness_score < 20
    AND r.advisable_compression IN ('BASIC', 'HCC_ARCHIVE_HIGH', 'HCC_ARCHIVE_LOW')
    AND r.potential_savings_mb > 0
ORDER BY
    r.potential_savings_mb DESC,
    r.hotness_score ASC;

COMMENT ON TABLE v_cold_objects IS 'Rarely accessed objects with low hotness scores, ideal candidates for aggressive compression';
-- ============================================================================
-- View: V_COMPRESSION_EFFECTIVENESS
-- Purpose: Analysis of compression results vs. predictions
-- ============================================================================
CREATE OR REPLACE VIEW v_compression_effectiveness AS
SELECT
    h.compression_type,
    h.object_type,
    COUNT(*) AS total_executions,
    COUNT(CASE WHEN h.status = 'COMPLETED' THEN 1 END) AS successful_executions,
    COUNT(CASE WHEN h.status = 'FAILED' THEN 1 END) AS failed_executions,
    ROUND(COUNT(CASE WHEN h.status = 'COMPLETED' THEN 1 END) * 100.0 / COUNT(*), 1) AS success_rate_pct,
    ROUND(AVG(h.compression_ratio), 2) AS avg_actual_compression_ratio,
    ROUND(MIN(h.compression_ratio), 2) AS min_compression_ratio,
    ROUND(MAX(h.compression_ratio), 2) AS max_compression_ratio,
    ROUND(SUM(h.space_saved_mb), 2) AS total_space_saved_mb,
    ROUND(AVG((h.end_time - h.start_time) * 24 * 60), 2) AS avg_execution_time_minutes,
    COUNT(CASE WHEN h.compression_ratio >= 2.0 THEN 1 END) AS high_compression_count,
    COUNT(CASE WHEN h.compression_ratio < 1.5 THEN 1 END) AS low_compression_count
FROM
    hcc_execution_history h
WHERE
    h.status = 'COMPLETED'
    AND h.compression_ratio > 0
GROUP BY
    h.compression_type,
    h.object_type
ORDER BY
    total_space_saved_mb DESC;

COMMENT ON TABLE v_compression_effectiveness IS 'Performance metrics and effectiveness analysis of compression executions';
-- ============================================================================
-- View: V_STRATEGY_RECOMMENDATIONS
-- Purpose: Side-by-side comparison of recommendations across strategies
-- ============================================================================
CREATE OR REPLACE VIEW v_strategy_recommendations AS
WITH strategy_pivot AS (
    SELECT
        r.owner,
        r.object_name,
        r.object_type,
        r.current_size_mb,
        r.hotness_score,
        a.strategy_name,
        r.advisable_compression,
        r.potential_savings_mb,
        r.savings_pct,
        r.rationale
    FROM
        hcc_recommendations r
        JOIN hcc_analysis_runs a ON r.run_id = a.run_id
)
SELECT
    owner,
    object_name,
    object_type,
    ROUND(MAX(current_size_mb), 2) AS current_size_mb,
    MAX(hotness_score) AS hotness_score,
    MAX(CASE WHEN strategy_name = 'balanced' THEN advisable_compression END) AS balanced_recommendation,
    MAX(CASE WHEN strategy_name = 'balanced' THEN ROUND(potential_savings_mb, 2) END) AS balanced_savings_mb,
    MAX(CASE WHEN strategy_name = 'aggressive' THEN advisable_compression END) AS aggressive_recommendation,
    MAX(CASE WHEN strategy_name = 'aggressive' THEN ROUND(potential_savings_mb, 2) END) AS aggressive_savings_mb,
    MAX(CASE WHEN strategy_name = 'conservative' THEN advisable_compression END) AS conservative_recommendation,
    MAX(CASE WHEN strategy_name = 'conservative' THEN ROUND(potential_savings_mb, 2) END) AS conservative_savings_mb,
    MAX(CASE WHEN strategy_name = 'balanced' THEN rationale END) AS balanced_rationale
FROM
    strategy_pivot
GROUP BY
    owner,
    object_name,
    object_type
HAVING
    COUNT(DISTINCT strategy_name) > 1  -- Only show objects analyzed by multiple strategies
ORDER BY
    MAX(current_size_mb) DESC;

COMMENT ON TABLE v_strategy_recommendations IS 'Comparison of compression recommendations across different analysis strategies';
-- ============================================================================
-- View: V_SPACE_ANALYSIS
-- Purpose: Space usage and potential savings by tablespace
-- ============================================================================
CREATE OR REPLACE VIEW v_space_analysis AS
SELECT
    t.tablespace_name,
    COUNT(DISTINCT r.owner || '.' || r.object_name) AS total_objects,
    ROUND(SUM(r.current_size_mb), 2) AS current_space_used_mb,
    ROUND(SUM(r.potential_savings_mb), 2) AS potential_savings_mb,
    ROUND(SUM(r.current_size_mb) - SUM(r.potential_savings_mb), 2) AS projected_space_used_mb,
    ROUND(SUM(r.potential_savings_mb) * 100.0 / NULLIF(SUM(r.current_size_mb), 0), 1) AS savings_pct,
    ROUND(f.total_space_mb, 2) AS tablespace_total_mb,
    ROUND(f.free_space_mb, 2) AS tablespace_free_mb,
    ROUND(f.used_space_mb, 2) AS tablespace_used_mb,
    ROUND(f.free_space_mb + SUM(r.potential_savings_mb), 2) AS projected_free_mb
FROM
    hcc_recommendations r
    JOIN dba_segments s ON r.owner = s.owner
                        AND r.object_name = s.segment_name
                        AND r.object_type = s.segment_type
    JOIN dba_tablespaces t ON s.tablespace_name = t.tablespace_name
    LEFT JOIN (
        SELECT
            tablespace_name,
            ROUND(SUM(bytes) / 1024 / 1024, 2) AS total_space_mb,
            ROUND(SUM(CASE WHEN autoextensible = 'YES'
                           THEN maxbytes ELSE bytes END) / 1024 / 1024, 2) AS max_space_mb,
            ROUND(SUM(bytes - NVL(free.bytes, 0)) / 1024 / 1024, 2) AS used_space_mb,
            ROUND(SUM(NVL(free.bytes, 0)) / 1024 / 1024, 2) AS free_space_mb
        FROM
            dba_data_files df
            LEFT JOIN (
                SELECT tablespace_name, file_id, SUM(bytes) AS bytes
                FROM dba_free_space
                GROUP BY tablespace_name, file_id
            ) free ON df.tablespace_name = free.tablespace_name
                   AND df.file_id = free.file_id
        GROUP BY tablespace_name
    ) f ON t.tablespace_name = f.tablespace_name
WHERE
    r.potential_savings_mb > 0
GROUP BY
    t.tablespace_name,
    f.total_space_mb,
    f.free_space_mb,
    f.used_space_mb
ORDER BY
    potential_savings_mb DESC;

COMMENT ON TABLE v_space_analysis IS 'Space usage and potential savings analysis by tablespace';
-- ============================================================================
-- View: V_EXECUTION_QUEUE
-- Purpose: Pending compression operations prioritized by savings
-- ============================================================================
CREATE OR REPLACE VIEW v_execution_queue AS
SELECT
    r.recommendation_id,
    r.owner,
    r.object_name,
    r.object_type,
    r.advisable_compression AS target_compression,
    ROUND(r.current_size_mb, 2) AS current_size_mb,
    ROUND(r.potential_savings_mb, 2) AS potential_savings_mb,
    ROUND(r.savings_pct, 1) AS savings_pct,
    r.hotness_score,
    r.io_pattern,
    a.strategy_name,
    CASE
        WHEN r.potential_savings_mb > 1000 THEN 'HIGH'
        WHEN r.potential_savings_mb > 100 THEN 'MEDIUM'
        ELSE 'LOW'
    END AS priority,
    'ALTER TABLE ' || r.owner || '.' || r.object_name ||
    ' MOVE COMPRESS FOR ' || r.advisable_compression || ';' AS ddl_statement,
    CASE
        WHEN EXISTS (
            SELECT 1 FROM hcc_execution_history h
            WHERE h.owner = r.owner
            AND h.object_name = r.object_name
            AND h.status = 'IN_PROGRESS'
        ) THEN 'IN_PROGRESS'
        WHEN EXISTS (
            SELECT 1 FROM hcc_execution_history h
            WHERE h.owner = r.owner
            AND h.object_name = r.object_name
            AND h.status = 'COMPLETED'
            AND h.end_time > SYSDATE - 7
        ) THEN 'RECENTLY_COMPLETED'
        ELSE 'READY'
    END AS execution_status
FROM
    hcc_recommendations r
    JOIN hcc_analysis_runs a ON r.run_id = a.run_id
WHERE
    r.advisable_compression IS NOT NULL
    AND r.advisable_compression != 'NONE'
    AND r.potential_savings_mb > 0
    AND NOT EXISTS (
        SELECT 1 FROM hcc_execution_history h
        WHERE h.owner = r.owner
        AND h.object_name = r.object_name
        AND h.status IN ('IN_PROGRESS', 'PENDING')
    )
ORDER BY
    r.potential_savings_mb DESC,
    r.savings_pct DESC;

COMMENT ON TABLE v_execution_queue IS 'Prioritized queue of compression operations ready for execution';
-- ============================================================================
-- View: V_ADVISOR_SUMMARY
-- Purpose: High-level dashboard metrics and executive summary
-- ============================================================================
CREATE OR REPLACE VIEW v_advisor_summary AS
SELECT
    (SELECT COUNT(*) FROM hcc_analysis_runs) AS total_analysis_runs,
    (SELECT MAX(analysis_date) FROM hcc_analysis_runs) AS last_analysis_date,
    (SELECT COUNT(DISTINCT owner || '.' || object_name)
     FROM hcc_recommendations) AS total_objects_analyzed,
    (SELECT COUNT(DISTINCT owner || '.' || object_name)
     FROM hcc_recommendations
     WHERE advisable_compression IS NOT NULL
     AND advisable_compression != 'NONE') AS compression_candidates,
    (SELECT ROUND(SUM(current_size_mb), 2)
     FROM hcc_recommendations) AS total_database_size_mb,
    (SELECT ROUND(SUM(potential_savings_mb), 2)
     FROM hcc_recommendations
     WHERE potential_savings_mb > 0) AS total_potential_savings_mb,
    (SELECT ROUND(AVG(savings_pct), 1)
     FROM hcc_recommendations
     WHERE potential_savings_mb > 0) AS avg_savings_pct,
    (SELECT COUNT(*)
     FROM hcc_execution_history
     WHERE status = 'COMPLETED') AS total_compressions_executed,
    (SELECT ROUND(SUM(space_saved_mb), 2)
     FROM hcc_execution_history
     WHERE status = 'COMPLETED') AS actual_space_saved_mb,
    (SELECT ROUND(AVG(compression_ratio), 2)
     FROM hcc_execution_history
     WHERE status = 'COMPLETED'
     AND compression_ratio > 0) AS avg_actual_compression_ratio,
    (SELECT COUNT(*)
     FROM hcc_execution_history
     WHERE status = 'IN_PROGRESS') AS active_executions,
    (SELECT COUNT(*)
     FROM hcc_execution_history
     WHERE status = 'FAILED') AS failed_executions,
    (SELECT COUNT(DISTINCT owner)
     FROM hcc_recommendations) AS schemas_analyzed,
    (SELECT strategy_name
     FROM hcc_analysis_runs
     WHERE run_id = (SELECT MAX(run_id) FROM hcc_analysis_runs)) AS last_strategy_used
FROM DUAL;

COMMENT ON TABLE v_advisor_summary IS 'Executive dashboard summary with key metrics and statistics';
-- ============================================================================
-- View: V_COMPRESSION_ANALYSIS_WITH_AGE
-- Purpose: Compression analysis results with calculated DATA_AGE_DAYS
-- Note: DATA_AGE_DAYS is calculated at query time as TRUNC(SYSDATE - LAST_ANALYZED)
-- ============================================================================
CREATE OR REPLACE VIEW v_compression_analysis_with_age AS
SELECT
    analysis_id,
    owner,
    object_name,
    object_type,
    partition_name,
    subpartition_name,
    size_bytes,
    size_mb,
    size_gb,
    row_count,
    block_count,
    avg_row_length,
    basic_ratio,
    oltp_ratio,
    adv_low_ratio,
    adv_high_ratio,
    best_ratio,
    insert_count,
    update_count,
    delete_count,
    total_dml,
    logical_reads,
    physical_reads,
    access_frequency,
    last_access_date,
    hotness_score,
    hotness_category,
    read_ratio,
    write_ratio,
    dml_24h_rate,
    last_analyzed,
    TRUNC(SYSDATE - LAST_ANALYZED) AS data_age_days,
    current_compression,
    compression_enabled,
    advisable_compression,
    recommendation_reason,
    confidence_score,
    projected_savings_bytes,
    projected_savings_mb,
    projected_savings_pct,
    advisor_run_id,
    analysis_date,
    analysis_timestamp,
    analysis_duration_sec,
    sample_size_rows,
    last_updated
FROM
    t_compression_analysis;

COMMENT ON TABLE v_compression_analysis_with_age IS 'T_COMPRESSION_ANALYSIS with calculated DATA_AGE_DAYS (days since LAST_ANALYZED)';
-- ============================================================================
-- Grant SELECT privileges on views to PUBLIC or specific role
-- ============================================================================
PROMPT Granting SELECT privileges on views...

GRANT SELECT ON v_compression_candidates TO PUBLIC;
GRANT SELECT ON v_compression_summary TO PUBLIC;
GRANT SELECT ON v_compression_history TO PUBLIC;
GRANT SELECT ON v_compression_analysis_with_age TO PUBLIC;
GRANT SELECT ON v_hot_objects TO PUBLIC;
GRANT SELECT ON v_cold_objects TO PUBLIC;
GRANT SELECT ON v_compression_effectiveness TO PUBLIC;
GRANT SELECT ON v_strategy_recommendations TO PUBLIC;
GRANT SELECT ON v_space_analysis TO PUBLIC;
GRANT SELECT ON v_execution_queue TO PUBLIC;
GRANT SELECT ON v_advisor_summary TO PUBLIC;

-- ============================================================================
-- Create synonyms for easier access
-- ============================================================================
PROMPT Creating public synonyms...

CREATE OR REPLACE PUBLIC SYNONYM v_compression_candidates FOR v_compression_candidates;
CREATE OR REPLACE PUBLIC SYNONYM v_compression_summary FOR v_compression_summary;
CREATE OR REPLACE PUBLIC SYNONYM v_compression_history FOR v_compression_history;
CREATE OR REPLACE PUBLIC SYNONYM v_compression_analysis_with_age FOR v_compression_analysis_with_age;
CREATE OR REPLACE PUBLIC SYNONYM v_hot_objects FOR v_hot_objects;
CREATE OR REPLACE PUBLIC SYNONYM v_cold_objects FOR v_cold_objects;
CREATE OR REPLACE PUBLIC SYNONYM v_compression_effectiveness FOR v_compression_effectiveness;
CREATE OR REPLACE PUBLIC SYNONYM v_strategy_recommendations FOR v_strategy_recommendations;
CREATE OR REPLACE PUBLIC SYNONYM v_space_analysis FOR v_space_analysis;
CREATE OR REPLACE PUBLIC SYNONYM v_execution_queue FOR v_execution_queue;
CREATE OR REPLACE PUBLIC SYNONYM v_advisor_summary FOR v_advisor_summary;

-- ============================================================================
-- Verification Query
-- ============================================================================
PROMPT
PROMPT ============================================================================
PROMPT View Creation Summary
PROMPT ============================================================================
PROMPT

SELECT
    view_name,
    text_length,
    CASE
        WHEN view_name LIKE '%CANDIDATE%' THEN 'Actionable recommendations'
        WHEN view_name LIKE '%SUMMARY%' THEN 'Aggregated statistics'
        WHEN view_name LIKE '%HISTORY%' THEN 'Execution tracking'
        WHEN view_name LIKE '%HOT%' THEN 'Write-intensive objects'
        WHEN view_name LIKE '%COLD%' THEN 'Archive candidates'
        WHEN view_name LIKE '%EFFECTIVENESS%' THEN 'Performance metrics'
        WHEN view_name LIKE '%STRATEGY%' THEN 'Strategy comparison'
        WHEN view_name LIKE '%SPACE%' THEN 'Tablespace analysis'
        WHEN view_name LIKE '%QUEUE%' THEN 'Execution planning'
        WHEN view_name LIKE '%ADVISOR%' THEN 'Dashboard metrics'
    END AS purpose
FROM
    user_views
WHERE
    view_name LIKE 'V\_%' ESCAPE '\'
ORDER BY
    view_name;

PROMPT
PROMPT ============================================================================
PROMPT Compression Advisor Views Created Successfully
PROMPT ============================================================================
PROMPT
PROMPT Available Views:
PROMPT   1. V_COMPRESSION_CANDIDATES      - All compression recommendations
PROMPT   2. V_COMPRESSION_SUMMARY         - Aggregated statistics by owner/type
PROMPT   3. V_COMPRESSION_HISTORY         - Execution history and results
PROMPT   4. V_COMPRESSION_ANALYSIS_WITH_AGE - Analysis results with calculated data age
PROMPT   5. V_HOT_OBJECTS                 - Write-intensive objects (hotness >= 70)
PROMPT   6. V_COLD_OBJECTS                - Archive candidates (hotness < 20)
PROMPT   7. V_COMPRESSION_EFFECTIVENESS   - Compression performance analysis
PROMPT   8. V_STRATEGY_RECOMMENDATIONS    - Strategy comparison view
PROMPT   9. V_SPACE_ANALYSIS              - Tablespace space analysis
PROMPT  10. V_EXECUTION_QUEUE             - Prioritized execution queue
PROMPT  11. V_ADVISOR_SUMMARY             - Executive dashboard summary
PROMPT
PROMPT Usage Examples:
PROMPT   SELECT * FROM v_advisor_summary;
PROMPT   SELECT * FROM v_compression_candidates WHERE savings_pct > 50;
PROMPT   SELECT * FROM v_hot_objects WHERE current_size_mb > 100;
PROMPT   SELECT * FROM v_execution_queue WHERE priority = 'HIGH';
PROMPT
PROMPT ============================================================================
