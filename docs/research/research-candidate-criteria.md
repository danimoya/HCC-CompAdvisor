# HCC Candidate Table Identification Criteria

## Overview
Identifying optimal candidates for HCC compression requires analyzing multiple factors including table size, access patterns, DML activity, and business requirements. This document provides comprehensive criteria and methodologies.

## Primary Identification Criteria

### 1. Table Size Thresholds

#### Minimum Size Recommendations
- **Absolute minimum**: 100 MB (compression overhead not worthwhile below this)
- **Recommended minimum**: 1 GB (meaningful storage savings)
- **Optimal candidates**: 10 GB+ (maximum benefit from HCC)
- **Prime candidates**: 100 GB+ (dramatic storage reduction)

#### Size-Based Scoring
```
Score = 0 (< 100 MB) - Not recommended
Score = 1 (100 MB - 1 GB) - Low priority
Score = 3 (1 GB - 10 GB) - Medium priority
Score = 5 (10 GB - 100 GB) - High priority
Score = 7 (100 GB+) - Critical priority
```

#### Query to Identify Large Tables
```sql
SELECT
    owner,
    table_name,
    ROUND(bytes/1024/1024/1024, 2) as size_gb,
    num_rows,
    CASE
        WHEN bytes >= 107374182400 THEN 'Critical (100GB+)'
        WHEN bytes >= 10737418240 THEN 'High (10-100GB)'
        WHEN bytes >= 1073741824 THEN 'Medium (1-10GB)'
        WHEN bytes >= 104857600 THEN 'Low (100MB-1GB)'
        ELSE 'Too Small'
    END as candidate_priority
FROM (
    SELECT
        s.owner,
        s.segment_name as table_name,
        SUM(s.bytes) as bytes,
        t.num_rows
    FROM dba_segments s
    JOIN dba_tables t ON s.owner = t.owner AND s.segment_name = t.table_name
    WHERE s.segment_type = 'TABLE'
    AND s.owner NOT IN ('SYS','SYSTEM','OUTLN','DBSNMP')
    GROUP BY s.owner, s.segment_name, t.num_rows
)
WHERE bytes >= 104857600  -- 100 MB minimum
ORDER BY bytes DESC;
```

### 2. Access Pattern Analysis

#### Read vs Write Ratio
- **Ideal candidates**: 95%+ read operations
- **Good candidates**: 80-95% read operations
- **Marginal candidates**: 70-80% read operations
- **Poor candidates**: < 70% read operations

#### Query to Analyze Access Patterns
```sql
-- Identify read-heavy tables (requires AWR/Statspack)
SELECT
    obj.owner,
    obj.object_name as table_name,
    SUM(CASE WHEN s.operation = 'TABLE ACCESS FULL' THEN 1 ELSE 0 END) as full_scans,
    SUM(CASE WHEN s.operation LIKE '%INDEX%' THEN 1 ELSE 0 END) as index_scans,
    COUNT(DISTINCT s.sql_id) as unique_queries,
    ROUND(SUM(s.elapsed_time_delta)/1000000, 2) as total_elapsed_sec
FROM dba_hist_sql_plan p
JOIN dba_hist_sqlstat s ON p.sql_id = s.sql_id
JOIN dba_objects obj ON p.object_owner = obj.owner
    AND p.object_name = obj.object_name
WHERE obj.object_type = 'TABLE'
AND s.snap_id BETWEEN (SELECT MAX(snap_id)-168 FROM dba_hist_snapshot)  -- Last 7 days
    AND (SELECT MAX(snap_id) FROM dba_hist_snapshot)
GROUP BY obj.owner, obj.object_name
HAVING SUM(CASE WHEN s.operation = 'TABLE ACCESS FULL' THEN 1 ELSE 0 END) > 100
ORDER BY full_scans DESC;
```

### 3. DML Activity Analysis

#### DML Frequency Thresholds
- **Excellent**: No DML after initial load (archive tables)
- **Good**: Batch INSERT only (nightly/weekly loads)
- **Acceptable**: < 1% rows modified per month
- **Marginal**: 1-5% rows modified per month
- **Unsuitable**: > 5% rows modified per month or frequent UPDATE/DELETE

#### DML Tracking Query
```sql
-- Monitor DML activity over 30 days
SELECT
    table_owner,
    table_name,
    inserts,
    updates,
    deletes,
    ROUND((updates + deletes) / NULLIF(num_rows, 0) * 100, 2) as pct_modified,
    CASE
        WHEN (updates + deletes) = 0 THEN 'Excellent - No modifications'
        WHEN (updates + deletes) / NULLIF(num_rows, 0) < 0.01 THEN 'Good - <1% modified'
        WHEN (updates + deletes) / NULLIF(num_rows, 0) < 0.05 THEN 'Acceptable - 1-5% modified'
        ELSE 'Unsuitable - >5% modified'
    END as hcc_suitability
FROM dba_tab_modifications
WHERE table_owner NOT IN ('SYS','SYSTEM')
AND inserts + updates + deletes > 0
ORDER BY (updates + deletes) / NULLIF(num_rows, 0);
```

### 4. Data Age and Update Frequency

#### Time-Based Partitioning Analysis
- **Current partition**: No compression or QUERY LOW
- **Recent (< 90 days)**: QUERY LOW or QUERY HIGH
- **Historical (90-365 days)**: QUERY HIGH or ARCHIVE LOW
- **Archive (1-3 years)**: ARCHIVE LOW
- **Cold archive (3+ years)**: ARCHIVE HIGH

#### Age-Based Candidate Query
```sql
-- Identify partition candidates by age
SELECT
    table_owner,
    table_name,
    partition_name,
    high_value,
    ROUND(bytes/1024/1024/1024, 2) as size_gb,
    num_rows,
    compression,
    compress_for,
    CASE
        WHEN partition_position = MAX(partition_position) OVER (PARTITION BY table_name)
            THEN 'Current - No HCC'
        WHEN TO_DATE(SUBSTR(high_value, 11, 10), 'YYYY-MM-DD') > ADD_MONTHS(SYSDATE, -3)
            THEN 'Recent - QUERY LOW/HIGH'
        WHEN TO_DATE(SUBSTR(high_value, 11, 10), 'YYYY-MM-DD') > ADD_MONTHS(SYSDATE, -12)
            THEN 'Historical - QUERY HIGH/ARCHIVE LOW'
        WHEN TO_DATE(SUBSTR(high_value, 11, 10), 'YYYY-MM-DD') > ADD_MONTHS(SYSDATE, -36)
            THEN 'Archive - ARCHIVE LOW'
        ELSE 'Cold - ARCHIVE HIGH'
    END as recommended_compression
FROM dba_tab_partitions
WHERE table_owner NOT IN ('SYS','SYSTEM')
AND bytes > 1073741824  -- 1 GB minimum
ORDER BY table_owner, table_name, partition_position;
```

### 5. Storage Savings Potential

#### Compression Estimation
Use Oracle's `DBMS_COMPRESSION.GET_COMPRESSION_RATIO` to estimate potential savings.

```sql
-- Estimate compression ratio for a table
DECLARE
    l_blkcnt_cmp PLS_INTEGER;
    l_blkcnt_uncmp PLS_INTEGER;
    l_row_cmp PLS_INTEGER;
    l_row_uncmp PLS_INTEGER;
    l_cmp_ratio NUMBER;
    l_comptype_str VARCHAR2(100);
BEGIN
    DBMS_COMPRESSION.GET_COMPRESSION_RATIO(
        scratchtbsname => 'USERS',
        ownname => 'SALES_SCHEMA',
        objname => 'SALES_FACT',
        subobjname => NULL,
        comptype => DBMS_COMPRESSION.COMP_FOR_QUERY_HIGH,
        blkcnt_cmp => l_blkcnt_cmp,
        blkcnt_uncmp => l_blkcnt_uncmp,
        row_cmp => l_row_cmp,
        row_uncmp => l_row_uncmp,
        cmp_ratio => l_cmp_ratio,
        comptype_str => l_comptype_str,
        subset_numrows => 1000000  -- Sample size
    );

    DBMS_OUTPUT.PUT_LINE('Compression Type: ' || l_comptype_str);
    DBMS_OUTPUT.PUT_LINE('Compression Ratio: ' || l_cmp_ratio);
    DBMS_OUTPUT.PUT_LINE('Blocks Compressed: ' || l_blkcnt_cmp);
    DBMS_OUTPUT.PUT_LINE('Blocks Uncompressed: ' || l_blkcnt_uncmp);
    DBMS_OUTPUT.PUT_LINE('Rows Compressed: ' || l_row_cmp);
    DBMS_OUTPUT.PUT_LINE('Rows Uncompressed: ' || l_row_uncmp);
END;
/
```

#### ROI Calculation
```sql
-- Calculate storage savings ROI
WITH compression_estimates AS (
    SELECT
        owner,
        table_name,
        bytes as current_bytes,
        bytes / 10 as query_high_bytes,  -- Assume 10x compression
        bytes / 15 as archive_low_bytes,  -- Assume 15x compression
        bytes / 20 as archive_high_bytes  -- Assume 20x compression
    FROM (
        SELECT owner, segment_name as table_name, SUM(bytes) as bytes
        FROM dba_segments
        WHERE segment_type = 'TABLE'
        AND owner NOT IN ('SYS','SYSTEM')
        GROUP BY owner, segment_name
    )
    WHERE bytes > 1073741824  -- 1 GB minimum
)
SELECT
    owner,
    table_name,
    ROUND(current_bytes/1024/1024/1024, 2) as current_gb,
    ROUND((current_bytes - query_high_bytes)/1024/1024/1024, 2) as query_high_savings_gb,
    ROUND((current_bytes - archive_low_bytes)/1024/1024/1024, 2) as archive_low_savings_gb,
    ROUND((current_bytes - archive_high_bytes)/1024/1024/1024, 2) as archive_high_savings_gb,
    ROUND((1 - query_high_bytes/current_bytes) * 100, 1) as query_high_pct,
    ROUND((1 - archive_low_bytes/current_bytes) * 100, 1) as archive_low_pct,
    ROUND((1 - archive_high_bytes/current_bytes) * 100, 1) as archive_high_pct
FROM compression_estimates
ORDER BY current_bytes DESC;
```

## Advanced Candidate Identification

### 6. Workload Characteristics

#### Data Warehouse Tables
- **Fact tables**: Excellent candidates (large, read-heavy, batch loads)
- **Dimension tables**: Good candidates if > 1 GB
- **Staging tables**: Poor candidates (high DML churn)
- **Aggregate tables**: Good candidates (read-only after build)

#### OLTP Tables with History
- **Transaction history**: Excellent (append-only archives)
- **Audit trails**: Excellent (compliance retention)
- **Log tables**: Excellent (immutable after creation)
- **Active transactions**: Poor (frequent updates)

### 7. Column Characteristics

#### High-Compression Columns
- **Low cardinality**: Status codes, categories, flags
- **Repetitive values**: Postal codes, product IDs, region codes
- **Sorted data**: Sequential IDs, timestamps
- **Null-heavy columns**: Optional fields with sparse data

#### Query for Column Analysis
```sql
-- Analyze column characteristics for compression potential
SELECT
    owner,
    table_name,
    column_name,
    num_distinct,
    num_nulls,
    density,
    num_rows,
    ROUND((1 - (num_distinct / NULLIF(num_rows, 0))) * 100, 2) as repetition_pct,
    ROUND((num_nulls / NULLIF(num_rows, 0)) * 100, 2) as null_pct,
    CASE
        WHEN num_distinct / NULLIF(num_rows, 0) < 0.01 THEN 'Excellent - <1% cardinality'
        WHEN num_distinct / NULLIF(num_rows, 0) < 0.10 THEN 'Good - <10% cardinality'
        WHEN num_distinct / NULLIF(num_rows, 0) < 0.50 THEN 'Fair - <50% cardinality'
        ELSE 'Poor - High cardinality'
    END as compression_potential
FROM dba_tab_col_statistics
WHERE owner NOT IN ('SYS','SYSTEM')
AND num_rows > 1000000  -- Tables with 1M+ rows
ORDER BY repetition_pct DESC;
```

### 8. Index Considerations

#### Impact on Indexes
- **HCC does NOT compress indexes**: Indexes remain at their original size
- **Bitmap indexes**: Work well with HCC (common in DW)
- **B-tree indexes**: Performance unchanged
- **Index overhead**: May increase as % of total table+index size

#### Query for Index Analysis
```sql
-- Analyze index overhead for HCC candidates
SELECT
    t.owner,
    t.table_name,
    ROUND(SUM(s.bytes)/1024/1024/1024, 2) as table_gb,
    ROUND(SUM(i.bytes)/1024/1024/1024, 2) as index_gb,
    ROUND(SUM(i.bytes) / NULLIF(SUM(s.bytes), 0) * 100, 2) as index_overhead_pct,
    COUNT(DISTINCT i.index_name) as index_count
FROM dba_tables t
JOIN dba_segments s ON t.owner = s.owner AND t.table_name = s.segment_name
LEFT JOIN (
    SELECT owner, table_name, index_name, SUM(bytes) as bytes
    FROM dba_segments
    WHERE segment_type LIKE 'INDEX%'
    GROUP BY owner, table_name, index_name
) i ON t.owner = i.owner AND t.table_name = i.table_name
WHERE s.segment_type = 'TABLE'
AND t.owner NOT IN ('SYS','SYSTEM')
GROUP BY t.owner, t.table_name
HAVING SUM(s.bytes) > 1073741824  -- 1 GB minimum
ORDER BY SUM(s.bytes) DESC;
```

## Composite Scoring System

### Weighted Candidate Score
Combine multiple factors into a single HCC suitability score (0-100).

```sql
WITH candidate_metrics AS (
    SELECT
        t.owner,
        t.table_name,
        -- Size score (0-25 points)
        CASE
            WHEN seg.bytes >= 107374182400 THEN 25  -- 100GB+
            WHEN seg.bytes >= 10737418240 THEN 20   -- 10-100GB
            WHEN seg.bytes >= 1073741824 THEN 15    -- 1-10GB
            WHEN seg.bytes >= 104857600 THEN 10     -- 100MB-1GB
            ELSE 0
        END as size_score,
        -- DML score (0-25 points)
        CASE
            WHEN NVL(m.updates + m.deletes, 0) = 0 THEN 25
            WHEN (m.updates + m.deletes) / NULLIF(t.num_rows, 0) < 0.01 THEN 20
            WHEN (m.updates + m.deletes) / NULLIF(t.num_rows, 0) < 0.05 THEN 10
            ELSE 0
        END as dml_score,
        -- Access pattern score (0-25 points) - simplified
        CASE
            WHEN t.last_analyzed < SYSDATE - 90 THEN 20  -- Rarely accessed
            WHEN t.last_analyzed < SYSDATE - 30 THEN 15
            ELSE 10
        END as access_score,
        -- Compression potential score (0-25 points)
        25 as compression_score  -- Placeholder, would need column stats
    FROM dba_tables t
    JOIN (
        SELECT owner, segment_name, SUM(bytes) as bytes
        FROM dba_segments
        WHERE segment_type = 'TABLE'
        GROUP BY owner, segment_name
    ) seg ON t.owner = seg.owner AND t.table_name = seg.segment_name
    LEFT JOIN dba_tab_modifications m
        ON t.owner = m.table_owner AND t.table_name = m.table_name
    WHERE t.owner NOT IN ('SYS','SYSTEM')
    AND seg.bytes > 104857600  -- 100 MB minimum
)
SELECT
    owner,
    table_name,
    size_score,
    dml_score,
    access_score,
    compression_score,
    (size_score + dml_score + access_score + compression_score) as total_score,
    CASE
        WHEN (size_score + dml_score + access_score + compression_score) >= 80
            THEN 'Excellent Candidate - ARCHIVE'
        WHEN (size_score + dml_score + access_score + compression_score) >= 60
            THEN 'Good Candidate - QUERY HIGH'
        WHEN (size_score + dml_score + access_score + compression_score) >= 40
            THEN 'Fair Candidate - QUERY LOW'
        ELSE 'Poor Candidate - Consider ROW compression'
    END as recommendation
FROM candidate_metrics
ORDER BY total_score DESC;
```

## Decision Matrix

| Criterion | Weight | Excellent | Good | Fair | Poor |
|-----------|--------|-----------|------|------|------|
| Size | 25% | 100GB+ | 10-100GB | 1-10GB | <1GB |
| DML Activity | 25% | No DML | <1% modified | 1-5% modified | >5% modified |
| Access Pattern | 25% | Monthly+ | Weekly | Daily reads | Frequent writes |
| Data Type | 25% | Low cardinality | Repetitive | Mixed | High cardinality |

## Practical Recommendations

### Quick Win Candidates
1. **Historical partitions**: Older than 90 days, rarely accessed
2. **Archive tables**: Compliance/audit data with no modifications
3. **Large fact tables**: Data warehouse analytics with batch loads
4. **Log tables**: Application logs, immutable after creation

### Caution Candidates
1. **Frequently updated dimensions**: Small dimension tables with regular updates
2. **Active OLTP tables**: Tables with continuous INSERT/UPDATE/DELETE
3. **Small tables**: < 1 GB tables with minimal storage benefit
4. **Heavily indexed tables**: Index size may dominate after table compression

### Implementation Priority
1. **Phase 1**: Tables > 100 GB with no DML (highest impact)
2. **Phase 2**: Tables 10-100 GB with minimal DML (high impact)
3. **Phase 3**: Partitions of large tables by age (targeted compression)
4. **Phase 4**: Tables 1-10 GB with good characteristics (gradual rollout)

## Monitoring and Validation

### Post-Implementation Checks
```sql
-- Validate compression effectiveness
SELECT
    owner,
    table_name,
    compress_for,
    ROUND(SUM(bytes)/1024/1024/1024, 2) as compressed_gb,
    ROUND(SUM(bytes_before)/1024/1024/1024, 2) as original_gb,
    ROUND((1 - SUM(bytes)/SUM(bytes_before)) * 100, 2) as savings_pct
FROM (
    SELECT
        owner,
        table_name,
        compress_for,
        bytes,
        bytes * 10 as bytes_before  -- Assume 10x compression for QUERY HIGH
    FROM dba_segments
    WHERE segment_type = 'TABLE'
    AND compress_for LIKE '%QUERY%' OR compress_for LIKE '%ARCHIVE%'
)
GROUP BY owner, table_name, compress_for
ORDER BY savings_pct DESC;
```

## References
- Oracle Exadata Best Practices
- Oracle Database Administrator's Guide - Compression
- Oracle Pro Labs - HCC Candidate Identification
- AWS Prescriptive Guidance - Oracle Exadata Blueprint
