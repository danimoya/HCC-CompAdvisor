# HCC Compression Advisor - System Architecture

## Executive Summary

The HCC (Hybrid Columnar Compression) Compression Advisor is an enterprise-grade Oracle Database 19c system designed to identify, recommend, and execute optimal compression strategies for database objects. The architecture employs a modular, layered approach optimized for Oracle Exadata Cloud at Customer (ExaCC) environments with minimal performance impact and maximum storage efficiency.

## Architectural Principles

### Core Design Principles

1. **Separation of Concerns**: Analysis, execution, and reporting are isolated into distinct packages
2. **Data-Driven Recommendations**: Machine learning-ready scoring algorithms guide compression decisions
3. **Audit-First**: Complete historical tracking of all operations for compliance and rollback
4. **REST-Native**: All operations exposed through ORDS for dashboard and automation integration
5. **Performance-Conscious**: Parallel processing, sampling, and batch operations minimize overhead
6. **Fail-Safe**: Comprehensive error handling with automatic rollback capabilities

### Quality Attributes

| Attribute | Target | Implementation Strategy |
|-----------|--------|------------------------|
| **Performance** | <30 min for 1000+ tables | Parallel DML, bulk operations, sampling |
| **Accuracy** | 95%+ recommendation accuracy | Multi-factor scoring, historical learning |
| **Overhead** | <5% database load | Asynchronous execution, resource throttling |
| **Scalability** | 10TB+ databases | Partitioned processing, incremental analysis |
| **Reliability** | Zero data loss | Transactional integrity, validation checks |
| **Maintainability** | Enterprise-grade | Modular packages, comprehensive logging |

## System Layers

### Layer 1: Data Persistence Layer

**Purpose**: Store analysis results, historical operations, and configuration metadata.

**Components**:
- **Core Tables**: COMPRESSION_ANALYSIS_RESULTS, COMPRESSION_HISTORY, ADVISOR_RUN
- **Extended Tables**: INDEX_COMPRESSION_ANALYSIS, LOB_COMPRESSION_ANALYSIS, IOT_COMPRESSION_ANALYSIS
- **Configuration Tables**: COMPRESSION_STRATEGIES, COMPRESSION_THRESHOLDS, EXECUTION_SCHEDULES
- **Audit Tables**: OPERATION_LOG, ERROR_LOG, PERFORMANCE_METRICS

**Storage Strategy**:
- All repository tables use BASIC compression to minimize footprint
- Partitioned by analysis_date/execution_date for lifecycle management
- Local indexes for partition-wise operations
- Retention policy: 90 days for detailed metrics, 2 years for summaries

### Layer 2: Analysis Engine Layer

**Purpose**: Identify compression candidates and generate recommendations.

**Main Package**: `COMPRESSION_MGR.ADVISOR_PKG`

**Key Procedures**:
```
analyse_tables_p(p_owner VARCHAR2)
analyse_indexes_p(p_owner VARCHAR2)
analyse_lobs_p(p_owner VARCHAR2)
analyse_iots_p(p_owner VARCHAR2)
analyse_all_user_obj_p(p_owner VARCHAR2)
refresh_analysis_p(p_days_old NUMBER)
```

**Analysis Workflow**:
```
1. Object Discovery
   ↓ [Query DBA_TABLES, DBA_TAB_PARTITIONS, DBA_INDEXES]
2. Compression Ratio Calculation
   ↓ [DBMS_COMPRESSION.GET_COMPRESSION_RATIO for 5 types]
3. Activity Analysis
   ↓ [ALL_TAB_MODIFICATIONS, DBA_HIST_SEG_STAT]
4. Hotness Scoring
   ↓ [Physical/logical reads, DML frequency, last access]
5. Recommendation Logic
   ↓ [Multi-factor decision tree]
6. Results Persistence
   ↓ [Atomic transaction to analysis tables]
```

**Recommendation Algorithm**:

The system employs a multi-factor decision matrix:

```sql
FUNCTION calculate_recommendation(
    dml_rate_24h NUMBER,
    access_frequency NUMBER,
    object_size_gb NUMBER,
    data_age_days NUMBER,
    compression_ratios COMPRESSION_RATIOS_T
) RETURN VARCHAR2 IS
BEGIN
    -- High DML workloads
    IF dml_rate_24h > 100000 OR (dml_rate_24h > 10000 AND hotness_score > 75) THEN
        RETURN 'OLTP';  -- ROW STORE COMPRESS ADVANCED

    -- Active data with moderate changes
    ELSIF data_age_days < 90 AND dml_rate_24h > 1000 THEN
        RETURN 'QUERY_LOW';  -- COLUMN STORE COMPRESS FOR QUERY LOW

    -- Large, infrequently modified tables
    ELSIF object_size_gb > 10 AND dml_rate_24h < 100 THEN
        RETURN 'QUERY_HIGH';  -- COLUMN STORE COMPRESS FOR QUERY HIGH

    -- Archival data - very large, rarely accessed
    ELSIF object_size_gb > 50 AND dml_rate_24h < 10 AND data_age_days > 180 THEN
        RETURN 'ARCHIVE_LOW';  -- COLUMN STORE COMPRESS FOR ARCHIVE LOW

    -- Cold archival storage
    ELSIF object_size_gb > 100 AND dml_rate_24h = 0 AND data_age_days > 365 THEN
        RETURN 'ARCHIVE_HIGH';  -- COLUMN STORE COMPRESS FOR ARCHIVE HIGH

    -- Compression not beneficial
    ELSIF MAX(compression_ratios) < 1.5 THEN
        RETURN 'NONE';

    ELSE
        RETURN 'QUERY_LOW';  -- Default safe choice
    END IF;
END;
```

### Layer 3: Execution Engine Layer

**Purpose**: Apply compression operations with safety checks and tracking.

**Main Package**: `COMPRESSION_MGR.EXECUTOR_PKG`

**Key Procedures**:
```
compress_segment_p(p_owner, p_object_name, p_object_type, p_partition_name,
                   p_compression_type, p_parallel, p_verify_only)
compress_batch_p(p_schema, p_threshold_ratio, p_max_concurrent)
rollback_compression_p(p_execution_id)
validate_compression_p(p_execution_id)
```

**Execution Workflow**:
```
1. Pre-Execution Validation
   ↓ [Lock check, privilege verification, safety thresholds]
2. Size Capture (Before)
   ↓ [DBA_SEGMENTS query, store in history]
3. DDL Generation
   ↓ [ALTER TABLE/INDEX MOVE COMPRESS FOR ...]
4. Execution with Monitoring
   ↓ [DBMS_APPLICATION_INFO, V$SESSION_LONGOPS integration]
5. Index Rebuild
   ↓ [Automatic ONLINE rebuild of dependent indexes]
6. Size Capture (After)
   ↓ [Calculate actual compression ratio achieved]
7. History Update
   ↓ [Record success/failure, metrics, timing]
8. Commit/Rollback
   ↓ [Atomic transaction boundary]
```

**Safety Mechanisms**:
- **Lock Validation**: NOWAIT lock acquisition prevents blocking
- **Resource Throttling**: Configurable parallel execution limits
- **Verification Mode**: Dry-run capability with size estimates only
- **Automatic Rollback**: Failed operations logged with rollback procedures
- **Progress Tracking**: V$SESSION_LONGOPS integration for monitoring

### Layer 4: Reporting & Analytics Layer

**Purpose**: Provide insights for DBAs and dashboard visualization.

**Reporting Views**:

| View Name | Purpose | Key Metrics |
|-----------|---------|------------|
| `V_COMPRESSION_CANDIDATES` | Top candidates for compression | Hotness score, compression ratios, recommended type |
| `V_COMPRESSION_SUMMARY` | Schema-level statistics | Total objects, potential savings, risk assessment |
| `V_HOT_OBJECTS` | High-activity objects | DML rates, access patterns, OLTP candidates |
| `V_ARCHIVE_CANDIDATES` | Low-activity archival targets | Data age, size, ARCHIVE compression candidates |
| `V_COMPRESSION_HISTORY` | Execution audit trail | Success rate, space savings, execution times |
| `V_SPACE_SAVINGS` | ROI metrics | Total MB saved, compression ratios by schema |
| `V_COMPRESSION_EFFECTIVENESS` | Performance validation | Before/after comparison, recommendation accuracy |
| `V_COMPRESSION_TRENDS` | Historical analysis | Time-series savings, growth projections |

**Analytics Functions**:
```sql
FUNCTION forecast_savings(p_schema VARCHAR2) RETURN NUMBER;
FUNCTION calculate_roi(p_execution_id NUMBER) RETURN NUMBER;
FUNCTION recommend_schedule(p_schema VARCHAR2) RETURN COMPRESSION_SCHEDULE_T;
```

### Layer 5: REST API & Integration Layer

**Purpose**: Expose all functionality through ORDS REST endpoints.

**API Design**:

```
Module: /compression/v1/

Endpoints:
├── /advisor/
│   ├── POST /tables          → analyse_tables_p
│   ├── POST /indexes         → analyse_indexes_p
│   ├── POST /lobs            → analyse_lobs_p
│   ├── POST /iots            → analyse_iots_p
│   ├── POST /all             → analyse_all_user_obj_p
│   └── GET  /status/:run_id  → Get analysis job status
│
├── /execute/
│   ├── POST /compress        → compress_segment_p
│   ├── POST /batch           → compress_batch_p
│   ├── POST /rollback        → rollback_compression_p
│   └── GET  /status/:exec_id → Get execution status
│
├── /reports/
│   ├── GET  /candidates      → V_COMPRESSION_CANDIDATES
│   ├── GET  /summary/:schema → V_COMPRESSION_SUMMARY
│   ├── GET  /history         → V_COMPRESSION_HISTORY
│   ├── GET  /savings/:schema → V_SPACE_SAVINGS
│   └── GET  /trends          → V_COMPRESSION_TRENDS
│
└── /config/
    ├── GET  /strategies      → COMPRESSION_STRATEGIES table
    ├── POST /strategies      → Update strategy parameters
    └── GET  /thresholds      → COMPRESSION_THRESHOLDS table
```

**Request/Response Format**:

All endpoints follow REST conventions with JSON payloads:

```json
// POST /compression/v1/execute/compress
{
  "owner": "APP_SCHEMA",
  "object_name": "LARGE_ORDERS",
  "object_type": "TABLE",
  "partition_name": null,
  "compression_type": "QUERY_HIGH",
  "parallel": 4,
  "verify_only": false
}

// Response
{
  "status": "SUCCESS",
  "execution_id": 12345,
  "old_bytes": 107374182400,
  "new_bytes": 21474836480,
  "saved_pct": 80.0,
  "compression_ratio": 5.0,
  "duration_seconds": 1847
}
```

**Authentication & Authorization**:
- ORDS OAuth2 integration for secure access
- Role-based access control (COMPRESSION_MGR_ROLE)
- Schema-level authorization checks
- API key management for external integrations

## Extended Object Support

### Index Compression Analysis

**Strategy**:
- Analyze B-tree indexes for Advanced Index Compression
- Consider rebuild frequency, access patterns, and size
- Separate analysis for unique vs non-unique indexes
- IOT overflow segment handling

**Algorithm**:
```sql
-- High cardinality, large size → Advanced Index Compression
-- Frequent lookups, moderate size → Prefix Compression
-- Low cardinality → No compression (expansion risk)
```

### LOB Compression Analysis

**Strategy**:
- SecureFiles LOBs: Evaluate COMPRESS HIGH vs MEDIUM
- BasicFiles LOBs: Recommend migration to SecureFiles
- Consider access patterns (read vs write frequency)
- Analyze deduplication opportunities

**Algorithm**:
```sql
-- Large CLOBs/BLOBs with low write frequency → COMPRESS HIGH
-- Frequently updated LOBs → COMPRESS MEDIUM or NONE
-- Duplicate content detection → Enable deduplication
```

### IOT Compression Analysis

**Strategy**:
- Primary key compression evaluation
- Overflow segment analysis
- Key compression (prefix compression)
- Trade-off between space and performance

**Algorithm**:
```sql
-- Composite keys with redundant prefixes → Key compression
-- Large overflow segments → Apply standard table compression
-- High access frequency → Conservative compression
```

## Compression Strategy Configuration

### Strategy Table Structure

```sql
CREATE TABLE COMPRESSION_STRATEGIES (
    STRATEGY_ID         NUMBER PRIMARY KEY,
    STRATEGY_NAME       VARCHAR2(50),
    DESCRIPTION         VARCHAR2(500),
    DML_THRESHOLD_LOW   NUMBER,
    DML_THRESHOLD_HIGH  NUMBER,
    SIZE_THRESHOLD_GB   NUMBER,
    AGE_THRESHOLD_DAYS  NUMBER,
    COMPRESSION_TYPE    VARCHAR2(30),
    PRIORITY_SCORE      NUMBER,
    ENABLED_FLAG        VARCHAR2(1),
    CREATED_DATE        DATE,
    MODIFIED_DATE       DATE
);
```

### Three Default Strategies

**Strategy 1: High Performance (Minimal Latency)**
```
- DML Threshold: High (>10000 ops/day)
- Primary Compression: OLTP only
- Secondary: QUERY_LOW for read-heavy
- Use Case: Transactional systems, OLTP databases
- Trade-off: Less compression, better performance
```

**Strategy 2: Balanced (Production Default)**
```
- DML Threshold: Moderate (1000-10000 ops/day)
- Primary Compression: QUERY_LOW for active data
- Secondary: QUERY_HIGH for older data
- Use Case: General-purpose production databases
- Trade-off: 40-60% compression with <10% performance impact
```

**Strategy 3: Maximum Compression (Space Optimized)**
```
- DML Threshold: Low (<1000 ops/day)
- Primary Compression: QUERY_HIGH for most objects
- Secondary: ARCHIVE_HIGH for cold data
- Use Case: Data warehouses, archival systems
- Trade-off: 70-90% compression with query overhead
```

### Strategy Selection Logic

```sql
FUNCTION select_strategy(
    p_database_type VARCHAR2,    -- 'OLTP', 'DW', 'MIXED'
    p_performance_req VARCHAR2,  -- 'HIGH', 'MEDIUM', 'LOW'
    p_space_pressure NUMBER       -- 0-100 (utilization percentage)
) RETURN NUMBER IS
BEGIN
    IF p_database_type = 'OLTP' AND p_performance_req = 'HIGH' THEN
        RETURN 1;  -- High Performance Strategy
    ELSIF p_space_pressure > 85 THEN
        RETURN 3;  -- Maximum Compression Strategy
    ELSE
        RETURN 2;  -- Balanced Strategy
    END IF;
END;
```

Strategies are loaded as global package variables during initialization:

```sql
-- In ADVISOR_PKG specification
g_active_strategy    COMPRESSION_STRATEGIES%ROWTYPE;
g_dml_threshold_high NUMBER;
g_dml_threshold_low  NUMBER;
g_size_threshold_gb  NUMBER;
g_age_threshold_days NUMBER;

-- Initialization
PROCEDURE load_active_strategy(p_strategy_id NUMBER DEFAULT NULL);
```

## Performance Optimization Techniques

### 1. Parallel Processing

```sql
-- Enable parallel operations
EXECUTE IMMEDIATE 'ALTER SESSION ENABLE PARALLEL DML';
EXECUTE IMMEDIATE 'ALTER SESSION FORCE PARALLEL QUERY PARALLEL 4';

-- Parallel cursor processing
FOR rec IN (
    SELECT /*+ PARALLEL(t,4) */ owner, table_name
    FROM dba_tables t
    WHERE owner = p_schema
) LOOP
    -- Process in parallel
END LOOP;
```

### 2. Bulk Operations

```sql
-- Bulk collect for efficient processing
DECLARE
    TYPE t_table_list IS TABLE OF VARCHAR2(128);
    v_tables t_table_list;
BEGIN
    SELECT table_name
    BULK COLLECT INTO v_tables
    FROM user_tables
    WHERE num_rows > 100000;

    FORALL i IN 1..v_tables.COUNT
        INSERT INTO compression_analysis_results (object_name, ...)
        VALUES (v_tables(i), ...);
END;
```

### 3. Sampling Strategy

```sql
-- Adaptive sampling based on table size
FUNCTION calculate_sample_size(p_num_rows NUMBER) RETURN NUMBER IS
BEGIN
    RETURN CASE
        WHEN p_num_rows < 100000 THEN p_num_rows
        WHEN p_num_rows < 1000000 THEN 100000
        WHEN p_num_rows < 10000000 THEN 500000
        ELSE 1000000
    END;
END;
```

### 4. Incremental Analysis

```sql
-- Only re-analyze changed objects
PROCEDURE refresh_analysis_p(p_days_old NUMBER DEFAULT 7) IS
BEGIN
    FOR rec IN (
        SELECT owner, object_name
        FROM compression_analysis_results
        WHERE analysis_date < SYSDATE - p_days_old
           OR object_name IN (
               SELECT table_name
               FROM all_tab_modifications
               WHERE timestamp > SYSDATE - p_days_old
           )
    ) LOOP
        -- Re-analyze only modified objects
    END LOOP;
END;
```

### 5. Resource Throttling

```sql
-- Limit concurrent compression operations
PROCEDURE compress_batch_p(
    p_max_concurrent NUMBER DEFAULT 2
) IS
    v_running_jobs NUMBER;
BEGIN
    LOOP
        SELECT COUNT(*) INTO v_running_jobs
        FROM user_scheduler_jobs
        WHERE job_name LIKE 'COMPRESS_%' AND state = 'RUNNING';

        EXIT WHEN v_running_jobs < p_max_concurrent;
        DBMS_LOCK.SLEEP(5);
    END LOOP;

    -- Spawn next job
END;
```

## Monitoring & Observability

### Long Operations Tracking

```sql
-- Integrate with V$SESSION_LONGOPS
PROCEDURE set_longop_context(
    p_operation VARCHAR2,
    p_target VARCHAR2,
    p_sofar NUMBER,
    p_totalwork NUMBER
) IS
    v_rindex NUMBER;
    v_slno NUMBER;
BEGIN
    DBMS_APPLICATION_INFO.SET_MODULE(
        module_name => 'COMPRESSION_ADVISOR',
        action_name => p_operation
    );

    DBMS_APPLICATION_INFO.SET_SESSION_LONGOPS(
        rindex => v_rindex,
        slno => v_slno,
        op_name => p_operation,
        target => p_target,
        sofar => p_sofar,
        totalwork => p_totalwork,
        units => 'objects'
    );
END;
```

### Performance Metrics Collection

```sql
CREATE TABLE PERFORMANCE_METRICS (
    METRIC_ID           NUMBER PRIMARY KEY,
    OPERATION_TYPE      VARCHAR2(50),
    SCHEMA_NAME         VARCHAR2(128),
    OBJECTS_PROCESSED   NUMBER,
    START_TIME          TIMESTAMP,
    END_TIME            TIMESTAMP,
    DURATION_SECONDS    NUMBER,
    CPU_TIME_SECONDS    NUMBER,
    IO_WAIT_SECONDS     NUMBER,
    BYTES_PROCESSED     NUMBER,
    THROUGHPUT_MBPS     NUMBER
);

-- Capture metrics during execution
PROCEDURE capture_performance_metrics(
    p_operation_type VARCHAR2,
    p_start_time TIMESTAMP,
    p_end_time TIMESTAMP,
    p_objects_processed NUMBER
);
```

## Security Architecture

### Role-Based Access Control

```sql
-- Create dedicated role
CREATE ROLE COMPRESSION_MGR_ROLE;

-- Grant minimum required privileges
GRANT SELECT ON DBA_TABLES TO COMPRESSION_MGR_ROLE;
GRANT SELECT ON DBA_TAB_PARTITIONS TO COMPRESSION_MGR_ROLE;
GRANT SELECT ON DBA_SEGMENTS TO COMPRESSION_MGR_ROLE;
GRANT SELECT ON ALL_TAB_MODIFICATIONS TO COMPRESSION_MGR_ROLE;
GRANT SELECT ON DBA_HIST_SEG_STAT TO COMPRESSION_MGR_ROLE;
GRANT EXECUTE ON DBMS_COMPRESSION TO COMPRESSION_MGR_ROLE;

-- Application schema ownership
GRANT COMPRESSION_MGR_ROLE TO COMPRESSION_MGR;
```

### Package Security

```sql
-- Use AUTHID CURRENT_USER for invoker rights
CREATE OR REPLACE PACKAGE ADVISOR_PKG AUTHID CURRENT_USER AS
    -- Package specification
END;

-- Validate caller permissions
FUNCTION validate_caller_privilege(
    p_schema VARCHAR2,
    p_operation VARCHAR2
) RETURN BOOLEAN IS
    v_is_owner BOOLEAN;
    v_has_dba BOOLEAN;
BEGIN
    -- Check if caller owns schema
    SELECT 1 INTO v_is_owner
    FROM dual
    WHERE USER = p_schema;

    -- Check for DBA privilege
    SELECT 1 INTO v_has_dba
    FROM session_privs
    WHERE privilege = 'DBA';

    RETURN (v_is_owner OR v_has_dba);
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        RETURN FALSE;
END;
```

### Audit Logging

```sql
CREATE TABLE OPERATION_LOG (
    LOG_ID              NUMBER PRIMARY KEY,
    OPERATION_TYPE      VARCHAR2(50),
    OPERATION_DETAILS   CLOB,
    CALLER_USER         VARCHAR2(128),
    CALLER_IP           VARCHAR2(45),
    CALLER_PROGRAM      VARCHAR2(64),
    SUCCESS_FLAG        VARCHAR2(1),
    ERROR_MESSAGE       VARCHAR2(4000),
    LOGGED_AT           TIMESTAMP
);

-- Log all operations
PROCEDURE log_operation(
    p_operation_type VARCHAR2,
    p_details CLOB,
    p_success BOOLEAN,
    p_error_msg VARCHAR2 DEFAULT NULL
);
```

## Error Handling Strategy

### Custom Exception Framework

```sql
-- Define custom exceptions
e_insufficient_space    EXCEPTION;
e_invalid_compression   EXCEPTION;
e_object_locked         EXCEPTION;
e_privilege_denied      EXCEPTION;

PRAGMA EXCEPTION_INIT(e_insufficient_space, -1652);
PRAGMA EXCEPTION_INIT(e_object_locked, -54);

-- Centralized error handler
PROCEDURE handle_error(
    p_error_code NUMBER,
    p_error_msg VARCHAR2,
    p_context VARCHAR2
) IS
BEGIN
    INSERT INTO ERROR_LOG (
        error_code,
        error_message,
        error_context,
        error_backtrace,
        logged_at
    ) VALUES (
        p_error_code,
        p_error_msg,
        p_context,
        DBMS_UTILITY.FORMAT_ERROR_BACKTRACE,
        SYSTIMESTAMP
    );

    COMMIT;
    RAISE_APPLICATION_ERROR(-20000,
        'Compression operation failed: ' || p_error_msg);
END;
```

### Graceful Degradation

```sql
-- Continue processing on individual failures
FOR rec IN cursor_objects LOOP
    BEGIN
        process_object(rec);
    EXCEPTION
        WHEN OTHERS THEN
            log_error(rec, SQLERRM);
            CONTINUE;  -- Skip to next object
    END;
END LOOP;
```

## Deployment Architecture

### Schema Structure

```
COMPRESSION_MGR (Application Schema)
├── Tables
│   ├── COMPRESSION_ANALYSIS_RESULTS
│   ├── COMPRESSION_HISTORY
│   ├── ADVISOR_RUN
│   ├── COMPRESSION_STRATEGIES
│   ├── COMPRESSION_THRESHOLDS
│   ├── OPERATION_LOG
│   ├── ERROR_LOG
│   └── PERFORMANCE_METRICS
│
├── Packages
│   ├── ADVISOR_PKG (Specification & Body)
│   └── EXECUTOR_PKG (Specification & Body)
│
├── Views
│   ├── V_COMPRESSION_CANDIDATES
│   ├── V_COMPRESSION_SUMMARY
│   ├── V_HOT_OBJECTS
│   ├── V_ARCHIVE_CANDIDATES
│   ├── V_COMPRESSION_HISTORY
│   ├── V_SPACE_SAVINGS
│   ├── V_COMPRESSION_EFFECTIVENESS
│   └── V_COMPRESSION_TRENDS
│
├── Sequences
│   ├── SEQ_ADVISOR_RUN_ID
│   ├── SEQ_EXECUTION_ID
│   └── SEQ_METRIC_ID
│
└── Indexes
    ├── Performance indexes on lookup columns
    └── Partitioned indexes on date columns
```

### Installation Process

```sql
-- 1. Create schema and role
CREATE USER COMPRESSION_MGR IDENTIFIED BY <secure_password>
    DEFAULT TABLESPACE USERS
    QUOTA UNLIMITED ON USERS;

CREATE ROLE COMPRESSION_MGR_ROLE;

-- 2. Grant system privileges
GRANT CREATE SESSION TO COMPRESSION_MGR;
GRANT CREATE TABLE TO COMPRESSION_MGR;
GRANT CREATE VIEW TO COMPRESSION_MGR;
GRANT CREATE PROCEDURE TO COMPRESSION_MGR;
GRANT CREATE SEQUENCE TO COMPRESSION_MGR;

-- 3. Grant data dictionary access
GRANT SELECT_CATALOG_ROLE TO COMPRESSION_MGR_ROLE;
GRANT EXECUTE ON DBMS_COMPRESSION TO COMPRESSION_MGR_ROLE;

-- 4. Run installation script
@install_compression_mgr.sql

-- 5. Configure ORDS
@configure_ords_endpoints.sql

-- 6. Load default strategies
@load_default_strategies.sql
```

### Version Management

```sql
CREATE TABLE SYSTEM_VERSION (
    VERSION_NUMBER      VARCHAR2(20),
    INSTALLED_DATE      DATE,
    INSTALLED_BY        VARCHAR2(128),
    DESCRIPTION         VARCHAR2(500)
);

-- Track package versions
CREATE OR REPLACE PACKAGE ADVISOR_PKG AS
    c_version CONSTANT VARCHAR2(20) := '1.0.0';
    -- Package specification
END;
```

## Integration Points

### 1. Oracle Data Dictionary Integration

```
ALL_TABLES ─────────┐
ALL_TAB_PARTITIONS ─┤
ALL_SEGMENTS ───────┼──→ ADVISOR_PKG.analyse_*
ALL_TAB_MODIFICATIONS ──┤
DBA_HIST_SEG_STAT ──────┘
```

### 2. DBMS_COMPRESSION API

```
ADVISOR_PKG.calculate_compression_ratios
    ↓
DBMS_COMPRESSION.GET_COMPRESSION_RATIO
    ├── COMP_FOR_OLTP (1)
    ├── COMP_FOR_QUERY_LOW (2)
    ├── COMP_FOR_QUERY_HIGH (3)
    ├── COMP_FOR_ARCHIVE_LOW (4)
    └── COMP_FOR_ARCHIVE_HIGH (5)
```

### 3. ORDS REST Services

```
External Dashboard (Streamlit)
    ↓ HTTPS/JSON
ORDS REST Endpoints
    ↓ SQL Execution
ADVISOR_PKG / EXECUTOR_PKG
    ↓ DML
COMPRESSION_ANALYSIS_RESULTS / COMPRESSION_HISTORY
```

### 4. DBMS_SCHEDULER Integration

```sql
-- Schedule nightly analysis
BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name => 'NIGHTLY_COMPRESSION_ANALYSIS',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN COMPRESSION_MGR.ADVISOR_PKG.analyse_all_user_obj_p(NULL); END;',
        start_date => TRUNC(SYSDATE) + 1 + 2/24,  -- 2 AM daily
        repeat_interval => 'FREQ=DAILY',
        enabled => TRUE,
        comments => 'Daily compression analysis for all user schemas'
    );
END;
/
```

### 5. Streamlit Dashboard Integration

```
Dashboard Component Flow:
┌─────────────────────────────────────────┐
│  Streamlit Dashboard (Python)          │
│  - Authentication (ORDS OAuth2)        │
│  - Schema Selection                     │
│  - Analysis Trigger                     │
│  - Real-time Status Polling             │
│  - Report Visualization                 │
└───────────────┬─────────────────────────┘
                ↓ HTTPS REST API
┌─────────────────────────────────────────┐
│  ORDS REST Services                     │
│  /compression/v1/*                      │
└───────────────┬─────────────────────────┘
                ↓ PL/SQL Execution
┌─────────────────────────────────────────┐
│  COMPRESSION_MGR Packages               │
│  - ADVISOR_PKG                          │
│  - EXECUTOR_PKG                         │
└─────────────────────────────────────────┘
```

## Scalability Considerations

### Horizontal Scalability

- **Schema-level Parallelism**: Multiple schemas analyzed concurrently
- **Object-level Parallelism**: Tables within schema processed in parallel
- **Partition-level Parallelism**: Large partitioned tables split across workers

### Vertical Scalability

- **Adaptive Sampling**: Sample size scales with table size
- **Incremental Processing**: Only analyze changed objects
- **Result Caching**: Cache compression ratios for stable objects
- **Batch Size Tuning**: Dynamic batch sizes based on available resources

### Resource Management

```sql
-- Resource consumer group for compression operations
BEGIN
    DBMS_RESOURCE_MANAGER.CREATE_CONSUMER_GROUP(
        consumer_group => 'COMPRESSION_OPERATIONS',
        comment => 'Resource group for compression analysis/execution'
    );

    DBMS_RESOURCE_MANAGER.CREATE_PLAN_DIRECTIVE(
        plan => 'DEFAULT_PLAN',
        group_or_subplan => 'COMPRESSION_OPERATIONS',
        cpu_p1 => 20,  -- 20% CPU allocation
        parallel_degree_limit_p1 => 4
    );
END;
/

-- Set consumer group for compression sessions
EXEC DBMS_SESSION.SWITCH_CURRENT_CONSUMER_GROUP('COMPRESSION_OPERATIONS', NULL, FALSE);
```

## Technology Stack

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Database** | Oracle Database | 19c (19.20+) | Core platform |
| **Language** | PL/SQL | 19c | Business logic |
| **API** | Oracle REST Data Services | 20.4+ | REST endpoints |
| **Dashboard** | Streamlit | Latest | Web interface |
| **Python Client** | python-oracledb | Latest | Database connectivity |
| **Deployment** | Docker | Latest | Oracle 23c Free container |
| **Protocol** | HTTPS/TLS | 1.2+ | Secure communication |

## Non-Functional Requirements

### Performance Requirements

- **Analysis Throughput**: 1000+ tables in <30 minutes
- **Compression Execution**: Based on object size, not fixed time
- **API Response Time**: <2 seconds for reporting endpoints
- **Dashboard Load Time**: <5 seconds initial, <1 second refresh

### Reliability Requirements

- **Data Integrity**: Zero data loss, transactional consistency
- **Error Recovery**: Automatic rollback on failures
- **Availability**: 99.9% uptime for analysis services
- **Audit Trail**: 100% operation tracking

### Security Requirements

- **Authentication**: ORDS OAuth2 or database authentication
- **Authorization**: Role-based access control
- **Encryption**: TLS 1.2+ for all communications
- **Audit**: Comprehensive logging of all operations

### Maintainability Requirements

- **Code Quality**: Comprehensive inline documentation
- **Modularity**: Packages <2000 lines, procedures <200 lines
- **Testing**: Unit tests for all public procedures
- **Versioning**: Semantic versioning (MAJOR.MINOR.PATCH)

## Future Enhancements

### Phase 2 Capabilities

1. **Machine Learning Integration**
   - Pattern recognition for compression effectiveness
   - Predictive modeling for optimal compression timing
   - Anomaly detection for unusual storage growth

2. **Advanced Scheduling**
   - Workload-aware execution windows
   - Automatic rescheduling on high database load
   - Calendar-based execution policies

3. **Multi-PDB Support**
   - Cross-PDB analysis and reporting
   - Centralized management console
   - PDB-level resource allocation

4. **Enhanced Monitoring**
   - Real-time compression progress dashboards
   - Email/SMS alerting on completion or errors
   - Integration with enterprise monitoring tools

5. **What-If Analysis**
   - Simulate compression scenarios
   - ROI calculators
   - Capacity planning integration

## Conclusion

The HCC Compression Advisor architecture provides a robust, scalable, and maintainable solution for managing Oracle Database compression. The layered design ensures separation of concerns, while the modular package structure enables independent development and testing. Integration with ORDS provides seamless REST API access for the Streamlit dashboard and other automation tools.

The system achieves the critical balance between storage efficiency and performance impact, with comprehensive safety mechanisms and audit trails to ensure enterprise-grade reliability.

**Architecture Version**: 1.0.0
**Last Updated**: 2025-11-13
**Status**: Architecture Design Complete
