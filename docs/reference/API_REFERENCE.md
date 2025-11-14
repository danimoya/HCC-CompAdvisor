# HCC Compression Advisor REST API Reference

**Version:** 1.0
**Base URL:** `https://your-server/ords/compression/compression/v1/`
**Content-Type:** `application/json`

## Table of Contents

- [Overview](#overview)
- [Authentication](#authentication)
- [Base Path Structure](#base-path-structure)
- [Common Response Format](#common-response-format)
- [Error Handling](#error-handling)
- [Endpoints](#endpoints)
  - [Analysis Operations](#analysis-operations)
  - [Compression Execution](#compression-execution)
  - [Reporting & Monitoring](#reporting--monitoring)
  - [Configuration Management](#configuration-management)
  - [Utility Endpoints](#utility-endpoints)
- [Compression Types](#compression-types)
- [Common Workflows](#common-workflows)
- [Rate Limits](#rate-limits)

---

## Overview

The HCC Compression Advisor REST API provides programmatic access to Oracle Hybrid Columnar Compression (HCC) analysis, recommendations, and execution capabilities. This API enables automated compression management for Oracle databases with Exadata or ZFS Storage Appliance.

### Key Features

- Automated compression analysis and recommendations
- Safe execution with validation and rollback capabilities
- Real-time monitoring and history tracking
- Flexible strategy-based compression rules
- Batch processing for large-scale operations

---

## Authentication

Currently, the API does not require authentication (`p_auto_rest_auth => FALSE`). For production deployments, it is **strongly recommended** to implement one of the following:

- **Oracle ORDS OAuth2**: Token-based authentication
- **Database Authentication**: User/password validation
- **API Gateway**: External authentication layer

### Example with Basic Auth (when enabled):

```bash
curl -u username:password \
  "https://your-server/ords/compression/compression/v1/summary"
```

---

## Base Path Structure

All API endpoints follow this structure:

```
https://your-server/ords/{schema-alias}/{module-base-path}/{endpoint}
```

**Components:**
- `your-server`: Your Oracle ORDS server hostname
- `schema-alias`: Database schema alias (default: `compression`)
- `module-base-path`: API version path (`compression/v1`)
- `endpoint`: Specific API endpoint

**Example:**
```
https://db.example.com/ords/compression/compression/v1/analyze
```

---

## Common Response Format

### Success Response

```json
{
  "status": "success",
  "message": "Operation completed successfully",
  "data": { },
  "timestamp": "2025-11-13T10:30:45.123Z"
}
```

### Error Response

```json
{
  "status": "error",
  "message": "Detailed error message",
  "sqlcode": -1234,
  "details": { }
}
```

---

## Error Handling

### HTTP Status Codes

| Code | Description | Common Causes |
|------|-------------|---------------|
| `200` | Success | Operation completed successfully |
| `400` | Bad Request | Missing required parameters, invalid strategy_id |
| `404` | Not Found | Endpoint or resource does not exist |
| `500` | Internal Server Error | Database error, execution failure |

### Error Response Structure

```json
{
  "status": "error",
  "message": "Invalid or inactive strategy_id",
  "sqlcode": -20001,
  "details": {
    "parameter": "strategy_id",
    "value": 999
  }
}
```

---

## Endpoints

## Analysis Operations

### 1. Trigger Compression Analysis

Analyzes database objects and generates compression recommendations based on the selected strategy.

**Endpoint:** `POST /analyze`

#### Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `owner` | string | No | ALL | Schema owner to analyze (NULL = all schemas) |
| `strategy_id` | integer | No | 2 | Compression strategy ID (1-4) |

#### Request Body Example

```json
{
  "owner": "SALES",
  "strategy_id": 2
}
```

#### cURL Example

```bash
curl -X POST "https://your-server/ords/compression/compression/v1/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "SALES",
    "strategy_id": 2
  }'
```

#### Success Response (200)

```json
{
  "status": "success",
  "run_id": 1234,
  "owner": "SALES",
  "strategy_id": 2,
  "message": "Compression analysis completed successfully",
  "timestamp": "2025-11-13T10:30:45.123Z"
}
```

#### Error Response (400)

```json
{
  "status": "error",
  "message": "Invalid or inactive strategy_id"
}
```

#### Error Response (500)

```json
{
  "status": "error",
  "message": "ORA-00942: table or view does not exist",
  "sqlcode": -942
}
```

---

### 2. Get Compression Recommendations

Retrieves compression recommendations based on analysis results with flexible filtering.

**Endpoint:** `GET /recommendations`

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `strategy_id` | integer | No | NULL | Filter by strategy ID |
| `min_savings_pct` | decimal | No | NULL | Minimum savings percentage (e.g., 20 = 20%) |
| `owner` | string | No | NULL | Filter by schema owner |

#### cURL Examples

**Basic Request:**
```bash
curl "https://your-server/ords/compression/compression/v1/recommendations"
```

**With Filters:**
```bash
curl "https://your-server/ords/compression/compression/v1/recommendations?strategy_id=2&min_savings_pct=20&owner=SALES"
```

#### Success Response (200)

```json
{
  "items": [
    {
      "owner": "SALES",
      "object_name": "ORDERS",
      "object_type": "TABLE",
      "partition_name": null,
      "current_size_mb": 1024.50,
      "estimated_compressed_mb": 256.12,
      "estimated_savings_mb": 768.38,
      "estimated_savings_pct": 75.00,
      "recommended_compression": "QUERY HIGH",
      "compression_ratio": 4.00,
      "priority_score": 95.50,
      "strategy_name": "Balanced Compression",
      "compression_feasibility": "HIGH",
      "compression_benefit": "EXCELLENT",
      "last_analyzed": "2025-11-13T10:30:45.123Z"
    },
    {
      "owner": "SALES",
      "object_name": "CUSTOMERS",
      "object_type": "TABLE",
      "partition_name": null,
      "current_size_mb": 512.75,
      "estimated_compressed_mb": 153.83,
      "estimated_savings_mb": 358.92,
      "estimated_savings_pct": 70.00,
      "recommended_compression": "QUERY HIGH",
      "compression_ratio": 3.33,
      "priority_score": 88.25,
      "strategy_name": "Balanced Compression",
      "compression_feasibility": "HIGH",
      "compression_benefit": "EXCELLENT",
      "last_analyzed": "2025-11-13T10:30:45.123Z"
    }
  ],
  "hasMore": true,
  "limit": 50,
  "offset": 0,
  "count": 2
}
```

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `owner` | string | Schema owner |
| `object_name` | string | Table or index name |
| `object_type` | string | Object type (TABLE, TABLE PARTITION) |
| `partition_name` | string | Partition name (if applicable) |
| `current_size_mb` | decimal | Current object size in MB |
| `estimated_compressed_mb` | decimal | Estimated size after compression |
| `estimated_savings_mb` | decimal | Estimated space savings |
| `estimated_savings_pct` | decimal | Savings as percentage |
| `recommended_compression` | string | Recommended compression type |
| `compression_ratio` | decimal | Estimated compression ratio |
| `priority_score` | decimal | Priority score (0-100) |
| `strategy_name` | string | Strategy used for recommendation |
| `compression_feasibility` | string | Feasibility rating (LOW/MEDIUM/HIGH) |
| `compression_benefit` | string | Benefit rating (POOR/FAIR/GOOD/EXCELLENT) |
| `last_analyzed` | timestamp | Analysis timestamp |

---

## Compression Execution

### 3. Execute Compression Operation

Executes compression on a single table or partition with optional online operation.

**Endpoint:** `POST /execute`

#### Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `owner` | string | Yes | - | Schema owner |
| `object_name` | string | Yes | - | Table name |
| `object_type` | string | No | TABLE | Object type |
| `partition_name` | string | No | NULL | Partition name (for partitioned tables) |
| `compression_type` | string | Yes | - | Compression type (see [Compression Types](#compression-types)) |
| `online` | string | No | N | Online operation (Y/N) |

#### Request Body Example

```json
{
  "owner": "SALES",
  "object_name": "ORDERS",
  "compression_type": "QUERY HIGH",
  "online": "Y"
}
```

**Partitioned Table Example:**
```json
{
  "owner": "SALES",
  "object_name": "ORDERS",
  "partition_name": "P_2024_Q1",
  "compression_type": "ARCHIVE HIGH",
  "online": "N"
}
```

#### cURL Example

```bash
curl -X POST "https://your-server/ords/compression/compression/v1/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "SALES",
    "object_name": "ORDERS",
    "compression_type": "QUERY HIGH",
    "online": "Y"
  }'
```

#### Success Response (200)

```json
{
  "status": "success",
  "history_id": 5678,
  "owner": "SALES",
  "object_name": "ORDERS",
  "partition_name": null,
  "compression_type": "QUERY HIGH",
  "online": "Y",
  "message": "Compression operation completed successfully",
  "timestamp": "2025-11-13T10:35:20.456Z"
}
```

#### Error Response (400)

```json
{
  "status": "error",
  "message": "Required parameters: owner, object_name, compression_type"
}
```

#### Error Response (500)

```json
{
  "status": "error",
  "message": "ORA-14006: invalid partition name",
  "sqlcode": -14006,
  "details": {
    "owner": "SALES",
    "object_name": "ORDERS",
    "compression_type": "QUERY HIGH"
  }
}
```

---

### 4. Execute Batch Compression

Executes compression on multiple objects based on recommendations with configurable limits.

**Endpoint:** `POST /batch-execute`

#### Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `strategy_id` | integer | No | 2 | Strategy to use for selection |
| `max_tables` | integer | No | 10 | Maximum number of objects to process |
| `max_size_gb` | integer | No | 100 | Maximum object size in GB |
| `online` | string | No | N | Online operation (Y/N) |

#### Request Body Example

```json
{
  "strategy_id": 2,
  "max_tables": 10,
  "max_size_gb": 100,
  "online": "Y"
}
```

#### cURL Example

```bash
curl -X POST "https://your-server/ords/compression/compression/v1/batch-execute" \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_id": 2,
    "max_tables": 10,
    "max_size_gb": 100,
    "online": "Y"
  }'
```

#### Success Response (200)

```json
{
  "status": "success",
  "objects_processed": 10,
  "success_count": 9,
  "error_count": 1,
  "total_estimated_savings_mb": 5432.75,
  "total_estimated_savings_gb": 5.31,
  "strategy_id": 2,
  "online_mode": "Y",
  "message": "Batch compression completed",
  "timestamp": "2025-11-13T11:00:00.789Z"
}
```

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `objects_processed` | integer | Total objects attempted |
| `success_count` | integer | Successfully compressed objects |
| `error_count` | integer | Failed operations |
| `total_estimated_savings_mb` | decimal | Total space saved in MB |
| `total_estimated_savings_gb` | decimal | Total space saved in GB |
| `strategy_id` | integer | Strategy used |
| `online_mode` | string | Online operation flag |

---

## Reporting & Monitoring

### 5. Get Execution History

Retrieves historical compression execution records with filtering capabilities.

**Endpoint:** `GET /history`

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `days_back` | integer | No | 30 | Number of days to look back |
| `owner` | string | No | NULL | Filter by schema owner |
| `status` | string | No | NULL | Filter by operation status (SUCCESS/FAILED) |

#### cURL Examples

**Basic Request:**
```bash
curl "https://your-server/ords/compression/compression/v1/history"
```

**With Filters:**
```bash
curl "https://your-server/ords/compression/compression/v1/history?days_back=7&owner=SALES&status=SUCCESS"
```

#### Success Response (200)

```json
{
  "items": [
    {
      "history_id": 5678,
      "owner": "SALES",
      "object_name": "ORDERS",
      "object_type": "TABLE",
      "partition_name": null,
      "operation_type": "COMPRESS",
      "compression_type": "QUERY HIGH",
      "operation_status": "SUCCESS",
      "size_before_mb": 1024.50,
      "size_after_mb": 256.12,
      "space_saved_mb": 768.38,
      "compression_ratio": 4.00,
      "duration_seconds": 45.32,
      "online_operation": "Y",
      "ddl_statement": "ALTER TABLE SALES.ORDERS MOVE COMPRESS FOR QUERY HIGH ONLINE",
      "error_message": null,
      "execution_date": "2025-11-13T10:35:20.456Z"
    },
    {
      "history_id": 5679,
      "owner": "SALES",
      "object_name": "CUSTOMERS",
      "object_type": "TABLE",
      "partition_name": null,
      "operation_type": "COMPRESS",
      "compression_type": "QUERY HIGH",
      "operation_status": "FAILED",
      "size_before_mb": 512.75,
      "size_after_mb": null,
      "space_saved_mb": null,
      "compression_ratio": null,
      "duration_seconds": 12.10,
      "online_operation": "Y",
      "ddl_statement": "ALTER TABLE SALES.CUSTOMERS MOVE COMPRESS FOR QUERY HIGH ONLINE",
      "error_message": "ORA-14006: invalid partition name",
      "execution_date": "2025-11-13T10:36:45.789Z"
    }
  ],
  "hasMore": false,
  "limit": 50,
  "offset": 0,
  "count": 2
}
```

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `history_id` | integer | Unique history record ID |
| `owner` | string | Schema owner |
| `object_name` | string | Table name |
| `object_type` | string | Object type |
| `partition_name` | string | Partition name (if applicable) |
| `operation_type` | string | Operation type (COMPRESS/ROLLBACK) |
| `compression_type` | string | Compression type applied |
| `operation_status` | string | Operation status (SUCCESS/FAILED) |
| `size_before_mb` | decimal | Size before compression |
| `size_after_mb` | decimal | Size after compression |
| `space_saved_mb` | decimal | Actual space saved |
| `compression_ratio` | decimal | Actual compression ratio |
| `duration_seconds` | decimal | Operation duration |
| `online_operation` | string | Online operation flag |
| `ddl_statement` | string | SQL DDL statement executed |
| `error_message` | string | Error message (if failed) |
| `execution_date` | timestamp | Execution timestamp |

---

### 6. Get Advisor Summary

Retrieves dashboard summary metrics for compression advisor activity.

**Endpoint:** `GET /summary`

#### cURL Example

```bash
curl "https://your-server/ords/compression/compression/v1/summary"
```

#### Success Response (200)

```json
{
  "items": [
    {
      "metric_category": "Overview",
      "metric_name": "Total Objects Analyzed",
      "metric_value": "1,245",
      "metric_unit": "objects",
      "trend_indicator": "↑",
      "last_updated": "2025-11-13T10:30:45.123Z"
    },
    {
      "metric_category": "Overview",
      "metric_name": "Total Current Size",
      "metric_value": "15,678.50",
      "metric_unit": "GB",
      "trend_indicator": "→",
      "last_updated": "2025-11-13T10:30:45.123Z"
    },
    {
      "metric_category": "Savings Potential",
      "metric_name": "Total Potential Savings",
      "metric_value": "8,945.25",
      "metric_unit": "GB",
      "trend_indicator": "↑",
      "last_updated": "2025-11-13T10:30:45.123Z"
    },
    {
      "metric_category": "Savings Potential",
      "metric_name": "Average Savings Percentage",
      "metric_value": "57.05",
      "metric_unit": "%",
      "trend_indicator": "↑",
      "last_updated": "2025-11-13T10:30:45.123Z"
    },
    {
      "metric_category": "Execution Stats",
      "metric_name": "Total Compressions Executed",
      "metric_value": "423",
      "metric_unit": "operations",
      "trend_indicator": "↑",
      "last_updated": "2025-11-13T11:00:00.789Z"
    },
    {
      "metric_category": "Execution Stats",
      "metric_name": "Success Rate",
      "metric_value": "95.50",
      "metric_unit": "%",
      "trend_indicator": "→",
      "last_updated": "2025-11-13T11:00:00.789Z"
    },
    {
      "metric_category": "Performance",
      "metric_name": "Average Compression Time",
      "metric_value": "45.30",
      "metric_unit": "seconds",
      "trend_indicator": "↓",
      "last_updated": "2025-11-13T11:00:00.789Z"
    }
  ],
  "count": 7
}
```

#### Metric Categories

| Category | Description |
|----------|-------------|
| `Overview` | General statistics about analyzed objects |
| `Savings Potential` | Estimated compression benefits |
| `Execution Stats` | Historical execution metrics |
| `Performance` | Performance and timing metrics |

#### Trend Indicators

- `↑` - Increasing trend
- `↓` - Decreasing trend
- `→` - Stable/no change

---

## Configuration Management

### 7. List Compression Strategies

Retrieves available compression strategies with their configurations.

**Endpoint:** `GET /strategies`

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `active_only` | string | No | NULL | Filter to active strategies only (Y) |

#### cURL Examples

**All Strategies:**
```bash
curl "https://your-server/ords/compression/compression/v1/strategies"
```

**Active Only:**
```bash
curl "https://your-server/ords/compression/compression/v1/strategies?active_only=Y"
```

#### Success Response (200)

```json
{
  "items": [
    {
      "strategy_id": 1,
      "strategy_name": "Conservative Compression",
      "description": "Minimal compression with maximum safety - OLTP focused",
      "is_active": "Y",
      "created_date": "2025-11-13T08:00:00.000Z",
      "modified_date": "2025-11-13T08:00:00.000Z",
      "configuration": {
        "default_compression": "OLTP",
        "priority_weights": {
          "size_weight": 40,
          "access_weight": 40,
          "modification_weight": 20
        }
      }
    },
    {
      "strategy_id": 2,
      "strategy_name": "Balanced Compression",
      "description": "Optimal balance between compression ratio and performance",
      "is_active": "Y",
      "created_date": "2025-11-13T08:00:00.000Z",
      "modified_date": "2025-11-13T08:00:00.000Z",
      "configuration": {
        "default_compression": "QUERY HIGH",
        "priority_weights": {
          "size_weight": 50,
          "access_weight": 30,
          "modification_weight": 20
        }
      }
    },
    {
      "strategy_id": 3,
      "strategy_name": "Aggressive Compression",
      "description": "Maximum compression for warehousing and analytics",
      "is_active": "Y",
      "created_date": "2025-11-13T08:00:00.000Z",
      "modified_date": "2025-11-13T08:00:00.000Z",
      "configuration": {
        "default_compression": "ARCHIVE HIGH",
        "priority_weights": {
          "size_weight": 70,
          "access_weight": 20,
          "modification_weight": 10
        }
      }
    },
    {
      "strategy_id": 4,
      "strategy_name": "Archive Optimization",
      "description": "Specialized for long-term data retention and compliance",
      "is_active": "Y",
      "created_date": "2025-11-13T08:00:00.000Z",
      "modified_date": "2025-11-13T08:00:00.000Z",
      "configuration": {
        "default_compression": "ARCHIVE HIGH",
        "priority_weights": {
          "size_weight": 80,
          "access_weight": 10,
          "modification_weight": 10
        }
      }
    }
  ],
  "count": 4
}
```

---

### 8. Get Strategy Rules

Retrieves compression rules for a specific strategy.

**Endpoint:** `GET /strategy/:id/rules`

#### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | integer | Yes | Strategy ID |

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `active_only` | string | No | NULL | Filter to active rules only (Y) |

#### cURL Example

```bash
curl "https://your-server/ords/compression/compression/v1/strategy/2/rules?active_only=Y"
```

#### Success Response (200)

```json
{
  "items": [
    {
      "rule_id": 201,
      "rule_order": 1,
      "rule_name": "Large Historical Tables",
      "condition_type": "SIZE_AND_AGE",
      "condition_value": ">10GB AND >90 DAYS",
      "compression_type": "ARCHIVE HIGH",
      "is_active": "Y",
      "strategy_name": "Balanced Compression",
      "rule_details": {
        "priority": 90,
        "min_size_mb": 10240,
        "max_size_mb": null,
        "table_pattern": "%_HIST%",
        "exclude_pattern": "%_TEMP%"
      }
    },
    {
      "rule_id": 202,
      "rule_order": 2,
      "rule_name": "Medium Analytical Tables",
      "condition_type": "SIZE_AND_ACCESS",
      "condition_value": "1GB-10GB AND READ_HEAVY",
      "compression_type": "QUERY HIGH",
      "is_active": "Y",
      "strategy_name": "Balanced Compression",
      "rule_details": {
        "priority": 80,
        "min_size_mb": 1024,
        "max_size_mb": 10240,
        "table_pattern": null,
        "exclude_pattern": "%_TEMP%"
      }
    },
    {
      "rule_id": 203,
      "rule_order": 3,
      "rule_name": "Active OLTP Tables",
      "condition_type": "MODIFICATION_RATE",
      "condition_value": "HIGH_UPDATE_RATE",
      "compression_type": "OLTP",
      "is_active": "Y",
      "strategy_name": "Balanced Compression",
      "rule_details": {
        "priority": 70,
        "min_size_mb": 100,
        "max_size_mb": null,
        "table_pattern": null,
        "exclude_pattern": "%_ARCH%"
      }
    }
  ],
  "count": 3
}
```

#### Condition Types

| Type | Description |
|------|-------------|
| `SIZE_AND_AGE` | Based on table size and data age |
| `SIZE_AND_ACCESS` | Based on size and access patterns |
| `MODIFICATION_RATE` | Based on update frequency |
| `ACCESS_PATTERN` | Based on read/write patterns |
| `TABLE_TYPE` | Based on table characteristics |

---

## Utility Endpoints

### 9. API Health Check

Checks API and database health status.

**Endpoint:** `GET /health`

#### cURL Example

```bash
curl "https://your-server/ords/compression/compression/v1/health"
```

#### Success Response (200)

```json
{
  "status": "healthy",
  "api_version": "1.0",
  "database_schema": "COMPRESSION_ADMIN",
  "tables_installed": 3,
  "last_analysis_run": "2025-11-13T10:30:45.123Z",
  "timestamp": "2025-11-13T12:00:00.000Z"
}
```

#### Error Response (500)

```json
{
  "status": "error",
  "message": "ORA-00942: table or view does not exist"
}
```

---

### 10. API Metadata

Retrieves API capabilities, endpoints, and configuration information.

**Endpoint:** `GET /metadata`

#### cURL Example

```bash
curl "https://your-server/ords/compression/compression/v1/metadata"
```

#### Success Response (200)

```json
{
  "api_name": "HCC Compression Advisor REST API",
  "version": "1.0",
  "base_path": "/compression/v1/",
  "schema": "COMPRESSION_ADMIN",
  "endpoints": [
    {
      "method": "POST",
      "path": "/analyze",
      "description": "Trigger compression analysis"
    },
    {
      "method": "GET",
      "path": "/recommendations",
      "description": "Get compression recommendations"
    },
    {
      "method": "POST",
      "path": "/execute",
      "description": "Execute compression operation"
    },
    {
      "method": "GET",
      "path": "/history",
      "description": "Get execution history"
    },
    {
      "method": "GET",
      "path": "/summary",
      "description": "Get advisor summary"
    },
    {
      "method": "GET",
      "path": "/strategies",
      "description": "List compression strategies"
    },
    {
      "method": "GET",
      "path": "/strategy/:id/rules",
      "description": "Get strategy rules"
    },
    {
      "method": "POST",
      "path": "/batch-execute",
      "description": "Execute batch compression"
    },
    {
      "method": "GET",
      "path": "/health",
      "description": "Health check"
    },
    {
      "method": "GET",
      "path": "/metadata",
      "description": "API metadata"
    }
  ],
  "compression_types": [
    "BASIC",
    "OLTP",
    "QUERY LOW",
    "QUERY HIGH",
    "ARCHIVE LOW",
    "ARCHIVE HIGH"
  ],
  "timestamp": "2025-11-13T12:00:00.000Z"
}
```

---

## Compression Types

### Available Compression Types

| Type | Use Case | Compression Ratio | Performance Impact | Best For |
|------|----------|-------------------|-------------------|----------|
| `BASIC` | Legacy support | 2-3x | Very Low | Migration/compatibility |
| `OLTP` | Transaction processing | 2-3x | Very Low | High DML workloads |
| `QUERY LOW` | Mixed workloads | 6-10x | Low | Read-mostly with some DML |
| `QUERY HIGH` | Analytical queries | 10-15x | Low-Medium | Data warehouse, reporting |
| `ARCHIVE LOW` | Long-term storage | 10-15x | Medium | Historical data, light access |
| `ARCHIVE HIGH` | Deep archival | 15-20x+ | Medium-High | Compliance, cold data |

### Compression Type Selection Guidelines

**OLTP Compression:**
- High UPDATE/DELETE activity
- Transaction-oriented workloads
- Minimal query overhead required
- 24/7 availability needs

**QUERY LOW:**
- Balanced read/write workloads
- Medium-sized fact tables
- Frequent batch loads with queries

**QUERY HIGH:**
- Read-heavy analytical workloads
- Large fact tables
- Infrequent updates
- Data warehouse environments

**ARCHIVE HIGH:**
- Historical/compliance data
- Rarely accessed information
- Long-term retention requirements
- Maximum space savings priority

---

## Common Workflows

### Workflow 1: Initial Analysis and Execution

**Step 1: Run Analysis**
```bash
curl -X POST "https://your-server/ords/compression/compression/v1/analyze" \
  -H "Content-Type: application/json" \
  -d '{"owner": "SALES", "strategy_id": 2}'
```

**Step 2: Review Recommendations**
```bash
curl "https://your-server/ords/compression/compression/v1/recommendations?strategy_id=2&min_savings_pct=20"
```

**Step 3: Execute Top Candidate**
```bash
curl -X POST "https://your-server/ords/compression/compression/v1/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "SALES",
    "object_name": "ORDERS",
    "compression_type": "QUERY HIGH",
    "online": "Y"
  }'
```

**Step 4: Verify Results**
```bash
curl "https://your-server/ords/compression/compression/v1/history?owner=SALES&days_back=1"
```

---

### Workflow 2: Batch Processing

**Step 1: Check Available Strategies**
```bash
curl "https://your-server/ords/compression/compression/v1/strategies?active_only=Y"
```

**Step 2: Execute Batch Compression**
```bash
curl -X POST "https://your-server/ords/compression/compression/v1/batch-execute" \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_id": 2,
    "max_tables": 20,
    "max_size_gb": 50,
    "online": "Y"
  }'
```

**Step 3: Monitor Progress**
```bash
curl "https://your-server/ords/compression/compression/v1/summary"
```

---

### Workflow 3: Strategy Customization

**Step 1: List Existing Strategies**
```bash
curl "https://your-server/ords/compression/compression/v1/strategies"
```

**Step 2: Review Strategy Rules**
```bash
curl "https://your-server/ords/compression/compression/v1/strategy/2/rules?active_only=Y"
```

**Step 3: Run Analysis with Selected Strategy**
```bash
curl -X POST "https://your-server/ords/compression/compression/v1/analyze" \
  -H "Content-Type: application/json" \
  -d '{"strategy_id": 3}'
```

---

### Workflow 4: Monitoring and Reporting

**Daily Summary Dashboard:**
```bash
curl "https://your-server/ords/compression/compression/v1/summary"
```

**Recent Execution History:**
```bash
curl "https://your-server/ords/compression/compression/v1/history?days_back=7"
```

**Successful Operations Only:**
```bash
curl "https://your-server/ords/compression/compression/v1/history?status=SUCCESS&days_back=30"
```

---

## Rate Limits

Currently, no rate limits are enforced. For production environments, consider implementing:

- **Request throttling**: Limit requests per IP/user
- **Concurrent execution limits**: Prevent resource exhaustion
- **Batch operation quotas**: Control large-scale operations

### Recommended Limits

| Operation | Suggested Limit | Reasoning |
|-----------|----------------|-----------|
| Analysis runs | 10 per hour | Resource-intensive operation |
| Single executions | 100 per hour | Balance availability and control |
| Batch executions | 5 per hour | High-impact operations |
| Read operations | 1000 per hour | Low-impact, high-value |

---

## Best Practices

### 1. Analysis Scheduling

- Run analysis during maintenance windows
- Schedule regular analysis (weekly recommended)
- Use strategy_id parameter for different workload types

### 2. Execution Safety

- Always test on non-production first
- Use online operations (online=Y) for 24/7 systems
- Start with small objects before batch operations
- Monitor history for failures

### 3. Performance Optimization

- Filter recommendations with min_savings_pct
- Set appropriate max_size_gb for batch operations
- Use pagination for large result sets
- Cache metadata and strategies locally

### 4. Error Handling

- Implement retry logic with exponential backoff
- Log all error responses for troubleshooting
- Monitor health endpoint for system status
- Review history endpoint for failed operations

### 5. Monitoring

- Set up alerting for failed operations
- Track compression ratio trends
- Monitor space savings metrics
- Review execution duration patterns

---

## Support and Resources

### Documentation

- **Installation Guide**: See `INSTALLATION.md`
- **User Guide**: See `USER_GUIDE.md`
- **Architecture**: See `docs/ARCHITECTURE.md`

### Database Requirements

- Oracle Database 12c+ with Exadata or ZFS Storage Appliance
- HCC licensing (Exadata, ZDLRA, or ZFS Storage Appliance)
- Oracle REST Data Services (ORDS) 19.1+
- Sufficient privileges for compression operations

### Common Issues

**Issue: 400 - Invalid strategy_id**
- Solution: Verify strategy exists and is active using `/strategies` endpoint

**Issue: 500 - Table does not exist**
- Solution: Verify object owner and name, check user privileges

**Issue: Compression operation fails**
- Solution: Review error_message in `/history`, check online/offline requirements

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-11-13 | Initial release with 10 endpoints |

---

## License

Copyright (c) 2025 Daniel Moya. All rights reserved.
Author: Daniel Moya
GitHub: [github.com/danimoya](https://github.com/danimoya)
Website: [danielmoya.cv](https://danielmoya.cv)

This API is provided as-is without warranties. Use at your own risk in production environments.

---

**End of API Reference**
