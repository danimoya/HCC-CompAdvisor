UPDATE t_schema_metadata SET value = '3.0.0' WHERE key = 'schema_version';
UPDATE t_schema_metadata SET value = TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS') WHERE key = 'last_upgraded_at';

-- Insert last_upgraded_at if it doesn't exist
MERGE INTO t_schema_metadata tgt
USING (SELECT 'last_upgraded_at' as key FROM DUAL) src
ON (tgt.key = src.key)
WHEN NOT MATCHED THEN INSERT (key, value)
    VALUES ('last_upgraded_at', TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'));

COMMIT;
