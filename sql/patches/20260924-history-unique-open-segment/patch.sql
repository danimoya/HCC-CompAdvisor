-- At most one open (QUEUED / IN_PROGRESS) T_COMPRESSION_HISTORY row per segment
-- of a target, enforced by a function-based unique index. Its key is NULL for
-- closed rows (entirely-NULL keys are not indexed), so finished history never
-- collides. Idempotent: does nothing once UNQ_HISTORY_OPEN_SEGMENT exists.
--
-- Open rows that already break the rule are handled first. No row is deleted.
--   * A segment with more than one IN_PROGRESS row: the patch fails, lists them
--     and changes nothing. Each of them may still have its scheduler job or MOVE
--     running, so closing one here would lose its real outcome.
--   * Extra QUEUED copies of a segment (nothing has run for them yet): marked
--     FAILED "Duplicate open row closed by patch ...". The row kept is the
--     segment's IN_PROGRESS row, else its oldest QUEUED row (its FIFO position).
DECLARE
    v_exists  NUMBER;
    v_groups  NUMBER := 0;
    v_listed  NUMBER := 0;
    v_label   VARCHAR2(4000);
    v_list    VARCHAR2(4000);
BEGIN
    SELECT COUNT(*) INTO v_exists
      FROM user_indexes WHERE index_name = 'UNQ_HISTORY_OPEN_SEGMENT';
    IF v_exists > 0 THEN
        RETURN;
    END IF;

    -- 1. Segments with more than one IN_PROGRESS row: refuse, change nothing.
    FOR r IN (
        SELECT database_id, owner, object_name,
               MAX(partition_name) AS partition_name,
               MAX(subpartition_name) AS subpartition_name,
               LISTAGG(history_id, ', ') WITHIN GROUP (ORDER BY history_id) AS ids
          FROM t_compression_history
         WHERE operation_status = 'IN_PROGRESS'
         GROUP BY database_id, owner, object_name,
                  NVL(partition_name, '~'), NVL(subpartition_name, '~')
        HAVING COUNT(*) > 1
         ORDER BY database_id, owner, object_name
    ) LOOP
        v_groups := v_groups + 1;
        v_label := SUBSTRB('database_id ' || r.database_id || ' ' || r.owner || '.' || r.object_name
                           || CASE WHEN r.subpartition_name IS NOT NULL
                                   THEN ' subpartition ' || r.subpartition_name
                                   WHEN r.partition_name IS NOT NULL
                                   THEN ' partition ' || r.partition_name END
                           || ' (history_id ' || r.ids || ')', 1, 600);
        IF NVL(LENGTHB(v_list), 0) + LENGTHB(v_label) < 1200 THEN
            v_list := v_list || CASE WHEN v_list IS NOT NULL THEN '; ' END || v_label;
            v_listed := v_listed + 1;
        END IF;
    END LOOP;
    IF v_groups > 0 THEN
        RAISE_APPLICATION_ERROR(-20001, SUBSTRB(
            'UNQ_HISTORY_OPEN_SEGMENT not created: ' || v_groups
            || ' segment(s) have more than one IN_PROGRESS row in T_COMPRESSION_HISTORY: '
            || v_list
            || CASE WHEN v_listed < v_groups THEN '; and ' || (v_groups - v_listed) || ' more' END
            || '. Their scheduler jobs or MOVEs may still be running, so this patch does not'
            || ' close them and changed nothing. Wait until they finish and run Scheduler >'
            || ' Reconcile stale operations (or mark the stale rows FAILED by hand), then'
            || ' apply this patch again.', 1, 2000));
    END IF;

    -- 2. Extra QUEUED copies of a segment: close them, the reason on the row.
    FOR r IN (
        SELECT history_id, keeper_id
          FROM (SELECT history_id,
                       FIRST_VALUE(history_id) OVER (
                           PARTITION BY database_id, owner, object_name,
                                        NVL(partition_name, '~'), NVL(subpartition_name, '~')
                           ORDER BY CASE WHEN operation_status = 'IN_PROGRESS' THEN 0 ELSE 1 END,
                                    start_time, history_id) AS keeper_id
                  FROM t_compression_history
                 WHERE operation_status IN ('QUEUED', 'IN_PROGRESS'))
         WHERE history_id <> keeper_id
    ) LOOP
        UPDATE t_compression_history SET operation_status = 'FAILED', end_time = SYSTIMESTAMP,
               error_message = 'Duplicate open row closed by patch 20260924-history-unique-open-segment:'
                               || ' history_id ' || r.keeper_id
                               || ' is already queued or running for this segment.'
         WHERE history_id = r.history_id AND operation_status = 'QUEUED';
    END LOOP;

    -- 3. The index (DDL: commits step 2 first). Keep it identical to
    --    sql/central/01_central_schema.sql.
    EXECUTE IMMEDIATE q'[
        CREATE UNIQUE INDEX UNQ_HISTORY_OPEN_SEGMENT ON T_COMPRESSION_HISTORY(
            CASE WHEN OPERATION_STATUS IN ('QUEUED', 'IN_PROGRESS') THEN DATABASE_ID END,
            CASE WHEN OPERATION_STATUS IN ('QUEUED', 'IN_PROGRESS') THEN OWNER END,
            CASE WHEN OPERATION_STATUS IN ('QUEUED', 'IN_PROGRESS') THEN OBJECT_NAME END,
            CASE WHEN OPERATION_STATUS IN ('QUEUED', 'IN_PROGRESS') THEN NVL(PARTITION_NAME, '~') END,
            CASE WHEN OPERATION_STATUS IN ('QUEUED', 'IN_PROGRESS') THEN NVL(SUBPARTITION_NAME, '~') END
        )]';
END;
/
