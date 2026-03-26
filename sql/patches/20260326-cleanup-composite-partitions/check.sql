SELECT CASE WHEN COUNT(*) = 0 THEN 1 ELSE 0 END as result
FROM t_compression_analysis a
WHERE a.object_type = 'PARTITION'
  AND EXISTS (
    SELECT 1 FROM t_compression_analysis b
    WHERE b.database_id = a.database_id
      AND b.owner = a.owner
      AND b.object_name = a.object_name
      AND b.partition_name = a.partition_name
      AND b.object_type = 'SUBPARTITION'
  )
