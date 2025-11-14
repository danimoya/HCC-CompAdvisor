# HCC Compression Advisor - API Reference

## Table of Contents
1. [PL/SQL Package APIs](#plsql-package-apis)
2. [REST API Endpoints](#rest-api-endpoints)
3. [Database Views](#database-views)
4. [Data Structures](#data-structures)
5. [Error Codes](#error-codes)

## PL/SQL Package APIs

### PKG_COMPRESSION_ANALYZER

Package for analyzing database objects and generating compression recommendations.

#### ANALYZE_ALL_TABLES

Analyzes all user tables in the database or specific schema.

**Signature**:
```sql
PROCEDURE ANALYZE_ALL_TABLES(
    p_schema_filter   IN VARCHAR2 DEFAULT NULL,
    p_parallel_degree IN NUMBER DEFAULT 4
);
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| p_schema_filter | VARCHAR2 | No | Schema name to analyze (NULL = all user schemas) |
| p_parallel_degree | NUMBER | No | Degree of parallelism (default: 4) |

**Usage Example**:
```sql
-- Analyze all user tables
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES;

-- Analyze specific schema with 8-way parallel
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES('SALES', 8);
```

**Exceptions**:
- `E_ANALYSIS_FAILED`: Analysis failed for critical tables
- `E_INSUFFICIENT_PRIVILEGES`: Missing required privileges

---

#### ANALYZE_SPECIFIC_TABLE

Analyzes a single table and its partitions.

**Signature**:
```sql
PROCEDURE ANALYZE_SPECIFIC_TABLE(
    p_owner              IN VARCHAR2,
    p_table_name         IN VARCHAR2,
    p_include_partitions IN BOOLEAN DEFAULT TRUE
);
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| p_owner | VARCHAR2 | Yes | Table owner |
| p_table_name | VARCHAR2 | Yes | Table name |
| p_include_partitions | BOOLEAN | No | Include partition analysis (default: TRUE) |

**Usage Example**:
```sql
-- Analyze table with all partitions
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_SPECIFIC_TABLE('HR', 'EMPLOYEES', TRUE);

-- Analyze only the base table
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_SPECIFIC_TABLE('SALES', 'ORDERS', FALSE);
```

**Returns**: No return value; results stored in COMPRESSION_ANALYSIS table

---

#### REFRESH_ANALYSIS

Updates stale analysis results.

**Signature**:
```sql
PROCEDURE REFRESH_ANALYSIS(
    p_days_old IN NUMBER DEFAULT 7
);
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| p_days_old | NUMBER | No | Refresh analysis older than N days (default: 7) |

**Usage Example**:
```sql
-- Refresh analysis older than 7 days
EXEC PKG_COMPRESSION_ANALYZER.REFRESH_ANALYSIS;

-- Refresh analysis older than 30 days
EXEC PKG_COMPRESSION_ANALYZER.REFRESH_ANALYSIS(30);
```

---

#### GET_RECOMMENDATIONS

Returns compression recommendations as pipelined table function.

**Signature**:
```sql
FUNCTION GET_RECOMMENDATIONS(
    p_compression_threshold IN NUMBER DEFAULT 1.5,
    p_min_size_mb          IN NUMBER DEFAULT 100
) RETURN t_recommendation_list PIPELINED;
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| p_compression_threshold | NUMBER | No | Minimum compression ratio (default: 1.5) |
| p_min_size_mb | NUMBER | No | Minimum table size in MB (default: 100) |

**Return Type**: `t_recommendation_list` - Table of `t_compression_recommendation`

**Usage Example**:
```sql
-- Get recommendations with default thresholds
SELECT * FROM TABLE(PKG_COMPRESSION_ANALYZER.GET_RECOMMENDATIONS());

-- Get recommendations for tables > 500 MB with ratio > 2.0
SELECT * FROM TABLE(PKG_COMPRESSION_ANALYZER.GET_RECOMMENDATIONS(2.0, 500))
ORDER BY estimated_savings_mb DESC;
```

**Return Columns**:
- `owner` (VARCHAR2): Object owner
- `table_name` (VARCHAR2): Table name
- `advisable_compression` (VARCHAR2): Recommended compression type
- `estimated_savings_mb` (NUMBER): Projected space savings in MB
- `hot_score` (NUMBER): Activity score (0-100)

---

#### CALCULATE_HOT_SCORE

Calculates activity score for an object.

**Signature**:
```sql
FUNCTION CALCULATE_HOT_SCORE(
    p_inserts         IN NUMBER,
    p_updates         IN NUMBER,
    p_deletes         IN NUMBER,
    p_segment_size_mb IN NUMBER
) RETURN NUMBER;
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| p_inserts | NUMBER | Yes | Insert count |
| p_updates | NUMBER | Yes | Update count |
| p_deletes | NUMBER | Yes | Delete count |
| p_segment_size_mb | NUMBER | Yes | Segment size in MB |

**Returns**: NUMBER - Hotness score (0-100)

**Usage Example**:
```sql
SELECT PKG_COMPRESSION_ANALYZER.CALCULATE_HOT_SCORE(10000, 5000, 2000, 1024)
FROM DUAL;
-- Returns activity score based on DML operations
```

**Score Interpretation**:
- 0-20: Cold
- 21-40: Warm
- 41-70: Active
- 71-100: Hot

---

### PKG_COMPRESSION_EXECUTOR

Package for executing compression operations.

#### COMPRESS_TABLE

Compresses a single table.

**Signature**:
```sql
PROCEDURE COMPRESS_TABLE(
    p_owner            IN VARCHAR2,
    p_table_name       IN VARCHAR2,
    p_compression_type IN VARCHAR2 DEFAULT NULL,
    p_online           IN BOOLEAN DEFAULT TRUE,
    p_log_operation    IN BOOLEAN DEFAULT TRUE
);
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| p_owner | VARCHAR2 | Yes | Table owner |
| p_table_name | VARCHAR2 | Yes | Table name |
| p_compression_type | VARCHAR2 | No | Compression type (NULL = use recommendation) |
| p_online | BOOLEAN | No | Online operation (default: TRUE) |
| p_log_operation | BOOLEAN | No | Log to history (default: TRUE) |

**Compression Types**:
- `OLTP` - Row store compress advanced
- `QUERY LOW` - HCC query low
- `QUERY HIGH` - HCC query high
- `ARCHIVE LOW` - HCC archive low
- `ARCHIVE HIGH` - HCC archive high

**Usage Example**:
```sql
-- Use recommended compression (online)
EXEC PKG_COMPRESSION_EXECUTOR.COMPRESS_TABLE('SALES', 'ORDERS');

-- Force specific compression (offline)
EXEC PKG_COMPRESSION_EXECUTOR.COMPRESS_TABLE(
    p_owner => 'SALES',
    p_table_name => 'BIG_TABLE',
    p_compression_type => 'ARCHIVE HIGH',
    p_online => FALSE
);
```

**Exceptions**:
- `E_COMPRESSION_FAILED`: Compression operation failed
- `E_INVALID_OBJECT`: Table does not exist

---

#### COMPRESS_PARTITION

Compresses a table partition.

**Signature**:
```sql
PROCEDURE COMPRESS_PARTITION(
    p_owner            IN VARCHAR2,
    p_table_name       IN VARCHAR2,
    p_partition_name   IN VARCHAR2,
    p_compression_type IN VARCHAR2,
    p_online           IN BOOLEAN DEFAULT TRUE
);
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| p_owner | VARCHAR2 | Yes | Table owner |
| p_table_name | VARCHAR2 | Yes | Table name |
| p_partition_name | VARCHAR2 | Yes | Partition name |
| p_compression_type | VARCHAR2 | Yes | Compression type |
| p_online | BOOLEAN | No | Online operation (default: TRUE) |

**Usage Example**:
```sql
EXEC PKG_COMPRESSION_EXECUTOR.COMPRESS_PARTITION(
    p_owner => 'SALES',
    p_table_name => 'SALES_DATA',
    p_partition_name => 'P_2023_Q4',
    p_compression_type => 'QUERY HIGH'
);
```

---

#### EXECUTE_RECOMMENDATIONS

Executes compression for top recommended tables.

**Signature**:
```sql
PROCEDURE EXECUTE_RECOMMENDATIONS(
    p_max_tables  IN NUMBER DEFAULT 10,
    p_max_size_gb IN NUMBER DEFAULT 100
);
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| p_max_tables | NUMBER | No | Maximum tables to compress (default: 10) |
| p_max_size_gb | NUMBER | No | Maximum total size in GB (default: 100) |

**Usage Example**:
```sql
-- Compress top 10 tables
EXEC PKG_COMPRESSION_EXECUTOR.EXECUTE_RECOMMENDATIONS;

-- Compress up to 50 tables, max 500 GB total
EXEC PKG_COMPRESSION_EXECUTOR.EXECUTE_RECOMMENDATIONS(50, 500);
```

---

#### COMPRESS_COLD_TABLES

Compresses tables with low activity.

**Signature**:
```sql
PROCEDURE COMPRESS_COLD_TABLES(
    p_days_inactive    IN NUMBER DEFAULT 90,
    p_compression_type IN VARCHAR2 DEFAULT 'ARCHIVE HIGH'
);
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| p_days_inactive | NUMBER | No | Days of inactivity (default: 90) |
| p_compression_type | VARCHAR2 | No | Compression type (default: 'ARCHIVE HIGH') |

**Usage Example**:
```sql
-- Compress tables inactive for 90 days
EXEC PKG_COMPRESSION_EXECUTOR.COMPRESS_COLD_TABLES;

-- Compress tables inactive for 180 days with Archive Low
EXEC PKG_COMPRESSION_EXECUTOR.COMPRESS_COLD_TABLES(180, 'ARCHIVE LOW');
```

---

#### ROLLBACK_COMPRESSION

Reverses a compression operation.

**Signature**:
```sql
PROCEDURE ROLLBACK_COMPRESSION(
    p_operation_id IN NUMBER
);
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| p_operation_id | NUMBER | Yes | Operation ID from COMPRESSION_HISTORY |

**Usage Example**:
```sql
-- Find operation ID
SELECT operation_id, owner, object_name, compression_type_applied
FROM COMPRESSION_HISTORY
WHERE owner = 'SALES' AND object_name = 'ORDERS'
ORDER BY start_time DESC
FETCH FIRST 1 ROW ONLY;

-- Rollback compression
EXEC PKG_COMPRESSION_EXECUTOR.ROLLBACK_COMPRESSION(12345);
```

---

#### GET_SPACE_SAVINGS

Returns total space savings for a schema.

**Signature**:
```sql
FUNCTION GET_SPACE_SAVINGS(
    p_owner     IN VARCHAR2 DEFAULT NULL,
    p_days_back IN NUMBER DEFAULT 30
) RETURN NUMBER;
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| p_owner | VARCHAR2 | No | Schema name (NULL = all schemas) |
| p_days_back | NUMBER | No | Days to look back (default: 30) |

**Returns**: NUMBER - Total space saved in MB

**Usage Example**:
```sql
-- Total savings across all schemas (last 30 days)
SELECT PKG_COMPRESSION_EXECUTOR.GET_SPACE_SAVINGS() AS total_savings_mb
FROM DUAL;

-- Savings for specific schema (last 90 days)
SELECT PKG_COMPRESSION_EXECUTOR.GET_SPACE_SAVINGS('SALES', 90) AS savings_mb
FROM DUAL;
```

---

## REST API Endpoints

All ORDS endpoints are available at: `https://<host>:<port>/ords/compression/v1/`

### POST /advisor/tables

Run compression analysis for all tables.

**Request**:
```bash
curl -X POST https://example.com/ords/compression/v1/advisor/tables \
  -H "Content-Type: application/json"
```

**Response**:
```json
{
  "status": "OK",
  "run_id": 12345,
  "message": "Analysis initiated"
}
```

---

### GET /analysis/:owner/:table

Get analysis results for specific table.

**Request**:
```bash
curl -X GET https://example.com/ords/compression/v1/analysis/SALES/ORDERS
```

**Response**:
```json
{
  "items": [{
    "owner": "SALES",
    "table_name": "ORDERS",
    "object_type": "TABLE",
    "oltp_ratio": 2.5,
    "query_low_ratio": 4.2,
    "query_high_ratio": 6.8,
    "archive_low_ratio": 8.5,
    "archive_high_ratio": 12.3,
    "hot_score": 45.2,
    "advisable_compression": "QUERY LOW",
    "estimated_savings_mb": 2450.5,
    "analysis_date": "2025-01-13T10:30:00Z"
  }]
}
```

---

### POST /execute

Execute compression on a table.

**Request**:
```bash
curl -X POST https://example.com/ords/compression/v1/execute \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "SALES",
    "table_name": "ORDERS",
    "compression_type": "QUERY LOW"
  }'
```

**Response**:
```json
{
  "status": "OK",
  "operation_id": 67890,
  "message": "Compression initiated successfully"
}
```

---

### GET /recommendations

Get compression recommendations.

**Request**:
```bash
curl -X GET "https://example.com/ords/compression/v1/recommendations?threshold=1.5&min_size=100"
```

**Query Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| threshold | NUMBER | No | Minimum compression ratio (default: 1.5) |
| min_size | NUMBER | No | Minimum size in MB (default: 100) |

**Response**:
```json
{
  "items": [
    {
      "owner": "SALES",
      "table_name": "HISTORICAL_ORDERS",
      "advisable_compression": "ARCHIVE HIGH",
      "estimated_savings_mb": 15280.5,
      "hot_score": 8.3
    },
    {
      "owner": "SALES",
      "table_name": "PRODUCT_CATALOG",
      "advisable_compression": "QUERY LOW",
      "estimated_savings_mb": 3420.8,
      "hot_score": 52.1
    }
  ],
  "count": 2
}
```

---

### GET /history/:operation_id

Get compression operation history.

**Request**:
```bash
curl -X GET https://example.com/ords/compression/v1/history/67890
```

**Response**:
```json
{
  "operation_id": 67890,
  "owner": "SALES",
  "object_name": "ORDERS",
  "compression_type_applied": "QUERY LOW",
  "original_size_mb": 5200.5,
  "compressed_size_mb": 1240.2,
  "space_saved_mb": 3960.3,
  "compression_ratio_achieved": 4.19,
  "start_time": "2025-01-13T14:00:00Z",
  "end_time": "2025-01-13T14:15:30Z",
  "execution_status": "SUCCESS"
}
```

---

## Database Views

### V_COMPRESSION_CANDIDATES

Shows tables recommended for compression.

**Columns**:
| Column | Type | Description |
|--------|------|-------------|
| owner | VARCHAR2(128) | Table owner |
| object_name | VARCHAR2(128) | Table name |
| segment_size_mb | NUMBER | Current size in MB |
| hot_score | NUMBER | Activity score (0-100) |
| advisable_compression | VARCHAR2(30) | Recommended compression |
| estimated_savings_mb | NUMBER | Projected savings |
| savings_percentage | NUMBER | Savings as percentage |
| analysis_date | TIMESTAMP | Analysis timestamp |

**Usage**:
```sql
SELECT * FROM V_COMPRESSION_CANDIDATES
WHERE estimated_savings_mb > 1000
ORDER BY estimated_savings_mb DESC;
```

---

### V_COMPRESSION_SUMMARY

Aggregated compression statistics.

**Columns**:
| Column | Type | Description |
|--------|------|-------------|
| total_tables_analyzed | NUMBER | Count of analyzed tables |
| compressible_tables | NUMBER | Tables with recommendations |
| total_size_mb | NUMBER | Total size analyzed |
| total_potential_savings_mb | NUMBER | Total potential savings |
| avg_hot_score | NUMBER | Average activity score |
| last_analysis_date | TIMESTAMP | Most recent analysis |

**Usage**:
```sql
SELECT * FROM V_COMPRESSION_SUMMARY;
```

---

### V_COMPRESSION_HISTORY

Historical compression operations.

**Columns**:
| Column | Type | Description |
|--------|------|-------------|
| operation_id | NUMBER | Unique operation ID |
| owner | VARCHAR2(128) | Object owner |
| object_name | VARCHAR2(128) | Object name |
| compression_type | VARCHAR2(30) | Applied compression type |
| original_size_mb | NUMBER | Size before compression |
| compressed_size_mb | NUMBER | Size after compression |
| space_saved_mb | NUMBER | Space savings |
| compression_achieved | NUMBER | Actual compression ratio |
| operation_status | VARCHAR2(20) | SUCCESS/FAILED/IN_PROGRESS |
| duration_minutes | NUMBER | Operation duration |
| start_time | TIMESTAMP | Start time |
| end_time | TIMESTAMP | End time |
| error_message | VARCHAR2(4000) | Error message if failed |

**Usage**:
```sql
SELECT * FROM V_COMPRESSION_HISTORY
WHERE operation_status = 'SUCCESS'
  AND start_time > SYSTIMESTAMP - INTERVAL '7' DAY
ORDER BY space_saved_mb DESC;
```

---

### V_HOT_OBJECTS

Tables with high activity requiring OLTP compression.

**Columns**:
| Column | Type | Description |
|--------|------|-------------|
| owner | VARCHAR2(128) | Table owner |
| table_name | VARCHAR2(128) | Table name |
| hot_score | NUMBER | Activity score |
| total_operations | NUMBER | Total DML operations |
| total_updates | NUMBER | Update operations |
| segment_size_mb | NUMBER | Current size |
| advisable_compression | VARCHAR2(30) | Recommended compression |
| analysis_date | TIMESTAMP | Analysis timestamp |

**Usage**:
```sql
SELECT * FROM V_HOT_OBJECTS
WHERE hot_score > 80
ORDER BY total_operations DESC;
```

---

### V_ARCHIVE_CANDIDATES

Cold tables suitable for archive compression.

**Columns**:
| Column | Type | Description |
|--------|------|-------------|
| owner | VARCHAR2(128) | Table owner |
| table_name | VARCHAR2(128) | Table name |
| hot_score | NUMBER | Activity score |
| total_operations | NUMBER | Total DML operations |
| segment_size_mb | NUMBER | Current size |
| advisable_compression | VARCHAR2(30) | Recommended compression |
| estimated_savings_mb | NUMBER | Projected savings |
| archive_compression_ratio | NUMBER | Expected Archive High ratio |
| analysis_date | TIMESTAMP | Analysis timestamp |

**Usage**:
```sql
SELECT * FROM V_ARCHIVE_CANDIDATES
WHERE segment_size_mb > 10000  -- > 10 GB
ORDER BY estimated_savings_mb DESC;
```

---

### V_SPACE_SAVINGS

Aggregated space savings by owner.

**Columns**:
| Column | Type | Description |
|--------|------|-------------|
| owner | VARCHAR2(128) | Schema owner |
| objects_compressed | NUMBER | Count of compressed objects |
| total_original_mb | NUMBER | Original total size |
| total_compressed_mb | NUMBER | Compressed total size |
| total_saved_mb | NUMBER | Total space saved |
| avg_compression_ratio | NUMBER | Average compression ratio |
| last_compression_date | TIMESTAMP | Most recent compression |

**Usage**:
```sql
SELECT * FROM V_SPACE_SAVINGS
ORDER BY total_saved_mb DESC;
```

---

### V_COMPRESSION_EFFECTIVENESS

Evaluates compression decisions.

**Columns**:
| Column | Type | Description |
|--------|------|-------------|
| owner | VARCHAR2(128) | Object owner |
| object_name | VARCHAR2(128) | Object name |
| compression_type_applied | VARCHAR2(30) | Applied compression |
| compression_ratio_achieved | NUMBER | Actual ratio |
| space_saved_mb | NUMBER | Space savings |
| hotness_score | NUMBER | Activity score |
| effectiveness_assessment | VARCHAR2(30) | OPTIMAL/SUBOPTIMAL |

**Usage**:
```sql
-- Find suboptimal compressions
SELECT * FROM V_COMPRESSION_EFFECTIVENESS
WHERE effectiveness_assessment = 'SUBOPTIMAL'
ORDER BY space_saved_mb DESC;
```

---

## Data Structures

### t_compression_recommendation

Record type for recommendations.

**Structure**:
```sql
TYPE t_compression_recommendation IS RECORD (
    owner                VARCHAR2(128),
    table_name          VARCHAR2(128),
    advisable_compression VARCHAR2(30),
    estimated_savings_mb NUMBER,
    hot_score           NUMBER
);
```

---

### t_recommendation_list

Table type for pipelined recommendations.

**Structure**:
```sql
TYPE t_recommendation_list IS TABLE OF t_compression_recommendation;
```

---

## Error Codes

### Custom Exceptions

| Exception | Error Code | Description |
|-----------|-----------|-------------|
| E_ANALYSIS_FAILED | -20001 | Analysis operation failed |
| E_INSUFFICIENT_PRIVILEGES | -20002 | Missing required privileges |
| E_INVALID_COMPRESSION_TYPE | -20003 | Invalid compression type specified |
| E_COMPRESSION_FAILED | -20004 | Compression operation failed |
| E_INVALID_OBJECT | -20005 | Object does not exist |
| E_ROLLBACK_FAILED | -20006 | Rollback operation failed |

**Error Handling Example**:
```sql
DECLARE
    v_error_code NUMBER;
    v_error_msg VARCHAR2(4000);
BEGIN
    PKG_COMPRESSION_EXECUTOR.COMPRESS_TABLE('SALES', 'ORDERS');
EXCEPTION
    WHEN OTHERS THEN
        v_error_code := SQLCODE;
        v_error_msg := SQLERRM;
        DBMS_OUTPUT.PUT_LINE('Error Code: ' || v_error_code);
        DBMS_OUTPUT.PUT_LINE('Error Message: ' || v_error_msg);
END;
/
```

---

**Version**: 1.0.0
**Last Updated**: 2025-01-13
**Compatibility**: Oracle Database 19c and higher
