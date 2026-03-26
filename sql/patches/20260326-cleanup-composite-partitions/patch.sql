-- Delete PARTITION rows where SUBPARTITION rows exist for the same table+partition
-- (composite partitions that should only have subpartition-level entries)
DELETE FROM t_compression_analysis a
WHERE a.object_type = 'PARTITION'
  AND EXISTS (
    SELECT 1 FROM t_compression_analysis b
    WHERE b.database_id = a.database_id
      AND b.owner = a.owner
      AND b.object_name = a.object_name
      AND b.partition_name = a.partition_name
      AND b.object_type = 'SUBPARTITION'
);
COMMIT;
