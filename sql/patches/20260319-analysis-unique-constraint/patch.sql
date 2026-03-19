-- Remove existing duplicates: keep only the row with the highest ANALYSIS_ID per object
DELETE FROM t_compression_analysis a
WHERE a.analysis_id NOT IN (
    SELECT MAX(b.analysis_id)
    FROM t_compression_analysis b
    WHERE b.database_id = a.database_id
      AND b.owner = a.owner
      AND b.object_name = a.object_name
      AND NVL(b.partition_name, '~') = NVL(a.partition_name, '~')
      AND NVL(b.subpartition_name, '~') = NVL(a.subpartition_name, '~')
);
COMMIT;

-- Create unique index on the natural key
-- Uses NVL to handle NULLs in partition/subpartition names
BEGIN
    EXECUTE IMMEDIATE '
        CREATE UNIQUE INDEX UNQ_COMP_ANALYSIS_OBJECT ON t_compression_analysis (
            database_id, owner, object_name,
            NVL(partition_name, ''~''),
            NVL(subpartition_name, ''~'')
        )
    ';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE = -955 THEN NULL;  -- already exists
        ELSE RAISE;
        END IF;
END;
