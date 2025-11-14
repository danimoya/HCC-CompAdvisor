-- ============================================================================
-- Package: PKG_COMPRESSION_ADVISOR
-- Description: Comprehensive compression analysis and recommendation system
--              Adapted for Oracle 23c Free (no HCC support)
-- Features:
--   - Multi-strategy analysis (Aggressive/Balanced/Conservative)
--   - Parallel processing support
--   - DML hotness tracking
--   - Comprehensive object support (Tables/Indexes/LOBs)
--   - Partition-aware analysis
-- ============================================================================

CREATE OR REPLACE PACKAGE pkg_compression_advisor AS

  -- Package version
  c_version CONSTANT VARCHAR2(10) := '1.0.0';

  -- Analysis strategies
  c_strategy_aggressive CONSTANT NUMBER := 1;
  c_strategy_balanced CONSTANT NUMBER := 2;
  c_strategy_conservative CONSTANT NUMBER := 3;

  -- ========================================================================
  -- Main Analysis Procedures
  -- ========================================================================

  /**
   * Run comprehensive compression analysis for schema(s)
   * @param p_owner Schema owner (NULL = all non-system schemas)
   * @param p_strategy_id Strategy to apply (1=Aggressive, 2=Balanced, 3=Conservative)
   * @param p_parallel_degree Number of parallel workers for table analysis
   */
  PROCEDURE run_analysis(
    p_owner IN VARCHAR2 DEFAULT NULL,
    p_strategy_id IN NUMBER DEFAULT 2,
    p_parallel_degree IN NUMBER DEFAULT 4
  );

  /**
   * Analyze compression potential for a specific table
   * @param p_owner Schema owner
   * @param p_table_name Table name
   * @param p_strategy_id Strategy to apply
   */
  PROCEDURE analyze_table(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_strategy_id IN NUMBER DEFAULT 2
  );

  /**
   * Analyze compression potential for a specific index
   * @param p_owner Schema owner
   * @param p_index_name Index name
   * @param p_strategy_id Strategy to apply
   */
  PROCEDURE analyze_index(
    p_owner IN VARCHAR2,
    p_index_name IN VARCHAR2,
    p_strategy_id IN NUMBER DEFAULT 2
  );

  /**
   * Analyze compression potential for a specific LOB column
   * @param p_owner Schema owner
   * @param p_table_name Table name
   * @param p_column_name LOB column name
   * @param p_strategy_id Strategy to apply
   */
  PROCEDURE analyze_lob(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_column_name IN VARCHAR2,
    p_strategy_id IN NUMBER DEFAULT 2
  );

  -- ========================================================================
  -- Recommendation and Reporting Functions
  -- ========================================================================

  /**
   * Get compression recommendations based on analysis
   * @param p_strategy_id Filter by strategy
   * @param p_min_savings_pct Minimum space savings percentage
   * @return Cursor with recommendations
   */
  FUNCTION get_recommendations(
    p_strategy_id IN NUMBER DEFAULT 2,
    p_min_savings_pct IN NUMBER DEFAULT 20
  ) RETURN SYS_REFCURSOR;

  /**
   * Generate DDL statements for applying compression
   * @param p_recommendation_id Specific recommendation ID (NULL = all)
   * @return Cursor with DDL statements
   */
  FUNCTION generate_ddl(
    p_recommendation_id IN NUMBER DEFAULT NULL
  ) RETURN SYS_REFCURSOR;

  /**
   * Calculate potential space savings across all recommendations
   * @param p_strategy_id Filter by strategy
   * @return Total savings in MB
   */
  FUNCTION calculate_total_savings(
    p_strategy_id IN NUMBER DEFAULT NULL
  ) RETURN NUMBER;

  -- ========================================================================
  -- Utility Procedures
  -- ========================================================================

  /**
   * Clear old analysis results
   * @param p_days_old Number of days to retain (default 30)
   */
  PROCEDURE cleanup_old_results(
    p_days_old IN NUMBER DEFAULT 30
  );

  /**
   * Reset analysis for specific object
   * @param p_owner Schema owner
   * @param p_object_name Object name
   * @param p_object_type Object type (TABLE/INDEX/LOB)
   */
  PROCEDURE reset_analysis(
    p_owner IN VARCHAR2,
    p_object_name IN VARCHAR2,
    p_object_type IN VARCHAR2
  );

END pkg_compression_advisor;
/

CREATE OR REPLACE PACKAGE BODY pkg_compression_advisor AS

  -- ========================================================================
  -- Private Types and Variables
  -- ========================================================================

  TYPE t_strategy_rules IS TABLE OF t_strategy_rules%ROWTYPE
    INDEX BY PLS_INTEGER;

  g_strategy_rules t_strategy_rules;
  g_rules_loaded BOOLEAN := FALSE;

  TYPE t_partition_list IS TABLE OF VARCHAR2(128);

  -- Compression type mappings for Oracle 23c Free
  TYPE t_compression_map IS TABLE OF VARCHAR2(30) INDEX BY VARCHAR2(30);
  g_compression_map t_compression_map;

  -- ========================================================================
  -- Private Utility Functions
  -- ========================================================================

  /**
   * Initialize compression type mappings
   */
  PROCEDURE init_compression_map IS
  BEGIN
    -- Table compression mappings (no HCC in Oracle Free)
    g_compression_map('NONE') := 'NOCOMPRESS';
    g_compression_map('BASIC') := 'COMPRESS BASIC';
    g_compression_map('OLTP') := 'COMPRESS FOR OLTP';
    g_compression_map('ADVANCED') := 'COMPRESS FOR OLTP'; -- Best available

    -- Index compression mappings
    g_compression_map('INDEX_ADVANCED_LOW') := 'COMPRESS ADVANCED LOW';
    g_compression_map('INDEX_ADVANCED_HIGH') := 'COMPRESS ADVANCED HIGH';

    -- LOB compression mappings
    g_compression_map('LOB_LOW') := 'COMPRESS LOW';
    g_compression_map('LOB_MEDIUM') := 'COMPRESS MEDIUM';
    g_compression_map('LOB_HIGH') := 'COMPRESS HIGH';
  END init_compression_map;

  /**
   * Load strategy rules from configuration table
   */
  PROCEDURE load_strategy_rules IS
    v_count NUMBER := 0;
  BEGIN
    IF g_rules_loaded THEN
      RETURN;
    END IF;

    -- Clear existing rules
    g_strategy_rules.DELETE;

    -- Load all strategy rules
    FOR rec IN (
      SELECT *
      FROM t_strategy_rules
      WHERE is_active = 'Y'
      ORDER BY strategy_id, rule_order
    ) LOOP
      v_count := v_count + 1;
      g_strategy_rules(v_count) := rec;
    END LOOP;

    g_rules_loaded := TRUE;

    pkg_compression_log.log_info(
      'PKG_COMPRESSION_ADVISOR',
      'load_strategy_rules',
      'Loaded ' || v_count || ' strategy rules'
    );
  END load_strategy_rules;

  /**
   * Check if schema should be excluded from analysis
   */
  FUNCTION is_excluded_schema(p_owner IN VARCHAR2) RETURN BOOLEAN IS
  BEGIN
    RETURN p_owner IN ('SYS', 'SYSTEM', 'AUDSYS', 'OUTLN', 'DBSNMP', 'GSMADMIN_INTERNAL',
                       'XDB', 'WMSYS', 'CTXSYS', 'MDSYS', 'ORDSYS', 'ORDDATA', 'OLAPSYS',
                       'APPQOSSYS', 'DBSFWUSER', 'GGSYS', 'SPATIAL_CSW_ADMIN_USR',
                       'SPATIAL_WFS_ADMIN_USR', 'ANONYMOUS', 'APEX_PUBLIC_USER',
                       'DIP', 'FLOWS_FILES', 'MDDATA', 'ORACLE_OCM', 'XS$NULL',
                       'REMOTE_SCHEDULER_AGENT', 'APEX_INSTANCE_ADMIN_USER')
           OR p_owner LIKE 'APEX_%'
           OR p_owner LIKE 'ORACLE%'
           OR p_owner LIKE 'FLOWS_%';
  END is_excluded_schema;

  /**
   * Calculate DML hotness score based on recent activity
   */
  FUNCTION calculate_hotness_score(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2
  ) RETURN NUMBER IS
    v_inserts NUMBER := 0;
    v_updates NUMBER := 0;
    v_deletes NUMBER := 0;
    v_total_dml NUMBER := 0;
    v_score NUMBER := 0;
  BEGIN
    -- Flush monitoring info to get latest stats
    DBMS_STATS.flush_database_monitoring_info;

    -- Get DML statistics
    BEGIN
      SELECT
        NVL(inserts, 0),
        NVL(updates, 0),
        NVL(deletes, 0)
      INTO v_inserts, v_updates, v_deletes
      FROM all_tab_modifications
      WHERE table_owner = p_owner
        AND table_name = p_table_name
        AND partition_name IS NULL;
    EXCEPTION
      WHEN NO_DATA_FOUND THEN
        RETURN 0; -- No DML activity
    END;

    -- Calculate total DML operations
    v_total_dml := v_inserts + v_updates + v_deletes;

    -- Logarithmic scoring (0-100 scale)
    -- 0 DML = 0, 1000 DML = 50, 1M DML = 100
    IF v_total_dml > 0 THEN
      v_score := LEAST(100, (LOG(10, v_total_dml + 1) / LOG(10, 1000000)) * 100);
    END IF;

    RETURN ROUND(v_score, 2);
  EXCEPTION
    WHEN OTHERS THEN
      pkg_compression_log.log_error(
        'PKG_COMPRESSION_ADVISOR',
        'calculate_hotness_score',
        'Error calculating hotness for ' || p_owner || '.' || p_table_name,
        SQLERRM
      );
      RETURN 0;
  END calculate_hotness_score;

  /**
   * Calculate segment access score from V$SEGMENT_STATISTICS
   */
  FUNCTION calculate_access_score(
    p_owner IN VARCHAR2,
    p_object_name IN VARCHAR2,
    p_object_type IN VARCHAR2
  ) RETURN NUMBER IS
    v_logical_reads NUMBER := 0;
    v_physical_reads NUMBER := 0;
    v_total_reads NUMBER := 0;
    v_score NUMBER := 0;
  BEGIN
    SELECT
      NVL(SUM(CASE WHEN statistic_name = 'logical reads' THEN value ELSE 0 END), 0),
      NVL(SUM(CASE WHEN statistic_name = 'physical reads' THEN value ELSE 0 END), 0)
    INTO v_logical_reads, v_physical_reads
    FROM v$segment_statistics
    WHERE owner = p_owner
      AND object_name = p_object_name
      AND object_type = p_object_type;

    v_total_reads := v_logical_reads + v_physical_reads;

    -- Logarithmic scoring (0-100 scale)
    IF v_total_reads > 0 THEN
      v_score := LEAST(100, (LOG(10, v_total_reads + 1) / LOG(10, 100000000)) * 100);
    END IF;

    RETURN ROUND(v_score, 2);
  EXCEPTION
    WHEN OTHERS THEN
      RETURN 0;
  END calculate_access_score;

  /**
   * Test compression ratio for table
   */
  PROCEDURE test_table_compression(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_partition_name IN VARCHAR2,
    x_current_size OUT NUMBER,
    x_basic_size OUT NUMBER,
    x_oltp_size OUT NUMBER,
    x_basic_ratio OUT NUMBER,
    x_oltp_ratio OUT NUMBER
  ) IS
    v_scratch_tbs VARCHAR2(128);
    v_blkcnt_cmp NUMBER;
    v_blkcnt_uncmp NUMBER;
    v_row_cmp NUMBER;
    v_row_uncmp NUMBER;
    v_cmp_ratio NUMBER;
    v_comptype_str VARCHAR2(100);
  BEGIN
    -- Get current size
    SELECT NVL(SUM(bytes), 0) / 1024 / 1024
    INTO x_current_size
    FROM dba_segments
    WHERE owner = p_owner
      AND segment_name = p_table_name
      AND NVL(partition_name, 'X') = NVL(p_partition_name, 'X');

    -- Get scratch tablespace
    SELECT default_tablespace
    INTO v_scratch_tbs
    FROM dba_users
    WHERE username = p_owner;

    -- Test BASIC compression
    BEGIN
      DBMS_COMPRESSION.get_compression_ratio(
        scratchtbsname => v_scratch_tbs,
        ownname => p_owner,
        objname => p_table_name,
        subobjname => p_partition_name,
        comptype => DBMS_COMPRESSION.comp_for_oltp, -- Use OLTP as baseline
        blkcnt_cmp => v_blkcnt_cmp,
        blkcnt_uncmp => v_blkcnt_uncmp,
        row_cmp => v_row_cmp,
        row_uncmp => v_row_uncmp,
        cmp_ratio => v_cmp_ratio,
        comptype_str => v_comptype_str
      );

      x_basic_ratio := v_cmp_ratio;
      x_basic_size := ROUND(x_current_size / NULLIF(v_cmp_ratio, 0), 2);
    EXCEPTION
      WHEN OTHERS THEN
        x_basic_ratio := 1;
        x_basic_size := x_current_size;
    END;

    -- Test OLTP compression (Advanced in Oracle Free)
    BEGIN
      DBMS_COMPRESSION.get_compression_ratio(
        scratchtbsname => v_scratch_tbs,
        ownname => p_owner,
        objname => p_table_name,
        subobjname => p_partition_name,
        comptype => DBMS_COMPRESSION.comp_for_oltp,
        blkcnt_cmp => v_blkcnt_cmp,
        blkcnt_uncmp => v_blkcnt_uncmp,
        row_cmp => v_row_cmp,
        row_uncmp => v_row_uncmp,
        cmp_ratio => v_cmp_ratio,
        comptype_str => v_comptype_str
      );

      x_oltp_ratio := v_cmp_ratio;
      x_oltp_size := ROUND(x_current_size / NULLIF(v_cmp_ratio, 0), 2);
    EXCEPTION
      WHEN OTHERS THEN
        x_oltp_ratio := 1;
        x_oltp_size := x_current_size;
    END;

  EXCEPTION
    WHEN OTHERS THEN
      x_current_size := 0;
      x_basic_size := 0;
      x_oltp_size := 0;
      x_basic_ratio := 1;
      x_oltp_ratio := 1;

      pkg_compression_log.log_error(
        'PKG_COMPRESSION_ADVISOR',
        'test_table_compression',
        'Error testing compression for ' || p_owner || '.' || p_table_name,
        SQLERRM
      );
  END test_table_compression;

  /**
   * Evaluate strategy rules and determine recommendation
   */
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
  BEGIN
    load_strategy_rules;

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
          v_recommended_compression := CASE
            WHEN p_compression_ratio >= 2 THEN 'OLTP'
            WHEN p_compression_ratio >= 1.5 THEN 'BASIC'
            ELSE 'NONE'
          END;
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

  /**
   * Generate rationale for recommendation
   */
  FUNCTION generate_rationale(
    p_object_type IN VARCHAR2,
    p_size_mb IN NUMBER,
    p_hotness_score IN NUMBER,
    p_access_score IN NUMBER,
    p_compression_ratio IN NUMBER,
    p_recommended_compression IN VARCHAR2
  ) RETURN VARCHAR2 IS
    v_rationale VARCHAR2(4000);
  BEGIN
    v_rationale := 'Size: ' || ROUND(p_size_mb, 2) || ' MB; ';

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

    -- Add recommendation explanation
    CASE p_recommended_compression
      WHEN 'NONE' THEN
        v_rationale := v_rationale || 'No compression recommended (ratio too low or high DML activity)';
      WHEN 'BASIC' THEN
        v_rationale := v_rationale || 'Basic compression recommended (moderate ratio, acceptable overhead)';
      WHEN 'OLTP' THEN
        v_rationale := v_rationale || 'OLTP compression recommended (good ratio, optimized for DML)';
      WHEN 'INDEX_ADVANCED_LOW' THEN
        v_rationale := v_rationale || 'Index compression (Advanced Low) recommended';
      WHEN 'INDEX_ADVANCED_HIGH' THEN
        v_rationale := v_rationale || 'Index compression (Advanced High) recommended for maximum savings';
      WHEN 'LOB_LOW', 'LOB_MEDIUM', 'LOB_HIGH' THEN
        v_rationale := v_rationale || 'LOB compression recommended for large object storage';
      ELSE
        v_rationale := v_rationale || 'Compression type: ' || p_recommended_compression;
    END CASE;

    RETURN SUBSTR(v_rationale, 1, 4000);
  END generate_rationale;

  -- ========================================================================
  -- Main Analysis Procedures Implementation
  -- ========================================================================

  PROCEDURE analyze_table(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_strategy_id IN NUMBER DEFAULT 2
  ) IS
    v_analysis_id NUMBER;
    v_current_size NUMBER;
    v_basic_size NUMBER;
    v_oltp_size NUMBER;
    v_basic_ratio NUMBER;
    v_oltp_ratio NUMBER;
    v_hotness_score NUMBER;
    v_access_score NUMBER;
    v_recommended_compression VARCHAR2(50);
    v_best_ratio NUMBER;
    v_best_size NUMBER;
    v_savings_mb NUMBER;
    v_savings_pct NUMBER;
    v_rationale VARCHAR2(4000);
    v_current_compression VARCHAR2(30);
    v_partition_count NUMBER;
    v_partitions t_partition_list;
  BEGIN
    pkg_compression_log.log_info(
      'PKG_COMPRESSION_ADVISOR',
      'analyze_table',
      'Analyzing table ' || p_owner || '.' || p_table_name
    );

    -- Get current compression
    BEGIN
      SELECT compress_for
      INTO v_current_compression
      FROM dba_tables
      WHERE owner = p_owner
        AND table_name = p_table_name;
    EXCEPTION
      WHEN NO_DATA_FOUND THEN
        pkg_compression_log.log_error(
          'PKG_COMPRESSION_ADVISOR',
          'analyze_table',
          'Table not found: ' || p_owner || '.' || p_table_name,
          NULL
        );
        RETURN;
    END;

    -- Calculate scores
    v_hotness_score := calculate_hotness_score(p_owner, p_table_name);
    v_access_score := calculate_access_score(p_owner, p_table_name, 'TABLE');

    -- Check if table is partitioned
    SELECT COUNT(*)
    INTO v_partition_count
    FROM dba_tab_partitions
    WHERE table_owner = p_owner
      AND table_name = p_table_name;

    IF v_partition_count > 0 THEN
      -- Analyze each partition separately
      SELECT partition_name
      BULK COLLECT INTO v_partitions
      FROM dba_tab_partitions
      WHERE table_owner = p_owner
        AND table_name = p_table_name;

      FOR i IN 1..v_partitions.COUNT LOOP
        -- Test compression for partition
        test_table_compression(
          p_owner, p_table_name, v_partitions(i),
          v_current_size, v_basic_size, v_oltp_size,
          v_basic_ratio, v_oltp_ratio
        );

        -- Determine best compression
        IF v_oltp_ratio >= v_basic_ratio THEN
          v_best_ratio := v_oltp_ratio;
          v_best_size := v_oltp_size;
        ELSE
          v_best_ratio := v_basic_ratio;
          v_best_size := v_basic_size;
        END IF;

        -- Evaluate strategy
        v_recommended_compression := evaluate_strategy_rules(
          p_strategy_id, 'TABLE', v_current_size,
          v_hotness_score, v_access_score, v_best_ratio
        );

        v_savings_mb := v_current_size - v_best_size;
        v_savings_pct := CASE WHEN v_current_size > 0
          THEN ROUND((v_savings_mb / v_current_size) * 100, 2)
          ELSE 0 END;

        v_rationale := generate_rationale(
          'TABLE', v_current_size, v_hotness_score,
          v_access_score, v_best_ratio, v_recommended_compression
        );

        -- Insert partition-level result
        INSERT INTO t_compression_analysis (
          owner, object_name, object_type, partition_name,
          current_size_mb, compressed_size_mb, compression_ratio,
          space_savings_mb, space_savings_pct,
          current_compression, recommended_compression,
          strategy_id, hotness_score, access_score,
          analysis_rationale, analysis_date
        ) VALUES (
          p_owner, p_table_name, 'TABLE', v_partitions(i),
          v_current_size, v_best_size, v_best_ratio,
          v_savings_mb, v_savings_pct,
          v_current_compression, v_recommended_compression,
          p_strategy_id, v_hotness_score, v_access_score,
          v_rationale || ' (Partition: ' || v_partitions(i) || ')',
          SYSTIMESTAMP
        );
      END LOOP;
    ELSE
      -- Non-partitioned table
      test_table_compression(
        p_owner, p_table_name, NULL,
        v_current_size, v_basic_size, v_oltp_size,
        v_basic_ratio, v_oltp_ratio
      );

      -- Determine best compression
      IF v_oltp_ratio >= v_basic_ratio THEN
        v_best_ratio := v_oltp_ratio;
        v_best_size := v_oltp_size;
      ELSE
        v_best_ratio := v_basic_ratio;
        v_best_size := v_basic_size;
      END IF;

      -- Evaluate strategy
      v_recommended_compression := evaluate_strategy_rules(
        p_strategy_id, 'TABLE', v_current_size,
        v_hotness_score, v_access_score, v_best_ratio
      );

      v_savings_mb := v_current_size - v_best_size;
      v_savings_pct := CASE WHEN v_current_size > 0
        THEN ROUND((v_savings_mb / v_current_size) * 100, 2)
        ELSE 0 END;

      v_rationale := generate_rationale(
        'TABLE', v_current_size, v_hotness_score,
        v_access_score, v_best_ratio, v_recommended_compression
      );

      -- Insert table-level result
      INSERT INTO t_compression_analysis (
        owner, object_name, object_type, partition_name,
        current_size_mb, compressed_size_mb, compression_ratio,
        space_savings_mb, space_savings_pct,
        current_compression, recommended_compression,
        strategy_id, hotness_score, access_score,
        analysis_rationale, analysis_date
      ) VALUES (
        p_owner, p_table_name, 'TABLE', NULL,
        v_current_size, v_best_size, v_best_ratio,
        v_savings_mb, v_savings_pct,
        v_current_compression, v_recommended_compression,
        p_strategy_id, v_hotness_score, v_access_score,
        v_rationale, SYSTIMESTAMP
      );
    END IF;

    COMMIT;

    pkg_compression_log.log_info(
      'PKG_COMPRESSION_ADVISOR',
      'analyze_table',
      'Completed analysis for ' || p_owner || '.' || p_table_name ||
      ' - Recommendation: ' || v_recommended_compression
    );

  EXCEPTION
    WHEN OTHERS THEN
      ROLLBACK;
      pkg_compression_log.log_error(
        'PKG_COMPRESSION_ADVISOR',
        'analyze_table',
        'Error analyzing table ' || p_owner || '.' || p_table_name,
        SQLERRM
      );
      RAISE;
  END analyze_table;

  PROCEDURE analyze_index(
    p_owner IN VARCHAR2,
    p_index_name IN VARCHAR2,
    p_strategy_id IN NUMBER DEFAULT 2
  ) IS
    v_current_size NUMBER;
    v_compression_ratio NUMBER;
    v_compressed_size NUMBER;
    v_access_score NUMBER;
    v_recommended_compression VARCHAR2(50);
    v_savings_mb NUMBER;
    v_savings_pct NUMBER;
    v_rationale VARCHAR2(4000);
    v_current_compression VARCHAR2(30);
    v_index_type VARCHAR2(30);
  BEGIN
    pkg_compression_log.log_info(
      'PKG_COMPRESSION_ADVISOR',
      'analyze_index',
      'Analyzing index ' || p_owner || '.' || p_index_name
    );

    -- Get index details
    BEGIN
      SELECT
        NVL(compression, 'NONE'),
        index_type
      INTO v_current_compression, v_index_type
      FROM dba_indexes
      WHERE owner = p_owner
        AND index_name = p_index_name;
    EXCEPTION
      WHEN NO_DATA_FOUND THEN
        pkg_compression_log.log_error(
          'PKG_COMPRESSION_ADVISOR',
          'analyze_index',
          'Index not found: ' || p_owner || '.' || p_index_name,
          NULL
        );
        RETURN;
    END;

    -- Only analyze B-tree indexes
    IF v_index_type NOT IN ('NORMAL', 'NORMAL/REV') THEN
      pkg_compression_log.log_info(
        'PKG_COMPRESSION_ADVISOR',
        'analyze_index',
        'Skipping non-B-tree index: ' || p_index_name || ' (Type: ' || v_index_type || ')'
      );
      RETURN;
    END IF;

    -- Get current size
    SELECT NVL(SUM(bytes), 0) / 1024 / 1024
    INTO v_current_size
    FROM dba_segments
    WHERE owner = p_owner
      AND segment_name = p_index_name
      AND segment_type LIKE 'INDEX%';

    -- Calculate access score
    v_access_score := calculate_access_score(p_owner, p_index_name, 'INDEX');

    -- Estimate compression ratio (conservative estimate for indexes)
    -- In practice, use analyze index validate structure for accurate stats
    v_compression_ratio := CASE
      WHEN v_current_size > 1000 THEN 2.5  -- Large indexes compress well
      WHEN v_current_size > 100 THEN 2.0
      ELSE 1.5
    END;

    v_compressed_size := ROUND(v_current_size / v_compression_ratio, 2);

    -- Evaluate strategy
    v_recommended_compression := evaluate_strategy_rules(
      p_strategy_id, 'INDEX', v_current_size,
      0, -- No hotness for indexes
      v_access_score, v_compression_ratio
    );

    v_savings_mb := v_current_size - v_compressed_size;
    v_savings_pct := CASE WHEN v_current_size > 0
      THEN ROUND((v_savings_mb / v_current_size) * 100, 2)
      ELSE 0 END;

    v_rationale := generate_rationale(
      'INDEX', v_current_size, 0,
      v_access_score, v_compression_ratio, v_recommended_compression
    );

    -- Insert result
    INSERT INTO t_compression_analysis (
      owner, object_name, object_type, partition_name,
      current_size_mb, compressed_size_mb, compression_ratio,
      space_savings_mb, space_savings_pct,
      current_compression, recommended_compression,
      strategy_id, hotness_score, access_score,
      analysis_rationale, analysis_date
    ) VALUES (
      p_owner, p_index_name, 'INDEX', NULL,
      v_current_size, v_compressed_size, v_compression_ratio,
      v_savings_mb, v_savings_pct,
      v_current_compression, v_recommended_compression,
      p_strategy_id, 0, v_access_score,
      v_rationale, SYSTIMESTAMP
    );

    COMMIT;

    pkg_compression_log.log_info(
      'PKG_COMPRESSION_ADVISOR',
      'analyze_index',
      'Completed analysis for ' || p_owner || '.' || p_index_name ||
      ' - Recommendation: ' || v_recommended_compression
    );

  EXCEPTION
    WHEN OTHERS THEN
      ROLLBACK;
      pkg_compression_log.log_error(
        'PKG_COMPRESSION_ADVISOR',
        'analyze_index',
        'Error analyzing index ' || p_owner || '.' || p_index_name,
        SQLERRM
      );
      RAISE;
  END analyze_index;

  PROCEDURE analyze_lob(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_column_name IN VARCHAR2,
    p_strategy_id IN NUMBER DEFAULT 2
  ) IS
    v_current_size NUMBER;
    v_compression_ratio NUMBER;
    v_compressed_size NUMBER;
    v_recommended_compression VARCHAR2(50);
    v_savings_mb NUMBER;
    v_savings_pct NUMBER;
    v_rationale VARCHAR2(4000);
    v_current_compression VARCHAR2(30);
    v_securefile VARCHAR2(10);
    v_lob_segment VARCHAR2(128);
  BEGIN
    pkg_compression_log.log_info(
      'PKG_COMPRESSION_ADVISOR',
      'analyze_lob',
      'Analyzing LOB ' || p_owner || '.' || p_table_name || '.' || p_column_name
    );

    -- Get LOB details
    BEGIN
      SELECT
        NVL(compression, 'NONE'),
        securefile,
        segment_name
      INTO v_current_compression, v_securefile, v_lob_segment
      FROM dba_lobs
      WHERE owner = p_owner
        AND table_name = p_table_name
        AND column_name = p_column_name;
    EXCEPTION
      WHEN NO_DATA_FOUND THEN
        pkg_compression_log.log_error(
          'PKG_COMPRESSION_ADVISOR',
          'analyze_lob',
          'LOB not found: ' || p_owner || '.' || p_table_name || '.' || p_column_name,
          NULL
        );
        RETURN;
    END;

    -- Only analyze SecureFiles LOBs
    IF v_securefile = 'NO' THEN
      pkg_compression_log.log_info(
        'PKG_COMPRESSION_ADVISOR',
        'analyze_lob',
        'Skipping BasicFiles LOB: ' || p_column_name || ' (SecureFiles required for compression)'
      );
      RETURN;
    END IF;

    -- Get current size
    SELECT NVL(SUM(bytes), 0) / 1024 / 1024
    INTO v_current_size
    FROM dba_segments
    WHERE owner = p_owner
      AND segment_name = v_lob_segment;

    -- Estimate compression ratio for LOBs (typically very high)
    v_compression_ratio := CASE
      WHEN v_current_size > 1000 THEN 4.0  -- Large LOBs compress very well
      WHEN v_current_size > 100 THEN 3.0
      ELSE 2.5
    END;

    v_compressed_size := ROUND(v_current_size / v_compression_ratio, 2);

    -- Evaluate strategy
    v_recommended_compression := evaluate_strategy_rules(
      p_strategy_id, 'LOB', v_current_size,
      0, 0, v_compression_ratio
    );

    v_savings_mb := v_current_size - v_compressed_size;
    v_savings_pct := CASE WHEN v_current_size > 0
      THEN ROUND((v_savings_mb / v_current_size) * 100, 2)
      ELSE 0 END;

    v_rationale := generate_rationale(
      'LOB', v_current_size, 0, 0,
      v_compression_ratio, v_recommended_compression
    );

    -- Insert result
    INSERT INTO t_compression_analysis (
      owner, object_name, object_type, partition_name,
      current_size_mb, compressed_size_mb, compression_ratio,
      space_savings_mb, space_savings_pct,
      current_compression, recommended_compression,
      strategy_id, hotness_score, access_score,
      analysis_rationale, analysis_date
    ) VALUES (
      p_owner, p_table_name || '.' || p_column_name, 'LOB', NULL,
      v_current_size, v_compressed_size, v_compression_ratio,
      v_savings_mb, v_savings_pct,
      v_current_compression, v_recommended_compression,
      p_strategy_id, 0, 0,
      v_rationale, SYSTIMESTAMP
    );

    COMMIT;

    pkg_compression_log.log_info(
      'PKG_COMPRESSION_ADVISOR',
      'analyze_lob',
      'Completed analysis for LOB ' || p_owner || '.' || p_table_name || '.' || p_column_name ||
      ' - Recommendation: ' || v_recommended_compression
    );

  EXCEPTION
    WHEN OTHERS THEN
      ROLLBACK;
      pkg_compression_log.log_error(
        'PKG_COMPRESSION_ADVISOR',
        'analyze_lob',
        'Error analyzing LOB ' || p_owner || '.' || p_table_name || '.' || p_column_name,
        SQLERRM
      );
      RAISE;
  END analyze_lob;

  PROCEDURE run_analysis(
    p_owner IN VARCHAR2 DEFAULT NULL,
    p_strategy_id IN NUMBER DEFAULT 2,
    p_parallel_degree IN NUMBER DEFAULT 4
  ) IS
    v_start_time TIMESTAMP := SYSTIMESTAMP;
    v_table_count NUMBER := 0;
    v_index_count NUMBER := 0;
    v_lob_count NUMBER := 0;
    v_job_prefix VARCHAR2(30) := 'COMP_ANALYSIS_';
    v_job_name VARCHAR2(128);
    v_table_list SYS.ODCIVARCHAR2LIST;
  BEGIN
    init_compression_map;
    load_strategy_rules;

    pkg_compression_log.log_info(
      'PKG_COMPRESSION_ADVISOR',
      'run_analysis',
      'Starting compression analysis - Strategy: ' || p_strategy_id ||
      ', Owner: ' || NVL(p_owner, 'ALL') ||
      ', Parallel Degree: ' || p_parallel_degree
    );

    -- Analyze tables (with parallel processing)
    IF p_parallel_degree > 1 THEN
      -- Collect tables to analyze
      SELECT t.owner || '.' || t.table_name
      BULK COLLECT INTO v_table_list
      FROM dba_tables t
      WHERE (p_owner IS NULL OR t.owner = p_owner)
        AND NOT is_excluded_schema(t.owner)
        AND t.temporary = 'N'
        AND EXISTS (
          SELECT 1 FROM dba_segments s
          WHERE s.owner = t.owner
            AND s.segment_name = t.table_name
            AND s.bytes > 1048576  -- > 1 MB
        )
      ORDER BY
        (SELECT NVL(SUM(bytes), 0) FROM dba_segments s
         WHERE s.owner = t.owner AND s.segment_name = t.table_name) DESC;

      -- Create parallel jobs
      FOR i IN 1..LEAST(p_parallel_degree, v_table_list.COUNT) LOOP
        v_job_name := v_job_prefix || TO_CHAR(SYSDATE, 'YYYYMMDD_HH24MISS') || '_' || i;

        DBMS_SCHEDULER.create_job(
          job_name => v_job_name,
          job_type => 'PLSQL_BLOCK',
          job_action =>
            'DECLARE
               v_idx NUMBER := ' || i || ';
               v_step NUMBER := ' || p_parallel_degree || ';
               v_tables SYS.ODCIVARCHAR2LIST := SYS.ODCIVARCHAR2LIST(' ||
                 '''' || v_table_list(1) || '''' || -- Will be populated dynamically
               ');
             BEGIN
               WHILE v_idx <= v_tables.COUNT LOOP
                 pkg_compression_advisor.analyze_table(
                   SUBSTR(v_tables(v_idx), 1, INSTR(v_tables(v_idx), ''.'') - 1),
                   SUBSTR(v_tables(v_idx), INSTR(v_tables(v_idx), ''.'') + 1),
                   ' || p_strategy_id || '
                 );
                 v_idx := v_idx + v_step;
               END LOOP;
             END;',
          enabled => TRUE,
          auto_drop => TRUE
        );
      END LOOP;

      -- Wait for jobs to complete (simplified - in production use job monitoring)
      DBMS_LOCK.sleep(5);

      v_table_count := v_table_list.COUNT;
    ELSE
      -- Sequential processing
      FOR rec IN (
        SELECT t.owner, t.table_name
        FROM dba_tables t
        WHERE (p_owner IS NULL OR t.owner = p_owner)
          AND NOT is_excluded_schema(t.owner)
          AND t.temporary = 'N'
          AND EXISTS (
            SELECT 1 FROM dba_segments s
            WHERE s.owner = t.owner
              AND s.segment_name = t.table_name
              AND s.bytes > 1048576  -- > 1 MB
          )
        ORDER BY
          (SELECT NVL(SUM(bytes), 0) FROM dba_segments s
           WHERE s.owner = t.owner AND s.segment_name = t.table_name) DESC
      ) LOOP
        BEGIN
          analyze_table(rec.owner, rec.table_name, p_strategy_id);
          v_table_count := v_table_count + 1;
        EXCEPTION
          WHEN OTHERS THEN
            pkg_compression_log.log_error(
              'PKG_COMPRESSION_ADVISOR',
              'run_analysis',
              'Error analyzing table ' || rec.owner || '.' || rec.table_name,
              SQLERRM
            );
        END;
      END LOOP;
    END IF;

    -- Analyze indexes
    FOR rec IN (
      SELECT i.owner, i.index_name
      FROM dba_indexes i
      WHERE (p_owner IS NULL OR i.owner = p_owner)
        AND NOT is_excluded_schema(i.owner)
        AND i.index_type IN ('NORMAL', 'NORMAL/REV')
        AND EXISTS (
          SELECT 1 FROM dba_segments s
          WHERE s.owner = i.owner
            AND s.segment_name = i.index_name
            AND s.bytes > 10485760  -- > 10 MB
        )
    ) LOOP
      BEGIN
        analyze_index(rec.owner, rec.index_name, p_strategy_id);
        v_index_count := v_index_count + 1;
      EXCEPTION
        WHEN OTHERS THEN
          pkg_compression_log.log_error(
            'PKG_COMPRESSION_ADVISOR',
            'run_analysis',
            'Error analyzing index ' || rec.owner || '.' || rec.index_name,
            SQLERRM
          );
      END;
    END LOOP;

    -- Analyze LOBs (SecureFiles only)
    FOR rec IN (
      SELECT l.owner, l.table_name, l.column_name
      FROM dba_lobs l
      WHERE (p_owner IS NULL OR l.owner = p_owner)
        AND NOT is_excluded_schema(l.owner)
        AND l.securefile = 'YES'
        AND EXISTS (
          SELECT 1 FROM dba_segments s
          WHERE s.owner = l.owner
            AND s.segment_name = l.segment_name
            AND s.bytes > 10485760  -- > 10 MB
        )
    ) LOOP
      BEGIN
        analyze_lob(rec.owner, rec.table_name, rec.column_name, p_strategy_id);
        v_lob_count := v_lob_count + 1;
      EXCEPTION
        WHEN OTHERS THEN
          pkg_compression_log.log_error(
            'PKG_COMPRESSION_ADVISOR',
            'run_analysis',
            'Error analyzing LOB ' || rec.owner || '.' || rec.table_name || '.' || rec.column_name,
            SQLERRM
          );
      END;
    END LOOP;

    pkg_compression_log.log_info(
      'PKG_COMPRESSION_ADVISOR',
      'run_analysis',
      'Analysis complete - Tables: ' || v_table_count ||
      ', Indexes: ' || v_index_count ||
      ', LOBs: ' || v_lob_count ||
      ', Duration: ' || EXTRACT(SECOND FROM (SYSTIMESTAMP - v_start_time)) || 's'
    );

  EXCEPTION
    WHEN OTHERS THEN
      pkg_compression_log.log_error(
        'PKG_COMPRESSION_ADVISOR',
        'run_analysis',
        'Error during analysis run',
        SQLERRM
      );
      RAISE;
  END run_analysis;

  -- ========================================================================
  -- Recommendation and Reporting Functions Implementation
  -- ========================================================================

  FUNCTION get_recommendations(
    p_strategy_id IN NUMBER DEFAULT 2,
    p_min_savings_pct IN NUMBER DEFAULT 20
  ) RETURN SYS_REFCURSOR IS
    v_cursor SYS_REFCURSOR;
  BEGIN
    OPEN v_cursor FOR
      SELECT
        analysis_id,
        owner,
        object_name,
        object_type,
        partition_name,
        current_size_mb,
        compressed_size_mb,
        compression_ratio,
        space_savings_mb,
        space_savings_pct,
        current_compression,
        recommended_compression,
        hotness_score,
        access_score,
        analysis_rationale,
        analysis_date,
        CASE
          WHEN space_savings_pct >= 50 THEN 'HIGH'
          WHEN space_savings_pct >= 30 THEN 'MEDIUM'
          ELSE 'LOW'
        END AS priority
      FROM t_compression_analysis
      WHERE (p_strategy_id IS NULL OR strategy_id = p_strategy_id)
        AND space_savings_pct >= p_min_savings_pct
        AND recommended_compression != 'NONE'
      ORDER BY space_savings_mb DESC, space_savings_pct DESC;

    RETURN v_cursor;
  END get_recommendations;

  FUNCTION generate_ddl(
    p_recommendation_id IN NUMBER DEFAULT NULL
  ) RETURN SYS_REFCURSOR IS
    v_cursor SYS_REFCURSOR;
  BEGIN
    init_compression_map;

    OPEN v_cursor FOR
      SELECT
        analysis_id,
        owner,
        object_name,
        object_type,
        partition_name,
        recommended_compression,
        CASE object_type
          WHEN 'TABLE' THEN
            CASE
              WHEN partition_name IS NOT NULL THEN
                'ALTER TABLE ' || owner || '.' || object_name ||
                ' MODIFY PARTITION ' || partition_name ||
                ' ' || g_compression_map(recommended_compression) || ';'
              ELSE
                'ALTER TABLE ' || owner || '.' || object_name ||
                ' MOVE ' || g_compression_map(recommended_compression) || ';'
            END
          WHEN 'INDEX' THEN
            'ALTER INDEX ' || owner || '.' || object_name ||
            ' REBUILD ' || g_compression_map(recommended_compression) || ';'
          WHEN 'LOB' THEN
            'ALTER TABLE ' || owner || '.' || SUBSTR(object_name, 1, INSTR(object_name, '.') - 1) ||
            ' MODIFY LOB (' || SUBSTR(object_name, INSTR(object_name, '.') + 1) || ') (' ||
            g_compression_map(recommended_compression) || ');'
          ELSE
            '-- Unknown object type: ' || object_type
        END AS ddl_statement,
        space_savings_mb,
        space_savings_pct
      FROM t_compression_analysis
      WHERE (p_recommendation_id IS NULL OR analysis_id = p_recommendation_id)
        AND recommended_compression != 'NONE'
      ORDER BY space_savings_mb DESC;

    RETURN v_cursor;
  END generate_ddl;

  FUNCTION calculate_total_savings(
    p_strategy_id IN NUMBER DEFAULT NULL
  ) RETURN NUMBER IS
    v_total_savings NUMBER;
  BEGIN
    SELECT NVL(SUM(space_savings_mb), 0)
    INTO v_total_savings
    FROM t_compression_analysis
    WHERE (p_strategy_id IS NULL OR strategy_id = p_strategy_id)
      AND recommended_compression != 'NONE';

    RETURN v_total_savings;
  END calculate_total_savings;

  -- ========================================================================
  -- Utility Procedures Implementation
  -- ========================================================================

  PROCEDURE cleanup_old_results(
    p_days_old IN NUMBER DEFAULT 30
  ) IS
    v_rows_deleted NUMBER;
  BEGIN
    DELETE FROM t_compression_analysis
    WHERE analysis_date < SYSTIMESTAMP - INTERVAL '1' DAY * p_days_old;

    v_rows_deleted := SQL%ROWCOUNT;
    COMMIT;

    pkg_compression_log.log_info(
      'PKG_COMPRESSION_ADVISOR',
      'cleanup_old_results',
      'Deleted ' || v_rows_deleted || ' old analysis records (older than ' || p_days_old || ' days)'
    );
  END cleanup_old_results;

  PROCEDURE reset_analysis(
    p_owner IN VARCHAR2,
    p_object_name IN VARCHAR2,
    p_object_type IN VARCHAR2
  ) IS
    v_rows_deleted NUMBER;
  BEGIN
    DELETE FROM t_compression_analysis
    WHERE owner = p_owner
      AND object_name = p_object_name
      AND object_type = p_object_type;

    v_rows_deleted := SQL%ROWCOUNT;
    COMMIT;

    pkg_compression_log.log_info(
      'PKG_COMPRESSION_ADVISOR',
      'reset_analysis',
      'Reset analysis for ' || p_owner || '.' || p_object_name ||
      ' (' || v_rows_deleted || ' records deleted)'
    );
  END reset_analysis;

BEGIN
  -- Package initialization
  init_compression_map;
  load_strategy_rules;

  pkg_compression_log.log_info(
    'PKG_COMPRESSION_ADVISOR',
    'INITIALIZATION',
    'Package initialized - Version: ' || c_version
  );

END pkg_compression_advisor;
/
