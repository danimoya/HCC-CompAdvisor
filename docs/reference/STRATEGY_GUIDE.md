# Compression Strategy Guide - HCC Compression Advisor

This guide provides comprehensive information about compression strategies, helping you choose and customize the right approach for your database workload.

## Table of Contents

- [Overview](#overview)
- [Understanding Compression Types](#understanding-compression-types)
- [Pre-Configured Strategies](#pre-configured-strategies)
- [Strategy Selection Guide](#strategy-selection-guide)
- [Strategy Rules and Thresholds](#strategy-rules-and-thresholds)
- [Customizing Strategies](#customizing-strategies)
- [Strategy Comparison](#strategy-comparison)
- [Performance vs Space Savings](#performance-vs-space-savings)
- [Real-World Examples](#real-world-examples)
- [Best Practices](#best-practices)

---

## Overview

### What is a Compression Strategy?

A compression strategy is a set of rules that determines:
- **What** to compress (tables, indexes, LOBs)
- **When** to compress (based on size, access patterns)
- **How** to compress (compression type to use)

The HCC Compression Advisor provides 3 pre-configured strategies plus the ability to create custom strategies.

### Strategy Components

Each strategy consists of:

1. **Strategy Profile** - Name, description, and goal
2. **Object Rules** - Rules for different object types (tables, indexes, LOBs)
3. **Thresholds** - Criteria for applying compression (size, hotness, DML rate)
4. **Priority** - Order in which rules are evaluated

### How Strategies Work

```
┌─────────────────────────────────────────────────────────────┐
│                    COMPRESSION ANALYSIS                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  1. Analyze object characteristics:                         │
│     - Size (MB/GB)                                          │
│     - Hotness score (0-100, based on access frequency)      │
│     - DML pattern (read vs write ratio)                     │
│     - Data type and structure                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  2. Apply strategy rules in priority order:                 │
│     - Check if object meets minimum size threshold          │
│     - Evaluate hotness score against strategy thresholds    │
│     - Determine appropriate compression type                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  3. Generate recommendation:                                 │
│     - Recommended compression type (OLTP, BASIC, etc.)      │
│     - Expected compression ratio                            │
│     - Potential space savings                               │
│     - Rationale for recommendation                          │
└─────────────────────────────────────────────────────────────┘
```

---

## Understanding Compression Types

### Oracle Compression Types (23c Free Edition)

Oracle 23c Free Edition supports the following compression types:

#### 1. BASIC Compression (Row Store)

**How it works:**
- Eliminates duplicate values within a database block
- Applied during direct-path INSERT operations
- Block-level compression

**Characteristics:**
- **Compression Ratio**: 2-3x (50-67% space savings)
- **Performance Impact**: Minimal (mainly on INSERT)
- **Best For**: Bulk-loaded data, historical data
- **Oracle License**: Included in all editions

**Example:**
```sql
ALTER TABLE sales_history MOVE COMPRESS BASIC;
```

**Block Storage Diagram:**
```
Uncompressed Block:
┌──────────────────────────────────────┐
│ Row 1: USA, California, Los Angeles  │
│ Row 2: USA, California, San Diego    │
│ Row 3: USA, California, Sacramento   │
│ Row 4: USA, Texas, Houston           │
└──────────────────────────────────────┘
Size: 8KB

BASIC Compressed Block:
┌──────────────────────────────────────┐
│ Symbol Table: USA=1, California=2... │
│ Row 1: 1, 2, Los Angeles            │
│ Row 2: 1, 2, San Diego              │
│ Row 3: 1, 2, Sacramento             │
│ Row 4: 1, Texas, Houston            │
└──────────────────────────────────────┘
Size: 3KB (2.7x compression)
```

#### 2. OLTP Compression (Advanced Row Compression)

**How it works:**
- Compresses data during all DML operations (INSERT, UPDATE)
- Maintains compression even during transactions
- More sophisticated than BASIC

**Characteristics:**
- **Compression Ratio**: 1.5-2.5x (33-60% space savings)
- **Performance Impact**: Very low (2-5% on writes, often faster reads)
- **Best For**: Active transactional tables
- **Oracle License**: Included in Enterprise Edition (check licensing)

**Example:**
```sql
ALTER TABLE orders MOVE COMPRESS FOR OLTP;
```

**Advantages over BASIC:**
- Maintains compression during DML
- Better read performance (fewer I/Os)
- Suitable for high-transaction environments

#### 3. Index Compression

Oracle 23c Free supports index compression with two levels:

**ADVANCED LOW:**
- **Compression Ratio**: 1.5-2x
- **Performance Impact**: Minimal
- **Best For**: Most indexes

**ADVANCED HIGH:**
- **Compression Ratio**: 2-3x
- **Performance Impact**: Slightly higher
- **Best For**: Large, infrequently accessed indexes

**Example:**
```sql
-- Advanced Low (default)
ALTER INDEX orders_idx REBUILD COMPRESS ADVANCED LOW;

-- Advanced High
ALTER INDEX archive_idx REBUILD COMPRESS ADVANCED HIGH;
```

#### 4. LOB Compression

**How it works:**
- Compresses Large Objects (CLOB, BLOB)
- Uses specialized algorithms for unstructured data

**Compression Levels:**
- **BASIC**: Standard compression
- **MEDIUM**: Balanced compression (not in Free Edition)
- **HIGH**: Maximum compression

**Example:**
```sql
-- For new LOBs
CREATE TABLE documents (
  id NUMBER,
  content CLOB
) LOB (content) STORE AS SECUREFILE (
  COMPRESS HIGH
);

-- For existing LOBs
ALTER TABLE documents MODIFY LOB (content) (COMPRESS HIGH);
```

### HCC (Hybrid Columnar Compression) - Exadata Only

⚠️ **Not available in Oracle 23c Free Edition**

HCC provides extreme compression ratios but requires Exadata hardware:

- **QUERY LOW**: 3-5x compression
- **QUERY HIGH**: 5-10x compression
- **ARCHIVE LOW**: 10-20x compression
- **ARCHIVE HIGH**: 20-50x compression

**How HCC works:**
```
Row Store (BASIC/OLTP):        Columnar Store (HCC):
┌─────────────────────┐        ┌───────────────────────┐
│ Row 1: A, B, C, D   │        │ Col A: A, A, A, A ... │
│ Row 2: A, E, F, G   │        │ Col B: B, E, H, K ... │
│ Row 3: A, H, I, J   │        │ Col C: C, F, I, L ... │
│ Row 4: A, K, L, M   │        │ Col D: D, G, J, M ... │
└─────────────────────┘        └───────────────────────┘
                               (better compression due
                                to similar values)
```

Since HCC is not available in Oracle 23c Free, the strategies use BASIC/OLTP as alternatives.

---

## Pre-Configured Strategies

### Strategy 1: HIGH_PERFORMANCE

**Goal:** Minimize compression overhead, prioritize performance

**Philosophy:** Only compress when absolutely necessary, use fastest compression types.

**Target Workloads:**
- High-transaction OLTP systems
- Real-time applications
- Systems where every millisecond matters
- 24/7 availability requirements

**Compression Approach:**

| Object Type | Condition | Compression | Rationale |
|-------------|-----------|-------------|-----------|
| **Hot Tables** (80-100) | Size > 100MB | OLTP | Fast compression, good read performance |
| **Warm Tables** (50-79) | Size > 100MB | NOCOMPRESS | Avoid overhead on moderately active data |
| **Cold Tables** (0-49) | Size > 100MB | NOCOMPRESS | Even cold data not compressed to maximize speed |
| **Indexes** | All | ADVANCED LOW | Minimal impact on lookups |
| **LOBs** | All | NOCOMPRESS | Avoid decompression overhead |
| **IOTs** | All | NOCOMPRESS | Preserve index-organized performance |

**Minimum Size Threshold:** 100 MB (only compress large objects)

**Expected Results:**
- **Space Savings**: 15-25%
- **Compression Ratio**: 1.2-1.5x
- **Performance Impact**: <2% on writes, neutral to positive on reads
- **Best For**: Banking systems, payment processing, booking systems

**SQL Definition:**
```sql
SELECT strategy_id, strategy_name, description
FROM COMPRESSION_STRATEGIES
WHERE strategy_id = 1;

STRATEGY_ID: 1
STRATEGY_NAME: HIGH_PERFORMANCE
DESCRIPTION: Minimal compression overhead for high-performance OLTP systems
```

---

### Strategy 2: BALANCED (Default)

**Goal:** Optimal balance between space savings and performance

**Philosophy:** Compress intelligently based on access patterns, use appropriate compression types.

**Target Workloads:**
- General-purpose databases
- Mixed OLTP/reporting workloads
- Applications with varying access patterns
- E-commerce platforms
- SaaS applications

**Compression Approach:**

| Object Type | Condition | Compression | Rationale |
|-------------|-----------|-------------|-----------|
| **Hot Tables** (80-100) | Size > 50MB | OLTP | Maintains good performance with compression |
| **Warm Tables** (50-79) | Size > 50MB | BASIC | Better compression, acceptable performance |
| **Cold Tables** (0-49) | Size > 50MB | BASIC | Maximize savings on infrequently accessed data |
| **Indexes** | All | ADVANCED LOW | Good balance of compression and speed |
| **LOBs** | Size > 10MB | BASIC | Compress large unstructured data |
| **IOTs** | Size > 50MB | OLTP | Preserve ordered access performance |
| **Partitions** | Old partitions | BASIC | Archive older data more aggressively |

**Minimum Size Threshold:** 50 MB (compress more objects)

**Expected Results:**
- **Space Savings**: 40-60%
- **Compression Ratio**: 2.0-2.5x
- **Performance Impact**: 5-10% on writes, neutral to positive on reads
- **Best For**: Most production databases, ERP systems, CRM applications

**SQL Definition:**
```sql
SELECT r.rule_type, r.object_type, r.compression_type,
       r.threshold_value, r.priority
FROM COMPRESSION_STRATEGY_RULES r
WHERE r.strategy_id = 2
ORDER BY r.priority;

RULE_TYPE        OBJECT_TYPE  COMPRESSION    THRESHOLD  PRIORITY
-------------    -----------  -------------  ---------  --------
SIZE_THRESHOLD   ALL          N/A            50         10
TABLE_HOT        TABLE        OLTP           80         1
TABLE_WARM       TABLE        BASIC          50         2
TABLE_COLD       TABLE        BASIC          0          3
INDEX            INDEX        ADVANCED LOW   N/A        4
LOB              LOB          BASIC          N/A        5
IOT              IOT          OLTP           N/A        6
```

---

### Strategy 3: MAXIMUM_COMPRESSION

**Goal:** Achieve maximum space savings

**Philosophy:** Compress aggressively, prioritize space over performance.

**Target Workloads:**
- Data warehouses
- Archive systems
- Read-mostly historical data
- Backup databases
- Systems where storage cost is critical

**Compression Approach:**

| Object Type | Condition | Compression | Rationale |
|-------------|-----------|-------------|-----------|
| **Hot Tables** (80-100) | Size > 10MB | OLTP | Even hot data gets compressed |
| **Warm Tables** (50-79) | Size > 10MB | OLTP | Aggressive compression on warm data |
| **Cold Tables** (0-49) | Size > 10MB | BASIC | Maximum savings on cold data |
| **Indexes** | All | ADVANCED HIGH | Highest index compression |
| **LOBs** | All | HIGH | Maximum LOB compression |
| **IOTs** | All | OLTP | Compress index-organized tables |
| **Partitions** | All | BASIC | Compress all partitions |

**Minimum Size Threshold:** 10 MB (compress almost everything)

**Expected Results:**
- **Space Savings**: 60-70%
- **Compression Ratio**: 2.5-3.5x
- **Performance Impact**: 10-20% on writes, improved on full scans
- **Best For**: Data warehouses, reporting databases, archival systems

**SQL Definition:**
```sql
SELECT r.rule_type, r.object_type, r.compression_type,
       r.threshold_value, r.priority
FROM COMPRESSION_STRATEGY_RULES r
WHERE r.strategy_id = 3
ORDER BY r.priority;

RULE_TYPE        OBJECT_TYPE  COMPRESSION      THRESHOLD  PRIORITY
-------------    -----------  ---------------  ---------  --------
SIZE_THRESHOLD   ALL          N/A              10         10
TABLE_HOT        TABLE        OLTP             80         1
TABLE_WARM       TABLE        OLTP             50         2
TABLE_COLD       TABLE        BASIC            0          3
INDEX            INDEX        ADVANCED HIGH    N/A        4
LOB              LOB          HIGH             N/A        5
IOT              IOT          OLTP             N/A        6
```

---

## Strategy Selection Guide

### Decision Tree

```
START: What is your primary goal?
│
├─ Maximum Performance (speed is critical)
│  │
│  ├─ Very high transaction rate (>10,000 TPS)?
│  │  └─ ✅ HIGH_PERFORMANCE
│  │
│  └─ Moderate transaction rate?
│     └─ Consider BALANCED
│
├─ Balance Performance and Space
│  │
│  ├─ Mixed workload (OLTP + reporting)?
│  │  └─ ✅ BALANCED (recommended)
│  │
│  └─ Unsure about workload characteristics?
│     └─ ✅ BALANCED (safe default)
│
└─ Maximum Space Savings (cost is critical)
   │
   ├─ Mainly read-only queries?
   │  └─ ✅ MAXIMUM_COMPRESSION
   │
   ├─ Archive/historical data?
   │  └─ ✅ MAXIMUM_COMPRESSION
   │
   └─ Active warehouse with bulk loads?
      └─ ✅ MAXIMUM_COMPRESSION
```

### Workload-Based Selection

| Workload Type | Characteristics | Recommended Strategy | Alternative |
|---------------|-----------------|---------------------|-------------|
| **OLTP** | High TPS, small transactions, real-time | HIGH_PERFORMANCE | BALANCED |
| **Mixed OLTP/DSS** | Both transactions and reports | BALANCED | HIGH_PERFORMANCE |
| **Data Warehouse** | Bulk loads, complex queries, read-mostly | MAXIMUM_COMPRESSION | BALANCED |
| **Archive** | Historical data, rare access | MAXIMUM_COMPRESSION | - |
| **Reporting** | Read-only replicas, dashboards | MAXIMUM_COMPRESSION | BALANCED |
| **Development/Test** | Non-production, cost-sensitive | MAXIMUM_COMPRESSION | BALANCED |

### Use Case Examples

#### E-Commerce Platform

**Scenario:**
- Order processing (high transaction rate)
- Product catalog (frequent reads, infrequent updates)
- Order history (archival data)

**Recommendation:**
```sql
-- Use BALANCED strategy as default
EXEC PKG_COMPRESSION_ADVISOR.run_analysis(
  p_owner => NULL,
  p_strategy_id => 2  -- BALANCED
);

-- Then customize:
-- 1. Don't compress active orders table (hot, high DML)
UPDATE COMPRESSION_RECOMMENDATIONS
SET advisable_compression = 'NOCOMPRESS'
WHERE object_name = 'ORDERS'
  AND hotness_score > 90;

-- 2. Use BASIC for order history (cold, read-only)
UPDATE COMPRESSION_RECOMMENDATIONS
SET advisable_compression = 'BASIC'
WHERE object_name = 'ORDERS_HISTORY';

-- 3. Compress product images (LOBs)
UPDATE COMPRESSION_RECOMMENDATIONS
SET advisable_compression = 'HIGH'
WHERE object_type = 'LOB'
  AND object_name LIKE '%PRODUCT_IMAGES%';
```

#### Banking System

**Scenario:**
- Transaction processing (critical performance)
- Account balances (very hot)
- Transaction history (archive)

**Recommendation:**
```sql
-- Use HIGH_PERFORMANCE for core tables
EXEC PKG_COMPRESSION_ADVISOR.analyze_table(
  p_owner => 'BANKING',
  p_table_name => 'ACCOUNTS',
  p_strategy_id => 1  -- HIGH_PERFORMANCE
);

EXEC PKG_COMPRESSION_ADVISOR.analyze_table(
  p_owner => 'BANKING',
  p_table_name => 'TRANSACTIONS',
  p_strategy_id => 1  -- HIGH_PERFORMANCE
);

-- Use MAXIMUM_COMPRESSION for history
EXEC PKG_COMPRESSION_ADVISOR.analyze_table(
  p_owner => 'BANKING',
  p_table_name => 'TRANSACTION_HISTORY',
  p_strategy_id => 3  -- MAXIMUM_COMPRESSION
);
```

#### Data Warehouse

**Scenario:**
- Nightly ETL loads
- Complex analytical queries
- Historical data retention (7 years)

**Recommendation:**
```sql
-- Use MAXIMUM_COMPRESSION for everything
EXEC PKG_COMPRESSION_ADVISOR.run_analysis(
  p_owner => 'DW',
  p_strategy_id => 3  -- MAXIMUM_COMPRESSION
);

-- Compress partitions differently by age
-- Recent partitions: OLTP (more access)
-- Old partitions: BASIC (less access, more savings)
```

---

## Strategy Rules and Thresholds

### Understanding Hotness Score

The hotness score (0-100) indicates how frequently an object is accessed:

**Calculation:**
```sql
Hotness Score = (
  (Read Operations * 0.3) +
  (Write Operations * 0.5) +
  (Recent Access Factor * 0.2)
) / Max Possible * 100
```

**Interpretation:**

| Score Range | Classification | Access Pattern | Recommended Compression |
|-------------|----------------|----------------|------------------------|
| **90-100** | Extremely Hot | Constant access, real-time | OLTP or NOCOMPRESS |
| **80-89** | Very Hot | Frequent access, hourly updates | OLTP |
| **70-79** | Hot | Regular access, daily updates | OLTP |
| **50-69** | Warm | Moderate access, weekly updates | BASIC |
| **30-49** | Cool | Infrequent access, monthly updates | BASIC |
| **0-29** | Cold | Rare access, archival | BASIC or ADVANCED |

### Rule Priority System

Rules are evaluated in priority order (1 = highest):

**Example for BALANCED Strategy:**

```
Priority 1: Size Threshold Check
  └─ If size < 50 MB: SKIP (don't compress)
  └─ If size >= 50 MB: CONTINUE

Priority 2: Object Type Check
  └─ If TABLE: CONTINUE to Priority 3
  └─ If INDEX: Apply INDEX rule (ADVANCED LOW)
  └─ If LOB: Apply LOB rule (BASIC)

Priority 3: Hotness Evaluation (for tables)
  └─ If hotness >= 80: Apply TABLE_HOT rule (OLTP)
  └─ If 50 <= hotness < 80: Apply TABLE_WARM rule (BASIC)
  └─ If hotness < 50: Apply TABLE_COLD rule (BASIC)

Priority 4: DML Pattern Check (optional)
  └─ If >80% writes: Downgrade compression or NOCOMPRESS
  └─ If >80% reads: Upgrade compression if possible
```

### Threshold Customization

You can adjust thresholds to match your environment:

#### Example 1: More Aggressive BALANCED Strategy

```sql
-- Reduce minimum size threshold from 50MB to 20MB
UPDATE COMPRESSION_STRATEGY_RULES
SET threshold_value = 20
WHERE strategy_id = 2
  AND rule_type = 'SIZE_THRESHOLD';

-- Lower hotness threshold for OLTP compression
UPDATE COMPRESSION_STRATEGY_RULES
SET threshold_value = 70  -- was 80
WHERE strategy_id = 2
  AND rule_type = 'TABLE_HOT';

COMMIT;
```

#### Example 2: Conservative HIGH_PERFORMANCE Strategy

```sql
-- Increase minimum size threshold to 500MB
UPDATE COMPRESSION_STRATEGY_RULES
SET threshold_value = 500
WHERE strategy_id = 1
  AND rule_type = 'SIZE_THRESHOLD';

-- Only compress extremely hot tables
UPDATE COMPRESSION_STRATEGY_RULES
SET threshold_value = 90  -- was 80
WHERE strategy_id = 1
  AND rule_type = 'TABLE_HOT';

COMMIT;
```

---

## Customizing Strategies

### Creating a Custom Strategy

#### Example: ARCHIVAL Strategy

**Requirements:**
- Maximum compression for all objects
- No consideration for performance
- Compress objects as small as 1MB

**Step 1: Create Strategy**

```sql
INSERT INTO COMPRESSION_STRATEGIES (
  strategy_id,
  strategy_name,
  description,
  is_active
) VALUES (
  4,
  'ARCHIVAL',
  'Maximum compression for long-term storage with no performance requirements',
  1
);
COMMIT;
```

**Step 2: Create Rules**

```sql
-- Size threshold: compress anything >= 1 MB
INSERT INTO COMPRESSION_STRATEGY_RULES (
  rule_id, strategy_id, object_type, rule_type,
  compression_type, threshold_value, priority, is_active
) VALUES (
  SEQ_STRATEGY_RULES.NEXTVAL, 4, 'ALL', 'SIZE_THRESHOLD',
  NULL, 1, 10, 1
);

-- Tables: all get BASIC (maximum savings in 23c Free)
INSERT INTO COMPRESSION_STRATEGY_RULES (
  rule_id, strategy_id, object_type, rule_type,
  compression_type, threshold_value, priority, is_active
) VALUES (
  SEQ_STRATEGY_RULES.NEXTVAL, 4, 'TABLE', 'TABLE_ALL',
  'BASIC', NULL, 1, 1
);

-- Indexes: ADVANCED HIGH
INSERT INTO COMPRESSION_STRATEGY_RULES (
  rule_id, strategy_id, object_type, rule_type,
  compression_type, threshold_value, priority, is_active
) VALUES (
  SEQ_STRATEGY_RULES.NEXTVAL, 4, 'INDEX', 'INDEX',
  'ADVANCED HIGH', NULL, 2, 1
);

-- LOBs: HIGH
INSERT INTO COMPRESSION_STRATEGY_RULES (
  rule_id, strategy_id, object_type, rule_type,
  compression_type, threshold_value, priority, is_active
) VALUES (
  SEQ_STRATEGY_RULES.NEXTVAL, 4, 'LOB', 'LOB',
  'HIGH', NULL, 3, 1
);

COMMIT;
```

**Step 3: Test Strategy**

```sql
-- Run analysis with new strategy
EXEC PKG_COMPRESSION_ADVISOR.run_analysis(
  p_owner => 'ARCHIVE_SCHEMA',
  p_strategy_id => 4  -- ARCHIVAL
);

-- Review recommendations
SELECT object_name, current_size_mb,
       advisable_compression, potential_savings_mb
FROM V_COMPRESSION_CANDIDATES
WHERE strategy_id = 4
ORDER BY potential_savings_mb DESC;
```

#### Example: PARTITION_AWARE Strategy

**Requirements:**
- Different compression for different partition ages
- Recent partitions: OLTP
- Medium-age partitions: BASIC
- Old partitions: BASIC

```sql
-- Create strategy
INSERT INTO COMPRESSION_STRATEGIES (
  strategy_id, strategy_name, description, is_active
) VALUES (
  5, 'PARTITION_AWARE',
  'Age-based compression for partitioned tables', 1
);

-- Recent partitions (<30 days): OLTP
INSERT INTO COMPRESSION_STRATEGY_RULES (
  rule_id, strategy_id, object_type, rule_type,
  compression_type, threshold_value, priority, is_active, notes
) VALUES (
  SEQ_STRATEGY_RULES.NEXTVAL, 5, 'PARTITION', 'PARTITION_RECENT',
  'OLTP', 30, 1, 1, 'Partitions less than 30 days old'
);

-- Medium-age partitions (30-180 days): BASIC
INSERT INTO COMPRESSION_STRATEGY_RULES (
  rule_id, strategy_id, object_type, rule_type,
  compression_type, threshold_value, priority, is_active, notes
) VALUES (
  SEQ_STRATEGY_RULES.NEXTVAL, 5, 'PARTITION', 'PARTITION_MEDIUM',
  'BASIC', 180, 2, 1, 'Partitions 30-180 days old'
);

-- Old partitions (>180 days): BASIC
INSERT INTO COMPRESSION_STRATEGY_RULES (
  rule_id, strategy_id, object_type, rule_type,
  compression_type, threshold_value, priority, is_active, notes
) VALUES (
  SEQ_STRATEGY_RULES.NEXTVAL, 5, 'PARTITION', 'PARTITION_OLD',
  'BASIC', 999999, 3, 1, 'Partitions older than 180 days'
);

COMMIT;
```

### Modifying Existing Strategies

#### Example: Tune BALANCED for Your Workload

```sql
-- Scenario: Your "hot" data is less active than typical
-- Adjust thresholds to match your workload

-- Original BALANCED: hotness >= 80 → OLTP
-- Your workload: hotness >= 60 → OLTP

UPDATE COMPRESSION_STRATEGY_RULES
SET threshold_value = 60
WHERE strategy_id = 2
  AND rule_type = 'TABLE_HOT';

-- Adjust warm/cold boundary similarly
UPDATE COMPRESSION_STRATEGY_RULES
SET threshold_value = 30  -- was 50
WHERE strategy_id = 2
  AND rule_type = 'TABLE_WARM';

COMMIT;

-- Test the changes
EXEC PKG_COMPRESSION_ADVISOR.run_analysis(
  p_owner => NULL,
  p_strategy_id => 2
);
```

---

## Strategy Comparison

### Side-by-Side Comparison Table

| Aspect | HIGH_PERFORMANCE | BALANCED | MAXIMUM_COMPRESSION |
|--------|------------------|----------|---------------------|
| **Primary Goal** | Speed | Balance | Space Savings |
| **Space Savings** | 15-25% | 40-60% | 60-70% |
| **Compression Ratio** | 1.2-1.5x | 2.0-2.5x | 2.5-3.5x |
| **Write Performance** | -2% | -5 to -10% | -10 to -20% |
| **Read Performance** | 0 to +5% | 0 to +10% | +10 to +30% (full scans) |
| **Min Object Size** | 100 MB | 50 MB | 10 MB |
| **Hot Table Compression** | OLTP | OLTP | OLTP |
| **Warm Table Compression** | NOCOMPRESS | BASIC | OLTP |
| **Cold Table Compression** | NOCOMPRESS | BASIC | BASIC |
| **Index Compression** | ADVANCED LOW | ADVANCED LOW | ADVANCED HIGH |
| **LOB Compression** | NOCOMPRESS | BASIC | HIGH |
| **Best For** | OLTP | Mixed | DW/Archive |
| **Typical Use Cases** | Banking, Trading | ERP, SaaS | Reporting, Backup |

### Compression Ratio by Object Type

**Based on typical data:**

| Object Type | HIGH_PERFORMANCE | BALANCED | MAXIMUM_COMPRESSION |
|-------------|------------------|----------|---------------------|
| **Text-heavy tables** | 1.3x | 2.2x | 2.8x |
| **Numeric tables** | 1.2x | 1.9x | 2.4x |
| **Mixed data tables** | 1.4x | 2.1x | 2.7x |
| **Indexes (B-tree)** | 1.5x | 1.5x | 2.2x |
| **LOBs (text)** | 1.0x (none) | 2.5x | 3.5x |
| **LOBs (binary)** | 1.0x (none) | 1.8x | 2.2x |

### Performance Impact by Workload

**Performance change (negative = slower, positive = faster):**

| Workload Type | HIGH_PERFORMANCE | BALANCED | MAXIMUM_COMPRESSION |
|---------------|------------------|----------|---------------------|
| **OLTP Inserts** | -2% | -7% | -15% |
| **OLTP Updates** | -1% | -5% | -12% |
| **OLTP Point Queries** | +2% | +3% | +5% |
| **Full Table Scans** | +5% | +15% | +30% |
| **Index Range Scans** | +1% | +2% | +3% |
| **Analytical Queries** | +8% | +20% | +35% |
| **Batch Loads** | -3% | -10% | -18% |

---

## Performance vs Space Savings

### The Compression Trade-off

```
Performance Impact vs Space Savings
│
│ Space
│ Savings  MAXIMUM_COMPRESSION ●
│  70%                         │
│  60%              BALANCED ●─┤
│  50%                      │  │
│  40%                      │  │
│  30%                      │  │
│  20%   HIGH_PERFORMANCE ●─┘  │
│  10%                 │       │
│   0% ────────────────┴───────┴──────────
│      0%  5% 10% 15% 20% 25% 30%
│           Performance Impact (write overhead)
│
└─→ Optimal choice depends on your priorities
```

### When to Accept Performance Impact

**Accept higher impact when:**
- Storage costs are significant
- Data is read-mostly (DW, reporting)
- Full table scans are common
- Archival/historical data
- Development/test environments

**Minimize impact when:**
- Transaction performance is critical
- 24/7 availability required
- High write volume (>10,000 TPS)
- Real-time applications
- SLA requirements are strict

### Measuring Actual Impact

After compressing, measure the actual impact:

```sql
-- Before compression: capture baseline
CREATE TABLE perf_baseline AS
SELECT sql_id, executions, elapsed_time, cpu_time,
       buffer_gets, disk_reads
FROM v$sql
WHERE parsing_schema_name = 'YOUR_SCHEMA'
  AND executions > 100;

-- Run your workload for 24 hours

-- After compression: compare
SELECT b.sql_id,
       b.executions as before_execs,
       a.executions as after_execs,
       ROUND((a.elapsed_time/a.executions) /
             (b.elapsed_time/b.executions) * 100 - 100, 2)
         as pct_change_elapsed,
       ROUND((a.buffer_gets/a.executions) /
             (b.buffer_gets/b.executions) * 100 - 100, 2)
         as pct_change_logical_io
FROM perf_baseline b
JOIN v$sql a ON b.sql_id = a.sql_id
WHERE a.executions > 100
ORDER BY ABS(pct_change_elapsed) DESC;

-- Positive pct_change = slower
-- Negative pct_change = faster
```

---

## Real-World Examples

### Example 1: E-Commerce Platform Migration

**Initial State:**
- Database size: 2 TB
- 80% orders and order history
- 20% product catalog and user data
- Mixed OLTP and reporting workload

**Strategy Selection:**
- Chose **BALANCED** as base strategy
- Customized for specific tables

**Implementation:**

```sql
-- Phase 1: Analyze everything
EXEC PKG_COMPRESSION_ADVISOR.run_analysis(
  p_owner => NULL,
  p_strategy_id => 2  -- BALANCED
);

-- Phase 2: Customize recommendations
-- Keep hot order tables uncompressed
UPDATE COMPRESSION_RECOMMENDATIONS
SET advisable_compression = 'NOCOMPRESS',
    rationale = 'Override: Critical performance table'
WHERE object_name IN ('ORDERS', 'ORDER_ITEMS')
  AND hotness_score > 85;

-- Aggressively compress old orders
UPDATE COMPRESSION_RECOMMENDATIONS
SET advisable_compression = 'BASIC',
    rationale = 'Override: Historical data'
WHERE object_name LIKE 'ORDERS_2020%'
   OR object_name LIKE 'ORDERS_2021%';

-- Phase 3: Execute in batches
-- Week 1: Compress archive tables (low risk)
EXEC PKG_COMPRESSION_EXECUTOR.execute_recommendations(
  p_strategy_id => 2,
  p_max_tables => 50,
  p_owner_filter => 'ECOMMERCE',
  p_object_filter => '%_2020%,%_2021%'
);

-- Week 2: Compress product catalog (read-mostly)
EXEC PKG_COMPRESSION_EXECUTOR.compress_table(
  p_owner => 'ECOMMERCE',
  p_table_name => 'PRODUCTS',
  p_compression_type => 'OLTP',
  p_online => TRUE
);

-- Week 3: Compress user data
-- Week 4: Compress reporting tables
```

**Results:**
- **Space saved**: 780 GB (39% reduction)
- **Performance impact**:
  - Order processing: -3% (acceptable)
  - Reporting queries: +25% (faster!)
  - Batch jobs: -8% (acceptable)
- **Cost savings**: $15,000/year in storage
- **Execution time**: 4 weeks (phased approach)

### Example 2: Data Warehouse Consolidation

**Initial State:**
- Database size: 8 TB
- Mainly historical sales data
- Nightly ETL loads
- Complex analytical queries

**Strategy Selection:**
- Chose **MAXIMUM_COMPRESSION**
- Applied to all objects

**Implementation:**

```sql
-- Compress all fact tables
EXEC PKG_COMPRESSION_ADVISOR.run_analysis(
  p_owner => 'DW',
  p_strategy_id => 3  -- MAXIMUM_COMPRESSION
);

-- Execute all recommendations
EXEC PKG_COMPRESSION_EXECUTOR.execute_recommendations(
  p_strategy_id => 3,
  p_max_tables => 500,  -- all tables
  p_max_size_gb => 8000  -- entire database
);

-- Special handling for partitioned tables
-- Compress by partition age
FOR part_rec IN (
  SELECT table_owner, table_name, partition_name
  FROM all_tab_partitions
  WHERE table_owner = 'DW'
    AND partition_name < 'P_2024'  -- old partitions
) LOOP
  EXECUTE IMMEDIATE
    'ALTER TABLE ' || part_rec.table_owner || '.' ||
    part_rec.table_name ||
    ' MOVE PARTITION ' || part_rec.partition_name ||
    ' COMPRESS BASIC ONLINE';
END LOOP;
```

**Results:**
- **Space saved**: 5.2 TB (65% reduction)
- **Performance impact**:
  - ETL loads: -15% (acceptable for overnight batch)
  - Query performance: +30% (faster due to less I/O!)
  - Full table scans: +45% (much faster)
- **Cost savings**: $78,000/year in storage + infrastructure
- **Bonus**: Allowed deferring hardware upgrade for 2 years

### Example 3: Banking System Archive

**Initial State:**
- Production database: 4 TB (cannot compress)
- Archive database: 12 TB (7 years of history)
- Compliance requirement: keep 7 years
- Read-only queries for audits

**Strategy Selection:**
- Production: **HIGH_PERFORMANCE** (no compression)
- Archive: **MAXIMUM_COMPRESSION**

**Implementation:**

```sql
-- Production: verify no compression recommended
EXEC PKG_COMPRESSION_ADVISOR.run_analysis(
  p_owner => 'BANKING_PROD',
  p_strategy_id => 1  -- HIGH_PERFORMANCE
);

SELECT COUNT(*) FROM V_COMPRESSION_CANDIDATES;
-- Result: 0 recommendations (as expected, all hot tables)

-- Archive: aggressive compression
EXEC PKG_COMPRESSION_ADVISOR.run_analysis(
  p_owner => 'BANKING_ARCHIVE',
  p_strategy_id => 3  -- MAXIMUM_COMPRESSION
);

-- Compress by year (oldest first, safest)
FOR year IN 2018..2024 LOOP
  DBMS_OUTPUT.PUT_LINE('Compressing year: ' || year);

  EXEC PKG_COMPRESSION_EXECUTOR.execute_recommendations(
    p_strategy_id => 3,
    p_max_tables => 100,
    p_object_filter => '%_' || year || '%'
  );

  -- Wait 1 week between years to monitor impact
  DBMS_LOCK.SLEEP(604800);  -- 1 week
END LOOP;
```

**Results:**
- **Space saved**: 8.4 TB (70% reduction on archive)
- **Performance impact**:
  - Production: 0% (no changes)
  - Archive queries: +20% (faster, less I/O)
- **Cost avoidance**: $120,000 (avoided adding storage)
- **Compliance**: Met 7-year retention at lower cost

---

## Best Practices

### 1. Strategy Selection

✅ **Do:**
- Start with BALANCED for unknown workloads
- Test strategies on non-production first
- Match strategy to data lifecycle (recent vs historical)
- Review and adjust strategies quarterly

❌ **Don't:**
- Use MAXIMUM_COMPRESSION on high-transaction OLTP
- Compress system schemas (SYS, SYSTEM, etc.)
- Apply strategies blindly without analysis
- Forget to re-analyze after major application changes

### 2. Customization

✅ **Do:**
- Create custom strategies for specific schemas
- Adjust thresholds based on your data sizes
- Document why you customized rules
- Version control your strategy definitions

❌ **Don't:**
- Over-customize (keep it simple)
- Create too many strategies (3-5 max)
- Change strategies frequently without testing
- Ignore the pre-configured strategies

### 3. Testing

✅ **Do:**
- Test compression on representative data
- Measure actual performance impact
- Run before/after query performance tests
- Validate compression ratios match expectations

❌ **Don't:**
- Compress production without testing
- Skip performance validation
- Assume compression ratios from documentation
- Forget to test rollback procedures

### 4. Monitoring

✅ **Do:**
- Monitor query performance after compression
- Track space savings over time
- Review execution history regularly
- Set up alerts for compression failures

❌ **Don't:**
- Compress and forget
- Ignore performance degradation
- Let rollback window expire without validation
- Skip gathering statistics after compression

### 5. Maintenance

✅ **Do:**
- Gather statistics after compression
- Rebuild indexes if needed
- Reclaim freed space (shrink tablespace)
- Re-analyze periodically (monthly/quarterly)

❌ **Don't:**
- Forget to gather statistics
- Leave indexes in UNUSABLE state
- Assume space is automatically reclaimed
- Set and forget compression strategy

---

## Conclusion

Choosing the right compression strategy is critical for balancing space savings and performance. Key takeaways:

1. **BALANCED is a safe default** for most workloads
2. **Customize based on your specific needs** using hotness scores and access patterns
3. **Test thoroughly** before compressing production data
4. **Monitor and adjust** strategies as your workload evolves
5. **Consider data lifecycle** (recent vs archival) when selecting compression

For more information:
- [User Guide](USER_GUIDE.md) - How to use the system
- [Installation Guide](INSTALLATION.md) - Setup instructions
- [API Reference](API_REFERENCE.md) - REST API documentation

---

**Remember:** The best strategy is the one that meets YOUR requirements for space savings and performance. Use this guide to make informed decisions!
