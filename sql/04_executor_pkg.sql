--------------------------------------------------------------------------------
-- Package: PKG_COMPRESSION_EXECUTOR
-- Purpose: Execute compression operations with safety checks and logging
-- Author: Daniel Moya (copyright), GitHub: github.com/danimoya Website: danielmoya.cv
-- Date: 2025-11-13
--------------------------------------------------------------------------------

--------------------------------------------------------------------------------
-- PACKAGE SPECIFICATION
--------------------------------------------------------------------------------
CREATE OR REPLACE PACKAGE PKG_COMPRESSION_EXECUTOR AS

  -- Constants for compression types
  C_COMPRESS_BASIC     CONSTANT VARCHAR2(30) := 'BASIC';
  C_COMPRESS_OLTP      CONSTANT VARCHAR2(30) := 'OLTP';
  C_COMPRESS_ADV_LOW   CONSTANT VARCHAR2(30) := 'ADV_LOW';
  C_COMPRESS_ADV_HIGH  CONSTANT VARCHAR2(30) := 'ADV_HIGH';
  C_NOCOMPRESS         CONSTANT VARCHAR2(30) := 'NOCOMPRESS';

  -- Exception codes
  E_OBJECT_NOT_FOUND   EXCEPTION;
  E_INVALID_COMPRESSION_TYPE EXCEPTION;
  E_OBJECT_LOCKED      EXCEPTION;
  E_INSUFFICIENT_SPACE EXCEPTION;
  E_DEPENDENCY_EXISTS  EXCEPTION;

  PRAGMA EXCEPTION_INIT(E_OBJECT_NOT_FOUND, -20001);
  PRAGMA EXCEPTION_INIT(E_INVALID_COMPRESSION_TYPE, -20002);
  PRAGMA EXCEPTION_INIT(E_OBJECT_LOCKED, -20003);
  PRAGMA EXCEPTION_INIT(E_INSUFFICIENT_SPACE, -20004);
  PRAGMA EXCEPTION_INIT(E_DEPENDENCY_EXISTS, -20005);

  /**
   * Compress a table with comprehensive safety checks
   *
   * @param p_owner           Table owner
   * @param p_table_name      Table name
   * @param p_compression_type Compression type (BASIC, OLTP, NOCOMPRESS)
   * @param p_online          Use ONLINE clause if supported
   * @param p_dry_run         Generate DDL without executing
   */
  PROCEDURE compress_table(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_compression_type IN VARCHAR2,
    p_online IN BOOLEAN DEFAULT TRUE,
    p_dry_run IN BOOLEAN DEFAULT FALSE
  );

  /**
   * Compress an index with validation
   *
   * @param p_owner           Index owner
   * @param p_index_name      Index name
   * @param p_compression_type Compression type (ADV_LOW, ADV_HIGH, NOCOMPRESS)
   * @param p_online          Use ONLINE clause
   */
  PROCEDURE compress_index(
    p_owner IN VARCHAR2,
    p_index_name IN VARCHAR2,
    p_compression_type IN VARCHAR2,
    p_online IN BOOLEAN DEFAULT TRUE
  );

  /**
   * Compress a table partition preserving tablespace
   *
   * @param p_owner           Table owner
   * @param p_table_name      Table name
   * @param p_partition_name  Partition name
   * @param p_compression_type Compression type
   * @param p_online          Use ONLINE clause if supported
   */
  PROCEDURE compress_partition(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_partition_name IN VARCHAR2,
    p_compression_type IN VARCHAR2,
    p_online IN BOOLEAN DEFAULT TRUE
  );

  /**
   * Compress all partitions of a table preserving tablespaces
   *
   * @param p_owner           Table owner
   * @param p_table_name      Table name
   * @param p_compression_type Compression type
   * @param p_online          Use ONLINE clause if supported
   */
  PROCEDURE compress_all_partitions(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_compression_type IN VARCHAR2,
    p_online IN BOOLEAN DEFAULT TRUE
  );

  /**
   * Compress LOBs preserving tablespace
   *
   * @param p_owner           Table owner
   * @param p_table_name      Table name
   * @param p_column_name     LOB column name
   * @param p_compression_type Compression type
   */
  PROCEDURE compress_lob(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_column_name IN VARCHAR2,
    p_compression_type IN VARCHAR2
  );

  /**
   * Execute compression recommendations based on strategy
   *
   * @param p_strategy_id     Strategy ID (1=Conservative, 2=Moderate, 3=Aggressive)
   * @param p_max_tables      Maximum number of tables to process
   * @param p_max_size_gb     Maximum total size to process (GB)
   */
  PROCEDURE execute_recommendations(
    p_strategy_id IN NUMBER DEFAULT 2,
    p_max_tables IN NUMBER DEFAULT 10,
    p_max_size_gb IN NUMBER DEFAULT 100
  );

  /**
   * Rollback compression to original state
   *
   * @param p_history_id      History record ID to rollback
   */
  PROCEDURE rollback_compression(
    p_history_id IN NUMBER
  );

  /**
   * Get compression operation status
   *
   * @param p_history_id      History record ID
   * @return                  Status (SUCCESS, FAILED, IN_PROGRESS)
   */
  FUNCTION get_compression_status(
    p_history_id IN NUMBER
  ) RETURN VARCHAR2;

  /**
   * Validate object before compression
   *
   * @param p_owner           Object owner
   * @param p_object_name     Object name
   * @param p_object_type     Object type (TABLE, INDEX)
   * @return                  TRUE if valid for compression
   */
  FUNCTION validate_object(
    p_owner IN VARCHAR2,
    p_object_name IN VARCHAR2,
    p_object_type IN VARCHAR2
  ) RETURN BOOLEAN;

  /**
   * Get estimated compression ratio
   *
   * @param p_owner           Table owner
   * @param p_table_name      Table name
   * @param p_compression_type Target compression type
   * @return                  Estimated compression ratio
   */
  FUNCTION estimate_compression_ratio(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_compression_type IN VARCHAR2
  ) RETURN NUMBER;

END PKG_COMPRESSION_EXECUTOR;
/

--------------------------------------------------------------------------------
-- PACKAGE BODY
--------------------------------------------------------------------------------
CREATE OR REPLACE PACKAGE BODY PKG_COMPRESSION_EXECUTOR AS

  -- Private helper procedures

  /**
   * Log execution message
   */
  PROCEDURE log_message(
    p_message IN VARCHAR2,
    p_level IN VARCHAR2 DEFAULT 'INFO'
  ) IS
    PRAGMA AUTONOMOUS_TRANSACTION;
  BEGIN
    DBMS_OUTPUT.PUT_LINE('[' || p_level || '] ' || TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS.FF3') || ' - ' || p_message);
    COMMIT;
  END log_message;

  /**
   * Check if object is locked
   */
  FUNCTION is_object_locked(
    p_owner IN VARCHAR2,
    p_object_name IN VARCHAR2
  ) RETURN BOOLEAN IS
    v_locked NUMBER;
  BEGIN
    SELECT COUNT(*)
    INTO v_locked
    FROM DBA_LOCKS l
    JOIN DBA_OBJECTS o ON l.ID1 = o.OBJECT_ID
    WHERE o.OWNER = p_owner
      AND o.OBJECT_NAME = p_object_name
      AND l.LOCKED_MODE > 0;

    RETURN v_locked > 0;
  END is_object_locked;

  /**
   * Get current segment size in bytes
   */
  FUNCTION get_segment_size(
    p_owner IN VARCHAR2,
    p_segment_name IN VARCHAR2,
    p_segment_type IN VARCHAR2
  ) RETURN NUMBER IS
    v_bytes NUMBER;
  BEGIN
    SELECT NVL(SUM(bytes), 0)
    INTO v_bytes
    FROM DBA_SEGMENTS
    WHERE owner = p_owner
      AND segment_name = p_segment_name
      AND segment_type = p_segment_type;

    RETURN v_bytes;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RETURN 0;
  END get_segment_size;

  /**
   * Get compression clause for DDL
   */
  FUNCTION get_compression_clause(
    p_compression_type IN VARCHAR2
  ) RETURN VARCHAR2 IS
  BEGIN
    CASE UPPER(p_compression_type)
      WHEN C_COMPRESS_BASIC THEN
        RETURN 'COMPRESS BASIC';
      WHEN C_COMPRESS_OLTP THEN
        RETURN 'COMPRESS FOR OLTP';
      WHEN C_COMPRESS_ADV_LOW THEN
        RETURN 'COMPRESS ADVANCED LOW';
      WHEN C_COMPRESS_ADV_HIGH THEN
        RETURN 'COMPRESS ADVANCED HIGH';
      WHEN C_NOCOMPRESS THEN
        RETURN 'NOCOMPRESS';
      ELSE
        RAISE_APPLICATION_ERROR(-20002, 'Invalid compression type: ' || p_compression_type);
    END CASE;
  END get_compression_clause;

  /**
   * Check tablespace free space
   */
  FUNCTION has_sufficient_space(
    p_tablespace_name IN VARCHAR2,
    p_required_bytes IN NUMBER
  ) RETURN BOOLEAN IS
    v_free_bytes NUMBER;
  BEGIN
    SELECT NVL(SUM(bytes), 0)
    INTO v_free_bytes
    FROM DBA_FREE_SPACE
    WHERE tablespace_name = p_tablespace_name;

    -- Require at least 2x the current size for safety
    RETURN v_free_bytes >= (p_required_bytes * 2);
  END has_sufficient_space;

  /**
   * Rebuild indexes for a table
   * CRITICAL: Preserves original tablespace for each index
   */
  PROCEDURE rebuild_table_indexes(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_online IN BOOLEAN
  ) IS
    v_ddl VARCHAR2(4000);
    v_tablespace_name VARCHAR2(128);
  BEGIN
    log_message('Rebuilding indexes for ' || p_owner || '.' || p_table_name);

    FOR idx IN (
      SELECT i.index_name, i.tablespace_name
      FROM DBA_INDEXES i
      WHERE i.table_owner = p_owner
        AND i.table_name = p_table_name
        AND i.index_type NOT IN ('LOB', 'IOT - TOP')
    ) LOOP
      v_ddl := 'ALTER INDEX ' || p_owner || '.' || idx.index_name || ' REBUILD';

      -- CRITICAL: Preserve original index tablespace
      IF idx.tablespace_name IS NOT NULL THEN
        v_ddl := v_ddl || ' TABLESPACE ' || idx.tablespace_name;
        log_message('Preserving index tablespace: ' || idx.tablespace_name || ' for ' || idx.index_name);
      END IF;

      IF p_online THEN
        v_ddl := v_ddl || ' ONLINE';
      END IF;

      BEGIN
        EXECUTE IMMEDIATE v_ddl;
        log_message('Rebuilt index: ' || idx.index_name);
      EXCEPTION
        WHEN OTHERS THEN
          log_message('Warning: Failed to rebuild index ' || idx.index_name || ': ' || SQLERRM, 'WARN');
      END;
    END LOOP;
  END rebuild_table_indexes;

  /**
   * Gather table statistics
   */
  PROCEDURE gather_stats(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2
  ) IS
  BEGIN
    log_message('Gathering statistics for ' || p_owner || '.' || p_table_name);

    DBMS_STATS.GATHER_TABLE_STATS(
      ownname => p_owner,
      tabname => p_table_name,
      estimate_percent => DBMS_STATS.AUTO_SAMPLE_SIZE,
      method_opt => 'FOR ALL COLUMNS SIZE AUTO',
      degree => DBMS_STATS.AUTO_DEGREE,
      cascade => TRUE
    );

    log_message('Statistics gathered successfully');
  EXCEPTION
    WHEN OTHERS THEN
      log_message('Warning: Failed to gather statistics: ' || SQLERRM, 'WARN');
  END gather_stats;

  -- Public procedures implementation

  /**
   * Validate object before compression
   */
  FUNCTION validate_object(
    p_owner IN VARCHAR2,
    p_object_name IN VARCHAR2,
    p_object_type IN VARCHAR2
  ) RETURN BOOLEAN IS
    v_exists NUMBER;
    v_tablespace_name VARCHAR2(30);
    v_size_bytes NUMBER;
  BEGIN
    -- Check if object exists
    SELECT COUNT(*)
    INTO v_exists
    FROM DBA_OBJECTS
    WHERE owner = p_owner
      AND object_name = p_object_name
      AND object_type = p_object_type;

    IF v_exists = 0 THEN
      RAISE_APPLICATION_ERROR(-20001, 'Object not found: ' || p_owner || '.' || p_object_name);
    END IF;

    -- Check if object is locked
    IF is_object_locked(p_owner, p_object_name) THEN
      RAISE_APPLICATION_ERROR(-20003, 'Object is locked: ' || p_owner || '.' || p_object_name);
    END IF;

    -- Check tablespace space for tables
    IF p_object_type = 'TABLE' THEN
      SELECT tablespace_name
      INTO v_tablespace_name
      FROM DBA_TABLES
      WHERE owner = p_owner
        AND table_name = p_object_name;

      v_size_bytes := get_segment_size(p_owner, p_object_name, 'TABLE');

      IF NOT has_sufficient_space(v_tablespace_name, v_size_bytes) THEN
        RAISE_APPLICATION_ERROR(-20004, 'Insufficient tablespace space for: ' || p_owner || '.' || p_object_name);
      END IF;
    END IF;

    RETURN TRUE;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RAISE_APPLICATION_ERROR(-20001, 'Object metadata not found: ' || p_owner || '.' || p_object_name);
  END validate_object;

  /**
   * Estimate compression ratio
   */
  FUNCTION estimate_compression_ratio(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_compression_type IN VARCHAR2
  ) RETURN NUMBER IS
    v_ratio NUMBER;
  BEGIN
    -- Conservative estimates based on Oracle documentation
    -- Actual ratios depend on data characteristics
    CASE UPPER(p_compression_type)
      WHEN C_COMPRESS_BASIC THEN
        v_ratio := 2.0;  -- 2x compression
      WHEN C_COMPRESS_OLTP THEN
        v_ratio := 2.5;  -- 2.5x compression
      WHEN C_NOCOMPRESS THEN
        v_ratio := 1.0;  -- No compression
      ELSE
        v_ratio := 1.5;  -- Conservative default
    END CASE;

    RETURN v_ratio;
  END estimate_compression_ratio;

  /**
   * Compress a table
   * CRITICAL: Preserves original tablespace during compression operations
   * Handles regular tables, partitioned tables, IOTs, and LOBs
   */
  PROCEDURE compress_table(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_compression_type IN VARCHAR2,
    p_online IN BOOLEAN DEFAULT TRUE,
    p_dry_run IN BOOLEAN DEFAULT FALSE
  ) IS
    v_ddl VARCHAR2(4000);
    v_history_id NUMBER;
    v_size_before NUMBER;
    v_size_after NUMBER;
    v_compression_clause VARCHAR2(100);
    v_current_compression VARCHAR2(30);
    v_tablespace_name VARCHAR2(128);  -- Store original tablespace
    v_iot_type VARCHAR2(12);
    v_partitioned VARCHAR2(3);
  BEGIN
    log_message('=== Starting table compression ===');
    log_message('Table: ' || p_owner || '.' || p_table_name);
    log_message('Compression Type: ' || p_compression_type);
    log_message('Dry Run: ' || CASE WHEN p_dry_run THEN 'YES' ELSE 'NO' END);

    -- Validate object
    IF NOT validate_object(p_owner, p_table_name, 'TABLE') THEN
      RETURN;
    END IF;

    -- Get current state including tablespace and table type
    -- CRITICAL: Query tablespace to preserve it during MOVE operation
    SELECT NVL(compression, 'DISABLED'),
           tablespace_name,
           iot_type,
           partitioned
    INTO v_current_compression,
         v_tablespace_name,
         v_iot_type,
         v_partitioned
    FROM DBA_TABLES
    WHERE owner = p_owner
      AND table_name = p_table_name;

    v_size_before := get_segment_size(p_owner, p_table_name, 'TABLE');

    log_message('Current compression: ' || v_current_compression);
    log_message('Current tablespace: ' || NVL(v_tablespace_name, 'NULL'));
    log_message('Table type: ' || CASE WHEN v_iot_type IS NOT NULL THEN 'IOT'
                                       WHEN v_partitioned = 'YES' THEN 'PARTITIONED'
                                       ELSE 'REGULAR' END);
    log_message('Current size: ' || ROUND(v_size_before / 1024 / 1024, 2) || ' MB');

    -- Get compression clause
    v_compression_clause := get_compression_clause(p_compression_type);

    -- Build DDL with TABLESPACE preservation
    -- For non-partitioned tables, include TABLESPACE clause to preserve location
    IF v_partitioned = 'NO' THEN
      v_ddl := 'ALTER TABLE ' || p_owner || '.' || p_table_name || ' MOVE ' || v_compression_clause;

      -- CRITICAL: Add TABLESPACE clause to preserve original tablespace
      IF v_tablespace_name IS NOT NULL THEN
        v_ddl := v_ddl || ' TABLESPACE ' || v_tablespace_name;
        log_message('Preserving tablespace: ' || v_tablespace_name);
      END IF;

    ELSE
      -- For partitioned tables, use different approach
      log_message('WARNING: Partitioned table detected. Use compress_partition for individual partitions.');
      v_ddl := 'ALTER TABLE ' || p_owner || '.' || p_table_name || ' MOVE ' || v_compression_clause;
    END IF;

    IF p_online AND p_compression_type IN (C_COMPRESS_BASIC, C_COMPRESS_OLTP) THEN
      v_ddl := v_ddl || ' ONLINE';
    END IF;

    log_message('DDL: ' || v_ddl);

    IF p_dry_run THEN
      log_message('DRY RUN - DDL generated but not executed');
      RETURN;
    END IF;

    -- Create history record
    INSERT INTO T_COMPRESSION_HISTORY (
      owner, object_name, object_type,
      compression_before, compression_after,
      size_before_bytes, operation_type,
      executed_by, ddl_statement
    ) VALUES (
      p_owner, p_table_name, 'TABLE',
      v_current_compression, p_compression_type,
      v_size_before, 'COMPRESS',
      USER, v_ddl
    ) RETURNING history_id INTO v_history_id;

    COMMIT;

    -- Execute DDL
    BEGIN
      log_message('Executing compression...');
      EXECUTE IMMEDIATE v_ddl;
      log_message('Table compressed successfully');

      -- Rebuild indexes
      rebuild_table_indexes(p_owner, p_table_name, p_online);

      -- Gather statistics
      gather_stats(p_owner, p_table_name);

      -- Get new size
      v_size_after := get_segment_size(p_owner, p_table_name, 'TABLE');

      -- Update history
      UPDATE T_COMPRESSION_HISTORY
      SET size_after_bytes = v_size_after,
          space_saved_bytes = v_size_before - v_size_after,
          compression_ratio = CASE WHEN v_size_after > 0 THEN v_size_before / v_size_after ELSE 0 END,
          status = 'SUCCESS',
          end_time = SYSTIMESTAMP,
          execution_time_seconds = EXTRACT(SECOND FROM (SYSTIMESTAMP - start_time))
      WHERE history_id = v_history_id;

      COMMIT;

      log_message('New size: ' || ROUND(v_size_after / 1024 / 1024, 2) || ' MB');
      log_message('Space saved: ' || ROUND((v_size_before - v_size_after) / 1024 / 1024, 2) || ' MB');
      log_message('Compression ratio: ' || ROUND(v_size_before / NULLIF(v_size_after, 0), 2) || ':1');
      log_message('=== Compression completed successfully ===');

    EXCEPTION
      WHEN OTHERS THEN
        -- Update history with error
        UPDATE T_COMPRESSION_HISTORY
        SET status = 'FAILED',
            error_message = SUBSTR(SQLERRM, 1, 4000),
            end_time = SYSTIMESTAMP
        WHERE history_id = v_history_id;

        COMMIT;

        log_message('ERROR: ' || SQLERRM, 'ERROR');
        RAISE;
    END;

  EXCEPTION
    WHEN OTHERS THEN
      log_message('FATAL ERROR: ' || SQLERRM, 'ERROR');
      RAISE;
  END compress_table;

  /**
   * Compress an index
   */
  PROCEDURE compress_index(
    p_owner IN VARCHAR2,
    p_index_name IN VARCHAR2,
    p_compression_type IN VARCHAR2,
    p_online IN BOOLEAN DEFAULT TRUE
  ) IS
    v_ddl VARCHAR2(4000);
    v_history_id NUMBER;
    v_size_before NUMBER;
    v_size_after NUMBER;
    v_compression_clause VARCHAR2(100);
  BEGIN
    log_message('=== Starting index compression ===');
    log_message('Index: ' || p_owner || '.' || p_index_name);
    log_message('Compression Type: ' || p_compression_type);

    -- Validate compression type for indexes
    IF p_compression_type NOT IN (C_COMPRESS_ADV_LOW, C_COMPRESS_ADV_HIGH, C_NOCOMPRESS) THEN
      RAISE_APPLICATION_ERROR(-20002, 'Invalid index compression type. Use ADV_LOW, ADV_HIGH, or NOCOMPRESS');
    END IF;

    -- Validate object
    IF NOT validate_object(p_owner, p_index_name, 'INDEX') THEN
      RETURN;
    END IF;

    v_size_before := get_segment_size(p_owner, p_index_name, 'INDEX');
    log_message('Current size: ' || ROUND(v_size_before / 1024 / 1024, 2) || ' MB');

    -- Get compression clause
    v_compression_clause := get_compression_clause(p_compression_type);

    -- Build DDL
    v_ddl := 'ALTER INDEX ' || p_owner || '.' || p_index_name || ' REBUILD ' || v_compression_clause;

    IF p_online THEN
      v_ddl := v_ddl || ' ONLINE';
    END IF;

    log_message('DDL: ' || v_ddl);

    -- Create history record
    INSERT INTO T_COMPRESSION_HISTORY (
      owner, object_name, object_type,
      compression_after, size_before_bytes,
      operation_type, executed_by, ddl_statement
    ) VALUES (
      p_owner, p_index_name, 'INDEX',
      p_compression_type, v_size_before,
      'COMPRESS', USER, v_ddl
    ) RETURNING history_id INTO v_history_id;

    COMMIT;

    -- Execute DDL
    BEGIN
      log_message('Executing compression...');
      EXECUTE IMMEDIATE v_ddl;
      log_message('Index compressed successfully');

      v_size_after := get_segment_size(p_owner, p_index_name, 'INDEX');

      -- Update history
      UPDATE T_COMPRESSION_HISTORY
      SET size_after_bytes = v_size_after,
          space_saved_bytes = v_size_before - v_size_after,
          compression_ratio = CASE WHEN v_size_after > 0 THEN v_size_before / v_size_after ELSE 0 END,
          status = 'SUCCESS',
          end_time = SYSTIMESTAMP
      WHERE history_id = v_history_id;

      COMMIT;

      log_message('New size: ' || ROUND(v_size_after / 1024 / 1024, 2) || ' MB');
      log_message('=== Index compression completed successfully ===');

    EXCEPTION
      WHEN OTHERS THEN
        UPDATE T_COMPRESSION_HISTORY
        SET status = 'FAILED',
            error_message = SUBSTR(SQLERRM, 1, 4000),
            end_time = SYSTIMESTAMP
        WHERE history_id = v_history_id;

        COMMIT;

        log_message('ERROR: ' || SQLERRM, 'ERROR');
        RAISE;
    END;

  END compress_index;

  /**
   * Compress a table partition preserving tablespace
   * CRITICAL: Preserves the partition's original tablespace
   */
  PROCEDURE compress_partition(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_partition_name IN VARCHAR2,
    p_compression_type IN VARCHAR2,
    p_online IN BOOLEAN DEFAULT TRUE
  ) IS
    v_ddl VARCHAR2(4000);
    v_tablespace_name VARCHAR2(128);
    v_compression_clause VARCHAR2(100);
    v_size_before NUMBER;
    v_size_after NUMBER;
    v_history_id NUMBER;
  BEGIN
    log_message('=== Starting partition compression ===');
    log_message('Partition: ' || p_owner || '.' || p_table_name || '.' || p_partition_name);
    log_message('Compression Type: ' || p_compression_type);

    -- Query partition tablespace to preserve it
    -- CRITICAL: Each partition may be in a different tablespace
    BEGIN
      SELECT tablespace_name
      INTO v_tablespace_name
      FROM DBA_TAB_PARTITIONS
      WHERE table_owner = p_owner
        AND table_name = p_table_name
        AND partition_name = p_partition_name;
    EXCEPTION
      WHEN NO_DATA_FOUND THEN
        RAISE_APPLICATION_ERROR(-20001, 'Partition not found: ' || p_owner || '.' || p_table_name || '.' || p_partition_name);
    END;

    log_message('Current partition tablespace: ' || NVL(v_tablespace_name, 'NULL'));

    v_size_before := get_segment_size(p_owner, p_table_name || ':' || p_partition_name, 'TABLE PARTITION');
    log_message('Current size: ' || ROUND(v_size_before / 1024 / 1024, 2) || ' MB');

    -- Get compression clause
    v_compression_clause := get_compression_clause(p_compression_type);

    -- Build DDL with TABLESPACE preservation
    -- CRITICAL: Include TABLESPACE clause to preserve partition location
    v_ddl := 'ALTER TABLE ' || p_owner || '.' || p_table_name ||
             ' MOVE PARTITION ' || p_partition_name ||
             ' ' || v_compression_clause;

    IF v_tablespace_name IS NOT NULL THEN
      v_ddl := v_ddl || ' TABLESPACE ' || v_tablespace_name;
      log_message('Preserving partition tablespace: ' || v_tablespace_name);
    END IF;

    IF p_online AND p_compression_type IN (C_COMPRESS_BASIC, C_COMPRESS_OLTP) THEN
      v_ddl := v_ddl || ' ONLINE';
    END IF;

    log_message('DDL: ' || v_ddl);

    -- Create history record
    INSERT INTO T_COMPRESSION_HISTORY (
      owner, object_name, object_type,
      compression_after, size_before_bytes,
      operation_type, executed_by, ddl_statement
    ) VALUES (
      p_owner, p_table_name || '.' || p_partition_name, 'TABLE PARTITION',
      p_compression_type, v_size_before,
      'COMPRESS', USER, v_ddl
    ) RETURNING history_id INTO v_history_id;

    COMMIT;

    -- Execute DDL
    BEGIN
      log_message('Executing partition compression...');
      EXECUTE IMMEDIATE v_ddl;
      log_message('Partition compressed successfully');

      -- Rebuild partition indexes
      FOR idx IN (
        SELECT i.index_name, i.tablespace_name
        FROM DBA_INDEXES i
        WHERE i.table_owner = p_owner
          AND i.table_name = p_table_name
      ) LOOP
        BEGIN
          v_ddl := 'ALTER INDEX ' || p_owner || '.' || idx.index_name ||
                   ' REBUILD PARTITION ' || p_partition_name;

          -- Preserve index partition tablespace
          IF idx.tablespace_name IS NOT NULL THEN
            v_ddl := v_ddl || ' TABLESPACE ' || idx.tablespace_name;
          END IF;

          EXECUTE IMMEDIATE v_ddl;
          log_message('Rebuilt index partition: ' || idx.index_name || '.' || p_partition_name);
        EXCEPTION
          WHEN OTHERS THEN
            log_message('Warning: Failed to rebuild index partition: ' || SQLERRM, 'WARN');
        END;
      END LOOP;

      v_size_after := get_segment_size(p_owner, p_table_name || ':' || p_partition_name, 'TABLE PARTITION');

      -- Update history
      UPDATE T_COMPRESSION_HISTORY
      SET size_after_bytes = v_size_after,
          space_saved_bytes = v_size_before - v_size_after,
          compression_ratio = CASE WHEN v_size_after > 0 THEN v_size_before / v_size_after ELSE 0 END,
          status = 'SUCCESS',
          end_time = SYSTIMESTAMP
      WHERE history_id = v_history_id;

      COMMIT;

      log_message('New size: ' || ROUND(v_size_after / 1024 / 1024, 2) || ' MB');
      log_message('=== Partition compression completed ===');

    EXCEPTION
      WHEN OTHERS THEN
        UPDATE T_COMPRESSION_HISTORY
        SET status = 'FAILED',
            error_message = SUBSTR(SQLERRM, 1, 4000),
            end_time = SYSTIMESTAMP
        WHERE history_id = v_history_id;
        COMMIT;
        log_message('ERROR: ' || SQLERRM, 'ERROR');
        RAISE;
    END;
  END compress_partition;

  /**
   * Compress all partitions of a table preserving tablespaces
   * CRITICAL: Each partition's tablespace is individually preserved
   */
  PROCEDURE compress_all_partitions(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_compression_type IN VARCHAR2,
    p_online IN BOOLEAN DEFAULT TRUE
  ) IS
    v_partition_count NUMBER := 0;
    v_success_count NUMBER := 0;
    v_fail_count NUMBER := 0;
  BEGIN
    log_message('=== Starting batch partition compression ===');
    log_message('Table: ' || p_owner || '.' || p_table_name);
    log_message('Compression Type: ' || p_compression_type);

    -- Process each partition individually to preserve its tablespace
    FOR part IN (
      SELECT partition_name, tablespace_name
      FROM DBA_TAB_PARTITIONS
      WHERE table_owner = p_owner
        AND table_name = p_table_name
      ORDER BY partition_position
    ) LOOP
      v_partition_count := v_partition_count + 1;
      log_message('Processing partition ' || v_partition_count || ': ' || part.partition_name ||
                  ' (tablespace: ' || NVL(part.tablespace_name, 'NULL') || ')');

      BEGIN
        compress_partition(
          p_owner => p_owner,
          p_table_name => p_table_name,
          p_partition_name => part.partition_name,
          p_compression_type => p_compression_type,
          p_online => p_online
        );
        v_success_count := v_success_count + 1;
      EXCEPTION
        WHEN OTHERS THEN
          v_fail_count := v_fail_count + 1;
          log_message('Failed to compress partition ' || part.partition_name || ': ' || SQLERRM, 'ERROR');
          -- Continue with next partition
      END;
    END LOOP;

    log_message('=== Batch partition compression completed ===');
    log_message('Total partitions: ' || v_partition_count);
    log_message('Successful: ' || v_success_count);
    log_message('Failed: ' || v_fail_count);
  END compress_all_partitions;

  /**
   * Compress LOB segments preserving tablespace
   * CRITICAL: Preserves LOB segment tablespace
   */
  PROCEDURE compress_lob(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2,
    p_column_name IN VARCHAR2,
    p_compression_type IN VARCHAR2
  ) IS
    v_ddl VARCHAR2(4000);
    v_lob_tablespace VARCHAR2(128);
    v_lob_segment_name VARCHAR2(128);
    v_compression_clause VARCHAR2(100);
    v_size_before NUMBER;
    v_size_after NUMBER;
    v_history_id NUMBER;
  BEGIN
    log_message('=== Starting LOB compression ===');
    log_message('LOB: ' || p_owner || '.' || p_table_name || '.' || p_column_name);
    log_message('Compression Type: ' || p_compression_type);

    -- Query LOB segment information including tablespace
    -- CRITICAL: LOBs may be stored in different tablespaces than the base table
    BEGIN
      SELECT l.segment_name, l.tablespace_name
      INTO v_lob_segment_name, v_lob_tablespace
      FROM DBA_LOBS l
      WHERE l.owner = p_owner
        AND l.table_name = p_table_name
        AND l.column_name = p_column_name;
    EXCEPTION
      WHEN NO_DATA_FOUND THEN
        RAISE_APPLICATION_ERROR(-20001, 'LOB column not found: ' || p_owner || '.' || p_table_name || '.' || p_column_name);
    END;

    log_message('LOB segment: ' || v_lob_segment_name);
    log_message('LOB tablespace: ' || NVL(v_lob_tablespace, 'NULL'));

    v_size_before := get_segment_size(p_owner, v_lob_segment_name, 'LOBSEGMENT');
    log_message('Current LOB size: ' || ROUND(v_size_before / 1024 / 1024, 2) || ' MB');

    -- Get compression clause for LOBs
    v_compression_clause := CASE UPPER(p_compression_type)
      WHEN 'HIGH' THEN 'COMPRESS HIGH'
      WHEN 'MEDIUM' THEN 'COMPRESS MEDIUM'
      WHEN 'LOW' THEN 'COMPRESS LOW'
      WHEN 'NOCOMPRESS' THEN 'NOCOMPRESS'
      ELSE 'COMPRESS MEDIUM'
    END CASE;

    -- Build DDL to modify LOB storage with tablespace preservation
    -- CRITICAL: Include TABLESPACE clause to preserve LOB location
    v_ddl := 'ALTER TABLE ' || p_owner || '.' || p_table_name ||
             ' MODIFY LOB (' || p_column_name || ') (' || v_compression_clause;

    IF v_lob_tablespace IS NOT NULL THEN
      v_ddl := v_ddl || ' TABLESPACE ' || v_lob_tablespace;
      log_message('Preserving LOB tablespace: ' || v_lob_tablespace);
    END IF;

    v_ddl := v_ddl || ')';

    log_message('DDL: ' || v_ddl);

    -- Create history record
    INSERT INTO T_COMPRESSION_HISTORY (
      owner, object_name, object_type,
      compression_after, size_before_bytes,
      operation_type, executed_by, ddl_statement
    ) VALUES (
      p_owner, p_table_name || '.' || p_column_name, 'LOB',
      p_compression_type, v_size_before,
      'COMPRESS', USER, v_ddl
    ) RETURNING history_id INTO v_history_id;

    COMMIT;

    -- Execute DDL
    BEGIN
      log_message('Executing LOB compression...');
      EXECUTE IMMEDIATE v_ddl;
      log_message('LOB compressed successfully');

      -- Note: LOB compression may require moving data, check new size
      v_size_after := get_segment_size(p_owner, v_lob_segment_name, 'LOBSEGMENT');

      -- Update history
      UPDATE T_COMPRESSION_HISTORY
      SET size_after_bytes = v_size_after,
          space_saved_bytes = v_size_before - v_size_after,
          compression_ratio = CASE WHEN v_size_after > 0 THEN v_size_before / v_size_after ELSE 0 END,
          status = 'SUCCESS',
          end_time = SYSTIMESTAMP
      WHERE history_id = v_history_id;

      COMMIT;

      log_message('New LOB size: ' || ROUND(v_size_after / 1024 / 1024, 2) || ' MB');
      log_message('=== LOB compression completed ===');

    EXCEPTION
      WHEN OTHERS THEN
        UPDATE T_COMPRESSION_HISTORY
        SET status = 'FAILED',
            error_message = SUBSTR(SQLERRM, 1, 4000),
            end_time = SYSTIMESTAMP
        WHERE history_id = v_history_id;
        COMMIT;
        log_message('ERROR: ' || SQLERRM, 'ERROR');
        RAISE;
    END;
  END compress_lob;

  /**
   * Execute recommendations
   */
  PROCEDURE execute_recommendations(
    p_strategy_id IN NUMBER DEFAULT 2,
    p_max_tables IN NUMBER DEFAULT 10,
    p_max_size_gb IN NUMBER DEFAULT 100
  ) IS
    v_tables_processed NUMBER := 0;
    v_total_size_gb NUMBER := 0;
    v_max_size_bytes NUMBER := p_max_size_gb * 1024 * 1024 * 1024;
  BEGIN
    log_message('=== Starting batch compression execution ===');
    log_message('Strategy ID: ' || p_strategy_id);
    log_message('Max tables: ' || p_max_tables);
    log_message('Max size: ' || p_max_size_gb || ' GB');

    -- Process table recommendations
    FOR rec IN (
      SELECT r.owner, r.table_name, r.recommended_compression,
             t.size_bytes
      FROM V_COMPRESSION_RECOMMENDATIONS r
      JOIN T_TABLE_ANALYSIS t ON r.owner = t.owner AND r.table_name = t.table_name
      WHERE r.strategy_id = p_strategy_id
        AND r.object_type = 'TABLE'
        AND r.priority IN ('HIGH', 'MEDIUM')
      ORDER BY
        CASE r.priority WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
        t.size_bytes DESC
    ) LOOP
      EXIT WHEN v_tables_processed >= p_max_tables;
      EXIT WHEN v_total_size_gb >= v_max_size_bytes;

      BEGIN
        compress_table(
          p_owner => rec.owner,
          p_table_name => rec.table_name,
          p_compression_type => rec.recommended_compression,
          p_online => TRUE,
          p_dry_run => FALSE
        );

        v_tables_processed := v_tables_processed + 1;
        v_total_size_gb := v_total_size_gb + rec.size_bytes;

      EXCEPTION
        WHEN OTHERS THEN
          log_message('Failed to compress ' || rec.owner || '.' || rec.table_name || ': ' || SQLERRM, 'ERROR');
          -- Continue with next table
      END;
    END LOOP;

    log_message('=== Batch execution completed ===');
    log_message('Tables processed: ' || v_tables_processed);
    log_message('Total size processed: ' || ROUND(v_total_size_gb / 1024 / 1024 / 1024, 2) || ' GB');

  END execute_recommendations;

  /**
   * Rollback compression
   */
  PROCEDURE rollback_compression(
    p_history_id IN NUMBER
  ) IS
    v_owner VARCHAR2(128);
    v_object_name VARCHAR2(128);
    v_object_type VARCHAR2(30);
    v_compression_before VARCHAR2(30);
    v_ddl VARCHAR2(4000);
  BEGIN
    log_message('=== Starting compression rollback ===');
    log_message('History ID: ' || p_history_id);

    -- Get original compression state
    SELECT owner, object_name, object_type, compression_before
    INTO v_owner, v_object_name, v_object_type, v_compression_before
    FROM T_COMPRESSION_HISTORY
    WHERE history_id = p_history_id;

    log_message('Rolling back: ' || v_owner || '.' || v_object_name);
    log_message('Restoring compression: ' || v_compression_before);

    IF v_object_type = 'TABLE' THEN
      compress_table(
        p_owner => v_owner,
        p_table_name => v_object_name,
        p_compression_type => NVL(v_compression_before, C_NOCOMPRESS),
        p_online => TRUE,
        p_dry_run => FALSE
      );
    ELSIF v_object_type = 'INDEX' THEN
      compress_index(
        p_owner => v_owner,
        p_index_name => v_object_name,
        p_compression_type => NVL(v_compression_before, C_NOCOMPRESS),
        p_online => TRUE
      );
    END IF;

    -- Mark as rolled back
    UPDATE T_COMPRESSION_HISTORY
    SET status = 'ROLLED_BACK'
    WHERE history_id = p_history_id;

    COMMIT;

    log_message('=== Rollback completed successfully ===');

  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RAISE_APPLICATION_ERROR(-20001, 'History record not found: ' || p_history_id);
    WHEN OTHERS THEN
      log_message('ERROR during rollback: ' || SQLERRM, 'ERROR');
      RAISE;
  END rollback_compression;

  /**
   * Get compression status
   */
  FUNCTION get_compression_status(
    p_history_id IN NUMBER
  ) RETURN VARCHAR2 IS
    v_status VARCHAR2(30);
  BEGIN
    SELECT status
    INTO v_status
    FROM T_COMPRESSION_HISTORY
    WHERE history_id = p_history_id;

    RETURN v_status;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RETURN 'NOT_FOUND';
  END get_compression_status;

END PKG_COMPRESSION_EXECUTOR;
/

-- Grant execute permissions
GRANT EXECUTE ON PKG_COMPRESSION_EXECUTOR TO PUBLIC;

-- Create public synonym
CREATE OR REPLACE PUBLIC SYNONYM PKG_COMPRESSION_EXECUTOR FOR PKG_COMPRESSION_EXECUTOR;

-- Display completion message
PROMPT
PROMPT ================================================================================
PROMPT PKG_COMPRESSION_EXECUTOR package created successfully
PROMPT ================================================================================
PROMPT
PROMPT Available Procedures:
PROMPT   - compress_table           : Compress individual table (preserves tablespace)
PROMPT   - compress_index           : Compress individual index (preserves tablespace)
PROMPT   - compress_partition       : Compress single partition (preserves tablespace)
PROMPT   - compress_all_partitions  : Compress all partitions (preserves each tablespace)
PROMPT   - compress_lob             : Compress LOB column (preserves tablespace)
PROMPT   - execute_recommendations  : Execute batch compression
PROMPT   - rollback_compression     : Rollback to original state
PROMPT
PROMPT Available Functions:
PROMPT   - get_compression_status       : Get operation status
PROMPT   - validate_object              : Pre-execution validation
PROMPT   - estimate_compression_ratio   : Estimate compression savings
PROMPT
PROMPT Compression Types:
PROMPT   Tables/Partitions: BASIC, OLTP, NOCOMPRESS
PROMPT   Indexes          : ADV_LOW, ADV_HIGH, NOCOMPRESS
PROMPT   LOBs             : HIGH, MEDIUM, LOW, NOCOMPRESS
PROMPT
PROMPT CRITICAL: All compression operations preserve original tablespace assignments!
PROMPT
PROMPT Example Usage:
PROMPT   -- Compress single table (preserves tablespace)
PROMPT   EXEC PKG_COMPRESSION_EXECUTOR.compress_table('HR', 'EMPLOYEES', 'OLTP');
PROMPT
PROMPT   -- Compress single partition (preserves partition tablespace)
PROMPT   EXEC PKG_COMPRESSION_EXECUTOR.compress_partition('HR', 'SALES', 'Q1_2024', 'OLTP');
PROMPT
PROMPT   -- Compress all partitions (each partition's tablespace is preserved)
PROMPT   EXEC PKG_COMPRESSION_EXECUTOR.compress_all_partitions('HR', 'SALES', 'OLTP');
PROMPT
PROMPT   -- Compress LOB (preserves LOB tablespace)
PROMPT   EXEC PKG_COMPRESSION_EXECUTOR.compress_lob('HR', 'DOCUMENTS', 'CONTENT', 'HIGH');
PROMPT
PROMPT   -- Execute recommendations (preserves all tablespaces)
PROMPT   EXEC PKG_COMPRESSION_EXECUTOR.execute_recommendations(2, 10, 100);
PROMPT
PROMPT   -- Rollback compression (restores to original tablespace)
PROMPT   EXEC PKG_COMPRESSION_EXECUTOR.rollback_compression(12345);
PROMPT
PROMPT ================================================================================
PROMPT
