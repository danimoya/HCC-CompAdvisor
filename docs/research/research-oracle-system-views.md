# Oracle System Views for HCC Compression Analysis

## Overview
This document provides comprehensive reference for Oracle data dictionary views and dynamic performance views used to analyze, implement, and monitor HCC compression.

## Core Data Dictionary Views

### 1. DBA_TABLES / ALL_TABLES / USER_TABLES

Primary view for table-level compression information.

#### Key Columns for HCC Analysis

| Column | Data Type | Description |
|--------|-----------|-------------|
| OWNER | VARCHAR2(128) | Schema owner |
| TABLE_NAME | VARCHAR2(128) | Table name |
| COMPRESSION | VARCHAR2(8) | ENABLED or DISABLED |
| COMPRESS_FOR | VARCHAR2(30) | Compression type (QUERY LOW/HIGH, ARCHIVE LOW/HIGH) |
| NUM_ROWS | NUMBER | Approximate row count (from statistics) |
| BLOCKS | NUMBER | Number of blocks allocated |
| EMPTY_BLOCKS | NUMBER | Number of empty blocks |
| AVG_ROW_LEN | NUMBER | Average row length in bytes |
| CHAIN_CNT | NUMBER | Number of chained/migrated rows |
| LAST_ANALYZED | DATE | When statistics were last gathered |

#### Example Queries

```sql
-- Find all HCC compressed tables
SELECT
    owner,
    table_name,
    compress_for,
    num_rows,
    ROUND(blocks * 8192 / 1024 / 1024, 2) as size_mb,
    last_analyzed
FROM dba_tables
WHERE compression = 'ENABLED'
AND compress_for IN ('QUERY LOW','QUERY HIGH','ARCHIVE LOW','ARCHIVE HIGH')
AND owner NOT IN ('SYS','SYSTEM')
ORDER BY blocks DESC;

-- Check compression effectiveness
SELECT
    table_name,
    compress_for,
    num_rows,
    blocks,
    ROUND(num_rows / NULLIF(blocks, 0), 2) as rows_per_block,
    avg_row_len,
    chain_cnt,
    ROUND(chain_cnt / NULLIF(num_rows, 0) * 100, 2) as pct_chained
FROM user_tables
WHERE compression = 'ENABLED'
ORDER BY rows_per_block DESC;

-- Identify tables needing compression
SELECT
    owner,
    table_name,
    ROUND(bytes/1024/1024/1024, 2) as size_gb,
    compression,
    compress_for,
    num_rows
FROM dba_tables t
JOIN (
    SELECT owner, segment_name, SUM(bytes) as bytes
    FROM dba_segments
    WHERE segment_type = 'TABLE'
    GROUP BY owner, segment_name
) s ON t.owner = s.owner AND t.table_name = s.segment_name
WHERE t.compression = 'DISABLED'
AND bytes > 1073741824  -- 1 GB or larger
ORDER BY bytes DESC;
```

### 2. DBA_SEGMENTS / ALL_SEGMENTS / USER_SEGMENTS

Essential for actual storage space analysis.

#### Key Columns

| Column | Data Type | Description |
|--------|-----------|-------------|
| OWNER | VARCHAR2(128) | Schema owner |
| SEGMENT_NAME | VARCHAR2(128) | Name of segment (table, index, partition) |
| PARTITION_NAME | VARCHAR2(128) | Partition name (if partitioned) |
| SEGMENT_TYPE | VARCHAR2(18) | TABLE, TABLE PARTITION, INDEX, etc. |
| TABLESPACE_NAME | VARCHAR2(30) | Tablespace containing the segment |
| BYTES | NUMBER | Actual storage in bytes |
| BLOCKS | NUMBER | Number of Oracle blocks |
| EXTENTS | NUMBER | Number of extents allocated |

#### Example Queries

```sql
-- Storage by table with compression info
SELECT
    t.owner,
    t.table_name,
    t.compress_for,
    ROUND(SUM(s.bytes)/1024/1024/1024, 2) as table_gb,
    COUNT(s.partition_name) as partition_count
FROM dba_tables t
JOIN dba_segments s ON t.owner = s.owner AND t.table_name = s.segment_name
WHERE s.segment_type IN ('TABLE','TABLE PARTITION')
AND t.owner NOT IN ('SYS','SYSTEM')
GROUP BY t.owner, t.table_name, t.compress_for
ORDER BY SUM(s.bytes) DESC;

-- Compare table and index sizes
SELECT
    t.owner,
    t.table_name,
    t.compress_for,
    ROUND(SUM(CASE WHEN s.segment_type LIKE 'TABLE%' THEN s.bytes ELSE 0 END)/1024/1024/1024, 2) as table_gb,
    ROUND(SUM(CASE WHEN s.segment_type LIKE 'INDEX%' THEN s.bytes ELSE 0 END)/1024/1024/1024, 2) as index_gb,
    ROUND(SUM(CASE WHEN s.segment_type LIKE 'INDEX%' THEN s.bytes ELSE 0 END) /
          NULLIF(SUM(CASE WHEN s.segment_type LIKE 'TABLE%' THEN s.bytes ELSE 0 END), 0) * 100, 2) as index_overhead_pct
FROM dba_tables t
JOIN dba_segments s ON t.owner = s.owner AND (
    (s.segment_type LIKE 'TABLE%' AND s.segment_name = t.table_name) OR
    (s.segment_type LIKE 'INDEX%' AND s.segment_name IN (
        SELECT index_name FROM dba_indexes WHERE table_owner = t.owner AND table_name = t.table_name
    ))
)
WHERE t.owner NOT IN ('SYS','SYSTEM')
GROUP BY t.owner, t.table_name, t.compress_for
HAVING SUM(CASE WHEN s.segment_type LIKE 'TABLE%' THEN s.bytes ELSE 0 END) > 1073741824
ORDER BY SUM(s.bytes) DESC;

-- Storage savings calculation
SELECT
    owner,
    segment_name,
    ROUND(bytes/1024/1024/1024, 2) as current_gb,
    ROUND(bytes/1024/1024/1024 * 0.90, 2) as estimated_after_10x_compression,
    ROUND(bytes/1024/1024/1024 * 0.10, 2) as savings_gb
FROM dba_segments
WHERE segment_type = 'TABLE'
AND owner = 'DATA_WAREHOUSE'
AND bytes > 10737418240  -- 10 GB or larger
ORDER BY bytes DESC;
```

### 3. DBA_TAB_PARTITIONS / USER_TAB_PARTITIONS

Critical for partition-level compression analysis and management.

#### Key Columns

| Column | Data Type | Description |
|--------|-----------|-------------|
| TABLE_OWNER | VARCHAR2(128) | Schema owner |
| TABLE_NAME | VARCHAR2(128) | Table name |
| PARTITION_NAME | VARCHAR2(128) | Partition name |
| PARTITION_POSITION | NUMBER | Position in partition order |
| HIGH_VALUE | LONG | Upper bound for partition range |
| COMPRESSION | VARCHAR2(8) | ENABLED or DISABLED |
| COMPRESS_FOR | VARCHAR2(30) | Compression type |
| NUM_ROWS | NUMBER | Approximate row count |
| BLOCKS | NUMBER | Number of blocks |
| LAST_ANALYZED | DATE | Statistics timestamp |

#### Example Queries

```sql
-- Analyze compression by partition age
SELECT
    table_owner,
    table_name,
    partition_name,
    partition_position,
    SUBSTR(high_value, 1, 50) as high_value,
    compress_for,
    ROUND(bytes/1024/1024/1024, 2) as size_gb,
    num_rows,
    last_analyzed
FROM dba_tab_partitions p
JOIN dba_segments s ON p.table_owner = s.owner
    AND p.table_name = s.segment_name
    AND p.partition_name = s.partition_name
WHERE table_owner = 'SALES_SCHEMA'
AND table_name = 'SALES_HISTORY'
ORDER BY partition_position DESC;

-- Identify partitions for compression upgrade
SELECT
    table_owner,
    table_name,
    partition_name,
    compress_for,
    ROUND(bytes/1024/1024/1024, 2) as size_gb,
    CASE
        WHEN compress_for IS NULL THEN 'Add QUERY HIGH'
        WHEN compress_for = 'QUERY LOW' THEN 'Upgrade to QUERY HIGH'
        WHEN compress_for = 'QUERY HIGH' AND partition_position < 12
            THEN 'Upgrade to ARCHIVE LOW'
        WHEN compress_for = 'ARCHIVE LOW' AND partition_position < 4
            THEN 'Upgrade to ARCHIVE HIGH'
        ELSE 'Optimal'
    END as recommendation
FROM dba_tab_partitions p
JOIN dba_segments s ON p.table_owner = s.owner
    AND p.table_name = s.segment_name
    AND p.partition_name = s.partition_name
WHERE table_owner NOT IN ('SYS','SYSTEM')
AND bytes > 1073741824  -- 1 GB minimum
ORDER BY bytes DESC;

-- Partition compression consistency check
SELECT
    table_owner,
    table_name,
    compress_for,
    COUNT(*) as partition_count,
    ROUND(SUM(bytes)/1024/1024/1024, 2) as total_gb
FROM dba_tab_partitions p
JOIN dba_segments s ON p.table_owner = s.owner
    AND p.table_name = s.segment_name
    AND p.partition_name = s.partition_name
WHERE table_owner = 'DATA_WAREHOUSE'
GROUP BY table_owner, table_name, compress_for
ORDER BY table_owner, table_name, compress_for;
```

### 4. DBA_TAB_MODIFICATIONS

Tracks DML activity to identify HCC suitability.

#### Key Columns

| Column | Data Type | Description |
|--------|-----------|-------------|
| TABLE_OWNER | VARCHAR2(128) | Schema owner |
| TABLE_NAME | VARCHAR2(128) | Table name |
| PARTITION_NAME | VARCHAR2(128) | Partition name (if partitioned) |
| INSERTS | NUMBER | Approximate inserts since last stats |
| UPDATES | NUMBER | Approximate updates since last stats |
| DELETES | NUMBER | Approximate deletes since last stats |
| TIMESTAMP | DATE | When modifications were recorded |

#### Example Queries

```sql
-- Identify low-DML tables suitable for HCC
SELECT
    m.table_owner,
    m.table_name,
    t.compress_for,
    t.num_rows,
    NVL(m.inserts, 0) as inserts,
    NVL(m.updates, 0) as updates,
    NVL(m.deletes, 0) as deletes,
    ROUND((NVL(m.updates,0) + NVL(m.deletes,0)) / NULLIF(t.num_rows, 0) * 100, 2) as pct_modified,
    CASE
        WHEN (NVL(m.updates,0) + NVL(m.deletes,0)) = 0 THEN 'Excellent - Pure append'
        WHEN (NVL(m.updates,0) + NVL(m.deletes,0)) / NULLIF(t.num_rows, 0) < 0.01
            THEN 'Good - <1% modified'
        WHEN (NVL(m.updates,0) + NVL(m.deletes,0)) / NULLIF(t.num_rows, 0) < 0.05
            THEN 'Acceptable - 1-5% modified'
        ELSE 'Poor - Consider row compression'
    END as hcc_suitability
FROM dba_tab_modifications m
JOIN dba_tables t ON m.table_owner = t.owner AND m.table_name = t.table_name
WHERE m.table_owner NOT IN ('SYS','SYSTEM')
AND t.num_rows > 100000  -- Focus on larger tables
ORDER BY (NVL(m.updates,0) + NVL(m.deletes,0)) / NULLIF(t.num_rows, 0);

-- Monitor ongoing DML patterns
SELECT
    table_owner,
    table_name,
    SUM(inserts) as total_inserts,
    SUM(updates) as total_updates,
    SUM(deletes) as total_deletes,
    MAX(timestamp) as last_modification
FROM dba_tab_modifications
WHERE table_owner = 'SALES_SCHEMA'
AND timestamp > SYSDATE - 30  -- Last 30 days
GROUP BY table_owner, table_name
ORDER BY (SUM(updates) + SUM(deletes)) DESC;
```

### 5. DBA_TAB_COL_STATISTICS

Analyzes column characteristics for compression potential.

#### Key Columns

| Column | Data Type | Description |
|--------|-----------|-------------|
| OWNER | VARCHAR2(128) | Schema owner |
| TABLE_NAME | VARCHAR2(128) | Table name |
| COLUMN_NAME | VARCHAR2(128) | Column name |
| NUM_DISTINCT | NUMBER | Number of distinct values |
| NUM_NULLS | NUMBER | Number of NULL values |
| NUM_BUCKETS | NUMBER | Number of histogram buckets |
| DENSITY | NUMBER | Column density (1/NUM_DISTINCT approx.) |
| AVG_COL_LEN | NUMBER | Average column length |

#### Example Queries

```sql
-- Identify high-compression potential columns
SELECT
    owner,
    table_name,
    column_name,
    num_distinct,
    num_nulls,
    t.num_rows,
    ROUND(num_distinct / NULLIF(t.num_rows, 0) * 100, 2) as cardinality_pct,
    ROUND(num_nulls / NULLIF(t.num_rows, 0) * 100, 2) as null_pct,
    avg_col_len,
    CASE
        WHEN num_distinct / NULLIF(t.num_rows, 0) < 0.01 THEN 'Excellent - <1% cardinality'
        WHEN num_distinct / NULLIF(t.num_rows, 0) < 0.10 THEN 'Good - <10% cardinality'
        WHEN num_distinct / NULLIF(t.num_rows, 0) < 0.50 THEN 'Fair - <50% cardinality'
        ELSE 'Poor - High cardinality'
    END as compression_potential
FROM dba_tab_col_statistics c
JOIN dba_tables t ON c.owner = t.owner AND c.table_name = t.table_name
WHERE c.owner = 'DATA_WAREHOUSE'
AND t.num_rows > 1000000
ORDER BY num_distinct / NULLIF(t.num_rows, 0);

-- Column ordering recommendation
SELECT
    table_name,
    column_id,
    column_name,
    data_type,
    num_distinct,
    ROUND(num_distinct / NULLIF(num_rows, 0), 6) as cardinality_ratio,
    RANK() OVER (PARTITION BY table_name ORDER BY num_distinct / NULLIF(num_rows, 0)) as recommended_order
FROM dba_tab_columns c
JOIN dba_tables t ON c.owner = t.owner AND c.table_name = t.table_name
JOIN dba_tab_col_statistics s ON c.owner = s.owner
    AND c.table_name = s.table_name
    AND c.column_name = s.column_name
WHERE c.owner = 'SALES_SCHEMA'
AND c.table_name = 'CUSTOMER_ORDERS'
ORDER BY table_name, recommended_order;
```

## Dynamic Performance Views (V$ Views)

### 6. V$SQL / V$SQLSTATS

Monitors SQL performance for compressed tables.

#### Key Columns

| Column | Data Type | Description |
|--------|-----------|-------------|
| SQL_ID | VARCHAR2(13) | Unique SQL identifier |
| SQL_TEXT | VARCHAR2(1000) | SQL statement text |
| EXECUTIONS | NUMBER | Number of executions |
| ELAPSED_TIME | NUMBER | Total elapsed time (microseconds) |
| CPU_TIME | NUMBER | Total CPU time (microseconds) |
| BUFFER_GETS | NUMBER | Logical reads |
| DISK_READS | NUMBER | Physical reads |
| ROWS_PROCESSED | NUMBER | Rows returned/affected |

#### Example Queries

```sql
-- Performance of queries on compressed tables
SELECT
    sql_id,
    executions,
    ROUND(elapsed_time/1000000, 2) as total_elapsed_sec,
    ROUND(cpu_time/1000000, 2) as total_cpu_sec,
    ROUND(elapsed_time/NULLIF(executions,0)/1000, 2) as avg_elapsed_ms,
    buffer_gets,
    disk_reads,
    rows_processed,
    SUBSTR(sql_text, 1, 100) as sql_snippet
FROM v$sql
WHERE UPPER(sql_text) LIKE '%SALES_HISTORY%'
AND sql_text NOT LIKE '%v$sql%'
AND executions > 0
ORDER BY elapsed_time DESC;

-- Compare performance: compressed vs uncompressed
SELECT
    CASE
        WHEN UPPER(sql_text) LIKE '%_COMPRESSED%' THEN 'Compressed'
        ELSE 'Uncompressed'
    END as table_type,
    COUNT(*) as query_count,
    ROUND(AVG(elapsed_time/NULLIF(executions,0))/1000, 2) as avg_elapsed_ms,
    ROUND(AVG(cpu_time/NULLIF(executions,0))/1000, 2) as avg_cpu_ms,
    ROUND(AVG(buffer_gets/NULLIF(executions,0)), 2) as avg_buffer_gets,
    ROUND(AVG(disk_reads/NULLIF(executions,0)), 2) as avg_disk_reads
FROM v$sql
WHERE (UPPER(sql_text) LIKE '%SALES_FACT%'
    OR UPPER(sql_text) LIKE '%SALES_FACT_COMPRESSED%')
AND executions > 0
GROUP BY CASE WHEN UPPER(sql_text) LIKE '%_COMPRESSED%' THEN 'Compressed' ELSE 'Uncompressed' END;
```

### 7. V$SQL_PLAN

Examines execution plans for Smart Scan and compression.

#### Key Columns

| Column | Data Type | Description |
|--------|-----------|-------------|
| SQL_ID | VARCHAR2(13) | SQL identifier |
| OPERATION | VARCHAR2(30) | Plan operation (TABLE ACCESS FULL, etc.) |
| OPTIONS | VARCHAR2(255) | Operation options (STORAGE FULL, etc.) |
| OBJECT_OWNER | VARCHAR2(128) | Schema owner |
| OBJECT_NAME | VARCHAR2(128) | Object accessed |
| COST | NUMBER | Optimizer cost |
| CARDINALITY | NUMBER | Estimated rows |
| BYTES | NUMBER | Estimated bytes |

#### Example Queries

```sql
-- Identify Smart Scan operations on compressed tables
SELECT
    p.sql_id,
    p.object_owner,
    p.object_name,
    p.operation,
    p.options,
    t.compress_for,
    SUBSTR(s.sql_text, 1, 100) as sql_snippet
FROM v$sql_plan p
JOIN v$sql s ON p.sql_id = s.sql_id
LEFT JOIN dba_tables t ON p.object_owner = t.owner AND p.object_name = t.table_name
WHERE p.operation = 'TABLE ACCESS'
AND p.options LIKE '%STORAGE%'  -- Indicates Smart Scan
AND t.compress_for IS NOT NULL
ORDER BY p.sql_id, p.id;
```

### 8. V$CELL_STATE (Exadata-specific)

Monitors Exadata storage cell status and Smart Scan.

```sql
-- Check Smart Scan offloading for compressed tables
SELECT
    sql_id,
    sql_exec_id,
    io_cell_offload_eligible_bytes,
    io_cell_offload_returned_bytes,
    ROUND((io_cell_offload_eligible_bytes - io_cell_offload_returned_bytes) /
        NULLIF(io_cell_offload_eligible_bytes, 0) * 100, 2) as offload_pct
FROM v$sql
WHERE io_cell_offload_eligible_bytes > 0
ORDER BY offload_pct DESC;
```

## AWR/Statspack Historical Views

### 9. DBA_HIST_SQLSTAT

Historical SQL performance analysis.

```sql
-- Historical performance trends for compressed tables
SELECT
    TO_CHAR(s.end_interval_time, 'YYYY-MM-DD HH24') as snapshot_hour,
    sql.sql_id,
    SUM(st.executions_delta) as executions,
    ROUND(SUM(st.elapsed_time_delta)/1000000, 2) as total_elapsed_sec,
    ROUND(AVG(st.elapsed_time_delta/NULLIF(st.executions_delta,0))/1000, 2) as avg_elapsed_ms
FROM dba_hist_sqlstat st
JOIN dba_hist_snapshot s ON st.snap_id = s.snap_id
JOIN dba_hist_sqltext sql ON st.sql_id = sql.sql_id
WHERE UPPER(sql.sql_text) LIKE '%SALES_COMPRESSED%'
AND s.end_interval_time > SYSDATE - 7
GROUP BY TO_CHAR(s.end_interval_time, 'YYYY-MM-DD HH24'), sql.sql_id
ORDER BY snapshot_hour, sql_id;
```

### 10. DBA_HIST_SEG_STAT

Segment-level I/O statistics.

```sql
-- I/O patterns for compressed tables
SELECT
    obj.owner,
    obj.object_name,
    t.compress_for,
    SUM(st.logical_reads_delta) as logical_reads,
    SUM(st.physical_reads_delta) as physical_reads,
    ROUND(SUM(st.physical_reads_delta) / NULLIF(SUM(st.logical_reads_delta), 0) * 100, 2) as cache_miss_pct
FROM dba_hist_seg_stat st
JOIN dba_objects obj ON st.obj# = obj.object_id
LEFT JOIN dba_tables t ON obj.owner = t.owner AND obj.object_name = t.table_name
WHERE st.snap_id > (SELECT MAX(snap_id) - 168 FROM dba_hist_snapshot)  -- Last 7 days
AND obj.object_type = 'TABLE'
AND t.compress_for IS NOT NULL
GROUP BY obj.owner, obj.object_name, t.compress_for
ORDER BY SUM(st.logical_reads_delta) DESC;
```

## Utility Queries and Functions

### 11. DBMS_COMPRESSION Package

Oracle-provided compression utilities.

```sql
-- Estimate compression ratio
DECLARE
    l_scratch_tbs VARCHAR2(30) := 'USERS';
    l_owner VARCHAR2(30) := 'SALES_SCHEMA';
    l_table VARCHAR2(30) := 'SALES_FACT';
    l_blkcnt_cmp PLS_INTEGER;
    l_blkcnt_uncmp PLS_INTEGER;
    l_row_cmp PLS_INTEGER;
    l_row_uncmp PLS_INTEGER;
    l_cmp_ratio NUMBER;
    l_comptype_str VARCHAR2(100);
BEGIN
    -- Test QUERY HIGH compression
    DBMS_COMPRESSION.GET_COMPRESSION_RATIO(
        scratchtbsname => l_scratch_tbs,
        ownname => l_owner,
        objname => l_table,
        subobjname => NULL,
        comptype => DBMS_COMPRESSION.COMP_FOR_QUERY_HIGH,
        blkcnt_cmp => l_blkcnt_cmp,
        blkcnt_uncmp => l_blkcnt_uncmp,
        row_cmp => l_row_cmp,
        row_uncmp => l_row_uncmp,
        cmp_ratio => l_cmp_ratio,
        comptype_str => l_comptype_str,
        subset_numrows => 1000000
    );

    DBMS_OUTPUT.PUT_LINE('=== QUERY HIGH Compression Estimate ===');
    DBMS_OUTPUT.PUT_LINE('Compression Type: ' || l_comptype_str);
    DBMS_OUTPUT.PUT_LINE('Compression Ratio: ' || ROUND(l_cmp_ratio, 2) || ':1');
    DBMS_OUTPUT.PUT_LINE('Blocks (Compressed): ' || l_blkcnt_cmp);
    DBMS_OUTPUT.PUT_LINE('Blocks (Uncompressed): ' || l_blkcnt_uncmp);
    DBMS_OUTPUT.PUT_LINE('Estimated Space Savings: ' ||
        ROUND((1 - l_blkcnt_cmp/l_blkcnt_uncmp) * 100, 2) || '%');
END;
/
```

### 12. Comprehensive Compression Analysis Query

```sql
-- All-in-one compression analysis
WITH table_storage AS (
    SELECT
        owner,
        segment_name as table_name,
        SUM(bytes) as bytes,
        SUM(blocks) as blocks
    FROM dba_segments
    WHERE segment_type IN ('TABLE','TABLE PARTITION')
    AND owner NOT IN ('SYS','SYSTEM')
    GROUP BY owner, segment_name
),
dml_activity AS (
    SELECT
        table_owner,
        table_name,
        SUM(NVL(inserts,0)) as inserts,
        SUM(NVL(updates,0)) as updates,
        SUM(NVL(deletes,0)) as deletes
    FROM dba_tab_modifications
    WHERE timestamp > SYSDATE - 30
    GROUP BY table_owner, table_name
)
SELECT
    t.owner,
    t.table_name,
    t.compression,
    t.compress_for,
    ROUND(s.bytes/1024/1024/1024, 2) as size_gb,
    t.num_rows,
    ROUND(t.num_rows/NULLIF(s.blocks,0), 2) as rows_per_block,
    ROUND(t.chain_cnt/NULLIF(t.num_rows,0)*100, 2) as pct_chained,
    NVL(d.inserts, 0) as monthly_inserts,
    NVL(d.updates, 0) as monthly_updates,
    NVL(d.deletes, 0) as monthly_deletes,
    ROUND((NVL(d.updates,0) + NVL(d.deletes,0))/NULLIF(t.num_rows,0)*100, 2) as pct_modified,
    t.last_analyzed,
    CASE
        WHEN t.compress_for IS NULL AND s.bytes > 10737418240
            THEN 'Candidate: Add HCC compression'
        WHEN t.compress_for = 'QUERY LOW' AND (NVL(d.updates,0) + NVL(d.deletes,0)) = 0
            THEN 'Optimize: Upgrade to QUERY HIGH'
        WHEN t.chain_cnt/NULLIF(t.num_rows,0) > 0.10
            THEN 'Action: Recompress (excessive row migration)'
        WHEN t.last_analyzed < SYSDATE - 90
            THEN 'Action: Gather statistics'
        ELSE 'OK'
    END as recommendation
FROM dba_tables t
JOIN table_storage s ON t.owner = s.owner AND t.table_name = s.table_name
LEFT JOIN dml_activity d ON t.owner = d.table_owner AND t.table_name = d.table_name
WHERE s.bytes > 104857600  -- 100 MB minimum
ORDER BY s.bytes DESC;
```

## Summary Reference Table

| Analysis Task | Primary View | Supporting Views |
|--------------|--------------|------------------|
| Find compression candidates | DBA_SEGMENTS | DBA_TABLES, DBA_TAB_MODIFICATIONS |
| Check compression effectiveness | DBA_TABLES | DBA_SEGMENTS, DBA_TAB_PARTITIONS |
| Monitor DML activity | DBA_TAB_MODIFICATIONS | DBA_TABLES |
| Analyze column characteristics | DBA_TAB_COL_STATISTICS | DBA_TABLES |
| Track query performance | V$SQL, V$SQLSTATS | V$SQL_PLAN |
| Historical analysis | DBA_HIST_SQLSTAT | DBA_HIST_SEG_STAT, DBA_HIST_SNAPSHOT |
| Partition management | DBA_TAB_PARTITIONS | DBA_SEGMENTS |
| Smart Scan verification | V$SQL | V$SQL_PLAN |
| Compression estimation | DBMS_COMPRESSION | DBA_TABLES |

## References
- Oracle Database Reference Guide
- Oracle Database Administrator's Guide
- Oracle Performance Tuning Guide
- Exadata Storage Server Software Documentation
