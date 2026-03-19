## Add unique constraint to T_COMPRESSION_ANALYSIS

Prevents duplicate rows when re-analyzing the same objects.
Adds a unique index on (DATABASE_ID, OWNER, OBJECT_NAME, NVL(PARTITION_NAME,'~'), NVL(SUBPARTITION_NAME,'~')).

Also removes any existing duplicates (keeps the latest analysis_id per object).
