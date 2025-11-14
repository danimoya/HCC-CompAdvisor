# User Guide - HCC Compression Advisor

This comprehensive guide explains how to use the HCC Compression Advisor system for database compression analysis, recommendations, and execution.

## Table of Contents

- [Getting Started](#getting-started)
- [Dashboard Overview](#dashboard-overview)
- [Running Compression Analysis](#running-compression-analysis)
- [Viewing Recommendations](#viewing-recommendations)
- [Executing Compression](#executing-compression)
- [Monitoring History](#monitoring-history)
- [Managing Strategies](#managing-strategies)
- [Using SQL Interface](#using-sql-interface)
- [Using REST API](#using-rest-api)
- [Best Practices](#best-practices)
- [Common Workflows](#common-workflows)
- [FAQ](#faq)

---

## Getting Started

### Accessing the System

The HCC Compression Advisor provides three interfaces:

1. **Streamlit Dashboard** (Recommended for most users)
   - URL: `https://localhost:8501`
   - Username: `admin`
   - Password: Set during installation

2. **SQL Interface** (For advanced users and automation)
   - Connect: `sqlplus COMPRESSION_MGR/<password>@<service_name>`
   - Execute PL/SQL procedures and queries directly

3. **REST API** (For application integration)
   - Base URL: `http://localhost:8080/ords/compression/v1/`
   - Requires ORDS installation

### First Login

1. Open your web browser and navigate to `https://localhost:8501`
2. Accept the self-signed certificate warning (for development installations)
3. Enter your credentials:
   - Username: `admin`
   - Password: Your configured dashboard password
4. Click **Login**

### Dashboard Navigation

The dashboard consists of 5 main pages accessible from the left sidebar:

- **📊 Analysis** - Trigger and monitor compression analysis
- **💡 Recommendations** - View and filter compression candidates
- **⚙️ Execution** - Execute compression operations
- **📈 History** - View execution timeline and analytics
- **🎯 Strategies** - Compare and manage compression strategies

---

## Dashboard Overview

### Page 1: Analysis

The Analysis page is your starting point for discovering compression opportunities.

#### Key Features

- **Quick Analysis** - Analyze all database objects with one click
- **Targeted Analysis** - Focus on specific schemas or tables
- **Strategy Selection** - Choose compression strategy (HIGH_PERFORMANCE, BALANCED, MAXIMUM_COMPRESSION)
- **Real-time Progress** - Monitor analysis status and progress
- **Summary Statistics** - View total objects, size, and potential savings

#### Using the Analysis Page

##### Quick Start - Analyze Everything

1. Navigate to **📊 Analysis** page
2. Select strategy from dropdown (default: BALANCED)
3. Leave **Schema** field empty to analyze all schemas
4. Click **Run Analysis** button
5. Wait for completion (progress bar shows status)

**Expected Result:**
```
✅ Analysis Completed Successfully
Total Objects Analyzed: 1,234
Total Size: 45.6 GB
Potential Savings: 12.3 GB (27%)
Analysis Duration: 3 minutes 42 seconds
```

##### Targeted Analysis - Specific Schema

1. Navigate to **📊 Analysis** page
2. Select strategy: **BALANCED**
3. Enter schema name: `HR` (or your schema)
4. Click **Run Analysis**

**SQL Equivalent:**
```sql
EXEC PKG_COMPRESSION_ADVISOR.run_analysis(
  p_owner => 'HR',
  p_strategy_id => 2  -- BALANCED
);
```

##### Targeted Analysis - Single Table

1. Navigate to **📊 Analysis** page
2. Select **Advanced Options**
3. Select strategy: **BALANCED**
4. Enter schema name: `SALES`
5. Enter table name: `ORDERS`
6. Click **Run Analysis**

**SQL Equivalent:**
```sql
EXEC PKG_COMPRESSION_ADVISOR.analyze_table(
  p_owner => 'SALES',
  p_table_name => 'ORDERS',
  p_strategy_id => 2
);
```

#### Understanding Analysis Results

After analysis completes, you'll see:

| Metric | Description | Example |
|--------|-------------|---------|
| **Total Objects** | Number of objects analyzed | 1,234 |
| **Total Size** | Current uncompressed size | 45.6 GB |
| **Compressible Objects** | Objects recommended for compression | 456 |
| **Potential Savings** | Estimated space savings | 12.3 GB |
| **Compression Ratio** | Average compression ratio | 2.7:1 |
| **Analysis Duration** | Time taken to analyze | 3m 42s |

#### Analysis Progress Indicators

- **🔄 In Progress** - Analysis is currently running
- **✅ Completed** - Analysis finished successfully
- **❌ Failed** - Analysis encountered an error
- **⚠️ Partial** - Some objects failed to analyze

---

### Page 2: Recommendations

The Recommendations page displays compression candidates ranked by potential savings.

#### Key Features

- **Smart Filtering** - Filter by schema, object type, size, savings
- **Sortable Columns** - Sort by any column (size, savings, ratio)
- **Detailed Rationale** - Understand why compression is recommended
- **Export Options** - Download recommendations as CSV
- **Batch Selection** - Select multiple objects for execution

#### Using the Recommendations Page

##### View All Recommendations

1. Navigate to **💡 Recommendations** page
2. Default view shows all recommendations sorted by potential savings
3. Scroll to view all candidates

##### Filter Recommendations

**By Schema:**
```
1. Click "Schema" dropdown
2. Select desired schema (e.g., "SALES")
3. View filtered results
```

**By Object Type:**
```
1. Click "Object Type" dropdown
2. Select type: TABLE, INDEX, LOB, IOT
3. View filtered results
```

**By Minimum Savings:**
```
1. Set "Minimum Savings (MB)" slider to 100
2. View only objects with >100MB potential savings
```

**By Compression Type:**
```
1. Click "Recommended Compression" dropdown
2. Select: BASIC, OLTP, or NOCOMPRESS
3. View filtered results
```

##### Understanding Recommendation Details

Each recommendation includes:

| Column | Description | Example |
|--------|-------------|---------|
| **Owner** | Schema name | SALES |
| **Object Name** | Table/Index name | ORDERS |
| **Object Type** | Type of object | TABLE |
| **Current Size** | Uncompressed size | 2,450 MB |
| **Potential Savings** | Space that can be saved | 1,225 MB |
| **Compression Type** | Recommended compression | OLTP |
| **Compression Ratio** | Expected ratio | 2.0:1 |
| **Hotness Score** | Access frequency (0-100) | 85 |
| **Rationale** | Why recommended | High read frequency, low DML activity |

##### Hotness Score Interpretation

| Score | Meaning | Recommendation |
|-------|---------|----------------|
| **80-100** | Very Hot | Use OLTP compression (fast access) |
| **50-79** | Warm | Use BASIC compression (balanced) |
| **0-49** | Cold | Use aggressive compression (max savings) |

##### Export Recommendations

1. Click **Export CSV** button
2. Choose location to save file
3. File includes all filtered recommendations

**CSV Format:**
```csv
OWNER,OBJECT_NAME,OBJECT_TYPE,CURRENT_SIZE_MB,SAVINGS_MB,COMPRESSION_TYPE,RATIO
SALES,ORDERS,TABLE,2450,1225,OLTP,2.0
SALES,ORDER_ITEMS,TABLE,1800,1080,OLTP,2.1
...
```

---

### Page 3: Execution

The Execution page allows you to compress database objects safely.

#### Key Features

- **Dry Run Mode** - Preview changes without executing
- **Online Compression** - Compress without downtime (when supported)
- **Batch Execution** - Compress multiple objects at once
- **Rollback Support** - Undo compression if needed
- **Real-time Status** - Monitor execution progress

#### Safety Features

⚠️ **Important Safety Measures:**
- Dry run mode is **enabled by default**
- Automatic backup before compression
- Validation checks before execution
- Rollback capability for 30 days
- Audit trail of all operations

#### Using the Execution Page

##### Dry Run - Preview Changes

1. Navigate to **⚙️ Execution** page
2. Select object from recommendations list
3. **Dry Run Mode** is checked by default
4. Click **Execute Compression**
5. Review preview of changes

**Expected Output:**
```
🔍 DRY RUN MODE - No changes made

Preview of changes:
─────────────────────────────────────────
Object: SALES.ORDERS (TABLE)
Current Size: 2,450 MB
Compression Type: OLTP
Expected Size: 1,225 MB
Expected Savings: 1,225 MB (50%)
Estimated Duration: 8 minutes

SQL Command:
ALTER TABLE SALES.ORDERS MOVE COMPRESS FOR OLTP ONLINE;

✅ Validation: PASSED
- Sufficient space available
- No active transactions detected
- Object is accessible
- User has required privileges
```

##### Execute Compression - Single Object

1. Navigate to **⚙️ Execution** page
2. Select object: `SALES.ORDERS`
3. **Uncheck** "Dry Run Mode"
4. Check "Online Compression" (if supported)
5. Click **Execute Compression**
6. Confirm execution in popup dialog

**Expected Output:**
```
⚙️ Executing Compression...

Object: SALES.ORDERS
Start Time: 2025-01-13 14:30:00
Status: IN PROGRESS (35%)
Estimated Completion: 14:38:00

[Progress Bar: ████████░░░░░░░░░░░░ 35%]

...

✅ Compression Completed Successfully

Object: SALES.ORDERS
Duration: 7 minutes 42 seconds
Original Size: 2,450 MB
New Size: 1,215 MB
Actual Savings: 1,235 MB (50.4%)
Compression Ratio: 2.02:1

Execution ID: 12345 (for rollback reference)
```

**SQL Equivalent:**
```sql
EXEC PKG_COMPRESSION_EXECUTOR.compress_table(
  p_owner => 'SALES',
  p_table_name => 'ORDERS',
  p_compression_type => 'OLTP',
  p_online => TRUE
);
```

##### Batch Execution - Multiple Objects

1. Navigate to **⚙️ Execution** page
2. Click **Batch Execution** tab
3. Set filters:
   - Minimum savings: 100 MB
   - Maximum size: 10 GB
   - Strategy: BALANCED
4. Set limits:
   - Max objects: 20
   - Max total size: 100 GB
5. Review selected objects
6. **Uncheck** "Dry Run Mode"
7. Click **Execute Batch**

**Expected Output:**
```
⚙️ Batch Execution Started

Total Objects: 20
Total Size: 45.6 GB
Expected Savings: 18.2 GB
Estimated Duration: 2 hours 15 minutes

Progress:
─────────────────────────────────────────
[  1/20] ✅ SALES.ORDERS          (1,235 MB saved)
[  2/20] ✅ SALES.ORDER_ITEMS     (856 MB saved)
[  3/20] ⚙️  HR.EMPLOYEES         (in progress...)
[  4/20] ⏳ HR.DEPARTMENTS        (pending)
...

Overall Progress: [███░░░░░░░░░░░░░░░░░ 15%]
```

**SQL Equivalent:**
```sql
EXEC PKG_COMPRESSION_EXECUTOR.execute_recommendations(
  p_strategy_id => 2,
  p_max_tables => 20,
  p_max_size_gb => 100
);
```

#### Online vs Offline Compression

| Feature | Online | Offline |
|---------|--------|---------|
| **Downtime** | No downtime | Table locked during compression |
| **Performance Impact** | Low | High |
| **Duration** | Longer | Faster |
| **Oracle Version** | 11g+ | All versions |
| **Use Case** | Production systems | Maintenance windows |

**Recommendation:** Always use online compression for production databases unless in a maintenance window.

#### Rollback Compression

If you need to undo compression:

1. Navigate to **⚙️ Execution** page
2. Click **Rollback** tab
3. Enter Execution ID (from execution output)
4. Click **Rollback Compression**
5. Confirm rollback

**Expected Output:**
```
⏮️ Rolling Back Compression...

Execution ID: 12345
Object: SALES.ORDERS
Original Compression: NONE
Current Compression: OLTP

Restoring to uncompressed state...

✅ Rollback Completed Successfully

Object: SALES.ORDERS
Status: Restored to original state
Size: 2,450 MB (uncompressed)
Duration: 5 minutes 12 seconds
```

**SQL Equivalent:**
```sql
EXEC PKG_COMPRESSION_EXECUTOR.rollback_compression(
  p_execution_id => 12345
);
```

---

### Page 4: History

The History page provides a complete audit trail of all compression operations.

#### Key Features

- **Execution Timeline** - Chronological view of all operations
- **Success Rate Metrics** - Track success/failure rates
- **Space Savings Analytics** - Cumulative savings over time
- **Performance Trends** - Compression ratio trends
- **Detailed Logs** - View full execution details

#### Using the History Page

##### View Execution History

1. Navigate to **📈 History** page
2. Default view shows last 30 days
3. Scroll to view all executions

##### Filter History

**By Date Range:**
```
1. Set "Start Date" picker: 2025-01-01
2. Set "End Date" picker: 2025-01-31
3. Click "Apply Filter"
```

**By Status:**
```
1. Select "Status" dropdown: SUCCESS, FAILED, or IN PROGRESS
2. View filtered results
```

**By Schema:**
```
1. Enter schema name: SALES
2. Click "Filter"
```

##### Understanding History Metrics

**Summary Metrics:**
```
Total Executions: 156
Successful: 142 (91%)
Failed: 8 (5%)
In Progress: 6 (4%)

Total Space Saved: 234.5 GB
Average Compression Ratio: 2.3:1
Total Objects Compressed: 1,234
```

**Execution Details:**

| Column | Description | Example |
|--------|-------------|---------|
| **Execution ID** | Unique identifier | 12345 |
| **Timestamp** | When executed | 2025-01-13 14:30:00 |
| **Object** | Schema.Table | SALES.ORDERS |
| **Operation** | Type of operation | COMPRESS |
| **Compression Type** | Applied compression | OLTP |
| **Duration** | Time taken | 7m 42s |
| **Savings** | Space saved | 1,235 MB |
| **Status** | Result | SUCCESS |

##### View Execution Details

1. Click on any execution row
2. View detailed information panel:

```
═══════════════════════════════════════════════════════════════
Execution Details - ID: 12345
═══════════════════════════════════════════════════════════════

Object Information:
  Owner: SALES
  Object Name: ORDERS
  Object Type: TABLE
  Partition: (none)

Compression Details:
  Previous Compression: NONE
  New Compression: OLTP
  Strategy Used: BALANCED (ID: 2)

Size Information:
  Original Size: 2,450 MB
  Compressed Size: 1,215 MB
  Space Saved: 1,235 MB (50.4%)
  Compression Ratio: 2.02:1

Execution Information:
  Start Time: 2025-01-13 14:30:00
  End Time: 2025-01-13 14:37:42
  Duration: 7 minutes 42 seconds
  Online Mode: Yes
  Dry Run: No

Performance Metrics:
  Rows Processed: 12,456,789
  Rows/Second: 26,923
  MB/Second: 5.3 MB/s

Status: ✅ SUCCESS

SQL Executed:
  ALTER TABLE SALES.ORDERS MOVE COMPRESS FOR OLTP ONLINE;

Rollback Available: Yes (until 2025-02-12)
Rollback Command:
  EXEC PKG_COMPRESSION_EXECUTOR.rollback_compression(12345);
```

##### Export History

1. Click **Export History** button
2. Select format: CSV or JSON
3. Choose date range
4. Download file

**CSV Format:**
```csv
EXECUTION_ID,TIMESTAMP,OWNER,OBJECT_NAME,OPERATION,COMPRESSION,DURATION,SAVINGS_MB,STATUS
12345,2025-01-13 14:30:00,SALES,ORDERS,COMPRESS,OLTP,462,1235,SUCCESS
12344,2025-01-13 13:15:00,SALES,ORDER_ITEMS,COMPRESS,OLTP,325,856,SUCCESS
...
```

---

### Page 5: Strategies

The Strategies page allows you to compare, customize, and manage compression strategies.

#### Key Features

- **Strategy Comparison** - Side-by-side comparison of all strategies
- **Rule Customization** - Modify thresholds and rules
- **Performance Metrics** - View strategy effectiveness
- **Create Custom Strategies** - Define your own compression logic

#### Using the Strategies Page

##### Compare Strategies

1. Navigate to **🎯 Strategies** page
2. View comparison table:

```
═══════════════════════════════════════════════════════════════════════════════
Strategy Comparison
═══════════════════════════════════════════════════════════════════════════════

| Attribute            | HIGH_PERFORMANCE | BALANCED      | MAXIMUM_COMPRESSION |
|----------------------|------------------|---------------|---------------------|
| Strategy ID          | 1                | 2             | 3                   |
| Primary Goal         | Minimal overhead | Balance       | Maximum savings     |
| Hot Data (80-100)    | OLTP             | OLTP          | OLTP                |
| Warm Data (50-79)    | NOCOMPRESS       | BASIC         | OLTP                |
| Cold Data (0-49)     | NOCOMPRESS       | BASIC         | BASIC               |
| Index Compression    | ADVANCED LOW     | ADVANCED LOW  | ADVANCED HIGH       |
| LOB Compression      | NOCOMPRESS       | BASIC         | HIGH                |
| Min Object Size      | 100 MB           | 50 MB         | 10 MB               |
| DML Threshold        | High             | Medium        | Low                 |
| Best For             | OLTP systems     | Mixed workload| Data warehouses     |
| Expected Ratio       | 1.5:1            | 2.0:1         | 3.0:1               |
| Performance Impact   | Minimal (2-5%)   | Low (5-10%)   | Moderate (10-20%)   |
```

##### View Strategy Rules

1. Click on strategy name (e.g., **BALANCED**)
2. View detailed rules:

```
═══════════════════════════════════════════════════════════════
Strategy: BALANCED (ID: 2)
═══════════════════════════════════════════════════════════════

Description:
  Optimal balance between space savings and performance.
  Recommended for general-purpose databases with mixed workloads.

Active: ✅ Yes

Rules:
──────────────────────────────────────────────────────────────

1. Table Compression - Hot Data (Hotness >= 80)
   Rule Type: TABLE_HOT
   Object Type: TABLE
   Compression: OLTP
   Threshold: 80
   Priority: 1

2. Table Compression - Warm Data (50 <= Hotness < 80)
   Rule Type: TABLE_WARM
   Object Type: TABLE
   Compression: BASIC
   Threshold: 50
   Priority: 2

3. Table Compression - Cold Data (Hotness < 50)
   Rule Type: TABLE_COLD
   Object Type: TABLE
   Compression: BASIC
   Threshold: 0
   Priority: 3

4. Index Compression
   Rule Type: INDEX
   Object Type: INDEX
   Compression: ADVANCED LOW
   Threshold: N/A
   Priority: 4

5. LOB Compression
   Rule Type: LOB
   Object Type: LOB
   Compression: BASIC
   Threshold: N/A
   Priority: 5

6. Minimum Size Threshold
   Rule Type: SIZE_THRESHOLD
   Min Size: 50 MB
   Priority: 10
```

##### Customize Strategy Rules

1. Click **Edit Strategy** button
2. Modify rule parameters:

**Example: Change minimum size threshold**
```
1. Find "Minimum Size Threshold" rule
2. Change "Min Size" from 50 MB to 100 MB
3. Click "Save Changes"
```

**SQL Equivalent:**
```sql
UPDATE COMPRESSION_STRATEGY_RULES
SET threshold_value = 100
WHERE strategy_id = 2
  AND rule_type = 'SIZE_THRESHOLD';

COMMIT;
```

##### Create Custom Strategy

1. Click **Create New Strategy** button
2. Fill in strategy details:

```
Strategy Name: CUSTOM_ARCHIVE
Description: Custom strategy for archival data
Active: Yes

Rules:
──────────────────────────────────────────────────────────────
1. Hot Tables: BASIC (less aggressive for active archives)
2. Warm Tables: BASIC
3. Cold Tables: BASIC (Oracle 23c Free doesn't support HCC)
4. Indexes: ADVANCED HIGH
5. LOBs: HIGH
6. Min Size: 10 MB
```

3. Click **Create Strategy**

**SQL Equivalent:**
```sql
-- Insert strategy
INSERT INTO COMPRESSION_STRATEGIES (
  strategy_id, strategy_name, description, is_active
) VALUES (
  4, 'CUSTOM_ARCHIVE', 'Custom strategy for archival data', 1
);

-- Insert rules
INSERT INTO COMPRESSION_STRATEGY_RULES (
  rule_id, strategy_id, object_type, rule_type,
  compression_type, threshold_value, priority, is_active
) VALUES (
  SEQ_STRATEGY_RULES.NEXTVAL, 4, 'TABLE', 'TABLE_HOT',
  'BASIC', 80, 1, 1
);
-- (repeat for other rules)

COMMIT;
```

##### Test Strategy

1. Select your custom strategy
2. Click **Test Strategy** button
3. View simulation results:

```
═══════════════════════════════════════════════════════════════
Strategy Test Results: CUSTOM_ARCHIVE
═══════════════════════════════════════════════════════════════

Simulation based on current database objects:

Objects Analyzed: 1,234
Objects Recommended for Compression: 892 (72%)

Breakdown by Compression Type:
  BASIC: 756 objects (85%)
  OLTP: 89 objects (10%)
  ADVANCED HIGH (Indexes): 47 objects (5%)

Expected Savings:
  Current Total Size: 45.6 GB
  Expected Size After Compression: 16.2 GB
  Total Savings: 29.4 GB (64%)
  Average Compression Ratio: 2.8:1

Performance Impact Estimate:
  Read Performance: -5% to +2% (varies by workload)
  Write Performance: -10% to -5%
  Overall: Acceptable for archival workloads

Recommendation: ✅ Strategy is well-configured for archival data
```

---

## Using SQL Interface

For automation, scripting, and advanced users, the SQL interface provides full control.

### Connecting to Database

```bash
# Using SQL*Plus
sqlplus COMPRESSION_MGR/<password>@<service_name>

# Using SQLcl
sql COMPRESSION_MGR/<password>@<service_name>

# Using SQL Developer
# Host: localhost
# Port: 1521
# Service: FREEPDB1
# User: COMPRESSION_MGR
```

### Common SQL Operations

#### Run Analysis

```sql
-- Analyze all objects with BALANCED strategy
EXEC PKG_COMPRESSION_ADVISOR.run_analysis(
  p_owner => NULL,
  p_strategy_id => 2
);

-- Analyze specific schema
EXEC PKG_COMPRESSION_ADVISOR.run_analysis(
  p_owner => 'SALES',
  p_strategy_id => 2
);

-- Analyze specific table
EXEC PKG_COMPRESSION_ADVISOR.analyze_table(
  p_owner => 'SALES',
  p_table_name => 'ORDERS',
  p_strategy_id => 2
);
```

#### View Recommendations

```sql
-- Top 20 compression candidates
SELECT owner, object_name, object_type,
       current_size_mb, potential_savings_mb,
       advisable_compression, compression_ratio,
       hotness_score, rationale
FROM V_COMPRESSION_CANDIDATES
WHERE ROWNUM <= 20
ORDER BY potential_savings_mb DESC;

-- Recommendations for specific schema
SELECT object_name, current_size_mb, potential_savings_mb,
       advisable_compression
FROM V_COMPRESSION_CANDIDATES
WHERE owner = 'SALES'
ORDER BY potential_savings_mb DESC;

-- Filter by minimum savings
SELECT owner, object_name, potential_savings_mb,
       advisable_compression
FROM V_COMPRESSION_CANDIDATES
WHERE potential_savings_mb >= 100
ORDER BY potential_savings_mb DESC;
```

#### Execute Compression

```sql
-- Compress single table (online)
EXEC PKG_COMPRESSION_EXECUTOR.compress_table(
  p_owner => 'SALES',
  p_table_name => 'ORDERS',
  p_compression_type => 'OLTP',
  p_online => TRUE
);

-- Batch execute top recommendations
EXEC PKG_COMPRESSION_EXECUTOR.execute_recommendations(
  p_strategy_id => 2,
  p_max_tables => 10,
  p_max_size_gb => 50
);

-- Compress index
EXEC PKG_COMPRESSION_EXECUTOR.compress_index(
  p_owner => 'SALES',
  p_index_name => 'ORDERS_PK',
  p_compression_type => 'ADVANCED LOW'
);
```

#### View History

```sql
-- Recent executions
SELECT execution_id, execution_date,
       owner || '.' || object_name as object,
       operation_type, compression_type,
       ROUND((end_time - start_time) * 24 * 60, 2) as duration_minutes,
       size_before_mb, size_after_mb,
       size_before_mb - size_after_mb as savings_mb,
       status
FROM COMPRESSION_EXECUTION_LOG
WHERE execution_date >= SYSDATE - 7
ORDER BY execution_date DESC;

-- Success rate by schema
SELECT owner,
       COUNT(*) as total_executions,
       SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) as successful,
       ROUND(SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as success_rate_pct,
       ROUND(SUM(size_before_mb - size_after_mb), 2) as total_savings_mb
FROM COMPRESSION_EXECUTION_LOG
GROUP BY owner
ORDER BY total_savings_mb DESC;
```

#### Rollback Compression

```sql
-- Rollback specific execution
EXEC PKG_COMPRESSION_EXECUTOR.rollback_compression(
  p_execution_id => 12345
);

-- View rollback history
SELECT execution_id, rollback_date, status, notes
FROM COMPRESSION_ROLLBACK_LOG
ORDER BY rollback_date DESC;
```

---

## Using REST API

For application integration, use the ORDS REST API (requires ORDS installation).

### API Base URL

```
http://localhost:8080/ords/compression/compression/v1/
```

### Authentication

Currently, the API does not require authentication (development mode). For production, configure ORDS authentication.

### API Endpoints

#### Trigger Analysis

```bash
# Analyze all objects
curl -X POST http://localhost:8080/ords/compression/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_id": 2
  }'

# Response:
{
  "status": "success",
  "message": "Analysis completed",
  "objects_analyzed": 1234,
  "recommendations_generated": 456,
  "analysis_id": 789
}
```

#### Get Recommendations

```bash
# Get all recommendations
curl -X GET http://localhost:8080/ords/compression/v1/recommendations

# Response:
{
  "items": [
    {
      "owner": "SALES",
      "object_name": "ORDERS",
      "object_type": "TABLE",
      "current_size_mb": 2450,
      "potential_savings_mb": 1225,
      "compression_type": "OLTP",
      "compression_ratio": 2.0,
      "hotness_score": 85
    },
    ...
  ],
  "count": 456,
  "hasMore": true
}

# Filter by schema
curl -X GET "http://localhost:8080/ords/compression/v1/recommendations?owner=SALES"

# Filter by minimum savings
curl -X GET "http://localhost:8080/ords/compression/v1/recommendations?min_savings=100"
```

#### Execute Compression

```bash
# Compress single object
curl -X POST http://localhost:8080/ords/compression/v1/execute \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "SALES",
    "object_name": "ORDERS",
    "compression_type": "OLTP",
    "online": true
  }'

# Response:
{
  "status": "success",
  "execution_id": 12345,
  "message": "Compression completed",
  "duration_seconds": 462,
  "size_before_mb": 2450,
  "size_after_mb": 1215,
  "savings_mb": 1235
}
```

#### Get Execution History

```bash
# Recent history
curl -X GET http://localhost:8080/ords/compression/v1/history?limit=10

# Response:
{
  "items": [
    {
      "execution_id": 12345,
      "timestamp": "2025-01-13T14:30:00Z",
      "owner": "SALES",
      "object_name": "ORDERS",
      "operation": "COMPRESS",
      "compression_type": "OLTP",
      "duration_seconds": 462,
      "savings_mb": 1235,
      "status": "SUCCESS"
    },
    ...
  ],
  "count": 10
}
```

#### Get Summary Metrics

```bash
curl -X GET http://localhost:8080/ords/compression/v1/summary

# Response:
{
  "total_objects": 1234,
  "total_size_mb": 45600,
  "compressed_objects": 456,
  "compressed_size_mb": 27360,
  "total_savings_mb": 18240,
  "average_compression_ratio": 2.3,
  "last_analysis_date": "2025-01-13T14:30:00Z"
}
```

For complete API documentation, see [API_REFERENCE.md](API_REFERENCE.md).

---

## Best Practices

### 1. Analysis Best Practices

- **Schedule Regular Analysis** - Run analysis weekly or monthly
- **Start with BALANCED Strategy** - Good for most workloads
- **Analyze During Off-Peak Hours** - Reduces impact on production
- **Focus on Large Objects First** - Maximum savings with minimum effort
- **Review Recommendations Before Executing** - Understand impact

### 2. Execution Best Practices

- **Always Use Dry Run First** - Preview changes before executing
- **Use Online Compression** - Avoid downtime in production
- **Execute in Batches** - Don't compress everything at once
- **Monitor Performance** - Watch for query performance changes
- **Keep Rollback Window** - Don't purge execution history too soon

### 3. Strategy Best Practices

- **Match Strategy to Workload:**
  - OLTP systems → HIGH_PERFORMANCE
  - Mixed workloads → BALANCED
  - Data warehouses → MAXIMUM_COMPRESSION

- **Customize for Your Environment:**
  - Adjust thresholds based on your data patterns
  - Create custom strategies for specific schemas
  - Test strategies before deploying

- **Monitor Effectiveness:**
  - Track compression ratios over time
  - Measure performance impact
  - Adjust strategies as workload changes

### 4. Maintenance Best Practices

- **Gather Statistics After Compression** - Ensures optimal query plans
- **Monitor Index Health** - Rebuild indexes if needed
- **Review Space Reclamation** - Ensure space is actually freed
- **Document Changes** - Keep notes on why objects were compressed
- **Test Before Production** - Validate in development first

---

## Common Workflows

### Workflow 1: Initial Database Assessment

**Goal:** Understand compression opportunities in your database

```
1. Run full analysis with BALANCED strategy
   └─> Dashboard → Analysis → Run Analysis (all schemas)

2. Review recommendations
   └─> Dashboard → Recommendations → Sort by savings

3. Identify top candidates
   └─> Filter: Minimum savings 500MB

4. Export recommendations
   └─> Download CSV for review

5. Present findings to stakeholders
   └─> Use summary metrics and savings projections
```

### Workflow 2: Compress Large Tables

**Goal:** Compress a few large tables to free up space quickly

```
1. Identify largest uncompressed tables
   └─> SQL: SELECT * FROM V_COMPRESSION_CANDIDATES
            WHERE object_type = 'TABLE'
            ORDER BY current_size_mb DESC
            FETCH FIRST 10 ROWS ONLY;

2. Test compression on one table
   └─> Dashboard → Execution → Select table → Dry Run

3. Execute compression (online mode)
   └─> Dashboard → Execution → Uncheck Dry Run → Execute

4. Monitor progress
   └─> Watch progress bar and metrics

5. Verify results
   └─> Dashboard → History → View execution details

6. Gather statistics
   └─> SQL: EXEC DBMS_STATS.GATHER_TABLE_STATS(
                  'SALES', 'ORDERS', CASCADE => TRUE);

7. Repeat for remaining tables
   └─> Continue with next largest table
```

### Workflow 3: Schema-Wide Compression

**Goal:** Compress all objects in a schema

```
1. Run targeted analysis
   └─> Dashboard → Analysis → Enter schema name → Run

2. Review all recommendations for schema
   └─> Dashboard → Recommendations → Filter by schema

3. Execute batch compression
   └─> Dashboard → Execution → Batch tab
       ├─> Set filters (schema = SALES)
       ├─> Set limits (max 50 objects)
       └─> Execute

4. Monitor batch progress
   └─> Watch real-time status updates

5. Review results
   └─> Dashboard → History → Filter by schema

6. Handle any failures
   └─> Review error messages
   └─> Re-attempt failed objects manually
```

### Workflow 4: Ongoing Compression Management

**Goal:** Maintain optimal compression over time

```
1. Schedule weekly analysis
   └─> SQL: DBMS_SCHEDULER job (see installation guide)

2. Review new recommendations weekly
   └─> Dashboard → Recommendations → Filter by date

3. Compress new candidates monthly
   └─> Dashboard → Execution → Batch execute

4. Monitor compression effectiveness
   └─> Dashboard → History → View trends

5. Adjust strategies as needed
   └─> Dashboard → Strategies → Customize rules

6. Generate monthly reports
   └─> Export history and recommendations
```

### Workflow 5: Rollback and Recovery

**Goal:** Undo compression if issues arise

```
1. Identify problematic object
   └─> Dashboard → History → Find execution

2. Note execution ID
   └─> Click on execution for details

3. Execute rollback
   └─> Dashboard → Execution → Rollback tab
       └─> Enter execution ID → Rollback

4. Verify object restored
   └─> SQL: SELECT compression FROM user_tables
            WHERE table_name = 'ORDERS';

5. Investigate why compression caused issues
   └─> Review query performance metrics
   └─> Check for query plan changes

6. Adjust strategy or avoid compressing this object
   └─> Update strategy rules or exclude object
```

---

## FAQ

### General Questions

**Q: What is database compression?**
A: Database compression reduces the storage space required for database objects (tables, indexes) by encoding data more efficiently. Oracle supports several compression types with different trade-offs between space savings and performance.

**Q: Will compression slow down my database?**
A: It depends on the compression type and workload:
- **OLTP compression**: Minimal impact (2-5% on writes), often faster reads
- **BASIC compression**: Low impact (5-10% on writes)
- **Query/Archive compression** (Exadata only): Higher impact, best for read-mostly data

**Q: How much space can I save?**
A: Typical compression ratios:
- **OLTP**: 1.5-2.5x (40-60% savings)
- **BASIC**: 2-3x (50-65% savings)
- **HCC Query** (Exadata): 3-10x (70-90% savings)
- **HCC Archive** (Exadata): 10-50x (90-98% savings)

Actual results vary based on data characteristics.

**Q: Is compression reversible?**
A: Yes, you can uncompress objects by altering them to NOCOMPRESS. The system provides rollback functionality for 30 days after compression.

### Strategy Questions

**Q: Which strategy should I use?**
A:
- **HIGH_PERFORMANCE**: OLTP systems where performance is critical
- **BALANCED**: General-purpose databases (recommended default)
- **MAXIMUM_COMPRESSION**: Data warehouses, archives, read-mostly data

**Q: Can I create my own strategy?**
A: Yes, use the Strategies page to create custom strategies with your own rules and thresholds.

**Q: How often should I run analysis?**
A:
- Active databases: Weekly
- Growing databases: Every 2 weeks
- Stable databases: Monthly
- Data warehouses: After bulk loads

### Technical Questions

**Q: Does Oracle 23c Free support HCC?**
A: No, HCC (Hybrid Columnar Compression) is only available on Exadata. Oracle 23c Free supports BASIC and OLTP compression for tables, and ADVANCED LOW/HIGH for indexes.

**Q: What is online compression?**
A: Online compression allows you to compress tables without locking them, using `ALTER TABLE ... MOVE ONLINE`. Requires Oracle 11g+ and may have licensing implications.

**Q: Do I need to gather statistics after compression?**
A: Yes, always gather statistics after compression:
```sql
EXEC DBMS_STATS.GATHER_TABLE_STATS(
  ownname => 'SCHEMA',
  tabname => 'TABLE_NAME',
  cascade => TRUE
);
```

**Q: What happens to indexes when I compress a table?**
A: When you move a table (compress it), indexes become UNUSABLE and must be rebuilt:
```sql
ALTER INDEX schema.index_name REBUILD ONLINE;
```
The system automatically handles this for you.

**Q: Can I compress partitioned tables?**
A: Yes, you can compress entire partitioned tables or individual partitions. The advisor analyzes partitions separately and can recommend different compression for each.

### Troubleshooting Questions

**Q: Why is analysis taking so long?**
A: Large databases with many objects can take hours. Solutions:
- Analyze specific schemas instead of all schemas
- Run analysis during off-peak hours
- Exclude very large objects initially

**Q: Why didn't compression save as much space as predicted?**
A: Estimates are based on sampling. Actual results may vary due to:
- Data distribution differences
- Block fragmentation
- LOB storage overhead
- Index rebuilds

**Q: What if compression fails?**
A: Check the error message in the History page. Common causes:
- Insufficient tablespace space
- Active transactions on the object
- Missing privileges
- Unsupported data types (e.g., nested tables)

**Q: Can I compress system schemas?**
A: Not recommended. Avoid compressing:
- SYS
- SYSTEM
- SYSAUX
- Oracle-owned schemas

Focus on application schemas only.

### Performance Questions

**Q: How do I monitor performance impact?**
A: Compare query performance before/after compression:
```sql
-- Before compression
SELECT /*+ GATHER_PLAN_STATISTICS */ ...

-- After compression
SELECT /*+ GATHER_PLAN_STATISTICS */ ...

-- Compare execution plans
SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY_CURSOR(FORMAT=>'ALLSTATS LAST'));
```

**Q: Should I compress all tables?**
A: No, some tables should not be compressed:
- Very small tables (<10MB)
- Extremely high DML tables (>80% writes)
- Tables with unsupported data types
- System tables

**Q: Does compression help query performance?**
A: Sometimes:
- **Reads**: Often faster due to less I/O (fewer blocks to read)
- **Writes**: Slightly slower (compression overhead)
- **Full scans**: Usually faster (less data to scan)
- **Index lookups**: Minimal impact

---

## Additional Resources

- **[Installation Guide](INSTALLATION.md)** - Complete setup instructions
- **[Strategy Guide](STRATEGY_GUIDE.md)** - Detailed strategy information
- **[API Reference](API_REFERENCE.md)** - REST API documentation
- **[Oracle Documentation](https://docs.oracle.com/en/database/)** - Official Oracle docs

---

For questions or issues, please review this guide and consult the troubleshooting sections. If problems persist, check the system logs and contact your database administrator.
