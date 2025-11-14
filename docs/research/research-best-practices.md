# Oracle HCC Best Practices & Guidelines

## Overview
This document provides best practices for implementing, maintaining, and optimizing Oracle Hybrid Columnar Compression (HCC) on Exadata systems.

## Implementation Best Practices

### 1. Pre-Implementation Planning

#### Assessment Phase
1. **Baseline Metrics**: Capture current storage, performance, and query patterns
2. **Test Environment**: Always test HCC on non-production copies first
3. **Compression Estimation**: Use `DBMS_COMPRESSION.GET_COMPRESSION_RATIO` on sample data
4. **Impact Analysis**: Identify downstream applications and query patterns
5. **Rollback Plan**: Maintain uncompressed backups during initial migration

#### Capacity Planning
```sql
-- Calculate storage savings and timeline
WITH current_storage AS (
    SELECT SUM(bytes)/1024/1024/1024 as total_gb
    FROM dba_segments
    WHERE owner = 'DATA_WAREHOUSE'
),
estimated_savings AS (
    SELECT
        total_gb,
        total_gb * 0.9 as query_high_savings,  -- 10x compression
        total_gb * 0.93 as archive_low_savings, -- 15x compression
        total_gb * 0.95 as archive_high_savings -- 20x compression
    FROM current_storage
)
SELECT
    ROUND(total_gb, 2) as current_storage_gb,
    ROUND(query_high_savings, 2) as query_high_saved_gb,
    ROUND(archive_low_savings, 2) as archive_low_saved_gb,
    ROUND(archive_high_savings, 2) as archive_high_saved_gb
FROM estimated_savings;
```

### 2. Compression Strategy Selection

#### By Workload Type

**Data Warehouse / OLAP**
- **Primary recommendation**: COMPRESS FOR QUERY HIGH
- **Hot partitions** (< 30 days): COMPRESS FOR QUERY LOW or no compression
- **Warm partitions** (30-365 days): COMPRESS FOR QUERY HIGH
- **Cold partitions** (1+ years): COMPRESS FOR ARCHIVE LOW

**Archive / Compliance**
- **Primary recommendation**: COMPRESS FOR ARCHIVE HIGH
- **Regulatory data**: COMPRESS FOR ARCHIVE LOW (occasional access)
- **Long-term retention**: COMPRESS FOR ARCHIVE HIGH (rare access)

**Hybrid OLTP/Analytics**
- **Active partitions**: Advanced Row Compression
- **Historical partitions**: COMPRESS FOR QUERY HIGH
- **Archive partitions**: COMPRESS FOR ARCHIVE LOW

#### Decision Tree
```
Start
  │
  ├─ Frequent DML (updates/deletes)?
  │  └─ YES → Use Advanced Row Compression (NOT HCC)
  │  └─ NO → Continue
  │
  ├─ Access frequency?
  │  ├─ Daily/Hourly → QUERY LOW or QUERY HIGH
  │  ├─ Weekly/Monthly → QUERY HIGH or ARCHIVE LOW
  │  └─ Yearly/Rare → ARCHIVE HIGH
  │
  ├─ Load time critical?
  │  └─ YES → QUERY LOW
  │  └─ NO → Continue
  │
  ├─ Storage savings priority?
  │  └─ Maximum → ARCHIVE HIGH
  │  └─ Balanced → QUERY HIGH
  │
  └─ Final recommendation based on combined factors
```

### 3. Loading Data for HCC

#### Direct-Path INSERT (Required for HCC)

**Method 1: INSERT with APPEND hint**
```sql
-- Direct-path insert for HCC compression
INSERT /*+ APPEND */ INTO sales_compressed
SELECT * FROM sales_staging;
COMMIT;

-- Verify compression applied
SELECT table_name, compress_for, num_rows
FROM user_tables
WHERE table_name = 'SALES_COMPRESSED';
```

**Method 2: CREATE TABLE AS SELECT (CTAS)**
```sql
-- CTAS automatically uses direct-path
CREATE TABLE sales_q4_2024
COMPRESS FOR QUERY HIGH
AS
SELECT * FROM sales
WHERE sale_date >= DATE '2024-10-01'
AND sale_date < DATE '2025-01-01';
```

**Method 3: SQL*Loader with DIRECT=TRUE**
```bash
# Control file: sales_load.ctl
LOAD DATA
INFILE 'sales_data.csv'
APPEND INTO TABLE sales_compressed
FIELDS TERMINATED BY ','
(sale_id, sale_date, amount, customer_id)

# Load command
sqlldr userid=user/pass@db control=sales_load.ctl direct=true
```

**Method 4: Data Pump Import**
```bash
# Export from source
expdp user/pass@source_db directory=DATA_PUMP_DIR \
  dumpfile=sales.dmp tables=SALES

# Import with HCC compression
impdp user/pass@exadata_db directory=DATA_PUMP_DIR \
  dumpfile=sales.dmp \
  transform=table_compression_clause:"COMPRESS FOR QUERY HIGH"
```

**Method 5: ALTER TABLE MOVE**
```sql
-- Compress existing table (requires downtime)
ALTER TABLE sales MOVE COMPRESS FOR QUERY HIGH;

-- Rebuild indexes after MOVE
SELECT 'ALTER INDEX ' || index_name || ' REBUILD ONLINE;'
FROM user_indexes
WHERE table_name = 'SALES';
```

#### Conventional INSERT Behavior
```sql
-- WARNING: This will NOT compress with HCC
INSERT INTO sales_compressed VALUES (1, SYSDATE, 100, 'ACME');
-- Data stored in conventional row format

-- Check compression effectiveness
SELECT
    table_name,
    compress_for,
    num_rows,
    blocks,
    ROUND(num_rows/NULLIF(blocks,0), 2) as rows_per_block
FROM user_tables
WHERE table_name = 'SALES_COMPRESSED';
-- Low rows_per_block indicates poor compression
```

### 4. Partitioning Strategy

#### Time-Based Partitioning with Tiered Compression

```sql
-- Example: Sales table with monthly partitions and tiered compression
CREATE TABLE sales (
    sale_id NUMBER,
    sale_date DATE NOT NULL,
    customer_id NUMBER,
    product_id NUMBER,
    amount NUMBER(10,2),
    CONSTRAINT pk_sales PRIMARY KEY (sale_id, sale_date)
)
PARTITION BY RANGE (sale_date)
INTERVAL (NUMTOYMINTERVAL(1,'MONTH'))
(
    -- Seed partition for current month (no compression)
    PARTITION p_seed VALUES LESS THAN (DATE '2024-01-01')
)
COMPRESS FOR QUERY HIGH;  -- Default for new partitions

-- Modify older partitions to higher compression
BEGIN
    FOR part IN (
        SELECT partition_name, high_value
        FROM user_tab_partitions
        WHERE table_name = 'SALES'
    ) LOOP
        -- Archive partitions older than 1 year
        IF TO_DATE(part.high_value) < ADD_MONTHS(SYSDATE, -12) THEN
            EXECUTE IMMEDIATE
                'ALTER TABLE sales MODIFY PARTITION ' || part.partition_name ||
                ' COMPRESS FOR ARCHIVE LOW';
        -- Query compression for 1-12 months old
        ELSIF TO_DATE(part.high_value) < SYSDATE THEN
            EXECUTE IMMEDIATE
                'ALTER TABLE sales MODIFY PARTITION ' || part.partition_name ||
                ' COMPRESS FOR QUERY HIGH';
        END IF;
    END LOOP;
END;
/
```

#### Composite Partitioning Example
```sql
-- Range-hash composite partitioning with compression
CREATE TABLE order_history (
    order_id NUMBER,
    order_date DATE,
    customer_id NUMBER,
    order_total NUMBER(12,2)
)
PARTITION BY RANGE (order_date)
SUBPARTITION BY HASH (customer_id) SUBPARTITIONS 16
(
    PARTITION p_2024_q1 VALUES LESS THAN (DATE '2024-04-01')
        COMPRESS FOR QUERY HIGH,
    PARTITION p_2024_q2 VALUES LESS THAN (DATE '2024-07-01')
        COMPRESS FOR QUERY HIGH,
    PARTITION p_2023 VALUES LESS THAN (DATE '2024-01-01')
        COMPRESS FOR ARCHIVE LOW,
    PARTITION p_old VALUES LESS THAN (MAXVALUE)
        COMPRESS FOR ARCHIVE HIGH
);
```

### 5. Column Ordering Optimization

#### Best Practices for Column Order

**Optimal ordering for HCC compression:**
1. **Low cardinality columns first**: Status codes, categories, flags
2. **Group by data type**: NUMBERs together, DATEs together, VARCHAR2s together
3. **Frequently queried columns first**: Improves Smart Scan performance
4. **Sort by cardinality** (lowest to highest): Maximizes compression

```sql
-- Example: Optimized column order for HCC
CREATE TABLE customer_transactions (
    -- Low cardinality columns (high compression)
    transaction_type VARCHAR2(20),      -- 'SALE','RETURN','REFUND'
    status VARCHAR2(10),                 -- 'PENDING','COMPLETE','CANCELLED'
    region_code CHAR(2),                 -- 'US','EU','AP'

    -- Medium cardinality columns
    customer_segment VARCHAR2(30),       -- 'PREMIUM','STANDARD','BASIC'
    payment_method VARCHAR2(20),         -- 'CREDIT','DEBIT','PAYPAL'

    -- Date columns (good compression when sorted)
    transaction_date DATE,
    created_date TIMESTAMP,

    -- Numeric columns
    customer_id NUMBER(10),
    product_id NUMBER(10),
    quantity NUMBER(5),
    unit_price NUMBER(10,2),
    total_amount NUMBER(12,2),

    -- High cardinality columns last
    transaction_id VARCHAR2(50),         -- UUID or unique identifier
    description VARCHAR2(500),           -- Free text
    notes CLOB                           -- Long text
)
COMPRESS FOR QUERY HIGH;
```

### 6. Maintenance Operations

#### Monitoring Compression Effectiveness

```sql
-- Check actual compression ratios
SELECT
    table_name,
    compress_for,
    num_rows,
    blocks,
    ROUND(num_rows/NULLIF(blocks, 0), 2) as rows_per_block,
    ROUND((num_rows/NULLIF(blocks, 0)) /
        (SELECT AVG(num_rows/NULLIF(blocks, 0))
         FROM user_tables
         WHERE compression = 'DISABLED'), 2) as compression_factor
FROM user_tables
WHERE compress_for IS NOT NULL
ORDER BY compression_factor DESC;
```

#### Handling DML on HCC Tables

```sql
-- Identify tables with migrated rows (due to updates)
SELECT
    table_name,
    num_rows,
    chain_cnt as chained_rows,
    ROUND(chain_cnt / NULLIF(num_rows, 0) * 100, 2) as pct_chained,
    compress_for
FROM user_tables
WHERE compress_for IS NOT NULL
AND chain_cnt > num_rows * 0.05  -- More than 5% chained
ORDER BY pct_chained DESC;

-- Recompress tables with excessive row migration
-- WARNING: Requires table lock and index rebuilds
ALTER TABLE customer_history MOVE COMPRESS FOR QUERY HIGH;

-- Rebuild indexes after MOVE
BEGIN
    FOR idx IN (
        SELECT index_name
        FROM user_indexes
        WHERE table_name = 'CUSTOMER_HISTORY'
    ) LOOP
        EXECUTE IMMEDIATE 'ALTER INDEX ' || idx.index_name || ' REBUILD ONLINE';
    END LOOP;
END;
/
```

#### Partition Maintenance

```sql
-- Automated partition compression by age
CREATE OR REPLACE PROCEDURE compress_old_partitions (
    p_table_name VARCHAR2,
    p_months_old NUMBER DEFAULT 12
) AS
BEGIN
    FOR part IN (
        SELECT
            table_name,
            partition_name,
            high_value,
            compress_for
        FROM user_tab_partitions
        WHERE table_name = p_table_name
        AND compress_for IS NULL OR compress_for = 'DISABLED'
    ) LOOP
        -- Extract date from high_value
        DECLARE
            v_date DATE;
        BEGIN
            EXECUTE IMMEDIATE
                'SELECT ' || part.high_value || ' FROM DUAL'
            INTO v_date;

            IF v_date < ADD_MONTHS(SYSDATE, -p_months_old) THEN
                DBMS_OUTPUT.PUT_LINE('Compressing: ' || part.partition_name);
                EXECUTE IMMEDIATE
                    'ALTER TABLE ' || part.table_name ||
                    ' MODIFY PARTITION ' || part.partition_name ||
                    ' COMPRESS FOR ARCHIVE LOW';
            END IF;
        EXCEPTION
            WHEN OTHERS THEN
                DBMS_OUTPUT.PUT_LINE('Error processing: ' || part.partition_name);
        END;
    END LOOP;
END;
/
```

### 7. Performance Optimization

#### Smart Scan Optimization

```sql
-- Ensure Smart Scan is enabled
ALTER SESSION SET cell_offload_processing = TRUE;

-- Verify Smart Scan usage in execution plans
SELECT
    sql_id,
    child_number,
    sql_text,
    executions,
    io_cell_offload_eligible_bytes,
    io_cell_offload_returned_bytes,
    ROUND(100 * (io_cell_offload_eligible_bytes - io_cell_offload_returned_bytes) /
        NULLIF(io_cell_offload_eligible_bytes, 0), 2) as offload_pct
FROM v$sql
WHERE io_cell_offload_eligible_bytes > 0
ORDER BY offload_pct DESC;
```

#### Query Performance Monitoring

```sql
-- Compare query performance before/after HCC
CREATE TABLE query_performance_log (
    log_date TIMESTAMP DEFAULT SYSTIMESTAMP,
    table_name VARCHAR2(128),
    compression_type VARCHAR2(30),
    sql_id VARCHAR2(13),
    executions NUMBER,
    elapsed_time_sec NUMBER,
    cpu_time_sec NUMBER,
    buffer_gets NUMBER,
    disk_reads NUMBER,
    rows_processed NUMBER
);

-- Capture baseline performance
INSERT INTO query_performance_log
SELECT
    SYSTIMESTAMP,
    'SALES_HISTORY',
    'UNCOMPRESSED',
    sql_id,
    executions,
    elapsed_time / 1000000,
    cpu_time / 1000000,
    buffer_gets,
    disk_reads,
    rows_processed
FROM v$sql
WHERE sql_text LIKE '%SALES_HISTORY%'
AND sql_text NOT LIKE '%v$sql%';
```

#### Index Strategy for HCC Tables

```sql
-- Bitmap indexes work well with HCC (low cardinality columns)
CREATE BITMAP INDEX idx_sales_status
ON sales(status)
LOCAL  -- For partitioned tables
COMPRESS;  -- Compress the bitmap index too

-- B-tree indexes for high cardinality
CREATE INDEX idx_sales_customer
ON sales(customer_id)
LOCAL
COMPRESS 2;  -- Advanced index compression

-- Verify index effectiveness
SELECT
    index_name,
    index_type,
    compression,
    ROUND(SUM(bytes)/1024/1024, 2) as size_mb,
    num_rows,
    distinct_keys,
    clustering_factor
FROM user_indexes i
JOIN user_segments s ON i.index_name = s.segment_name
WHERE table_name = 'SALES'
GROUP BY index_name, index_type, compression, num_rows,
         distinct_keys, clustering_factor;
```

### 8. Storage Tiering

#### Flash vs Disk Placement

```sql
-- Pin frequently accessed compressed tables to flash
ALTER TABLE sales_current STORAGE (CELL_FLASH_CACHE KEEP);

-- Allow infrequently accessed archives on disk
ALTER TABLE sales_archive STORAGE (CELL_FLASH_CACHE NONE);

-- Check flash cache effectiveness
SELECT
    owner,
    object_name,
    object_type,
    keep,
    ROUND(total_mb, 2) as total_mb,
    ROUND(cached_mb, 2) as cached_mb,
    ROUND(cached_mb / NULLIF(total_mb, 0) * 100, 2) as cache_pct
FROM (
    SELECT
        owner,
        object_name,
        object_type,
        keep,
        SUM(size_mb) as total_mb,
        SUM(cached_mb) as cached_mb
    FROM v$flash_cache_stats
    WHERE owner NOT IN ('SYS','SYSTEM')
    GROUP BY owner, object_name, object_type, keep
)
ORDER BY cached_mb DESC;
```

### 9. Migration Best Practices

#### Phased Migration Approach

**Phase 1: Test and Validate (2-4 weeks)**
- Select 2-3 candidate tables (different sizes/workloads)
- Create compressed copies in test environment
- Run performance tests with production-like queries
- Validate compression ratios and query performance

**Phase 2: Pilot Implementation (1-2 months)**
- Implement on 10-20% of identified candidates
- Monitor performance and storage savings
- Gather user feedback on query response times
- Adjust compression strategy based on results

**Phase 3: Gradual Rollout (3-6 months)**
- Compress remaining candidates in priority order
- Implement partition-level compression on large tables
- Automate compression for new partitions
- Establish monitoring and maintenance procedures

**Phase 4: Continuous Optimization (Ongoing)**
- Review compression effectiveness quarterly
- Adjust compression levels based on access patterns
- Recompress tables with excessive row migration
- Update compression strategy for new tables

#### Migration Script Template

```sql
-- Template for table migration to HCC
CREATE OR REPLACE PROCEDURE migrate_to_hcc (
    p_owner VARCHAR2,
    p_table_name VARCHAR2,
    p_compression_type VARCHAR2 DEFAULT 'FOR QUERY HIGH',
    p_parallel_degree NUMBER DEFAULT 8
) AS
    v_ddl VARCHAR2(4000);
    v_index_ddl VARCHAR2(32767);
BEGIN
    -- Step 1: Gather current statistics
    DBMS_STATS.GATHER_TABLE_STATS(
        ownname => p_owner,
        tabname => p_table_name
    );

    -- Step 2: Create compressed copy
    v_ddl := 'CREATE TABLE ' || p_table_name || '_COMPRESSED ' ||
             'COMPRESS ' || p_compression_type || ' AS ' ||
             'SELECT /*+ PARALLEL(' || p_parallel_degree || ') */ * ' ||
             'FROM ' || p_owner || '.' || p_table_name;

    DBMS_OUTPUT.PUT_LINE('Creating compressed copy...');
    EXECUTE IMMEDIATE v_ddl;

    -- Step 3: Rebuild indexes on new table
    DBMS_OUTPUT.PUT_LINE('Rebuilding indexes...');
    FOR idx IN (
        SELECT index_name, index_type, uniqueness
        FROM dba_indexes
        WHERE owner = p_owner
        AND table_name = p_table_name
    ) LOOP
        -- Generate index DDL and create on new table
        DBMS_OUTPUT.PUT_LINE('  Index: ' || idx.index_name);
        -- Actual index creation code here
    END LOOP;

    -- Step 4: Validate row counts
    DECLARE
        v_orig_count NUMBER;
        v_comp_count NUMBER;
    BEGIN
        EXECUTE IMMEDIATE
            'SELECT COUNT(*) FROM ' || p_owner || '.' || p_table_name
        INTO v_orig_count;

        EXECUTE IMMEDIATE
            'SELECT COUNT(*) FROM ' || p_table_name || '_COMPRESSED'
        INTO v_comp_count;

        IF v_orig_count != v_comp_count THEN
            RAISE_APPLICATION_ERROR(-20001,
                'Row count mismatch: ' || v_orig_count || ' vs ' || v_comp_count);
        END IF;

        DBMS_OUTPUT.PUT_LINE('Validation passed: ' || v_orig_count || ' rows');
    END;

    -- Step 5: Swap tables (requires exclusive lock)
    DBMS_OUTPUT.PUT_LINE('Ready to swap tables - manual intervention required');
    DBMS_OUTPUT.PUT_LINE('Run: RENAME ' || p_table_name || ' TO ' || p_table_name || '_OLD;');
    DBMS_OUTPUT.PUT_LINE('Run: RENAME ' || p_table_name || '_COMPRESSED TO ' || p_table_name || ';');

EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('ERROR: ' || SQLERRM);
        -- Cleanup on error
        EXECUTE IMMEDIATE 'DROP TABLE ' || p_table_name || '_COMPRESSED PURGE';
        RAISE;
END;
/
```

## Common Pitfalls to Avoid

### 1. Compressing Frequently Updated Tables
**Problem**: Updates to HCC rows cause row migration and decompression
**Solution**: Use Advanced Row Compression for tables with > 5% monthly updates

### 2. Using Conventional INSERT
**Problem**: Data inserted without direct-path is not compressed
**Solution**: Always use APPEND hint, CTAS, or direct-path utilities

### 3. Neglecting Index Maintenance
**Problem**: Indexes remain uncompressed, dominate storage after table compression
**Solution**: Compress indexes with Advanced Index Compression

### 4. Over-Compressing Hot Data
**Problem**: ARCHIVE HIGH on frequently accessed data causes performance issues
**Solution**: Use QUERY LOW/HIGH for data accessed weekly or more frequently

### 5. Ignoring Row Migration
**Problem**: Excessive updates cause fragmentation and poor compression
**Solution**: Monitor chain_cnt and periodically recompress affected tables

## Monitoring and Validation

### Comprehensive Health Check

```sql
-- HCC health check query
SELECT
    owner,
    table_name,
    partition_name,
    compress_for,
    num_rows,
    ROUND(bytes/1024/1024/1024, 2) as size_gb,
    ROUND(num_rows/NULLIF(blocks,0), 2) as rows_per_block,
    ROUND(chain_cnt/NULLIF(num_rows,0)*100, 2) as pct_chained,
    last_analyzed,
    CASE
        WHEN compress_for LIKE '%QUERY%' AND chain_cnt/NULLIF(num_rows,0) > 0.10
            THEN 'WARNING: Recompress recommended'
        WHEN compress_for LIKE '%ARCHIVE%' AND last_analyzed < SYSDATE - 90
            THEN 'INFO: Update statistics'
        WHEN rows_per_block < 100 AND compress_for IS NOT NULL
            THEN 'WARNING: Poor compression detected'
        ELSE 'OK'
    END as health_status
FROM dba_tables
WHERE compress_for IS NOT NULL
ORDER BY bytes DESC;
```

## Summary Checklist

- [ ] Identify candidates using size, DML, and access pattern criteria
- [ ] Test compression on non-production copies first
- [ ] Use direct-path loading for all HCC inserts
- [ ] Implement partition-level compression for large tables
- [ ] Optimize column order for maximum compression
- [ ] Monitor compression effectiveness and row migration
- [ ] Rebuild indexes after compression operations
- [ ] Adjust compression levels based on access patterns
- [ ] Automate partition compression maintenance
- [ ] Validate query performance after implementation
- [ ] Document compression strategy and rationale
- [ ] Train team on HCC best practices and limitations

## References
- Oracle Database VLDB and Partitioning Guide
- Oracle Exadata Database Machine Owner's Guide
- Oracle Advanced Compression White Paper
- Exadata Smart Scan and HCC Technical Brief
