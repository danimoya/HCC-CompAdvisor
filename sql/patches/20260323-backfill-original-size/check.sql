SELECT CASE WHEN COUNT(*) = 0 THEN 1 ELSE 0 END as result
FROM t_compression_analysis a
JOIN t_compression_history h
    ON h.database_id = a.database_id AND h.owner = a.owner AND h.object_name = a.object_name
WHERE h.original_size_bytes > NVL(a.original_size_bytes, 0)
  AND h.original_size_bytes > 0
