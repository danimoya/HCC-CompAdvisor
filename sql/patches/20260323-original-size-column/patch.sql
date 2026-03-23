DECLARE
    v_exists NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_exists FROM user_tab_columns
    WHERE table_name = 'T_COMPRESSION_ANALYSIS' AND column_name = 'ORIGINAL_SIZE_BYTES';
    IF v_exists = 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE t_compression_analysis ADD (original_size_bytes NUMBER)';
    END IF;
END;
/

-- Backfill from existing data: original_size = current size_bytes for uncompressed objects
UPDATE t_compression_analysis SET original_size_bytes = size_bytes WHERE original_size_bytes IS NULL;

-- Backfill from compression history for objects that were compressed
MERGE INTO t_compression_analysis a
USING (
    SELECT owner, object_name, NVL(partition_name, '~') as pn, original_size_bytes
    FROM (
        SELECT owner, object_name, partition_name, original_size_bytes,
               ROW_NUMBER() OVER (PARTITION BY owner, object_name, NVL(partition_name, '~')
                                  ORDER BY start_time ASC) as rn
        FROM t_compression_history
        WHERE original_size_bytes IS NOT NULL AND original_size_bytes > 0
    ) WHERE rn = 1
) h ON (a.owner = h.owner AND a.object_name = h.object_name
        AND NVL(a.partition_name, '~') = h.pn)
WHEN MATCHED THEN UPDATE SET a.original_size_bytes = h.original_size_bytes;

COMMIT;
