# Test Tables Generator for Compression Type Evaluation

## Overview

The `test_tables_generator.sql` script creates 8 realistic test tables, each optimized as a target for a specific compression type. These tables include:

- **~52 Million total records** (10x production-scale)
- **~15+ GB of test data** (varies by compression type)
- **Realistic data patterns** with appropriate repetition for each compression type
- **Production-like characteristics** (departments, regions, products, etc.)

## Test Tables by Compression Type

### 1. TEST_BASIC_COMPRESSION (1,000,000 rows)
**Compression Type:** BASIC
**Use Case:** General purpose, small to medium tables
**Data Pattern:** Customer orders with product catalog, moderate repetition
**Characteristics:**
- 4 columns with VARCHAR2 (status, category, product_code)
- Numeric columns (amount, quantity, customer_id)
- Temporal data (order_date, created_date, updated_date)
- ~10-20 distinct values for categorical columns
- Suitable for initial compression testing

### 2. TEST_OLTP_COMPRESSION (2,000,000 rows)
**Compression Type:** OLTP
**Use Case:** High write activity, frequent updates, OLTP systems
**Data Pattern:** Real-time transaction log with high INSERT/UPDATE frequency
**Characteristics:**
- Transaction-oriented with session tracking
- Frequent update columns (status, updated_time)
- Low compression overhead requirements
- Short-lived records pattern
- Ideal for systems with constant DML activity

### 3. TEST_ADV_LOW_COMPRESSION (3,000,000 rows)
**Compression Type:** ADV_LOW (QUERY LOW)
**Use Case:** Read-heavy, moderate compression ratios
**Data Pattern:** Employee and project management data across global regions
**Characteristics:**
- 7 repeated categorical dimensions (region, country, city, department)
- Salary and financial columns
- Performance and skill level attributes
- Good balance of repetition and variation
- Suitable for query-optimized compression

### 4. TEST_ADV_HIGH_COMPRESSION (5,000,000 rows)
**Compression Type:** ADV_HIGH (QUERY HIGH)
**Use Case:** Read-heavy, aggressive compression
**Data Pattern:** System event log with very high repetition
**Characteristics:**
- 5-8 distinct values per categorical column
- Event type, severity, status all highly repetitive
- Metadata fields with consistent patterns
- Server names and components repeat frequently
- Excellent compression ratio potential

### 5. TEST_HCC_QUERY_LOW (10,000,000 rows)
**Compression Type:** QUERY_LOW (HCC - Exadata only)
**Use Case:** Exadata, query-optimized, balanced compression
**Data Pattern:** E-commerce sales transactions across regions and channels
**Characteristics:**
- 1M transaction records with global regional data
- High repetition of regions, countries, product lines
- Channel and payment method categorization
- Promo code and discount tracking
- Realistic sales metrics (price, amount, margin)
- Balanced compression for query performance on Exadata

### 6. TEST_HCC_QUERY_HIGH (20,000,000 rows)
**Compression Type:** QUERY_HIGH (HCC - Exadata only)
**Use Case:** Exadata, query-heavy, high compression
**Data Pattern:** Application log data with maximum repetition
**Characteristics:**
- 2M log entries with very repetitive server names, services
- 20 distinct server names repeated millions of times
- 10 distinct services, process/thread IDs highly repetitive
- Error codes, stack traces when present
- User/session/correlation IDs follow patterns
- Extreme compression opportunity for historical log data

### 7. TEST_HCC_ARCHIVE_LOW (5,000,000 rows)
**Compression Type:** ARCHIVE_LOW (HCC - Exadata only)
**Use Case:** Exadata, archival data, high compression
**Data Pattern:** Historical fiscal/financial summary data
**Characteristics:**
- 500K archival records spanning 20+ years
- Highly repetitive fiscal year/quarter/month dimensions
- Regional and product category repetition
- Financial metrics (revenue, cost, profit, growth)
- Status = 'ARCHIVED' consistency
- Ideal for cold data with access for regulatory/audit purposes

### 8. TEST_HCC_ARCHIVE_HIGH (10,000,000 rows)
**Compression Type:** ARCHIVE_HIGH (HCC - Exadata only)
**Use Case:** Exadata, archival data, maximum compression
**Data Pattern:** Historical transaction archive with all metadata
**Characteristics:**
- 1M archival records from legacy systems
- Year, month, week, day dimensions all repetitive
- 20 distinct source systems repeated throughout
- Fixed status values (ARCHIVED, APPROVED, DELETED)
- Department, cost center, project ID highly repetitive
- CLOB with long descriptions for compliance
- Perfect for compliance archival with minimal access

## Usage

### Create All Test Tables
```sql
@sql/tests/test_tables_generator.sql
```

### Create Individual Tables
```sql
EXEC PKG_TEST_TABLE_GENERATOR.create_basic_compression_table;
EXEC PKG_TEST_TABLE_GENERATOR.create_oltp_compression_table;
EXEC PKG_TEST_TABLE_GENERATOR.create_adv_low_compression_table;
EXEC PKG_TEST_TABLE_GENERATOR.create_adv_high_compression_table;
EXEC PKG_TEST_TABLE_GENERATOR.create_hcc_query_low_table;
EXEC PKG_TEST_TABLE_GENERATOR.create_hcc_query_high_table;
EXEC PKG_TEST_TABLE_GENERATOR.create_hcc_archive_low_table;
EXEC PKG_TEST_TABLE_GENERATOR.create_hcc_archive_high_table;
```

### Run Compression Analysis
```sql
EXEC PKG_COMPRESSION_ADVISOR.run_analysis(p_owner => NULL, p_strategy_id => 2);
```

### Analyze Specific Table
```sql
EXEC PKG_COMPRESSION_ADVISOR.analyze_table(
  p_owner => 'COMPRESSION_MGR',
  p_table_name => 'TEST_HCC_QUERY_LOW',
  p_strategy_id => 2
);
```

### View Compression Recommendations
```sql
SELECT owner, object_name, object_type,
       current_size_mb, potential_savings_mb,
       advisable_compression, rationale
FROM V_COMPRESSION_CANDIDATES
WHERE owner = 'COMPRESSION_MGR'
ORDER BY potential_savings_mb DESC;
```

### Apply Compression
```sql
-- Dry run to see DDL
EXEC PKG_COMPRESSION_EXECUTOR.compress_table(
  p_owner => 'COMPRESSION_MGR',
  p_table_name => 'TEST_BASIC_COMPRESSION',
  p_compression_type => 'BASIC',
  p_dry_run => TRUE
);

-- Execute compression
EXEC PKG_COMPRESSION_EXECUTOR.compress_table(
  p_owner => 'COMPRESSION_MGR',
  p_table_name => 'TEST_BASIC_COMPRESSION',
  p_compression_type => 'BASIC',
  p_dry_run => FALSE
);
```

### View Compression History
```sql
SELECT owner, object_name, compression_before, compression_after,
       ROUND(size_before_bytes / 1024 / 1024, 2) as size_before_mb,
       ROUND(size_after_bytes / 1024 / 1024, 2) as size_after_mb,
       ROUND(space_saved_bytes / 1024 / 1024, 2) as space_saved_mb,
       compression_ratio, status, start_time
FROM V_COMPRESSION_HISTORY
WHERE object_name LIKE 'TEST_%'
ORDER BY start_time DESC;
```

### Generate Size Report
```sql
EXEC PKG_TEST_TABLE_GENERATOR.report_test_tables;
```

### Drop All Test Tables
```sql
EXEC PKG_TEST_TABLE_GENERATOR.drop_all_test_tables;
```

## Compression Strategy Recommendations

### For Oracle 23c Free Edition:
- Use BASIC for test tables 1-4 (TEST_BASIC, TEST_OLTP, TEST_ADV_LOW, TEST_ADV_HIGH)
- All ADV_ types will fall back to appropriate BASIC/OLTP compression

### For Exadata Platforms:
- Use QUERY_LOW for test table 5 (TEST_HCC_QUERY_LOW) - balanced query performance
- Use QUERY_HIGH for test table 6 (TEST_HCC_QUERY_HIGH) - aggressive query compression
- Use ARCHIVE_LOW for test table 7 (TEST_HCC_ARCHIVE_LOW) - archival with occasional access
- Use ARCHIVE_HIGH for test table 8 (TEST_HCC_ARCHIVE_HIGH) - cold archival with minimal access

## Data Patterns Included

Each table uses realistic data patterns:

1. **Dimensional Repetition** - Countries, regions, departments repeat frequently
2. **Categorical Consistency** - Status, type, and category values follow fixed sets
3. **Temporal Clustering** - Dates grouped by year, month, quarter
4. **Hierarchical Grouping** - Parent-child relationships in identifiers
5. **Numeric Patterns** - Amounts, percentages, and metrics follow realistic distributions
6. **Text Compression** - Long descriptions, notes, and metadata benefit from compression
7. **Sparse Values** - NULL columns in error_code, promo_code demonstrate handling of sparse data

## Performance Testing

### Analyze Before & After
```sql
-- Before compression
SELECT
  table_name,
  ROUND((blocks * 8192 / 1024 / 1024), 2) as size_mb,
  num_rows,
  ROUND((blocks * 8192 / 1024 / 1024) / NULLIF(num_rows, 0), 6) as bytes_per_row
FROM user_tables
WHERE table_name LIKE 'TEST_%'
ORDER BY table_name;

-- After compression (run same query)
-- Compare bytes_per_row to see compression effectiveness
```

### Query Performance Comparison
```sql
-- Example: Count by category (good for compression)
SET TIMING ON
SELECT status, COUNT(*) as cnt
FROM TEST_BASIC_COMPRESSION
GROUP BY status;

-- Run before and after compression to compare I/O and CPU
```

## Notes

- Tables are created without initial compression for analysis purposes
- Insert operations use BULK operations for performance
- All tables use surrogate primary keys for efficient indexing
- Commit is executed after each table creation
- Tables can be dropped individually or all at once
- Supports both DRY-RUN and actual compression execution
- All compression operations are logged in V_COMPRESSION_HISTORY
- Original tablespaces are preserved during compression

## File Location

`sql/tests/test_tables_generator.sql`

## Related Documentation

- [Compression Strategies Guide](../reference/STRATEGY_GUIDE.md)
- [API Reference](../reference/API_REFERENCE.md)
- [System Architecture](../architecture/system-architecture.md)
