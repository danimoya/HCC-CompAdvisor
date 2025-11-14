# HCC Compression Advisor - Integration Flows

## Overview

This document details the integration workflows, process flows, and data flows for the HCC Compression Advisor system. It covers interactions between components, external systems, and data movement through the architecture.

## System Integration Points

```
┌──────────────────────────────────────────────────────────────────────┐
│                    External Integration Points                        │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌────────────────┐   ┌──────────────┐   ┌───────────────────────┐  │
│  │  Streamlit     │   │  DBMS_       │   │  Enterprise           │  │
│  │  Dashboard     │   │  SCHEDULER   │   │  Monitoring           │  │
│  │                │   │              │   │  (OEM, Grafana, etc.) │  │
│  │  - Python      │   │  - Automated │   │  - Metrics Export     │  │
│  │  - oracledb    │   │    Analysis  │   │  - Alert Integration  │  │
│  │  - HTTPS/TLS   │   │  - Scheduled │   │  - REST APIs          │  │
│  │  - OAuth2      │   │    Compress  │   │                       │  │
│  └────────┬───────┘   └──────┬───────┘   └───────────┬───────────┘  │
│           │                  │                       │               │
└───────────┼──────────────────┼───────────────────────┼───────────────┘
            │                  │                       │
            ↓                  ↓                       ↓
┌──────────────────────────────────────────────────────────────────────┐
│                    ORDS REST Data Services Layer                      │
│                     (Oracle REST Interface)                           │
└──────────────────────────────────────────────────────────────────────┘
            ↓                  ↓                       ↓
┌──────────────────────────────────────────────────────────────────────┐
│                    PL/SQL Application Layer                           │
│                  (ADVISOR_PKG / EXECUTOR_PKG)                         │
└──────────────────────────────────────────────────────────────────────┘
            ↓                  ↓                       ↓
┌──────────────────────────────────────────────────────────────────────┐
│                   Oracle Database Services                            │
│  ┌──────────────┐  ┌───────────────┐  ┌─────────────────────────┐   │
│  │ DBMS_        │  │ Data          │  │ AWR / ASH               │   │
│  │ COMPRESSION  │  │ Dictionary    │  │ Statistics              │   │
│  └──────────────┘  └───────────────┘  └─────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

## Primary Integration Flows

### Flow 1: Streamlit Dashboard Integration

#### 1.1 Dashboard Authentication Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  Streamlit Dashboard Startup Sequence                               │
└─────────────────────────────────────────────────────────────────────┘

1. User accesses https://dashboard:8443
   ↓
2. Dashboard presents login form
   ↓
3. User enters credentials
   ↓
4. Dashboard establishes DB connection:
   ┌─────────────────────────────────────────────┐
   │  import oracledb                            │
   │  import ssl                                 │
   │                                             │
   │  # SSL Context for self-signed cert        │
   │  ssl_context = ssl.create_default_context()│
   │  ssl_context.check_hostname = False        │
   │  ssl_context.verify_mode = ssl.CERT_NONE   │
   │                                             │
   │  # Database connection                     │
   │  connection = oracledb.connect(            │
   │      user="compression_mgr",               │
   │      password=user_password,               │
   │      dsn="exacc-scan:1521/pdb_name",       │
   │      ssl_context=ssl_context               │
   │  )                                          │
   └─────────────────────────────────────────────┘
   ↓
5. Validate user privileges
   ↓
6. Load dashboard home page
   ↓
7. Establish session state
```

#### 1.2 Analysis Trigger Flow (Dashboard → ORDS → PL/SQL)

```
┌─────────────────────────────────────────────────────────────────────┐
│  User Initiates Analysis from Dashboard                             │
└─────────────────────────────────────────────────────────────────────┘

[Streamlit Dashboard]
    │
    │ 1. User selects schema and clicks "Analyze"
    ↓
┌───────────────────────────────────────┐
│  Python Code (streamlit app)          │
├───────────────────────────────────────┤
│  import requests                      │
│  import json                          │
│                                       │
│  payload = {                          │
│      "owner": selected_schema,        │
│      "sample_size": 1000000,          │
│      "parallel_degree": 4,            │
│      "strategy_id": 2                 │
│  }                                    │
│                                       │
│  response = requests.post(            │
│      url="https://ords-host/ords/    │
│           compression/v1/advisor/    │
│           tables",                    │
│      json=payload,                    │
│      headers={                        │
│          "Content-Type":              │
│              "application/json"       │
│      },                               │
│      auth=(username, password),       │
│      verify=False  # self-signed cert │
│  )                                    │
│                                       │
│  result = response.json()             │
└───────────┬───────────────────────────┘
            │
            │ 2. HTTPS POST to ORDS endpoint
            ↓
┌───────────────────────────────────────┐
│  ORDS REST Handler                    │
├───────────────────────────────────────┤
│  POST /compression/v1/advisor/tables  │
│                                       │
│  Handler executes:                    │
│  BEGIN                                │
│      :run_id :=                       │
│          COMPRESSION_MGR.ADVISOR_PKG. │
│          analyse_tables_p(            │
│              p_owner => :owner,       │
│              p_sample_size =>         │
│                  :sample_size,        │
│              p_parallel_degree =>     │
│                  :parallel_degree,    │
│              p_strategy_id =>         │
│                  :strategy_id         │
│          );                           │
│      :status := 'SUCCESS';            │
│  EXCEPTION                            │
│      WHEN OTHERS THEN                 │
│          :status := 'ERROR';          │
│          :error_msg := SQLERRM;       │
│  END;                                 │
└───────────┬───────────────────────────┘
            │
            │ 3. PL/SQL procedure execution
            ↓
┌───────────────────────────────────────┐
│  ADVISOR_PKG.analyse_tables_p         │
├───────────────────────────────────────┤
│  1. Validate input parameters         │
│  2. Create ADVISOR_RUN record         │
│  3. Load active strategy config       │
│  4. Enable parallel execution         │
│  5. Loop through tables:              │
│     a. Get compression ratios         │
│     b. Analyze DML activity           │
│     c. Calculate hotness score        │
│     d. Generate recommendation        │
│     e. Save to ANALYSIS_RESULTS       │
│  6. Update run statistics             │
│  7. Return run_id                     │
└───────────┬───────────────────────────┘
            │
            │ 4. Return JSON response
            ↓
┌───────────────────────────────────────┐
│  JSON Response                        │
├───────────────────────────────────────┤
│  {                                    │
│      "status": "SUCCESS",             │
│      "run_id": 12345,                 │
│      "objects_analyzed": 847,         │
│      "duration_minutes": 12.5,        │
│      "recommendations": {             │
│          "oltp": 125,                 │
│          "query_low": 342,            │
│          "query_high": 198,           │
│          "archive_low": 87,           │
│          "archive_high": 45,          │
│          "none": 50                   │
│      }                                │
│  }                                    │
└───────────┬───────────────────────────┘
            │
            │ 5. Dashboard processes response
            ↓
[Streamlit Dashboard]
    │
    │ 6. Update UI with results
    │ 7. Display analysis summary
    │ 8. Enable compression execution
    ↓
[User reviews recommendations]
```

#### 1.3 Real-time Status Polling Flow

```
[Dashboard initiates polling]
    │
    │ Every 5 seconds while analysis running:
    ↓
GET /compression/v1/advisor/status/{run_id}
    │
    ↓
SELECT run_status, objects_analyzed,
       objects_succeeded, objects_failed,
       (SYSDATE - start_time) * 24 * 60 as minutes_elapsed
FROM advisor_run
WHERE run_id = :run_id;
    │
    ↓
[Return JSON status]
    │
    ↓
{
    "run_id": 12345,
    "status": "RUNNING",
    "progress_pct": 67,
    "objects_analyzed": 567,
    "objects_total": 847,
    "elapsed_minutes": 8.2,
    "estimated_remaining_minutes": 4.3
}
    │
    ↓
[Dashboard updates progress bar]
```

### Flow 2: Compression Execution Flow

#### 2.1 Interactive Compression Execution

```
┌─────────────────────────────────────────────────────────────────────┐
│  User Initiates Compression from Dashboard                          │
└─────────────────────────────────────────────────────────────────────┘

[Dashboard displays compression candidates]
    │
    │ User selects objects and clicks "Compress"
    ↓
┌───────────────────────────────────────┐
│  Dashboard Validation                 │
├───────────────────────────────────────┤
│  • Confirm user selection             │
│  • Display estimated space savings    │
│  • Show expected downtime (if offline)│
│  • Request final confirmation         │
└───────────┬───────────────────────────┘
            │
            │ User confirms
            ↓
┌───────────────────────────────────────┐
│  POST /compression/v1/execute/        │
│       compress                        │
├───────────────────────────────────────┤
│  {                                    │
│      "owner": "APP_SCHEMA",           │
│      "object_name": "LARGE_ORDERS",   │
│      "object_type": "TABLE",          │
│      "partition_name": null,          │
│      "compression_type": "QUERY_HIGH",│
│      "parallel": 4,                   │
│      "online": true,                  │
│      "verify_only": false             │
│  }                                    │
└───────────┬───────────────────────────┘
            │
            ↓
┌───────────────────────────────────────┐
│  EXECUTOR_PKG.compress_segment_p      │
├───────────────────────────────────────┤
│  STEP 1: Pre-execution validation     │
│  ┌─────────────────────────────────┐ │
│  │ • Check object exists           │ │
│  │ • Validate compression type     │ │
│  │ • Check object lock (NOWAIT)    │ │
│  │ • Verify privileges             │ │
│  │ • Check tablespace space        │ │
│  └─────────────────────────────────┘ │
│                                       │
│  STEP 2: Capture before metrics      │
│  ┌─────────────────────────────────┐ │
│  │ SELECT SUM(bytes), SUM(blocks)  │ │
│  │ FROM dba_segments               │ │
│  │ WHERE owner = p_owner           │ │
│  │   AND segment_name =            │ │
│  │       p_object_name;            │ │
│  │                                 │ │
│  │ → original_size_bytes           │ │
│  │ → original_blocks               │ │
│  └─────────────────────────────────┘ │
│                                       │
│  STEP 3: Create history record       │
│  ┌─────────────────────────────────┐ │
│  │ INSERT INTO compression_history │ │
│  │ (owner, object_name,            │ │
│  │  compression_type_applied,      │ │
│  │  original_size_bytes,           │ │
│  │  execution_status,              │ │
│  │  start_time)                    │ │
│  │ VALUES (...)                    │ │
│  │ RETURNING execution_id          │ │
│  │ INTO v_execution_id;            │ │
│  └─────────────────────────────────┘ │
│                                       │
│  STEP 4: Generate DDL                │
│  ┌─────────────────────────────────┐ │
│  │ v_ddl := 'ALTER TABLE ' ||      │ │
│  │          p_owner || '.' ||      │ │
│  │          p_object_name ||       │ │
│  │          ' MOVE ONLINE ' ||     │ │
│  │          'COLUMN STORE ' ||     │ │
│  │          'COMPRESS FOR ' ||     │ │
│  │          p_compression_type ||  │ │
│  │          ' PARALLEL ' ||        │ │
│  │          p_parallel;            │ │
│  └─────────────────────────────────┘ │
│                                       │
│  STEP 5: Execute with monitoring     │
│  ┌─────────────────────────────────┐ │
│  │ DBMS_APPLICATION_INFO.          │ │
│  │     SET_MODULE(                 │ │
│  │         'COMPRESSION_ADVISOR',  │ │
│  │         'Compressing ' ||       │ │
│  │         p_object_name);         │ │
│  │                                 │ │
│  │ EXECUTE IMMEDIATE v_ddl;        │ │
│  └─────────────────────────────────┘ │
│                                       │
│  STEP 6: Rebuild indexes             │
│  ┌─────────────────────────────────┐ │
│  │ FOR idx IN (                    │ │
│  │   SELECT index_name             │ │
│  │   FROM all_indexes              │ │
│  │   WHERE table_owner = p_owner   │ │
│  │     AND table_name =            │ │
│  │         p_object_name           │ │
│  │ ) LOOP                          │ │
│  │   v_idx_ddl := 'ALTER INDEX '|| │ │
│  │                idx.index_name|| │ │
│  │                ' REBUILD '||    │ │
│  │                ' ONLINE PARALLEL│ │
│  │                ' || p_parallel; │ │
│  │   EXECUTE IMMEDIATE v_idx_ddl;  │ │
│  │ END LOOP;                       │ │
│  └─────────────────────────────────┘ │
│                                       │
│  STEP 7: Capture after metrics       │
│  ┌─────────────────────────────────┐ │
│  │ SELECT SUM(bytes), SUM(blocks)  │ │
│  │ FROM dba_segments               │ │
│  │ WHERE owner = p_owner           │ │
│  │   AND segment_name =            │ │
│  │       p_object_name;            │ │
│  │                                 │ │
│  │ → compressed_size_bytes         │ │
│  │ → compressed_blocks             │ │
│  └─────────────────────────────────┘ │
│                                       │
│  STEP 8: Update history              │
│  ┌─────────────────────────────────┐ │
│  │ UPDATE compression_history      │ │
│  │ SET compressed_size_bytes = ...,│ │
│  │     compression_ratio_achieved  │ │
│  │         = original / compressed,│ │
│  │     end_time = SYSTIMESTAMP,    │ │
│  │     execution_status = 'SUCCESS'│ │
│  │ WHERE execution_id =            │ │
│  │       v_execution_id;           │ │
│  └─────────────────────────────────┘ │
│                                       │
│  STEP 9: Return results              │
│  ┌─────────────────────────────────┐ │
│  │ RETURN JSON_PKG.                │ │
│  │     execution_result_to_json(   │ │
│  │         v_execution_id);        │ │
│  └─────────────────────────────────┘ │
└───────────┬───────────────────────────┘
            │
            ↓
┌───────────────────────────────────────┐
│  JSON Response to Dashboard           │
├───────────────────────────────────────┤
│  {                                    │
│      "status": "SUCCESS",             │
│      "execution_id": 98765,           │
│      "object_name": "LARGE_ORDERS",   │
│      "compression_type": "QUERY_HIGH",│
│      "original_size_mb": 102400,      │
│      "compressed_size_mb": 20480,     │
│      "space_saved_mb": 81920,         │
│      "space_saved_pct": 80.0,         │
│      "compression_ratio": 5.0,        │
│      "duration_seconds": 1847,        │
│      "indexes_rebuilt": 8             │
│  }                                    │
└───────────┬───────────────────────────┘
            │
            ↓
[Dashboard displays success message and metrics]
```

#### 2.2 Batch Compression Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  Batch Compression Execution (Multiple Objects)                     │
└─────────────────────────────────────────────────────────────────────┘

[Dashboard: User selects multiple objects]
    │
    │ Batch compression request
    ↓
POST /compression/v1/execute/batch
{
    "schema": "APP_SCHEMA",
    "threshold_ratio": 2.0,
    "max_concurrent": 2,
    "objects": [
        {"name": "TABLE1", "type": "QUERY_HIGH"},
        {"name": "TABLE2", "type": "QUERY_LOW"},
        {"name": "TABLE3", "type": "ARCHIVE_HIGH"}
    ]
}
    │
    ↓
EXECUTOR_PKG.compress_batch_p
    │
    ├─→ Prioritize objects by hotness (coldest first)
    │
    ├─→ Create job queue
    │
    └─→ For each object:
        │
        ├─→ Check concurrent job count
        │   │
        │   └─→ If >= max_concurrent:
        │       └─→ Wait 5 seconds and recheck
        │
        ├─→ Create DBMS_SCHEDULER job:
        │   │
        │   DBMS_SCHEDULER.CREATE_JOB(
        │       job_name => 'COMPRESS_TABLE1_20251113142530',
        │       job_type => 'PLSQL_BLOCK',
        │       job_action => 'BEGIN
        │           EXECUTOR_PKG.compress_segment_p(...);
        │       END;',
        │       start_date => SYSTIMESTAMP,
        │       enabled => TRUE,
        │       auto_drop => TRUE
        │   );
        │
        └─→ Increment job counter
    │
    ↓
[Dashboard polls batch status]
    │
    │ Every 10 seconds:
    ↓
GET /compression/v1/execute/batch/status/{batch_id}
    │
    ↓
{
    "batch_id": "BATCH_12345",
    "total_objects": 3,
    "completed": 1,
    "in_progress": 1,
    "pending": 1,
    "failed": 0,
    "total_space_saved_mb": 35000,
    "elapsed_minutes": 18.5
}
```

### Flow 3: DBMS_SCHEDULER Automation Flow

#### 3.1 Scheduled Nightly Analysis

```
┌─────────────────────────────────────────────────────────────────────┐
│  Automated Nightly Analysis Job                                     │
└─────────────────────────────────────────────────────────────────────┘

[Job Creation - One-time setup]
    │
    ↓
BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name => 'NIGHTLY_COMPRESSION_ANALYSIS',
        job_type => 'PLSQL_BLOCK',
        job_action => '
            DECLARE
                v_run_id NUMBER;
            BEGIN
                -- Analyze all user schemas
                FOR schema_rec IN (
                    SELECT username
                    FROM dba_users
                    WHERE oracle_maintained = ''N''
                      AND username NOT IN (
                          ''COMPRESSION_MGR'',
                          ''ORDS_METADATA''
                      )
                ) LOOP
                    v_run_id := COMPRESSION_MGR.ADVISOR_PKG.
                                analyse_all_user_obj_p(
                                    p_owner => schema_rec.username,
                                    p_incremental => TRUE
                                );
                END LOOP;

                COMMIT;
            EXCEPTION
                WHEN OTHERS THEN
                    COMPRESSION_MGR.LOGGING_PKG.log_error(
                        p_error_code => SQLCODE,
                        p_error_msg => SQLERRM,
                        p_error_context => ''Nightly Analysis Job''
                    );
                    RAISE;
            END;
        ',
        start_date => TRUNC(SYSDATE) + 1 + 2/24,  -- 2 AM tomorrow
        repeat_interval => 'FREQ=DAILY; BYHOUR=2; BYMINUTE=0',
        enabled => TRUE,
        comments => 'Daily incremental compression analysis for all user schemas'
    );

    -- Set job priority and resource allocation
    DBMS_SCHEDULER.SET_ATTRIBUTE(
        name => 'NIGHTLY_COMPRESSION_ANALYSIS',
        attribute => 'RESOURCE_CONSUMER_GROUP',
        value => 'COMPRESSION_OPERATIONS'
    );

    -- Enable logging
    DBMS_SCHEDULER.SET_ATTRIBUTE(
        name => 'NIGHTLY_COMPRESSION_ANALYSIS',
        attribute => 'LOGGING_LEVEL',
        value => DBMS_SCHEDULER.LOGGING_FULL
    );
END;
/

[Job Execution Flow - Nightly at 2 AM]
    │
    │ DBMS_SCHEDULER triggers job
    ↓
[Job Starts]
    │
    ├─→ Loop through user schemas
    │   │
    │   └─→ For each schema:
    │       │
    │       ├─→ ADVISOR_PKG.analyse_all_user_obj_p(
    │       │       p_owner => schema,
    │       │       p_incremental => TRUE
    │       │   )
    │       │
    │       ├─→ Only re-analyze objects modified
    │       │   in last 24 hours
    │       │
    │       └─→ Update recommendations
    │
    ├─→ COMMIT results
    │
    └─→ Log completion
    │
    ↓
[Job Completes]
    │
    │ Results available next morning in dashboard
    ↓
[Users review updated recommendations]
```

#### 3.2 Scheduled Compression Execution (Maintenance Window)

```
┌─────────────────────────────────────────────────────────────────────┐
│  Automated Compression During Maintenance Window                    │
└─────────────────────────────────────────────────────────────────────┘

[Job Creation]
    │
    ↓
BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name => 'WEEKEND_COMPRESSION_BATCH',
        job_type => 'PLSQL_BLOCK',
        job_action => '
            BEGIN
                COMPRESSION_MGR.EXECUTOR_PKG.compress_batch_p(
                    p_schema_name => ''APP_SCHEMA'',
                    p_threshold_ratio => 2.5,
                    p_max_concurrent => 4
                );
            END;
        ',
        start_date => NEXT_DAY(TRUNC(SYSDATE), 'SATURDAY') + 22/24,
        repeat_interval => 'FREQ=WEEKLY; BYDAY=SAT; BYHOUR=22',
        enabled => TRUE,
        comments => 'Weekend batch compression at 10 PM Saturday'
    );
END;
/

[Execution Flow - Saturday 10 PM]
    │
    ↓
[Get compression candidates]
    │
    ↓
SELECT owner, object_name, advisable_compression,
       best_ratio, hotness_score
FROM compression_analysis_results
WHERE advisable_compression != 'NONE'
  AND best_ratio >= 2.5
ORDER BY hotness_score ASC  -- Coldest objects first
    │
    ↓
[Spawn concurrent jobs]
    │
    ├─→ Job 1: COMPRESS_TABLE_A (ARCHIVE_HIGH)
    ├─→ Job 2: COMPRESS_TABLE_B (QUERY_HIGH)
    ├─→ Job 3: COMPRESS_TABLE_C (QUERY_LOW)
    └─→ Job 4: COMPRESS_TABLE_D (OLTP)
    │
    │ (Max 4 concurrent as configured)
    ↓
[Monitor job completion]
    │
    ├─→ As each job completes, start next
    │
    └─→ Continue until all candidates processed
    │
    ↓
[Generate summary report]
    │
    ↓
INSERT INTO PERFORMANCE_METRICS (
    metric_type,
    metric_name,
    metric_value,
    metric_context
) VALUES (
    'BATCH_COMPRESSION',
    'TOTAL_SPACE_SAVED_GB',
    v_total_saved_gb,
    'Weekend Batch - ' || TO_CHAR(SYSDATE, 'YYYY-MM-DD')
);
```

### Flow 4: Oracle Data Dictionary Integration

#### 4.1 Metadata Collection Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  Data Dictionary Query Integration                                  │
└─────────────────────────────────────────────────────────────────────┘

[ADVISOR_PKG Analysis Execution]
    │
    ↓
┌───────────────────────────────────────┐
│  Query 1: Discover Objects            │
├───────────────────────────────────────┤
│  SELECT owner, table_name,            │
│         num_rows, blocks,             │
│         avg_row_len, last_analyzed,   │
│         compression,                  │
│         tablespace_name               │
│  FROM all_tables                      │
│  WHERE owner = p_schema               │
│    AND owner NOT IN (                 │
│        SELECT username                │
│        FROM dba_users                 │
│        WHERE oracle_maintained = 'Y'  │
│    )                                  │
│    AND temporary = 'N'                │
│    AND nested = 'N'                   │
│  ORDER BY num_rows DESC;              │
└───────────┬───────────────────────────┘
            │
            ↓ For each table
┌───────────────────────────────────────┐
│  Query 2: Get Partition Info          │
├───────────────────────────────────────┤
│  SELECT partition_name,               │
│         subpartition_name,            │
│         num_rows, blocks,             │
│         compression                   │
│  FROM all_tab_partitions              │
│  WHERE table_owner = p_owner          │
│    AND table_name = p_table           │
│  UNION ALL                            │
│  SELECT partition_name,               │
│         subpartition_name,            │
│         num_rows, blocks,             │
│         compression                   │
│  FROM all_tab_subpartitions           │
│  WHERE table_owner = p_owner          │
│    AND table_name = p_table;          │
└───────────┬───────────────────────────┘
            │
            ↓
┌───────────────────────────────────────┐
│  Query 3: Get DML Statistics          │
├───────────────────────────────────────┤
│  SELECT inserts, updates, deletes,    │
│         timestamp,                    │
│         truncated                     │
│  FROM all_tab_modifications           │
│  WHERE table_owner = p_owner          │
│    AND table_name = p_table           │
│    AND partition_name IS NULL         │
│  ORDER BY timestamp DESC              │
│  FETCH FIRST 1 ROW ONLY;              │
└───────────┬───────────────────────────┘
            │
            ↓
┌───────────────────────────────────────┐
│  Query 4: Get Access Patterns (AWR)   │
├───────────────────────────────────────┤
│  SELECT SUM(logical_reads_delta)      │
│             as logical_reads,         │
│         SUM(physical_reads_delta)     │
│             as physical_reads,        │
│         MAX(snap_time)                │
│             as last_access            │
│  FROM dba_hist_seg_stat dhss          │
│  JOIN dba_hist_snapshot dhs           │
│       ON dhss.snap_id = dhs.snap_id   │
│  WHERE dhss.owner = p_owner           │
│    AND dhss.object_name = p_table     │
│    AND dhs.begin_interval_time >      │
│        SYSDATE - 30                   │
│  GROUP BY dhss.owner,                 │
│           dhss.object_name;           │
└───────────┬───────────────────────────┘
            │
            ↓
┌───────────────────────────────────────┐
│  Query 5: Get Segment Size            │
├───────────────────────────────────────┤
│  SELECT SUM(bytes) as total_bytes,    │
│         SUM(blocks) as total_blocks   │
│  FROM dba_segments                    │
│  WHERE owner = p_owner                │
│    AND segment_name = p_table         │
│    AND segment_type LIKE 'TABLE%';    │
└───────────┬───────────────────────────┘
            │
            ↓
[Combine all metrics into analysis record]
```

#### 4.2 DBMS_COMPRESSION API Integration

```
┌─────────────────────────────────────────────────────────────────────┐
│  Compression Ratio Calculation Using DBMS_COMPRESSION               │
└─────────────────────────────────────────────────────────────────────┘

FOR comp_type IN 1..5 LOOP
    │
    │ Set compression type constant
    ↓
v_comptype := CASE comp_type
    WHEN 1 THEN DBMS_COMPRESSION.COMP_FOR_OLTP
    WHEN 2 THEN DBMS_COMPRESSION.COMP_FOR_QUERY_LOW
    WHEN 3 THEN DBMS_COMPRESSION.COMP_FOR_QUERY_HIGH
    WHEN 4 THEN DBMS_COMPRESSION.COMP_FOR_ARCHIVE_LOW
    WHEN 5 THEN DBMS_COMPRESSION.COMP_FOR_ARCHIVE_HIGH
END;
    │
    ↓
┌───────────────────────────────────────────────────────────────┐
│  Call DBMS_COMPRESSION.GET_COMPRESSION_RATIO                  │
├───────────────────────────────────────────────────────────────┤
│  DBMS_COMPRESSION.GET_COMPRESSION_RATIO(                      │
│      scratchtbsname => 'USERS',                               │
│      ownname => p_owner,                                      │
│      objname => p_table_name,                                 │
│      subobjname => p_partition_name,  -- NULL for whole table │
│      comptype => v_comptype,                                  │
│      blkcnt_cmp => v_blkcnt_cmp,      -- OUT: compressed blks │
│      blkcnt_uncmp => v_blkcnt_uncmp,  -- OUT: uncompressed    │
│      row_cmp => v_row_cmp,            -- OUT: rows compressed │
│      row_uncmp => v_row_uncmp,        -- OUT: rows sample     │
│      cmp_ratio => v_cmp_ratio,        -- OUT: ratio achieved  │
│      comptype_str => v_comptype_str,  -- OUT: type string     │
│      subset_numrows => v_sample_size  -- Sample size          │
│  );                                                            │
└───────────┬───────────────────────────────────────────────────┘
            │
            │ Process results
            ↓
v_compression_ratio := v_blkcnt_uncmp / NULLIF(v_blkcnt_cmp, 0);
    │
    │ Store in appropriate column
    ↓
UPDATE compression_analysis_results
SET oltp_ratio = CASE WHEN comp_type = 1 THEN v_compression_ratio
                      ELSE oltp_ratio END,
    query_low_ratio = CASE WHEN comp_type = 2 THEN v_compression_ratio
                           ELSE query_low_ratio END,
    query_high_ratio = CASE WHEN comp_type = 3 THEN v_compression_ratio
                            ELSE query_high_ratio END,
    archive_low_ratio = CASE WHEN comp_type = 4 THEN v_compression_ratio
                             ELSE archive_low_ratio END,
    archive_high_ratio = CASE WHEN comp_type = 5 THEN v_compression_ratio
                              ELSE archive_high_ratio END
WHERE owner = p_owner
  AND object_name = p_table_name;
    │
    ↓
END LOOP;  -- Next compression type
```

### Flow 5: Error Handling and Rollback Flow

#### 5.1 Compression Failure and Automatic Rollback

```
┌─────────────────────────────────────────────────────────────────────┐
│  Compression Execution Error Handling                               │
└─────────────────────────────────────────────────────────────────────┘

[EXECUTOR_PKG.compress_segment_p execution]
    │
    ↓
BEGIN
    -- Pre-execution validation
    validate_object_exists(...);
    validate_compression_type(...);
    check_object_lock(...);
    │
    │ Create history record
    ↓
INSERT INTO compression_history (
    owner, object_name,
    compression_type_applied,
    execution_status
) VALUES (
    p_owner, p_object_name,
    p_compression_type,
    'IN_PROGRESS'
) RETURNING execution_id INTO v_exec_id;
    │
    │ Execute compression DDL
    ↓
EXECUTE IMMEDIATE v_compression_ddl;
    │
    │ ❌ ERROR OCCURS (e.g., insufficient space)
    ↓
EXCEPTION
    WHEN e_insufficient_space THEN
        │
        ├─→ Log error details
        │   │
        │   INSERT INTO error_log (
        │       error_code,
        │       error_message,
        │       error_context,
        │       execution_id
        │   ) VALUES (
        │       SQLCODE,
        │       SQLERRM,
        │       'Compression execution failed',
        │       v_exec_id
        │   );
        │
        ├─→ Update history status
        │   │
        │   UPDATE compression_history
        │   SET execution_status = 'FAILED',
        │       error_message = SQLERRM,
        │       end_time = SYSTIMESTAMP
        │   WHERE execution_id = v_exec_id;
        │
        ├─→ ROLLBACK transaction
        │   │
        │   ROLLBACK;
        │
        └─→ Return error response
            │
            RETURN JSON_PKG.error_response_json(
                p_code => -1652,
                p_msg => 'Insufficient tablespace'
            );
END;
```

#### 5.2 Manual Rollback Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  User-Initiated Compression Rollback                                │
└─────────────────────────────────────────────────────────────────────┘

[Dashboard: User selects execution to rollback]
    │
    ↓
POST /compression/v1/execute/rollback
{
    "execution_id": 98765
}
    │
    ↓
EXECUTOR_PKG.rollback_compression_p(p_execution_id => 98765)
    │
    ├─→ Validate rollback is possible
    │   │
    │   SELECT rollback_possible,
    │          execution_status,
    │          original_ddl
    │   FROM compression_history
    │   WHERE execution_id = 98765;
    │   │
    │   IF rollback_possible != 'Y' THEN
    │       RAISE e_rollback_not_possible;
    │   END IF;
    │
    ├─→ Generate rollback DDL
    │   │
    │   v_rollback_ddl := 'ALTER TABLE ' ||
    │                     v_owner || '.' ||
    │                     v_object_name ||
    │                     ' MOVE NOCOMPRESS ' ||
    │                     'ONLINE PARALLEL 4';
    │
    ├─→ Execute rollback
    │   │
    │   EXECUTE IMMEDIATE v_rollback_ddl;
    │
    ├─→ Rebuild indexes
    │   │
    │   FOR idx IN (SELECT index_name ...) LOOP
    │       EXECUTE IMMEDIATE 'ALTER INDEX ' ||
    │                        idx.index_name ||
    │                        ' REBUILD ONLINE';
    │   END LOOP;
    │
    └─→ Update history
        │
        UPDATE compression_history
        SET rollback_status = 'COMPLETED',
            execution_status = 'ROLLED_BACK'
        WHERE execution_id = 98765;
```

### Flow 6: Monitoring and Alerting Integration

#### 6.1 Export Metrics to Enterprise Monitoring

```
┌─────────────────────────────────────────────────────────────────────┐
│  Metrics Export for Grafana/Prometheus                              │
└─────────────────────────────────────────────────────────────────────┘

[Create materialized view for metrics export]
    │
    ↓
CREATE MATERIALIZED VIEW MV_COMPRESSION_METRICS
REFRESH ON DEMAND
AS
SELECT
    'compression_space_saved_total_gb' as metric_name,
    SUM(space_saved_mb)/1024 as metric_value,
    SYSTIMESTAMP as timestamp,
    owner as label_schema
FROM compression_history
WHERE execution_status = 'SUCCESS'
  AND start_time > SYSDATE - 30
GROUP BY owner
UNION ALL
SELECT
    'compression_objects_analyzed_total' as metric_name,
    COUNT(*) as metric_value,
    SYSTIMESTAMP as timestamp,
    owner as label_schema
FROM compression_analysis_results
WHERE analysis_date > SYSDATE - 7
GROUP BY owner
UNION ALL
SELECT
    'compression_execution_duration_avg_minutes' as metric_name,
    AVG(duration_minutes) as metric_value,
    SYSTIMESTAMP as timestamp,
    owner as label_schema
FROM compression_history
WHERE execution_status = 'SUCCESS'
  AND start_time > SYSDATE - 7
GROUP BY owner;
    │
    ↓
[External monitoring tool polls metrics endpoint]
    │
    ↓
GET /compression/v1/metrics/prometheus
    │
    ↓
SELECT * FROM MV_COMPRESSION_METRICS;
    │
    ↓
[Format as Prometheus metrics]
    │
    ↓
# HELP compression_space_saved_total_gb Total space saved by compression
# TYPE compression_space_saved_total_gb gauge
compression_space_saved_total_gb{schema="APP_SCHEMA"} 847.5
compression_space_saved_total_gb{schema="REPORTS_SCHEMA"} 234.2

# HELP compression_objects_analyzed_total Total objects analyzed
# TYPE compression_objects_analyzed_total counter
compression_objects_analyzed_total{schema="APP_SCHEMA"} 1247
```

#### 6.2 Alert Integration

```
┌─────────────────────────────────────────────────────────────────────┐
│  Alerting on Compression Events                                     │
└─────────────────────────────────────────────────────────────────────┘

[Create alert trigger]
    │
    ↓
CREATE OR REPLACE TRIGGER trg_compression_alert
AFTER INSERT OR UPDATE ON compression_history
FOR EACH ROW
WHEN (NEW.execution_status IN ('FAILED', 'SUCCESS'))
DECLARE
    v_alert_message VARCHAR2(4000);
BEGIN
    IF :NEW.execution_status = 'FAILED' THEN
        v_alert_message := 'ALERT: Compression failed for ' ||
                          :NEW.owner || '.' || :NEW.object_name ||
                          ' - Error: ' || :NEW.error_message;

        -- Send to monitoring system via DBMS_NETWORK_ACL_ADMIN
        UTL_HTTP.REQUEST(
            url => 'https://monitoring-server/webhook',
            body => JSON_OBJECT(
                'severity' VALUE 'ERROR',
                'message' VALUE v_alert_message,
                'execution_id' VALUE :NEW.execution_id
            )
        );

    ELSIF :NEW.execution_status = 'SUCCESS' AND
          :NEW.space_saved_mb > 10000 THEN

        v_alert_message := 'SUCCESS: Large compression completed for ' ||
                          :NEW.owner || '.' || :NEW.object_name ||
                          ' - Saved ' || :NEW.space_saved_mb || ' MB';

        -- Send success notification
        UTL_HTTP.REQUEST(
            url => 'https://monitoring-server/webhook',
            body => JSON_OBJECT(
                'severity' VALUE 'INFO',
                'message' VALUE v_alert_message,
                'execution_id' VALUE :NEW.execution_id
            )
        );
    END IF;
END;
/
```

## Data Flow Summary

### Analysis Data Flow

```
User Schemas → ALL_TABLES → ADVISOR_PKG → DBMS_COMPRESSION
                    ↓              ↓              ↓
            ALL_TAB_MODIFICATIONS   │     Compression Ratios
                    ↓              ↓              ↓
            DBA_HIST_SEG_STAT  Scoring Engine    │
                    ↓              ↓              ↓
                DBA_SEGMENTS   Recommendation     │
                                Engine            ↓
                                    ↓             ↓
                        COMPRESSION_ANALYSIS_RESULTS
                                    ↓
                            ORDS REST API
                                    ↓
                          Streamlit Dashboard
```

### Execution Data Flow

```
Dashboard → ORDS → EXECUTOR_PKG → DDL Generation
                        ↓               ↓
                DBA_SEGMENTS    ALTER TABLE MOVE
                        ↓               ↓
                Before Size      Compression
                        ↓               ↓
                        │       Index Rebuild
                        ↓               ↓
                DBA_SEGMENTS      After Size
                        ↓               ↓
                        └───────────────┘
                                ↓
                    COMPRESSION_HISTORY
                                ↓
                        ORDS REST API
                                ↓
                      Dashboard Update
```

## Conclusion

The integration flows demonstrate:
- **Seamless REST API Integration**: ORDS provides clean HTTP/JSON interface
- **Real-time Monitoring**: Polling and webhook support for status updates
- **Automated Workflows**: DBMS_SCHEDULER integration for hands-free operation
- **Error Resilience**: Comprehensive error handling and rollback capabilities
- **Enterprise Integration**: Metrics export and alerting for monitoring tools
- **Data Dictionary Leverage**: Efficient use of Oracle metadata for analysis

**Integration Flows Version**: 1.0.0
**Last Updated**: 2025-11-13
**Status**: Design Complete
