# Tablespace Preservation in HCC Compression Advisor

## Overview

The HCC Compression Advisor now ensures that all compression operations preserve the original tablespace assignments of database objects. This is critical for maintaining storage architecture and avoiding unintended data movement between tablespaces.

## Implementation Date
2025-11-13

## Affected Components

### 1. PKG_COMPRESSION_EXECUTOR Package
**File:** `/home/claude/Oracle-Database-Related/HCC-CompAdvisor/sql/04_executor_pkg.sql`

All DDL generation functions have been updated to include tablespace preservation logic.

## Key Changes

### 1. Regular Tables (`compress_table`)

**Before:**
```sql
ALTER TABLE owner.table_name MOVE COMPRESS FOR OLTP;
```

**After:**
```sql
-- Query current tablespace
SELECT tablespace_name INTO v_tablespace_name
FROM DBA_TABLES
WHERE owner = p_owner AND table_name = p_table_name;

-- Include in DDL
ALTER TABLE owner.table_name MOVE COMPRESS FOR OLTP TABLESPACE v_tablespace_name;
```

**Implementation Details:**
- Queries `DBA_TABLES.tablespace_name` before generating DDL
- Adds `TABLESPACE` clause to all `ALTER TABLE ... MOVE` statements
- Logs tablespace information for audit trail
- Handles NULL tablespaces gracefully

### 2. Indexes (`rebuild_table_indexes`)

**Before:**
```sql
ALTER INDEX owner.index_name REBUILD ONLINE;
```

**After:**
```sql
-- Query current index tablespace
SELECT tablespace_name FROM DBA_INDEXES
WHERE owner = p_owner AND index_name = idx.index_name;

-- Include in DDL
ALTER INDEX owner.index_name REBUILD TABLESPACE v_tablespace_name ONLINE;
```

**Implementation Details:**
- Queries `DBA_INDEXES.tablespace_name` for each index
- Adds `TABLESPACE` clause to all `REBUILD` statements
- Preserves individual index tablespaces when rebuilding multiple indexes

### 3. Partitioned Tables (`compress_partition`)

**New Procedure - Critical for Partitioned Objects**

```sql
PROCEDURE compress_partition(
  p_owner IN VARCHAR2,
  p_table_name IN VARCHAR2,
  p_partition_name IN VARCHAR2,
  p_compression_type IN VARCHAR2,
  p_online IN BOOLEAN DEFAULT TRUE
);
```

**Features:**
- Queries `DBA_TAB_PARTITIONS.tablespace_name` for specific partition
- Each partition may be in a different tablespace
- Generates partition-specific DDL with tablespace preservation
- Rebuilds partition indexes with tablespace preservation

**Example:**
```sql
-- Partition P1 in TS_DATA1, P2 in TS_DATA2
-- Both tablespaces are preserved after compression
EXEC PKG_COMPRESSION_EXECUTOR.compress_partition('HR', 'SALES', 'Q1_2024', 'OLTP');
```

### 4. Batch Partition Compression (`compress_all_partitions`)

**New Procedure - Process All Partitions**

```sql
PROCEDURE compress_all_partitions(
  p_owner IN VARCHAR2,
  p_table_name IN VARCHAR2,
  p_compression_type IN VARCHAR2,
  p_online IN BOOLEAN DEFAULT TRUE
);
```

**Features:**
- Iterates through all partitions via `DBA_TAB_PARTITIONS`
- Calls `compress_partition` for each partition individually
- Each partition's tablespace is independently preserved
- Continues processing if individual partitions fail
- Provides summary statistics at completion

**Example:**
```sql
-- Compress all partitions, each preserving its original tablespace
EXEC PKG_COMPRESSION_EXECUTOR.compress_all_partitions('HR', 'SALES_HISTORY', 'OLTP');
```

### 5. LOB Segments (`compress_lob`)

**New Procedure - LOB-Specific Compression**

```sql
PROCEDURE compress_lob(
  p_owner IN VARCHAR2,
  p_table_name IN VARCHAR2,
  p_column_name IN VARCHAR2,
  p_compression_type IN VARCHAR2
);
```

**Features:**
- Queries `DBA_LOBS.tablespace_name` for LOB segment
- LOBs may be stored separately from base table
- Uses `ALTER TABLE ... MODIFY LOB` syntax
- Preserves LOB tablespace in storage clause

**Example:**
```sql
-- LOB in TS_LOBS tablespace is preserved
EXEC PKG_COMPRESSION_EXECUTOR.compress_lob('HR', 'DOCUMENTS', 'CONTENT', 'HIGH');
```

**Generated DDL:**
```sql
ALTER TABLE owner.table_name
MODIFY LOB (column_name) (
  COMPRESS HIGH
  TABLESPACE ts_lob_name
);
```

## Testing

### Comprehensive Test Suite
**File:** `/home/claude/Oracle-Database-Related/HCC-CompAdvisor/tests/test_tablespace_preservation.sql`

**Test Coverage:**
1. **TEST 1:** Regular table tablespace preservation
2. **TEST 2:** Index tablespace preservation during rebuild
3. **TEST 3:** Partitioned table individual partition tablespaces
4. **TEST 4:** LOB segment tablespace preservation
5. **TEST 5:** Batch partition compression with multiple tablespaces

### Test Execution

```sql
@/home/claude/Oracle-Database-Related/HCC-CompAdvisor/tests/test_tablespace_preservation.sql
```

**Expected Results:**
- All tests should pass with "✓ TEST X PASSED" messages
- Compression history table should show all operations
- No objects should move to unexpected tablespaces

### Test Scenarios Covered

#### Regular Tables
- Table in TS_TEST_DATA remains in TS_TEST_DATA after compression
- Compression type changes from DISABLED to ENABLED
- Indexes are rebuilt in their original tablespaces

#### Partitioned Tables
- Partition P1 in TS_TEST_PART1 stays in TS_TEST_PART1
- Partition P2 in TS_TEST_PART2 stays in TS_TEST_PART2
- Mixed tablespace configurations are preserved

#### LOB Segments
- LOB in TS_TEST_LOB remains in TS_TEST_LOB
- Base table can be in different tablespace
- LOB compression applied correctly

## Benefits

### 1. Storage Architecture Integrity
- Maintains planned data distribution across tablespaces
- Prevents unintended storage migrations
- Preserves disaster recovery strategies

### 2. Performance Characteristics
- Objects remain on intended storage tiers (SSD vs HDD)
- I/O patterns remain consistent
- Query performance stays predictable

### 3. Space Management
- Tablespace quotas remain accurate
- Free space calculations stay valid
- Capacity planning remains reliable

### 4. Compliance and Auditing
- Storage location requirements are maintained
- Audit trails show tablespace preservation
- Regulatory requirements for data locality satisfied

## Technical Implementation Details

### Query Patterns

**Tables:**
```sql
SELECT tablespace_name, iot_type, partitioned
FROM DBA_TABLES
WHERE owner = p_owner AND table_name = p_table_name;
```

**Partitions:**
```sql
SELECT tablespace_name
FROM DBA_TAB_PARTITIONS
WHERE table_owner = p_owner
  AND table_name = p_table_name
  AND partition_name = p_partition_name;
```

**Indexes:**
```sql
SELECT tablespace_name
FROM DBA_INDEXES
WHERE owner = p_owner AND index_name = p_index_name;
```

**LOBs:**
```sql
SELECT segment_name, tablespace_name
FROM DBA_LOBS
WHERE owner = p_owner
  AND table_name = p_table_name
  AND column_name = p_column_name;
```

### DDL Generation Pattern

```sql
-- 1. Query current tablespace
SELECT tablespace_name INTO v_tablespace_name
FROM dba_objects_view
WHERE ... ;

-- 2. Build base DDL
v_ddl := 'ALTER TABLE/INDEX ... MOVE/REBUILD ... COMPRESS ...';

-- 3. Add tablespace clause if not null
IF v_tablespace_name IS NOT NULL THEN
  v_ddl := v_ddl || ' TABLESPACE ' || v_tablespace_name;
END IF;

-- 4. Add optional clauses (ONLINE, etc.)
-- 5. Execute and log
```

## Error Handling

### Scenarios Handled

1. **NULL Tablespace:** Objects without explicit tablespace assignment skip clause
2. **Missing Objects:** Raises appropriate error before attempting compression
3. **Invalid Tablespace:** Oracle validates during execution
4. **Insufficient Space:** Pre-execution checks validate free space

### Logging

All operations log:
- Original tablespace name
- Target tablespace name (same as original)
- Confirmation of preservation
- Any warnings or errors

Example log output:
```
[INFO] Current tablespace: TS_DATA
[INFO] Preserving tablespace: TS_DATA
[INFO] DDL: ALTER TABLE HR.EMPLOYEES MOVE COMPRESS FOR OLTP TABLESPACE TS_DATA ONLINE
```

## Backward Compatibility

### Existing Code
- All existing procedures maintain same signatures
- Default behavior now includes tablespace preservation
- No breaking changes to public API

### Migration
- Existing compression history preserved
- New operations automatically include tablespace tracking
- No manual intervention required

## Future Enhancements

### Potential Improvements

1. **Subpartition Support:** Extend to compress subpartitions with tablespace preservation
2. **IOT Support:** Add specialized handling for Index-Organized Tables
3. **Tablespace Mapping:** Allow optional tablespace remapping during compression
4. **Cross-Tablespace Validation:** Verify sufficient space in target tablespace

### Configuration Options

Future enhancement could add:
```sql
-- Optional parameter to override tablespace
PROCEDURE compress_table(
  ...
  p_target_tablespace IN VARCHAR2 DEFAULT NULL  -- NULL = preserve original
);
```

## Usage Examples

### Regular Table Compression
```sql
-- Compress HR.EMPLOYEES preserving current tablespace
EXEC PKG_COMPRESSION_EXECUTOR.compress_table('HR', 'EMPLOYEES', 'OLTP', TRUE, FALSE);
```

### Partition Compression
```sql
-- Compress specific partition preserving its tablespace
EXEC PKG_COMPRESSION_EXECUTOR.compress_partition('SALES', 'ORDERS', 'P_2024_Q1', 'OLTP');
```

### Batch Partition Compression
```sql
-- Compress all partitions, each preserving its tablespace
EXEC PKG_COMPRESSION_EXECUTOR.compress_all_partitions('SALES', 'ORDERS', 'OLTP');
```

### LOB Compression
```sql
-- Compress LOB column preserving LOB tablespace
EXEC PKG_COMPRESSION_EXECUTOR.compress_lob('HR', 'RESUMES', 'RESUME_TEXT', 'HIGH');
```

### Batch Recommendations
```sql
-- Execute recommendations with tablespace preservation
EXEC PKG_COMPRESSION_EXECUTOR.execute_recommendations(2, 10, 100);
```

## Verification Queries

### Check Table Tablespace
```sql
SELECT table_name, tablespace_name, compression, compress_for
FROM user_tables
WHERE table_name = 'YOUR_TABLE';
```

### Check Partition Tablespaces
```sql
SELECT partition_name, tablespace_name, compression
FROM user_tab_partitions
WHERE table_name = 'YOUR_TABLE'
ORDER BY partition_position;
```

### Check Index Tablespace
```sql
SELECT index_name, tablespace_name, compression
FROM user_indexes
WHERE table_name = 'YOUR_TABLE';
```

### Check LOB Tablespace
```sql
SELECT column_name, segment_name, tablespace_name, compression
FROM user_lobs
WHERE table_name = 'YOUR_TABLE';
```

## Troubleshooting

### Issue: Object moved to wrong tablespace

**Diagnosis:**
```sql
-- Check compression history
SELECT object_name, ddl_statement
FROM T_COMPRESSION_HISTORY
WHERE object_name = 'YOUR_OBJECT'
ORDER BY history_id DESC;
```

**Resolution:**
- Review DDL statement in history
- Verify tablespace clause present
- Check for manual DDL executed outside package

### Issue: Insufficient space error

**Diagnosis:**
```sql
-- Check tablespace free space
SELECT tablespace_name,
       ROUND(SUM(bytes)/1024/1024/1024, 2) AS free_gb
FROM dba_free_space
GROUP BY tablespace_name;
```

**Resolution:**
- Add datafile to tablespace
- Extend autoextend limit
- Move to different tablespace manually

## References

### Oracle Documentation
- Oracle Database SQL Language Reference: ALTER TABLE
- Oracle Database Administrator's Guide: Managing Tablespaces
- Oracle Database VLDB and Partitioning Guide: Partitioned Tables

### Internal Documentation
- `/home/claude/Oracle-Database-Related/HCC-CompAdvisor/README.md`
- `/home/claude/Oracle-Database-Related/HCC-CompAdvisor/sql/04_executor_pkg.sql`
- `/home/claude/Oracle-Database-Related/HCC-CompAdvisor/tests/test_tablespace_preservation.sql`

## Conclusion

The tablespace preservation feature ensures that compression operations maintain storage architecture integrity. All compression DDL now includes appropriate TABLESPACE clauses to prevent unintended object movement. Comprehensive testing validates functionality across regular tables, partitioned tables, indexes, and LOB segments.
