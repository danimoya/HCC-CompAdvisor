# Oracle HCC Compression Types & Performance Characteristics

## Overview
Oracle Hybrid Columnar Compression (HCC) is a proprietary compression technology available on Oracle Exadata Database Machine and other Oracle Engineered Systems. It provides superior compression ratios compared to traditional row-based compression.

## HCC Compression Modes

### 1. QUERY Compression (Warehouse Optimization)
Optimized for data warehouse applications with balanced compression and query performance.

#### QUERY LOW
- **Algorithm**: LZO (Lempel-Ziv-Oberhumer)
- **Compression Ratio**: 6x - 10x average
- **Use Case**: Environments where load time service levels are critical
- **Performance**: Fastest decompression speed among HCC options
- **Best For**:
  - Frequently accessed data warehouse tables
  - Tables with regular data loads requiring faster insert times
  - Query-intensive workloads with moderate compression needs
  - OLAP systems with frequent complex queries

#### QUERY HIGH
- **Algorithm**: ZLIB (Gzip)
- **Compression Ratio**: 10x - 12x average
- **Use Case**: Default warehouse compression for maximum space savings
- **Performance**: Good query performance with higher compression
- **Best For**:
  - Large fact tables with infrequent loads
  - Historical data warehouse partitions
  - Maximum storage optimization while maintaining query speed
  - Tables with columnar access patterns

### 2. ARCHIVE Compression (Maximum Compression)
Optimized for maximum compression of historical, rarely-accessed data.

#### ARCHIVE LOW
- **Algorithm**: Enhanced ZLIB
- **Compression Ratio**: 12x - 15x average
- **Use Case**: Historical data with occasional access requirements
- **Performance**: Slower query performance than QUERY modes
- **Best For**:
  - Aging partitions in time-series data
  - Compliance and regulatory data retention
  - Data accessed monthly or quarterly
  - Archival workloads with storage constraints

#### ARCHIVE HIGH
- **Algorithm**: BZIP2
- **Compression Ratio**: 15x - 20x (highest compression)
- **Use Case**: Rarely accessed archival data
- **Performance**: Slowest query performance, highest compression
- **Best For**:
  - Long-term data retention (7+ years)
  - Data accessed annually or for audits only
  - Maximum storage reduction requirements
  - Cold data migration from tape alternatives

## Performance Characteristics

### Query Performance

#### Smart Scan Integration
- HCC works directly with Exadata Smart Scan technology
- Decompression offloaded to storage server processors
- Reduced I/O due to higher compression ratios
- Most analytic workloads run **faster** with HCC than without

#### Columnar Flash Cache
- Dual format architecture in Exadata flash storage
- Frequently scanned HCC data automatically transformed to pure columnar format
- Smart scans on columnar flash read only selected columns
- Reduces flash I/O and storage server CPU consumption

#### Performance by Compression Type
```
Query Speed (fastest to slowest):
1. QUERY LOW (LZO) - Fastest queries
2. QUERY HIGH (ZLIB) - Fast queries
3. ARCHIVE LOW (Enhanced ZLIB) - Moderate queries
4. ARCHIVE HIGH (BZIP2) - Slower queries

Load Speed (fastest to slowest):
1. QUERY LOW - Fastest loads
2. QUERY HIGH - Moderate loads
3. ARCHIVE LOW - Slower loads
4. ARCHIVE HIGH - Slowest loads
```

### Storage Savings

#### Compression Ratios by Data Type
- **Numeric columns**: 10x - 15x compression
- **Date/timestamp columns**: 8x - 12x compression
- **VARCHAR2 with repetition**: 12x - 20x compression
- **VARCHAR2 random data**: 3x - 8x compression
- **CLOB/BLOB data**: Varies widely (5x - 15x)

#### Real-World Examples
- **Fact tables**: 10x - 15x average compression
- **Dimension tables**: 8x - 12x average compression
- **Transaction logs**: 12x - 18x average compression
- **Historical archives**: 15x - 20x with ARCHIVE HIGH

### Hardware Considerations

#### Exadata X9M Generation (Current)
- High Capacity (HC) storage: 216 TB per cell
- Extended (XT) storage: 216 TB per cell
- With 15x HCC compression: Effective 3.2 PB per HC cell
- 48 TB increase from X8M generation

#### Storage Tiers
- **Flash storage**: Best for QUERY compression (frequently accessed)
- **Hard disk storage**: Suitable for ARCHIVE compression (cold data)
- **Mixed workloads**: Partition by access pattern and tier accordingly

## Trade-offs and Considerations

### When to Use Each Compression Level

| Compression Type | Data Access Frequency | DML Activity | Primary Goal |
|-----------------|----------------------|--------------|--------------|
| QUERY LOW | Daily/Hourly | Minimal | Fast queries + space savings |
| QUERY HIGH | Daily/Weekly | None/Minimal | Maximum query performance |
| ARCHIVE LOW | Monthly | Rare | Balance compression/access |
| ARCHIVE HIGH | Yearly/Audit | None | Maximum compression |

### DML Impact
- **HCC is write-once optimized**: Best with direct-path INSERT
- **UPDATE operations**: Migrated rows stored in OLTP format
- **DELETE operations**: Can fragment compression units
- **Frequent DML**: Consider Advanced Row Compression instead

### Loading Considerations
- **Direct-path INSERT**: Required for HCC compression
  - `INSERT /*+ APPEND */ INTO ...`
  - SQL*Loader DIRECT=TRUE
  - Data Pump imports
  - CTAS (CREATE TABLE AS SELECT)
- **Conventional INSERT**: Data stored uncompressed
- **Bulk loading**: Higher compression levels may increase load time

## Performance Optimization Tips

### 1. Partitioning Strategy
```sql
-- Example: Hybrid partitioning with compression
CREATE TABLE sales_history (
    sale_date DATE,
    product_id NUMBER,
    amount NUMBER
)
PARTITION BY RANGE (sale_date)
(
    PARTITION p_current VALUES LESS THAN (SYSDATE - 30)
        COMPRESS FOR QUERY HIGH,
    PARTITION p_archive_2024 VALUES LESS THAN (TO_DATE('2025-01-01','YYYY-MM-DD'))
        COMPRESS FOR ARCHIVE LOW,
    PARTITION p_archive_old VALUES LESS THAN (MAXVALUE)
        COMPRESS FOR ARCHIVE HIGH
);
```

### 2. Column Ordering
- Place frequently accessed columns first
- Group similar data types together
- Order by cardinality (low to high)

### 3. Compression Unit Size
- Default: 32KB compression units
- Larger units = better compression
- Smaller units = faster random access
- Tune based on workload patterns

### 4. Monitoring Query Performance
```sql
-- Check compression effectiveness on queries
SELECT sql_id,
       executions,
       elapsed_time/1000000 avg_elapsed_sec,
       buffer_gets/executions avg_buffer_gets,
       disk_reads/executions avg_disk_reads
FROM v$sql
WHERE sql_text LIKE '%compressed_table%'
ORDER BY elapsed_time DESC;
```

## Migration Recommendations

### Gradual Migration Path
1. **Phase 1**: QUERY LOW on recent partitions (test performance)
2. **Phase 2**: QUERY HIGH on stable warehouse data
3. **Phase 3**: ARCHIVE LOW on aging partitions (1+ year old)
4. **Phase 4**: ARCHIVE HIGH on archival data (3+ years old)

### Risk Mitigation
- Test compression on non-production copies first
- Monitor query performance after compression
- Keep uncompressed backup during transition
- Validate compression ratios match expectations

## Summary Matrix

| Metric | QUERY LOW | QUERY HIGH | ARCHIVE LOW | ARCHIVE HIGH |
|--------|-----------|------------|-------------|--------------|
| Compression Ratio | 6x-10x | 10x-12x | 12x-15x | 15x-20x |
| Query Speed | Fastest | Fast | Moderate | Slowest |
| Load Speed | Fastest | Moderate | Slow | Slowest |
| CPU Usage | Low | Medium | Medium-High | High |
| Storage Savings | Good | Very Good | Excellent | Maximum |
| Ideal Access | Hourly/Daily | Daily/Weekly | Monthly | Yearly |

## References
- Oracle Hybrid Columnar Compression Brief (July 2025, Version 23ai)
- Exadata Database Machine Documentation
- Oracle Advanced Compression White Paper
- Exadata X9M Technical Specifications
