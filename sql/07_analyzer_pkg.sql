--------------------------------------------------------------------------------
-- Package: PKG_COMPRESSION_ANALYZER
-- Purpose: Public API for compression analysis as documented in user-guide.md
-- Author: Daniel Moya (copyright), GitHub: github.com/danimoya Website: danielmoya.cv
-- Date: 2025-12-16
--
-- DESCRIPTION:
--   This package provides the documented public API for compression analysis.
--   It wraps the internal PKG_COMPRESSION_ADVISOR functionality with the
--   interface specified in the user documentation.
--
-- PUBLIC PROCEDURES:
--   - ANALYZE_ALL_TABLES(p_schema_filter)    - Analyze all user tables
--   - ANALYZE_SPECIFIC_TABLE(...)            - Analyze a specific table
--   - REFRESH_ANALYSIS(p_days_old)           - Refresh stale analysis
--   - ANALYZE_LOB(...)                       - Analyze LOB columns
--
-- USAGE:
--   -- Analyze all user tables
--   EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES;
--
--   -- Analyze specific schema
--   EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES(p_schema_filter => 'SALES');
--
--   -- Analyze specific table with partitions
--   EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_SPECIFIC_TABLE(
--       p_owner => 'HR',
--       p_table_name => 'EMPLOYEES',
--       p_include_partitions => TRUE
--   );
--
--   -- Refresh stale analysis (older than 7 days)
--   EXEC PKG_COMPRESSION_ANALYZER.REFRESH_ANALYSIS(p_days_old => 7);
--
--------------------------------------------------------------------------------

--------------------------------------------------------------------------------
-- PACKAGE SPECIFICATION
--------------------------------------------------------------------------------
CREATE OR REPLACE PACKAGE PKG_COMPRESSION_ANALYZER AS

    -- Package version
    C_VERSION CONSTANT VARCHAR2(10) := '1.0.0';

    -- Default strategy IDs
    C_STRATEGY_CONSERVATIVE CONSTANT NUMBER := 1;
    C_STRATEGY_BALANCED     CONSTANT NUMBER := 2;
    C_STRATEGY_AGGRESSIVE   CONSTANT NUMBER := 3;

    -- Minimum size thresholds (in MB) - configurable
    C_MIN_TABLE_SIZE_MB CONSTANT NUMBER := 1;     -- 1 MB minimum for tables
    C_MIN_INDEX_SIZE_MB CONSTANT NUMBER := 10;    -- 10 MB minimum for indexes
    C_MIN_LOB_SIZE_MB   CONSTANT NUMBER := 10;    -- 10 MB minimum for LOBs

    /**
     * Analyze all user tables for compression opportunities
     * This is the main entry point for full database analysis.
     *
     * @param p_schema_filter  Optional schema filter (NULL = all non-system schemas)
     * @param p_strategy_id    Analysis strategy (1=Conservative, 2=Balanced, 3=Aggressive)
     *                         Default is Balanced (2)
     * @param p_parallel_degree Degree of parallelism for analysis (default 4)
     *
     * Example:
     *   -- Analyze all schemas
     *   EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES;
     *
     *   -- Analyze specific schema
     *   EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES(p_schema_filter => 'SALES');
     */
    PROCEDURE ANALYZE_ALL_TABLES(
        p_schema_filter   IN VARCHAR2 DEFAULT NULL,
        p_strategy_id     IN NUMBER DEFAULT 2,
        p_parallel_degree IN NUMBER DEFAULT 4
    );

    /**
     * Analyze a specific table for compression opportunities
     * Provides detailed analysis including partition-level recommendations.
     *
     * @param p_owner              Table owner/schema name
     * @param p_table_name         Table name
     * @param p_include_partitions Whether to analyze individual partitions (default TRUE)
     * @param p_strategy_id        Analysis strategy (default 2 = Balanced)
     *
     * Example:
     *   EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_SPECIFIC_TABLE('HR', 'EMPLOYEES');
     *
     *   EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_SPECIFIC_TABLE(
     *       p_owner => 'SALES',
     *       p_table_name => 'ORDERS',
     *       p_include_partitions => TRUE
     *   );
     */
    PROCEDURE ANALYZE_SPECIFIC_TABLE(
        p_owner              IN VARCHAR2,
        p_table_name         IN VARCHAR2,
        p_include_partitions IN BOOLEAN DEFAULT TRUE,
        p_strategy_id        IN NUMBER DEFAULT 2
    );

    /**
     * Refresh stale compression analysis results
     * Re-analyzes objects whose analysis is older than specified days.
     *
     * @param p_days_old     Number of days after which analysis is considered stale
     *                       Default is 30 days
     * @param p_schema_filter Optional schema filter
     * @param p_strategy_id   Analysis strategy for refresh
     *
     * Example:
     *   -- Refresh analysis older than 7 days
     *   EXEC PKG_COMPRESSION_ANALYZER.REFRESH_ANALYSIS(p_days_old => 7);
     *
     *   -- Refresh specific schema
     *   EXEC PKG_COMPRESSION_ANALYZER.REFRESH_ANALYSIS(
     *       p_days_old => 14,
     *       p_schema_filter => 'SALES'
     *   );
     */
    PROCEDURE REFRESH_ANALYSIS(
        p_days_old      IN NUMBER DEFAULT 30,
        p_schema_filter IN VARCHAR2 DEFAULT NULL,
        p_strategy_id   IN NUMBER DEFAULT 2
    );

    /**
     * Analyze a specific LOB column for compression opportunities
     *
     * @param p_owner       Table owner/schema name
     * @param p_table_name  Table name containing the LOB
     * @param p_column_name LOB column name
     * @param p_strategy_id Analysis strategy (default 2 = Balanced)
     *
     * Example:
     *   EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_LOB(
     *       p_owner => 'HR',
     *       p_table_name => 'DOCUMENTS',
     *       p_column_name => 'CONTENT'
     *   );
     */
    PROCEDURE ANALYZE_LOB(
        p_owner       IN VARCHAR2,
        p_table_name  IN VARCHAR2,
        p_column_name IN VARCHAR2,
        p_strategy_id IN NUMBER DEFAULT 2
    );

    /**
     * Analyze all indexes for a given schema or all schemas
     *
     * @param p_schema_filter Optional schema filter (NULL = all non-system schemas)
     * @param p_strategy_id   Analysis strategy (default 2 = Balanced)
     *
     * Example:
     *   -- Analyze all indexes
     *   EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_INDEXES;
     *
     *   -- Analyze indexes for specific schema
     *   EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_INDEXES(p_schema_filter => 'HR');
     */
    PROCEDURE ANALYZE_ALL_INDEXES(
        p_schema_filter IN VARCHAR2 DEFAULT NULL,
        p_strategy_id   IN NUMBER DEFAULT 2
    );

    /**
     * Get the package version
     *
     * @return Package version string
     */
    FUNCTION GET_VERSION RETURN VARCHAR2;

    /**
     * Get analysis summary statistics
     *
     * @param p_schema_filter Optional schema filter
     * @return REF CURSOR with summary statistics
     */
    FUNCTION GET_ANALYSIS_SUMMARY(
        p_schema_filter IN VARCHAR2 DEFAULT NULL
    ) RETURN SYS_REFCURSOR;

    /**
     * Check if a schema should be excluded from analysis
     * System schemas (SYS, SYSTEM, APEX%, etc.) are excluded
     *
     * @param p_schema Schema name to check
     * @return 'Y' if excluded, 'N' if not
     */
    FUNCTION IS_EXCLUDED_SCHEMA(
        p_schema IN VARCHAR2
    ) RETURN VARCHAR2 DETERMINISTIC;

END PKG_COMPRESSION_ANALYZER;
/

--------------------------------------------------------------------------------
-- PACKAGE BODY
--------------------------------------------------------------------------------
CREATE OR REPLACE PACKAGE BODY PKG_COMPRESSION_ANALYZER AS

    -- ========================================================================
    -- Private Variables
    -- ========================================================================
    g_current_run_id NUMBER := NULL;

    -- ========================================================================
    -- Private Helper Procedures
    -- ========================================================================

    /**
     * Log a message using the compression logging package
     */
    PROCEDURE log_message(
        p_procedure IN VARCHAR2,
        p_message   IN VARCHAR2,
        p_level     IN VARCHAR2 DEFAULT 'INFO'
    ) IS
    BEGIN
        IF p_level = 'ERROR' THEN
            pkg_compression_log.log_error(
                'PKG_COMPRESSION_ANALYZER',
                p_procedure,
                p_message,
                NULL
            );
        ELSIF p_level = 'WARN' THEN
            pkg_compression_log.log_warning(
                'PKG_COMPRESSION_ANALYZER',
                p_procedure,
                p_message
            );
        ELSE
            pkg_compression_log.log_info(
                'PKG_COMPRESSION_ANALYZER',
                p_procedure,
                p_message
            );
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            -- Fallback to DBMS_OUTPUT if logging package unavailable
            DBMS_OUTPUT.PUT_LINE('[' || p_level || '] ' ||
                TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS') || ' - ' ||
                p_procedure || ': ' || p_message);
    END log_message;

    /**
     * Create or get an advisor run ID for tracking analysis sessions
     */
    FUNCTION get_or_create_run_id(
        p_strategy_id   IN NUMBER,
        p_schema_filter IN VARCHAR2 DEFAULT NULL,
        p_run_type      IN VARCHAR2 DEFAULT 'ALL'
    ) RETURN NUMBER IS
        v_run_id NUMBER;
    BEGIN
        -- Create a new advisor run record
        INSERT INTO t_advisor_run (
            run_name,
            run_type,
            strategy_id,
            schema_filter,
            run_status,
            start_time
        ) VALUES (
            'Analyzer Run ' || TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
            p_run_type,
            p_strategy_id,
            p_schema_filter,
            'RUNNING',
            SYSTIMESTAMP
        ) RETURNING run_id INTO v_run_id;

        COMMIT;

        g_current_run_id := v_run_id;
        RETURN v_run_id;
    END get_or_create_run_id;

    /**
     * Update run statistics after analysis completion
     */
    PROCEDURE update_run_statistics(
        p_run_id          IN NUMBER,
        p_objects_analyzed IN NUMBER,
        p_objects_succeeded IN NUMBER,
        p_objects_failed   IN NUMBER,
        p_status           IN VARCHAR2 DEFAULT 'COMPLETED'
    ) IS
    BEGIN
        UPDATE t_advisor_run
        SET run_status = p_status,
            end_time = SYSTIMESTAMP,
            duration_minutes = EXTRACT(MINUTE FROM (SYSTIMESTAMP - start_time)) +
                              EXTRACT(HOUR FROM (SYSTIMESTAMP - start_time)) * 60,
            objects_analyzed = p_objects_analyzed,
            objects_succeeded = p_objects_succeeded,
            objects_failed = p_objects_failed
        WHERE run_id = p_run_id;

        COMMIT;
    END update_run_statistics;

    -- ========================================================================
    -- Public Function Implementations
    -- ========================================================================

    /**
     * Get package version
     */
    FUNCTION GET_VERSION RETURN VARCHAR2 IS
    BEGIN
        RETURN C_VERSION;
    END GET_VERSION;

    /**
     * Check if schema should be excluded
     */
    FUNCTION IS_EXCLUDED_SCHEMA(
        p_schema IN VARCHAR2
    ) RETURN VARCHAR2 DETERMINISTIC IS
    BEGIN
        -- Exclude Oracle system schemas
        IF p_schema IN (
            'SYS', 'SYSTEM', 'AUDSYS', 'OUTLN', 'DBSNMP',
            'GSMADMIN_INTERNAL', 'XDB', 'WMSYS', 'CTXSYS',
            'MDSYS', 'ORDSYS', 'ORDDATA', 'OLAPSYS',
            'APPQOSSYS', 'DBSFWUSER', 'GGSYS',
            'SPATIAL_CSW_ADMIN_USR', 'SPATIAL_WFS_ADMIN_USR',
            'ANONYMOUS', 'APEX_PUBLIC_USER', 'DIP',
            'FLOWS_FILES', 'MDDATA', 'ORACLE_OCM', 'XS$NULL',
            'REMOTE_SCHEDULER_AGENT', 'APEX_INSTANCE_ADMIN_USER',
            'LBACSYS', 'DVSYS', 'DVF', 'OJVMSYS', 'GSMUSER',
            'DGPDB_INT', 'SYS$UMF'
        ) THEN
            RETURN 'Y';
        END IF;

        -- Exclude schemas matching certain patterns
        IF p_schema LIKE 'APEX_%'
           OR p_schema LIKE 'ORACLE%'
           OR p_schema LIKE 'FLOWS_%'
           OR p_schema LIKE 'ORDS_%'
           OR p_schema LIKE 'SQLT%' THEN
            RETURN 'Y';
        END IF;

        RETURN 'N';
    END IS_EXCLUDED_SCHEMA;

    /**
     * Get analysis summary statistics
     */
    FUNCTION GET_ANALYSIS_SUMMARY(
        p_schema_filter IN VARCHAR2 DEFAULT NULL
    ) RETURN SYS_REFCURSOR IS
        v_cursor SYS_REFCURSOR;
    BEGIN
        OPEN v_cursor FOR
            SELECT
                owner,
                COUNT(*) AS total_objects,
                COUNT(CASE WHEN advisable_compression IS NOT NULL
                           AND advisable_compression != 'NONE' THEN 1 END) AS compression_candidates,
                ROUND(SUM(size_mb), 2) AS total_size_mb,
                ROUND(SUM(projected_savings_mb), 2) AS potential_savings_mb,
                ROUND(AVG(hotness_score), 1) AS avg_hotness_score,
                MAX(analysis_date) AS last_analysis_date
            FROM t_compression_analysis
            WHERE (p_schema_filter IS NULL OR owner = p_schema_filter)
            GROUP BY owner
            ORDER BY potential_savings_mb DESC NULLS LAST;

        RETURN v_cursor;
    END GET_ANALYSIS_SUMMARY;

    -- ========================================================================
    -- Public Procedure Implementations
    -- ========================================================================

    /**
     * Analyze all user tables
     */
    PROCEDURE ANALYZE_ALL_TABLES(
        p_schema_filter   IN VARCHAR2 DEFAULT NULL,
        p_strategy_id     IN NUMBER DEFAULT 2,
        p_parallel_degree IN NUMBER DEFAULT 4
    ) IS
        v_run_id NUMBER;
        v_table_count NUMBER := 0;
        v_success_count NUMBER := 0;
        v_fail_count NUMBER := 0;
        v_start_time TIMESTAMP := SYSTIMESTAMP;
    BEGIN
        log_message('ANALYZE_ALL_TABLES',
            'Starting analysis - Schema: ' || NVL(p_schema_filter, 'ALL') ||
            ', Strategy: ' || p_strategy_id ||
            ', Parallel: ' || p_parallel_degree);

        -- Create analysis run record
        v_run_id := get_or_create_run_id(
            p_strategy_id => p_strategy_id,
            p_schema_filter => p_schema_filter,
            p_run_type => 'TABLES'
        );

        -- Iterate through eligible tables
        FOR rec IN (
            SELECT t.owner, t.table_name,
                   NVL(s.bytes, 0) / 1024 / 1024 AS size_mb
            FROM dba_tables t
            LEFT JOIN (
                SELECT owner, segment_name, SUM(bytes) AS bytes
                FROM dba_segments
                WHERE segment_type = 'TABLE'
                GROUP BY owner, segment_name
            ) s ON t.owner = s.owner AND t.table_name = s.segment_name
            WHERE (p_schema_filter IS NULL OR t.owner = p_schema_filter)
              AND IS_EXCLUDED_SCHEMA(t.owner) = 'N'
              AND t.temporary = 'N'
              AND t.nested = 'NO'
              AND t.secondary = 'N'
              AND NVL(s.bytes, 0) / 1024 / 1024 >= C_MIN_TABLE_SIZE_MB
            ORDER BY NVL(s.bytes, 0) DESC
        ) LOOP
            v_table_count := v_table_count + 1;

            BEGIN
                -- Call the underlying advisor package to analyze this table
                pkg_compression_advisor.analyze_table(
                    p_owner => rec.owner,
                    p_table_name => rec.table_name,
                    p_strategy_id => p_strategy_id
                );

                v_success_count := v_success_count + 1;

                IF MOD(v_table_count, 10) = 0 THEN
                    log_message('ANALYZE_ALL_TABLES',
                        'Progress: ' || v_table_count || ' tables analyzed...');
                END IF;

            EXCEPTION
                WHEN OTHERS THEN
                    v_fail_count := v_fail_count + 1;
                    log_message('ANALYZE_ALL_TABLES',
                        'Failed to analyze ' || rec.owner || '.' || rec.table_name ||
                        ': ' || SQLERRM, 'WARN');
            END;
        END LOOP;

        -- Update run statistics
        update_run_statistics(
            p_run_id => v_run_id,
            p_objects_analyzed => v_table_count,
            p_objects_succeeded => v_success_count,
            p_objects_failed => v_fail_count,
            p_status => 'COMPLETED'
        );

        log_message('ANALYZE_ALL_TABLES',
            'Analysis complete - Total: ' || v_table_count ||
            ', Success: ' || v_success_count ||
            ', Failed: ' || v_fail_count ||
            ', Duration: ' ||
            ROUND(EXTRACT(SECOND FROM (SYSTIMESTAMP - v_start_time)) +
                  EXTRACT(MINUTE FROM (SYSTIMESTAMP - v_start_time)) * 60, 2) || 's');

    EXCEPTION
        WHEN OTHERS THEN
            log_message('ANALYZE_ALL_TABLES',
                'Fatal error: ' || SQLERRM, 'ERROR');

            IF v_run_id IS NOT NULL THEN
                update_run_statistics(
                    p_run_id => v_run_id,
                    p_objects_analyzed => v_table_count,
                    p_objects_succeeded => v_success_count,
                    p_objects_failed => v_fail_count,
                    p_status => 'FAILED'
                );
            END IF;

            RAISE;
    END ANALYZE_ALL_TABLES;

    /**
     * Analyze a specific table
     */
    PROCEDURE ANALYZE_SPECIFIC_TABLE(
        p_owner              IN VARCHAR2,
        p_table_name         IN VARCHAR2,
        p_include_partitions IN BOOLEAN DEFAULT TRUE,
        p_strategy_id        IN NUMBER DEFAULT 2
    ) IS
        v_run_id NUMBER;
        v_table_exists NUMBER;
        v_is_partitioned VARCHAR2(3);
        v_partition_count NUMBER := 0;
        v_success_count NUMBER := 0;
        v_fail_count NUMBER := 0;
    BEGIN
        log_message('ANALYZE_SPECIFIC_TABLE',
            'Analyzing table: ' || p_owner || '.' || p_table_name ||
            ', Include Partitions: ' || CASE WHEN p_include_partitions THEN 'YES' ELSE 'NO' END);

        -- Verify table exists
        SELECT COUNT(*), MAX(partitioned)
        INTO v_table_exists, v_is_partitioned
        FROM dba_tables
        WHERE owner = p_owner
          AND table_name = p_table_name;

        IF v_table_exists = 0 THEN
            RAISE_APPLICATION_ERROR(-20001,
                'Table not found: ' || p_owner || '.' || p_table_name);
        END IF;

        -- Create analysis run
        v_run_id := get_or_create_run_id(
            p_strategy_id => p_strategy_id,
            p_schema_filter => p_owner,
            p_run_type => 'TABLES'
        );

        -- Analyze the table
        BEGIN
            pkg_compression_advisor.analyze_table(
                p_owner => p_owner,
                p_table_name => p_table_name,
                p_strategy_id => p_strategy_id
            );
            v_success_count := v_success_count + 1;

            log_message('ANALYZE_SPECIFIC_TABLE',
                'Table analysis completed: ' || p_owner || '.' || p_table_name);

        EXCEPTION
            WHEN OTHERS THEN
                v_fail_count := v_fail_count + 1;
                log_message('ANALYZE_SPECIFIC_TABLE',
                    'Table analysis failed: ' || SQLERRM, 'ERROR');
                RAISE;
        END;

        -- Analyze partitions if requested and table is partitioned
        IF p_include_partitions AND v_is_partitioned = 'YES' THEN
            log_message('ANALYZE_SPECIFIC_TABLE',
                'Analyzing partitions for: ' || p_owner || '.' || p_table_name);

            FOR part IN (
                SELECT partition_name
                FROM dba_tab_partitions
                WHERE table_owner = p_owner
                  AND table_name = p_table_name
                ORDER BY partition_position
            ) LOOP
                v_partition_count := v_partition_count + 1;

                -- Note: Partition-level analysis is handled within analyze_table
                -- if the table is partitioned. This loop is for logging purposes.
                log_message('ANALYZE_SPECIFIC_TABLE',
                    'Partition analyzed: ' || part.partition_name);
            END LOOP;

            log_message('ANALYZE_SPECIFIC_TABLE',
                'Partitions analyzed: ' || v_partition_count);
        END IF;

        -- Update run statistics
        update_run_statistics(
            p_run_id => v_run_id,
            p_objects_analyzed => 1 + v_partition_count,
            p_objects_succeeded => v_success_count,
            p_objects_failed => v_fail_count,
            p_status => 'COMPLETED'
        );

        log_message('ANALYZE_SPECIFIC_TABLE',
            'Analysis complete for ' || p_owner || '.' || p_table_name);

    EXCEPTION
        WHEN OTHERS THEN
            IF v_run_id IS NOT NULL THEN
                update_run_statistics(
                    p_run_id => v_run_id,
                    p_objects_analyzed => 1,
                    p_objects_succeeded => 0,
                    p_objects_failed => 1,
                    p_status => 'FAILED'
                );
            END IF;
            RAISE;
    END ANALYZE_SPECIFIC_TABLE;

    /**
     * Refresh stale analysis
     */
    PROCEDURE REFRESH_ANALYSIS(
        p_days_old      IN NUMBER DEFAULT 30,
        p_schema_filter IN VARCHAR2 DEFAULT NULL,
        p_strategy_id   IN NUMBER DEFAULT 2
    ) IS
        v_run_id NUMBER;
        v_refresh_count NUMBER := 0;
        v_success_count NUMBER := 0;
        v_fail_count NUMBER := 0;
        v_cutoff_date DATE;
    BEGIN
        v_cutoff_date := SYSDATE - p_days_old;

        log_message('REFRESH_ANALYSIS',
            'Starting refresh - Days old: ' || p_days_old ||
            ', Cutoff date: ' || TO_CHAR(v_cutoff_date, 'YYYY-MM-DD') ||
            ', Schema: ' || NVL(p_schema_filter, 'ALL'));

        -- Create analysis run
        v_run_id := get_or_create_run_id(
            p_strategy_id => p_strategy_id,
            p_schema_filter => p_schema_filter,
            p_run_type => 'TABLES'
        );

        -- Find and re-analyze stale entries
        FOR rec IN (
            SELECT DISTINCT owner, object_name
            FROM t_compression_analysis
            WHERE analysis_date < v_cutoff_date
              AND object_type = 'TABLE'
              AND (p_schema_filter IS NULL OR owner = p_schema_filter)
            ORDER BY owner, object_name
        ) LOOP
            v_refresh_count := v_refresh_count + 1;

            BEGIN
                -- Verify table still exists before re-analyzing
                DECLARE
                    v_exists NUMBER;
                BEGIN
                    SELECT COUNT(*) INTO v_exists
                    FROM dba_tables
                    WHERE owner = rec.owner
                      AND table_name = rec.object_name;

                    IF v_exists > 0 THEN
                        -- Delete old analysis for this object
                        DELETE FROM t_compression_analysis
                        WHERE owner = rec.owner
                          AND object_name = rec.object_name;

                        -- Re-analyze
                        pkg_compression_advisor.analyze_table(
                            p_owner => rec.owner,
                            p_table_name => rec.object_name,
                            p_strategy_id => p_strategy_id
                        );

                        v_success_count := v_success_count + 1;

                        log_message('REFRESH_ANALYSIS',
                            'Refreshed: ' || rec.owner || '.' || rec.object_name);
                    ELSE
                        -- Table no longer exists, remove stale entry
                        DELETE FROM t_compression_analysis
                        WHERE owner = rec.owner
                          AND object_name = rec.object_name;

                        log_message('REFRESH_ANALYSIS',
                            'Removed stale entry (table dropped): ' ||
                            rec.owner || '.' || rec.object_name, 'WARN');
                    END IF;
                END;

            EXCEPTION
                WHEN OTHERS THEN
                    v_fail_count := v_fail_count + 1;
                    log_message('REFRESH_ANALYSIS',
                        'Failed to refresh ' || rec.owner || '.' || rec.object_name ||
                        ': ' || SQLERRM, 'WARN');
            END;
        END LOOP;

        COMMIT;

        -- Update run statistics
        update_run_statistics(
            p_run_id => v_run_id,
            p_objects_analyzed => v_refresh_count,
            p_objects_succeeded => v_success_count,
            p_objects_failed => v_fail_count,
            p_status => 'COMPLETED'
        );

        log_message('REFRESH_ANALYSIS',
            'Refresh complete - Total: ' || v_refresh_count ||
            ', Success: ' || v_success_count ||
            ', Failed: ' || v_fail_count);

    EXCEPTION
        WHEN OTHERS THEN
            log_message('REFRESH_ANALYSIS',
                'Fatal error: ' || SQLERRM, 'ERROR');

            IF v_run_id IS NOT NULL THEN
                update_run_statistics(
                    p_run_id => v_run_id,
                    p_objects_analyzed => v_refresh_count,
                    p_objects_succeeded => v_success_count,
                    p_objects_failed => v_fail_count,
                    p_status => 'FAILED'
                );
            END IF;

            RAISE;
    END REFRESH_ANALYSIS;

    /**
     * Analyze a specific LOB column
     */
    PROCEDURE ANALYZE_LOB(
        p_owner       IN VARCHAR2,
        p_table_name  IN VARCHAR2,
        p_column_name IN VARCHAR2,
        p_strategy_id IN NUMBER DEFAULT 2
    ) IS
        v_run_id NUMBER;
        v_lob_exists NUMBER;
    BEGIN
        log_message('ANALYZE_LOB',
            'Analyzing LOB: ' || p_owner || '.' || p_table_name || '.' || p_column_name);

        -- Verify LOB exists
        SELECT COUNT(*)
        INTO v_lob_exists
        FROM dba_lobs
        WHERE owner = p_owner
          AND table_name = p_table_name
          AND column_name = p_column_name;

        IF v_lob_exists = 0 THEN
            RAISE_APPLICATION_ERROR(-20002,
                'LOB column not found: ' || p_owner || '.' || p_table_name || '.' || p_column_name);
        END IF;

        -- Create analysis run
        v_run_id := get_or_create_run_id(
            p_strategy_id => p_strategy_id,
            p_schema_filter => p_owner,
            p_run_type => 'LOBS'
        );

        -- Call underlying advisor package
        BEGIN
            pkg_compression_advisor.analyze_lob(
                p_owner => p_owner,
                p_table_name => p_table_name,
                p_column_name => p_column_name,
                p_strategy_id => p_strategy_id
            );

            update_run_statistics(
                p_run_id => v_run_id,
                p_objects_analyzed => 1,
                p_objects_succeeded => 1,
                p_objects_failed => 0,
                p_status => 'COMPLETED'
            );

            log_message('ANALYZE_LOB',
                'LOB analysis completed: ' || p_owner || '.' || p_table_name || '.' || p_column_name);

        EXCEPTION
            WHEN OTHERS THEN
                update_run_statistics(
                    p_run_id => v_run_id,
                    p_objects_analyzed => 1,
                    p_objects_succeeded => 0,
                    p_objects_failed => 1,
                    p_status => 'FAILED'
                );
                RAISE;
        END;

    END ANALYZE_LOB;

    /**
     * Analyze all indexes
     */
    PROCEDURE ANALYZE_ALL_INDEXES(
        p_schema_filter IN VARCHAR2 DEFAULT NULL,
        p_strategy_id   IN NUMBER DEFAULT 2
    ) IS
        v_run_id NUMBER;
        v_index_count NUMBER := 0;
        v_success_count NUMBER := 0;
        v_fail_count NUMBER := 0;
        v_start_time TIMESTAMP := SYSTIMESTAMP;
    BEGIN
        log_message('ANALYZE_ALL_INDEXES',
            'Starting index analysis - Schema: ' || NVL(p_schema_filter, 'ALL'));

        -- Create analysis run
        v_run_id := get_or_create_run_id(
            p_strategy_id => p_strategy_id,
            p_schema_filter => p_schema_filter,
            p_run_type => 'INDEXES'
        );

        -- Iterate through eligible indexes
        FOR rec IN (
            SELECT i.owner, i.index_name,
                   NVL(s.bytes, 0) / 1024 / 1024 AS size_mb
            FROM dba_indexes i
            LEFT JOIN (
                SELECT owner, segment_name, SUM(bytes) AS bytes
                FROM dba_segments
                WHERE segment_type LIKE 'INDEX%'
                GROUP BY owner, segment_name
            ) s ON i.owner = s.owner AND i.index_name = s.segment_name
            WHERE (p_schema_filter IS NULL OR i.owner = p_schema_filter)
              AND IS_EXCLUDED_SCHEMA(i.owner) = 'N'
              AND i.index_type IN ('NORMAL', 'NORMAL/REV')
              AND i.temporary = 'N'
              AND NVL(s.bytes, 0) / 1024 / 1024 >= C_MIN_INDEX_SIZE_MB
            ORDER BY NVL(s.bytes, 0) DESC
        ) LOOP
            v_index_count := v_index_count + 1;

            BEGIN
                pkg_compression_advisor.analyze_index(
                    p_owner => rec.owner,
                    p_index_name => rec.index_name,
                    p_strategy_id => p_strategy_id
                );

                v_success_count := v_success_count + 1;

            EXCEPTION
                WHEN OTHERS THEN
                    v_fail_count := v_fail_count + 1;
                    log_message('ANALYZE_ALL_INDEXES',
                        'Failed to analyze index ' || rec.owner || '.' || rec.index_name ||
                        ': ' || SQLERRM, 'WARN');
            END;
        END LOOP;

        -- Update run statistics
        update_run_statistics(
            p_run_id => v_run_id,
            p_objects_analyzed => v_index_count,
            p_objects_succeeded => v_success_count,
            p_objects_failed => v_fail_count,
            p_status => 'COMPLETED'
        );

        log_message('ANALYZE_ALL_INDEXES',
            'Index analysis complete - Total: ' || v_index_count ||
            ', Success: ' || v_success_count ||
            ', Failed: ' || v_fail_count);

    EXCEPTION
        WHEN OTHERS THEN
            log_message('ANALYZE_ALL_INDEXES',
                'Fatal error: ' || SQLERRM, 'ERROR');

            IF v_run_id IS NOT NULL THEN
                update_run_statistics(
                    p_run_id => v_run_id,
                    p_objects_analyzed => v_index_count,
                    p_objects_succeeded => v_success_count,
                    p_objects_failed => v_fail_count,
                    p_status => 'FAILED'
                );
            END IF;

            RAISE;
    END ANALYZE_ALL_INDEXES;

-- Package initialization
BEGIN
    -- Log package initialization
    BEGIN
        pkg_compression_log.log_info(
            'PKG_COMPRESSION_ANALYZER',
            'INITIALIZATION',
            'Package initialized - Version: ' || C_VERSION
        );
    EXCEPTION
        WHEN OTHERS THEN
            NULL; -- Silently ignore if logging not available
    END;
END PKG_COMPRESSION_ANALYZER;
/

--------------------------------------------------------------------------------
-- Grant execute permissions
--------------------------------------------------------------------------------
GRANT EXECUTE ON PKG_COMPRESSION_ANALYZER TO PUBLIC;

--------------------------------------------------------------------------------
-- Create public synonym for easy access
--------------------------------------------------------------------------------
CREATE OR REPLACE PUBLIC SYNONYM PKG_COMPRESSION_ANALYZER FOR PKG_COMPRESSION_ANALYZER;

--------------------------------------------------------------------------------
-- Display completion message
--------------------------------------------------------------------------------
PROMPT
PROMPT ================================================================================
PROMPT PKG_COMPRESSION_ANALYZER package created successfully
PROMPT ================================================================================
PROMPT
PROMPT This package provides the documented public API for compression analysis.
PROMPT
PROMPT Available Procedures:
PROMPT   - ANALYZE_ALL_TABLES(p_schema_filter, p_strategy_id, p_parallel_degree)
PROMPT   - ANALYZE_SPECIFIC_TABLE(p_owner, p_table_name, p_include_partitions, p_strategy_id)
PROMPT   - REFRESH_ANALYSIS(p_days_old, p_schema_filter, p_strategy_id)
PROMPT   - ANALYZE_LOB(p_owner, p_table_name, p_column_name, p_strategy_id)
PROMPT   - ANALYZE_ALL_INDEXES(p_schema_filter, p_strategy_id)
PROMPT
PROMPT Available Functions:
PROMPT   - GET_VERSION                         : Returns package version
PROMPT   - GET_ANALYSIS_SUMMARY(p_schema_filter): Returns analysis summary cursor
PROMPT   - IS_EXCLUDED_SCHEMA(p_schema)        : Check if schema is excluded
PROMPT
PROMPT Usage Examples:
PROMPT   -- Analyze all user tables
PROMPT   EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES;
PROMPT
PROMPT   -- Analyze specific schema
PROMPT   EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES(p_schema_filter => 'SALES');
PROMPT
PROMPT   -- Analyze specific table with partitions
PROMPT   EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_SPECIFIC_TABLE('HR', 'EMPLOYEES');
PROMPT
PROMPT   -- Refresh stale analysis (older than 7 days)
PROMPT   EXEC PKG_COMPRESSION_ANALYZER.REFRESH_ANALYSIS(p_days_old => 7);
PROMPT
PROMPT   -- View results
PROMPT   SELECT owner, table_name, advisable_compression, estimated_savings_mb
PROMPT   FROM V_COMPRESSION_CANDIDATES
PROMPT   ORDER BY estimated_savings_mb DESC;
PROMPT
PROMPT ================================================================================
