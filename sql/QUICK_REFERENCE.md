# Quick Reference - Schema Objects

## Table Reference

### Strategy Configuration
```sql
-- View all strategies
SELECT strategy_name, category, active_flag, is_default
FROM t_compression_strategies
ORDER BY priority DESC;

-- Get default strategy thresholds
SELECT hotness_threshold_hot, hotness_threshold_warm, hotness_threshold_cool
FROM t_compression_strategies
WHERE is_default = 'Y';
```

### Analysis Results
```sql
-- View recent analysis results
SELECT owner, object_name, hotness_score, hotness_category,
       advisable_compression, projected_savings_mb
FROM t_compression_analysis
WHERE analysis_date >= SYSDATE - 7
ORDER BY projected_savings_mb DESC;

-- Get compression ratio summary
SELECT advisable_compression,
       COUNT(*) as object_count,
       ROUND(AVG(best_ratio), 2) as avg_ratio,
       ROUND(SUM(projected_savings_mb), 2) as total_savings_mb
FROM t_compression_analysis
GROUP BY advisable_compression
ORDER BY total_savings_mb DESC;
```

### Execution History
```sql
-- View recent compression executions
SELECT owner, object_name, compression_type_applied,
       space_saved_mb, compression_ratio_achieved,
       operation_status, duration_minutes
FROM t_compression_history
WHERE start_time >= SYSTIMESTAMP - INTERVAL '7' DAY
ORDER BY start_time DESC;

-- Calculate total space savings
SELECT
    COUNT(*) as total_executions,
    SUM(CASE WHEN operation_status = 'SUCCESS' THEN 1 ELSE 0 END) as successful,
    ROUND(SUM(space_saved_mb), 2) as total_saved_mb,
    ROUND(AVG(compression_ratio_achieved), 2) as avg_ratio
FROM t_compression_history
WHERE operation_status = 'SUCCESS';
```

### Advisor Runs
```sql
-- View analysis sessions
SELECT run_id, run_name, run_type, run_status,
       objects_analyzed, success_rate_pct,
       projected_savings_mb, duration_minutes
FROM t_advisor_run
ORDER BY start_time DESC;

-- Get latest run summary
SELECT
    run_name,
    recommend_none, recommend_basic, recommend_oltp,
    recommend_adv_low, recommend_adv_high
FROM t_advisor_run
WHERE run_status = 'COMPLETED'
ORDER BY start_time DESC
FETCH FIRST 1 ROW ONLY;
```

## Common Queries

### Top Compression Candidates
```sql
SELECT
    owner, object_name, size_mb, hotness_score,
    advisable_compression, projected_savings_mb,
    ROUND(projected_savings_pct, 1) as savings_pct
FROM t_compression_analysis
WHERE advisable_compression != 'NONE'
  AND projected_savings_mb > 100
ORDER BY projected_savings_mb DESC
FETCH FIRST 20 ROWS ONLY;
```

### Objects by Hotness Category
```sql
SELECT
    hotness_category,
    COUNT(*) as object_count,
    ROUND(SUM(size_mb), 2) as total_size_mb,
    ROUND(AVG(hotness_score), 1) as avg_score
FROM t_compression_analysis
GROUP BY hotness_category
ORDER BY DECODE(hotness_category, 'HOT', 1, 'WARM', 2, 'COOL', 3, 'COLD', 4);
```

### Compression Effectiveness
```sql
SELECT
    compression_type_applied,
    COUNT(*) as execution_count,
    ROUND(AVG(compression_ratio_achieved), 2) as avg_ratio,
    ROUND(SUM(space_saved_mb), 2) as total_savings_mb,
    ROUND(AVG(duration_minutes), 1) as avg_duration_min
FROM t_compression_history
WHERE operation_status = 'SUCCESS'
GROUP BY compression_type_applied
ORDER BY total_savings_mb DESC;
```

### Failed Executions
```sql
SELECT owner, object_name, compression_type_applied,
       error_message, start_time
FROM t_compression_history
WHERE operation_status = 'FAILED'
ORDER BY start_time DESC;
```

## Maintenance Queries

### Cleanup Old Analysis Data
```sql
-- Delete analysis results older than 90 days
DELETE FROM t_compression_analysis
WHERE analysis_date < SYSDATE - 90;

-- Archive old execution history
CREATE TABLE t_compression_history_archive AS
SELECT * FROM t_compression_history
WHERE start_time < SYSTIMESTAMP - INTERVAL '180' DAY;

DELETE FROM t_compression_history
WHERE start_time < SYSTIMESTAMP - INTERVAL '180' DAY;
```

### Statistics Management
```sql
-- Gather statistics on all compression tables
BEGIN
    FOR t IN (
        SELECT table_name
        FROM user_tables
        WHERE table_name LIKE 'T_%COMPRESS%'
    ) LOOP
        DBMS_STATS.GATHER_TABLE_STATS(
            ownname => USER,
            tabname => t.table_name,
            cascade => TRUE
        );
    END LOOP;
END;
/
```

### Index Monitoring
```sql
-- Check index usage
SELECT index_name, table_name, uniqueness, status
FROM user_indexes
WHERE table_name LIKE 'T_%COMPRESS%'
ORDER BY table_name, index_name;
```

## Data Dictionary Queries

### Object Counts
```sql
SELECT
    object_type,
    COUNT(*) as count,
    SUM(CASE WHEN status = 'VALID' THEN 1 ELSE 0 END) as valid,
    SUM(CASE WHEN status != 'VALID' THEN 1 ELSE 0 END) as invalid
FROM user_objects
WHERE object_name LIKE 'T_%COMPRESS%'
   OR object_name LIKE 'SEQ_%'
   OR object_name LIKE '%COMP%'
GROUP BY object_type
ORDER BY object_type;
```

### Storage Allocation
```sql
SELECT
    segment_name,
    segment_type,
    ROUND(bytes/1024/1024, 2) as size_mb,
    blocks
FROM user_segments
WHERE segment_name LIKE 'T_%COMPRESS%'
ORDER BY bytes DESC;
```

### Constraint Validation
```sql
-- Check all constraints
SELECT
    constraint_name,
    constraint_type,
    table_name,
    status
FROM user_constraints
WHERE table_name LIKE 'T_%COMPRESS%'
ORDER BY table_name, constraint_type;
```

## Sequence Operations

### Get Next Execution ID
```sql
SELECT seq_execution_id.NEXTVAL FROM dual;
```

### Reset Sequence (if needed)
```sql
-- Drop and recreate
DROP SEQUENCE seq_execution_id;
CREATE SEQUENCE seq_execution_id START WITH 1000 INCREMENT BY 1 CACHE 20;
```

## Testing Queries

### Insert Test Strategy
```sql
INSERT INTO t_compression_strategies (
    strategy_name, description, category,
    active_flag, is_default
) VALUES (
    'TEST_STRATEGY', 'Test strategy for development', 'CUSTOM',
    'Y', 'N'
);
```

### Insert Test Advisor Run
```sql
INSERT INTO t_advisor_run (
    run_name, run_type, run_status,
    objects_analyzed, objects_succeeded
) VALUES (
    'TEST_RUN_001', 'TABLES', 'RUNNING',
    0, 0
)
RETURNING run_id INTO :v_run_id;
```

### Simulate Analysis Result
```sql
INSERT INTO t_compression_analysis (
    owner, object_name, object_type,
    size_bytes, row_count,
    basic_ratio, oltp_ratio,
    hotness_score, advisable_compression,
    advisor_run_id
) VALUES (
    'TEST_SCHEMA', 'TEST_TABLE', 'TABLE',
    1024*1024*100, 10000,
    1.5, 2.3,
    45, 'OLTP',
    :v_run_id
);
```

## Validation Queries

### Check Foreign Keys
```sql
-- Verify all analysis results have valid run_id
SELECT COUNT(*)
FROM t_compression_analysis a
WHERE NOT EXISTS (
    SELECT 1 FROM t_advisor_run r
    WHERE r.run_id = a.advisor_run_id
);
-- Should return 0
```

### Validate Compression Types
```sql
-- Check for invalid compression types
SELECT advisable_compression, COUNT(*)
FROM t_compression_analysis
WHERE advisable_compression NOT IN ('NONE', 'BASIC', 'OLTP', 'ADV_LOW', 'ADV_HIGH')
GROUP BY advisable_compression;
-- Should return no rows
```

### Check Hotness Scores
```sql
-- Verify scores are in valid range
SELECT COUNT(*)
FROM t_compression_analysis
WHERE hotness_score < 0 OR hotness_score > 100;
-- Should return 0
```

## Performance Tuning

### Index Rebuild
```sql
-- Rebuild all compression indexes
BEGIN
    FOR idx IN (
        SELECT index_name
        FROM user_indexes
        WHERE table_name LIKE 'T_%COMPRESS%'
    ) LOOP
        EXECUTE IMMEDIATE 'ALTER INDEX ' || idx.index_name || ' REBUILD';
    END LOOP;
END;
/
```

### Analyze Plans
```sql
-- Explain plan for common query
EXPLAIN PLAN FOR
SELECT * FROM t_compression_analysis
WHERE hotness_score >= 75
  AND projected_savings_mb > 100;

SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY);
```

## Export/Import

### Export Analysis Results
```sql
-- Export to CSV (SQL*Plus)
SET MARKUP CSV ON
SPOOL compression_analysis.csv
SELECT owner, object_name, hotness_score, advisable_compression,
       projected_savings_mb
FROM t_compression_analysis
ORDER BY projected_savings_mb DESC;
SPOOL OFF
```

### Backup Tables
```sql
-- Create backup
CREATE TABLE t_compression_analysis_bkp AS
SELECT * FROM t_compression_analysis;

-- Restore from backup
TRUNCATE TABLE t_compression_analysis;
INSERT INTO t_compression_analysis
SELECT * FROM t_compression_analysis_bkp;
COMMIT;
```

## Useful Views (to be created)

These queries can be used as templates for creating views:

```sql
-- Compression candidates view
CREATE OR REPLACE VIEW v_compression_candidates AS
SELECT owner, object_name, size_mb, hotness_category,
       advisable_compression, projected_savings_mb,
       best_ratio
FROM t_compression_analysis
WHERE advisable_compression != 'NONE'
  AND projected_savings_mb > 100
ORDER BY projected_savings_mb DESC;

-- Space savings summary view
CREATE OR REPLACE VIEW v_space_savings_summary AS
SELECT
    owner,
    COUNT(*) as objects_compressed,
    ROUND(SUM(space_saved_mb), 2) as total_saved_mb,
    ROUND(AVG(compression_ratio_achieved), 2) as avg_ratio
FROM t_compression_history
WHERE operation_status = 'SUCCESS'
GROUP BY owner;
```

## Tips

1. **Always check run status** before analyzing results
2. **Use indexes** - queries on owner/object_name are indexed
3. **Monitor space** - cleanup old analysis data regularly
4. **Validate data** - use check constraint queries
5. **Gather stats** - after large data changes
6. **Use virtual columns** - they're computed automatically
7. **Check foreign keys** - ensure referential integrity

## Common Patterns

### Create → Analyze → Execute → Monitor
```sql
-- 1. Create advisor run
INSERT INTO t_advisor_run (...) RETURNING run_id INTO :v_run_id;

-- 2. Analyze objects (via package)
-- PKG_COMPRESSION_ANALYZER.analyze_table(...);

-- 3. Review recommendations
SELECT * FROM t_compression_analysis WHERE advisor_run_id = :v_run_id;

-- 4. Execute compression (via package)
-- PKG_COMPRESSION_EXECUTOR.compress_table(...);

-- 5. Monitor results
SELECT * FROM t_compression_history WHERE execution_id = :v_exec_id;
```
