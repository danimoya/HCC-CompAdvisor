MERGE INTO t_compression_analysis a
USING (
    SELECT database_id, owner, object_name,
           NVL(partition_name, CHR(126)) as pn,
           original_size_bytes
    FROM (
        SELECT database_id, owner, object_name, partition_name,
               original_size_bytes,
               ROW_NUMBER() OVER (
                   PARTITION BY database_id, owner, object_name,
                                NVL(partition_name, CHR(126))
                   ORDER BY start_time ASC
               ) as rn
        FROM t_compression_history
        WHERE original_size_bytes IS NOT NULL
          AND original_size_bytes > 0
    ) WHERE rn = 1
) h ON (    a.database_id = h.database_id
        AND a.owner = h.owner
        AND a.object_name = h.object_name
        AND NVL(a.partition_name, CHR(126)) = h.pn)
WHEN MATCHED THEN UPDATE
    SET a.original_size_bytes = h.original_size_bytes
    WHERE h.original_size_bytes > NVL(a.original_size_bytes, 0);
COMMIT;
