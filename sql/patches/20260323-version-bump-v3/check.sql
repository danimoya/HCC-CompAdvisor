SELECT COUNT(*) as result FROM t_schema_metadata WHERE key = 'schema_version' AND TO_NUMBER(REGEXP_SUBSTR(value, '^[0-9]+')) >= 3
