# HCC Compression Advisor - User Guide

## Table of Contents
1. [Introduction](#introduction)
2. [Getting Started](#getting-started)
3. [Configuration](#configuration)
4. [Using the Compression Advisor](#using-the-compression-advisor)
5. [Understanding Compression Strategies](#understanding-compression-strategies)
6. [Troubleshooting Guide](#troubleshooting-guide)
7. [FAQ](#faq)

## Introduction

The HCC (Hybrid Columnar Compression) Compression Advisor is an automated system that analyzes Oracle database objects and recommends optimal compression strategies to maximize storage savings while minimizing performance impact.

### Key Features
- **Intelligent Analysis**: Automatically analyzes tables, partitions, indexes, and LOBs
- **Smart Recommendations**: Uses workload patterns and access metrics to suggest optimal compression
- **Three Compression Strategies**: Conservative, Balanced, and Aggressive approaches
- **ORDS Integration**: RESTful API for remote management
- **Streamlit Dashboard**: Web-based interface for monitoring and management
- **Complete Audit Trail**: Tracks all compression operations with before/after metrics

### System Requirements
- Oracle Database 19c or higher (Enterprise Edition)
- ExaCC (Exadata Cloud at Customer) for HCC features
- Python 3.8+ with oracledb client (for dashboard)
- ORDS 20.4+ (for REST API)

## Getting Started

### First Time Setup

#### 1. Verify Installation
Connect to your PDB and verify the compression packages are installed:

```sql
-- Check packages
SELECT object_name, object_type, status
FROM user_objects
WHERE object_name LIKE 'PKG_COMPRESS%'
ORDER BY object_name;

-- Expected output:
-- PKG_COMPRESS_ADVISOR (PACKAGE)
-- PKG_COMPRESS_ADVISOR (PACKAGE BODY)
-- PKG_COMPRESS_EXECUTOR (PACKAGE)
-- PKG_COMPRESS_EXECUTOR (PACKAGE BODY)
```

#### 2. Verify Scratch Tablespace
The compression advisor requires a scratch tablespace:

```sql
-- Create scratch tablespace if not exists
CREATE TABLESPACE SCRATCH
DATAFILE SIZE 500M
AUTOEXTEND ON NEXT 100M MAXSIZE 2G;

-- Grant quota to compression manager schema
ALTER USER COMPRESSION_MGR QUOTA UNLIMITED ON SCRATCH;
```

#### 3. Run Initial Analysis
Perform your first compression analysis:

```sql
-- Analyze all user tables
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES;

-- View results
SELECT owner, table_name, advisable_compression,
       estimated_savings_mb, hot_score
FROM V_COMPRESSION_CANDIDATES
ORDER BY estimated_savings_mb DESC
FETCH FIRST 20 ROWS ONLY;
```

### Quick Start Example

Analyze and compress a single table:

```sql
-- 1. Analyze specific table
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_SPECIFIC_TABLE('HR', 'EMPLOYEES');

-- 2. Check recommendation
SELECT advisable_compression, estimated_savings_mb, hot_score
FROM COMPRESSION_ANALYSIS
WHERE owner = 'HR' AND table_name = 'EMPLOYEES';

-- 3. Apply recommended compression
EXEC PKG_COMPRESSION_EXECUTOR.COMPRESS_TABLE(
    p_owner => 'HR',
    p_table_name => 'EMPLOYEES',
    p_compression_type => NULL,  -- Use recommended
    p_online => TRUE
);

-- 4. Verify results
SELECT original_size_mb, compressed_size_mb,
       space_saved_mb, compression_ratio_achieved
FROM COMPRESSION_HISTORY
WHERE owner = 'HR' AND object_name = 'EMPLOYEES'
ORDER BY start_time DESC
FETCH FIRST 1 ROW ONLY;
```

## Configuration

### Compression Strategies

The system supports three configurable compression strategies that can be stored in control tables:

#### 1. Conservative Strategy
**Best for**: High-transaction OLTP systems
- Minimum table size threshold: 50 GB
- Preferred compression: OLTP or Query Low
- Avoids aggressive compression for hot tables
- Lower risk, moderate savings (20-40%)

```sql
-- Configuration example
UPDATE COMPRESSION_CONFIG
SET strategy_type = 'CONSERVATIVE',
    min_table_size_gb = 50,
    preferred_compression = 'OLTP',
    hot_score_threshold = 80
WHERE strategy_name = 'PRIMARY_STRATEGY';
```

#### 2. Balanced Strategy (Default)
**Best for**: Mixed workloads
- Minimum table size threshold: 10 GB
- Dynamic compression based on access patterns
- Balances savings and performance (40-60%)

```sql
-- Configuration example
UPDATE COMPRESSION_CONFIG
SET strategy_type = 'BALANCED',
    min_table_size_gb = 10,
    hot_score_threshold = 50
WHERE strategy_name = 'PRIMARY_STRATEGY';
```

#### 3. Aggressive Strategy
**Best for**: Data warehouses and archival systems
- Minimum table size threshold: 1 GB
- Maximizes compression ratios
- Highest savings (60-90%)

```sql
-- Configuration example
UPDATE COMPRESSION_CONFIG
SET strategy_type = 'AGGRESSIVE',
    min_table_size_gb = 1,
    preferred_compression = 'ARCHIVE_HIGH',
    hot_score_threshold = 30
WHERE strategy_name = 'PRIMARY_STRATEGY';
```

### Global Parameters

Configure system-wide parameters:

```sql
-- Update minimum compression ratio threshold
UPDATE GLOBAL_PARAMS
SET param_value = '1.5'
WHERE param_name = 'MIN_COMPRESSION_RATIO';

-- Set parallel degree for analysis
UPDATE GLOBAL_PARAMS
SET param_value = '4'
WHERE param_name = 'PARALLEL_DEGREE';

-- Set maximum concurrent compressions
UPDATE GLOBAL_PARAMS
SET param_value = '2'
WHERE param_name = 'MAX_CONCURRENT_COMPRESS';

COMMIT;
```

## Using the Compression Advisor

### Analyzing Objects

#### Analyze All User Tables
```sql
-- Full database analysis (may take 15-30 minutes for 1000+ tables)
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES;

-- Analyze specific schema
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES(p_schema_filter => 'SALES');
```

#### Analyze Specific Objects
```sql
-- Single table
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_SPECIFIC_TABLE('SALES', 'ORDERS');

-- Table with partitions
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_SPECIFIC_TABLE(
    p_owner => 'SALES',
    p_table_name => 'SALES_DATA',
    p_include_partitions => TRUE
);

-- Refresh stale analysis (older than 7 days)
EXEC PKG_COMPRESSION_ANALYZER.REFRESH_ANALYSIS(p_days_old => 7);
```

### Viewing Recommendations

#### Best Compression Candidates
```sql
-- Top savings opportunities
SELECT owner, object_name, segment_size_mb,
       advisable_compression, estimated_savings_mb,
       ROUND(estimated_savings_mb/segment_size_mb*100,1) AS savings_pct
FROM V_COMPRESSION_CANDIDATES
ORDER BY estimated_savings_mb DESC
FETCH FIRST 20 ROWS ONLY;
```

#### Hot Tables Requiring OLTP Compression
```sql
SELECT owner, table_name, hot_score, total_operations,
       advisable_compression, segment_size_mb
FROM V_HOT_OBJECTS
ORDER BY hot_score DESC;
```

#### Cold Tables for Archive Compression
```sql
SELECT owner, table_name, hot_score, segment_size_mb,
       advisable_compression, estimated_savings_mb,
       archive_high_ratio
FROM V_ARCHIVE_CANDIDATES
ORDER BY segment_size_mb DESC;
```

### Executing Compression

#### Single Table Compression
```sql
-- Use recommended compression (online operation)
EXEC PKG_COMPRESSION_EXECUTOR.COMPRESS_TABLE(
    p_owner => 'SALES',
    p_table_name => 'ORDERS',
    p_compression_type => NULL,  -- Uses recommendation
    p_online => TRUE,
    p_log_operation => TRUE
);

-- Force specific compression type
EXEC PKG_COMPRESSION_EXECUTOR.COMPRESS_TABLE(
    p_owner => 'SALES',
    p_table_name => 'HISTORICAL_DATA',
    p_compression_type => 'ARCHIVE HIGH',
    p_online => FALSE  -- Faster offline compression
);
```

#### Batch Compression
```sql
-- Compress top 10 candidates
EXEC PKG_COMPRESSION_EXECUTOR.EXECUTE_RECOMMENDATIONS(
    p_max_tables => 10,
    p_max_size_gb => 100
);

-- Compress all cold tables (inactive > 90 days)
EXEC PKG_COMPRESSION_EXECUTOR.COMPRESS_COLD_TABLES(
    p_days_inactive => 90,
    p_compression_type => 'ARCHIVE HIGH'
);
```

#### Partition-Level Compression
```sql
-- Compress specific partition
EXEC PKG_COMPRESSION_EXECUTOR.COMPRESS_PARTITION(
    p_owner => 'SALES',
    p_table_name => 'SALES_DATA',
    p_partition_name => 'P_2023_Q1',
    p_compression_type => 'QUERY HIGH',
    p_online => TRUE
);
```

### Monitoring Operations

#### Check Compression Status
```sql
-- View recent compression operations
SELECT operation_id, owner, object_name,
       compression_type_applied, execution_status,
       original_size_mb, compressed_size_mb,
       space_saved_mb, compression_ratio_achieved,
       TO_CHAR(start_time, 'YYYY-MM-DD HH24:MI:SS') AS start_time
FROM V_COMPRESSION_HISTORY
ORDER BY start_time DESC
FETCH FIRST 20 ROWS ONLY;
```

#### Space Savings Summary
```sql
-- Total savings by owner
SELECT * FROM V_SPACE_SAVINGS
ORDER BY total_saved_mb DESC;
```

#### Compression Effectiveness
```sql
-- Evaluate compression decisions
SELECT owner, object_name, compression_type_applied,
       compression_ratio_achieved, space_saved_mb,
       hotness_score, effectiveness_assessment
FROM V_COMPRESSION_EFFECTIVENESS
WHERE effectiveness_assessment != 'OPTIMAL'
ORDER BY space_saved_mb DESC;
```

## Understanding Compression Strategies

### Compression Types Explained

#### 1. OLTP Compression (Row Store Compress Advanced)
- **Use Case**: High DML activity (inserts, updates, deletes)
- **Compression Ratio**: 2-3x
- **CPU Impact**: Low
- **When Recommended**: Hot score > 70, high write ratio
- **Example**: Customer orders, transaction tables

#### 2. Query Low (Hybrid Columnar - Query Low)
- **Use Case**: Read-heavy with moderate DML
- **Compression Ratio**: 4-6x
- **CPU Impact**: Moderate
- **When Recommended**: Balanced read/write workload
- **Example**: Reference data, product catalogs

#### 3. Query High (Hybrid Columnar - Query High)
- **Use Case**: Read-mostly workloads
- **Compression Ratio**: 6-10x
- **CPU Impact**: Moderate-High
- **When Recommended**: Read ratio > 70%, moderate access
- **Example**: Historical reports, analytics tables

#### 4. Archive Low (Hybrid Columnar - Archive Low)
- **Use Case**: Infrequently accessed data
- **Compression Ratio**: 8-12x
- **CPU Impact**: High
- **When Recommended**: Cold data, low access frequency
- **Example**: Compliance data, audit logs

#### 5. Archive High (Hybrid Columnar - Archive High)
- **Use Case**: Archival/compliance data
- **Compression Ratio**: 10-20x
- **CPU Impact**: Very High
- **When Recommended**: Rarely accessed, size > 100 GB
- **Example**: Multi-year historical data

### Hotness Score Interpretation

The system calculates a "hotness score" (0-100) based on:
- DML operations (inserts, updates, deletes)
- Logical and physical reads
- Access frequency patterns
- Last analysis date

**Score Ranges**:
- **0-20**: Cold (Archive compression recommended)
- **21-40**: Warm (Query High recommended)
- **41-70**: Active (Query Low or OLTP recommended)
- **71-100**: Hot (OLTP compression or no compression)

## Troubleshooting Guide

### Common Issues

#### Issue: "ORA-01652: unable to extend temp segment"
**Cause**: Insufficient scratch tablespace

**Solution**:
```sql
-- Resize scratch tablespace
ALTER DATABASE DATAFILE '/path/to/scratch01.dbf' RESIZE 2G;

-- Or add new datafile
ALTER TABLESPACE SCRATCH
ADD DATAFILE SIZE 1G AUTOEXTEND ON MAXSIZE 5G;
```

#### Issue: "Compression analysis returns no ratios"
**Cause**: Insufficient table statistics or empty tables

**Solution**:
```sql
-- Gather table statistics first
EXEC DBMS_STATS.GATHER_TABLE_STATS('SCHEMA', 'TABLE_NAME', CASCADE => TRUE);

-- Then re-run analysis
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_SPECIFIC_TABLE('SCHEMA', 'TABLE_NAME');
```

#### Issue: "Index becomes unusable after compression"
**Cause**: Offline table move invalidates indexes

**Solution**:
```sql
-- Use online compression
EXEC PKG_COMPRESSION_EXECUTOR.COMPRESS_TABLE(
    p_owner => 'SCHEMA',
    p_table_name => 'TABLE_NAME',
    p_online => TRUE  -- Keeps indexes valid
);

-- Or rebuild indexes manually after offline move
SELECT 'ALTER INDEX ' || owner || '.' || index_name || ' REBUILD ONLINE;'
FROM dba_indexes
WHERE table_owner = 'SCHEMA'
  AND table_name = 'TABLE_NAME'
  AND status = 'UNUSABLE';
```

#### Issue: "Performance degraded after compression"
**Cause**: Compression type too aggressive for workload

**Solution**:
```sql
-- Roll back compression
EXEC PKG_COMPRESSION_EXECUTOR.ROLLBACK_COMPRESSION(p_operation_id => 12345);

-- Or apply lighter compression
EXEC PKG_COMPRESSION_EXECUTOR.COMPRESS_TABLE(
    p_owner => 'SCHEMA',
    p_table_name => 'TABLE_NAME',
    p_compression_type => 'OLTP'  -- Less aggressive
);
```

#### Issue: "Analysis takes too long"
**Cause**: Large number of tables or insufficient parallel degree

**Solution**:
```sql
-- Increase parallel degree
ALTER SESSION FORCE PARALLEL QUERY PARALLEL 8;

-- Analyze in batches by schema
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES(p_schema_filter => 'SCHEMA1');
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES(p_schema_filter => 'SCHEMA2');
```

### Performance Tuning Tips

1. **Schedule analysis during maintenance windows**: Large-scale analysis can consume resources
2. **Use parallel processing**: Configure appropriate `p_parallel_degree` based on CPU count
3. **Start with largest tables**: Focus on objects > 10 GB for maximum impact
4. **Test on non-production first**: Validate compression ratios and performance impact
5. **Monitor AWR reports**: Compare before/after performance metrics

## FAQ

### General Questions

**Q: Will compression slow down my queries?**
A: It depends on the compression type and workload. OLTP compression typically has minimal impact, while Archive High may slow DML but can speed up full-table scans due to reduced I/O.

**Q: Can I compress system tables?**
A: No, the advisor automatically excludes Oracle-maintained schemas (SYS, SYSTEM, etc.) for safety.

**Q: How much space will I save?**
A: Typical savings range from 40-80% depending on data type and compression choice. Use the `estimated_savings_mb` column for projections.

**Q: Is compression reversible?**
A: Yes, you can decompress tables using `ROLLBACK_COMPRESSION` or manually with `ALTER TABLE ... MOVE NOCOMPRESS`.

### Technical Questions

**Q: What's the difference between OLTP and Query compression?**
A: OLTP uses row-level compression (optimized for DML), while Query/Archive use columnar compression (optimized for reads, higher ratios).

**Q: Can I compress partitioned tables differently?**
A: Yes! Each partition can have its own compression type. Compress recent partitions with OLTP and older partitions with Archive.

**Q: Does compression work with encryption?**
A: Yes, you can use both Transparent Data Encryption (TDE) and compression together.

**Q: How often should I re-analyze?**
A: Monthly for active databases, quarterly for stable environments, or after major data changes.

**Q: Can I schedule automatic compression?**
A: Yes, use DBMS_SCHEDULER to run analysis and compression procedures:

```sql
BEGIN
  DBMS_SCHEDULER.CREATE_JOB(
    job_name => 'MONTHLY_COMPRESSION_ANALYSIS',
    job_type => 'PLSQL_BLOCK',
    job_action => 'BEGIN PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES; END;',
    start_date => SYSTIMESTAMP,
    repeat_interval => 'FREQ=MONTHLY;BYMONTHDAY=1;BYHOUR=2',
    enabled => TRUE,
    comments => 'Monthly compression analysis'
  );
END;
/
```

### Best Practices

**Q: What's the recommended workflow?**
1. Run analysis monthly
2. Review recommendations in V_COMPRESSION_CANDIDATES
3. Test compression on non-production copy
4. Apply compression during maintenance window
5. Monitor performance for 1-2 weeks
6. Adjust strategy if needed

**Q: Should I compress indexes?**
A: Yes, especially for large indexes (> 5 GB). Use ADVANCED LOW for most cases, ADVANCED HIGH for read-only indexes.

**Q: How do I handle LOBs?**
A: SecureFiles LOBs support compression. Analyze with `ANALYZE_LOB` and apply LOW/MEDIUM/HIGH based on access patterns.

**Q: What about temporary tables?**
A: Compression is not supported on temporary tables and is automatically excluded from analysis.

---

For additional assistance, consult the [Administrator Guide](admin-guide.md) for advanced configuration or the [Developer Guide](developer-guide.md) for API integration.
