# HCC Compression Advisor - Component Diagram

## Overview

This document provides detailed component diagrams showing the modular organization, interfaces, and dependencies of the HCC Compression Advisor system.

## High-Level Component View

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         External Integrations                            │
│  ┌─────────────────┐  ┌──────────────────┐  ┌─────────────────────┐   │
│  │ Streamlit       │  │ DBMS_SCHEDULER   │  │ Enterprise          │   │
│  │ Dashboard       │  │ (Automation)     │  │ Monitoring Tools    │   │
│  └────────┬────────┘  └────────┬─────────┘  └──────────┬──────────┘   │
└───────────┼─────────────────────┼──────────────────────┼───────────────┘
            │                     │                      │
            ↓                     ↓                      ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                        ORDS REST API Layer                               │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  Module: /compression/v1/                                        │   │
│  │  ├── /advisor/*    (Analysis Endpoints)                         │   │
│  │  ├── /execute/*    (Execution Endpoints)                        │   │
│  │  ├── /reports/*    (Reporting Endpoints)                        │   │
│  │  └── /config/*     (Configuration Endpoints)                    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└───────────┼─────────────────────┼──────────────────────┼───────────────┘
            │                     │                      │
            ↓                     ↓                      ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                      PL/SQL Package Layer                                │
│  ┌──────────────────────┐         ┌──────────────────────────┐         │
│  │  ADVISOR_PKG         │         │  EXECUTOR_PKG            │         │
│  │  ┌────────────────┐  │         │  ┌────────────────────┐  │         │
│  │  │ Analysis       │  │         │  │ Compression        │  │         │
│  │  │ Engine         │  │         │  │ Execution          │  │         │
│  │  ├────────────────┤  │         │  ├────────────────────┤  │         │
│  │  │ Scoring        │  │         │  │ Validation         │  │         │
│  │  │ Algorithm      │  │         │  │ Engine             │  │         │
│  │  ├────────────────┤  │         │  ├────────────────────┤  │         │
│  │  │ Recommendation │  │         │  │ Rollback           │  │         │
│  │  │ Engine         │  │         │  │ Manager            │  │         │
│  │  └────────────────┘  │         │  └────────────────────┘  │         │
│  └──────────┬───────────┘         └───────────┬──────────────┘         │
└─────────────┼─────────────────────────────────┼────────────────────────┘
              │                                 │
              ↓                                 ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                      Utility Package Layer                               │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  ┌───────────┐ │
│  │ COMMON_PKG   │  │ LOGGING_PKG  │  │ VALIDATION_   │  │ JSON_PKG  │ │
│  │              │  │              │  │ PKG           │  │           │ │
│  │ - Constants  │  │ - Operation  │  │ - Privileges  │  │ - Parsing │ │
│  │ - Helpers    │  │   Log        │  │ - Syntax      │  │ - Format  │ │
│  │ - Formatters │  │ - Error Log  │  │ - Thresholds  │  │           │ │
│  └──────────────┘  └──────────────┘  └───────────────┘  └───────────┘ │
└─────────────┼─────────────────────────────────┼────────────────────────┘
              │                                 │
              ↓                                 ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                      Data Persistence Layer                              │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Core Tables:                                                     │  │
│  │  - COMPRESSION_ANALYSIS_RESULTS                                  │  │
│  │  - COMPRESSION_HISTORY                                           │  │
│  │  - ADVISOR_RUN                                                   │  │
│  │  - COMPRESSION_STRATEGIES                                        │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Extended Tables:                                                 │  │
│  │  - INDEX_COMPRESSION_ANALYSIS                                    │  │
│  │  - LOB_COMPRESSION_ANALYSIS                                      │  │
│  │  - IOT_COMPRESSION_ANALYSIS                                      │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Supporting Tables:                                               │  │
│  │  - OPERATION_LOG, ERROR_LOG, PERFORMANCE_METRICS                │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Core Package Components

### ADVISOR_PKG - Analysis Package

```
┌────────────────────────────────────────────────────────────────┐
│                        ADVISOR_PKG                              │
├────────────────────────────────────────────────────────────────┤
│  Package Specification (Public Interface)                      │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Public Procedures (ORDS-Callable)                        │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  • analyse_tables_p(p_owner VARCHAR2)                    │ │
│  │  • analyse_indexes_p(p_owner VARCHAR2)                   │ │
│  │  • analyse_lobs_p(p_owner VARCHAR2)                      │ │
│  │  • analyse_iots_p(p_owner VARCHAR2)                      │ │
│  │  • analyse_all_user_obj_p(p_owner VARCHAR2)              │ │
│  │  • refresh_analysis_p(p_days_old NUMBER)                 │ │
│  │  • get_recommendations_json(p_schema VARCHAR2) → CLOB    │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Public Functions                                         │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  • calculate_hotness_score(...) → NUMBER                 │ │
│  │  • get_analysis_status(p_run_id NUMBER) → VARCHAR2       │ │
│  │  • estimate_analysis_duration(...) → NUMBER              │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
├────────────────────────────────────────────────────────────────┤
│  Package Body (Private Implementation)                         │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Module 1: Object Discovery                              │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  discover_user_tables(p_owner) → table_list_t           │ │
│  │  discover_partitions(p_owner, p_table) → partition_t     │ │
│  │  filter_system_objects(p_object_list) → filtered_list    │ │
│  │  validate_object_access(p_owner, p_object) → BOOLEAN     │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Module 2: Compression Ratio Calculation                 │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  get_compression_ratio_oltp(...) → NUMBER                │ │
│  │  get_compression_ratio_query_low(...) → NUMBER           │ │
│  │  get_compression_ratio_query_high(...) → NUMBER          │ │
│  │  get_compression_ratio_archive_low(...) → NUMBER         │ │
│  │  get_compression_ratio_archive_high(...) → NUMBER        │ │
│  │  calculate_all_ratios(...) → compression_ratios_t        │ │
│  │  determine_sample_size(p_num_rows) → NUMBER              │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Module 3: Activity Analysis                             │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  get_dml_statistics(p_owner, p_object) → dml_stats_t    │ │
│  │  calculate_dml_rate(p_stats) → NUMBER                    │ │
│  │  get_access_patterns(p_owner, p_object) → access_t      │ │
│  │  analyze_segment_statistics(...) → segment_stats_t       │ │
│  │  detect_hot_objects(p_schema) → hot_objects_t           │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Module 4: Scoring Engine                                │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  calculate_activity_score(...) → NUMBER                  │ │
│  │  calculate_age_score(...) → NUMBER                       │ │
│  │  calculate_size_score(...) → NUMBER                      │ │
│  │  calculate_access_score(...) → NUMBER                    │ │
│  │  calculate_composite_score(...) → NUMBER                 │ │
│  │  normalize_score(p_raw_score) → NUMBER                   │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Module 5: Recommendation Engine                         │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  recommend_compression_type(...) → VARCHAR2              │ │
│  │  apply_strategy_rules(p_strategy_id, ...) → VARCHAR2     │ │
│  │  calculate_confidence_score(...) → NUMBER                │ │
│  │  generate_recommendation_reason(...) → VARCHAR2          │ │
│  │  estimate_space_savings(...) → NUMBER                    │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Module 6: Results Persistence                           │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  create_advisor_run(p_params) → NUMBER (run_id)         │ │
│  │  save_analysis_result(p_result) → BOOLEAN               │ │
│  │  update_run_statistics(p_run_id, p_stats) → BOOLEAN     │ │
│  │  finalize_advisor_run(p_run_id) → BOOLEAN               │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Module 7: Parallel Processing                           │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  enable_parallel_execution(p_degree) → BOOLEAN           │ │
│  │  spawn_analysis_job(p_object, p_params) → job_id        │ │
│  │  monitor_parallel_jobs(p_run_id) → job_status_t         │ │
│  │  wait_for_job_completion(p_job_id) → BOOLEAN            │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Global Package Variables                                │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  g_active_strategy     COMPRESSION_STRATEGIES%ROWTYPE    │ │
│  │  g_dml_threshold_high  NUMBER                            │ │
│  │  g_dml_threshold_low   NUMBER                            │ │
│  │  g_size_threshold_gb   NUMBER                            │ │
│  │  g_age_threshold_days  NUMBER                            │ │
│  │  g_debug_mode          BOOLEAN := FALSE                  │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

### EXECUTOR_PKG - Execution Package

```
┌────────────────────────────────────────────────────────────────┐
│                       EXECUTOR_PKG                              │
├────────────────────────────────────────────────────────────────┤
│  Package Specification (Public Interface)                      │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Public Procedures (ORDS-Callable)                        │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  • compress_segment_p(                                   │ │
│  │      p_owner VARCHAR2,                                   │ │
│  │      p_object_name VARCHAR2,                             │ │
│  │      p_object_type VARCHAR2,                             │ │
│  │      p_partition_name VARCHAR2 := NULL,                  │ │
│  │      p_compression_type VARCHAR2,                        │ │
│  │      p_parallel NUMBER := 2,                             │ │
│  │      p_verify_only VARCHAR2 := 'N'                       │ │
│  │    )                                                      │ │
│  │  • compress_batch_p(p_schema, p_max_concurrent)          │ │
│  │  • rollback_compression_p(p_execution_id)                │ │
│  │  • validate_compression_p(p_execution_id)                │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Public Functions                                         │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  • get_execution_status(p_exec_id) → VARCHAR2            │ │
│  │  • get_execution_progress(p_exec_id) → NUMBER            │ │
│  │  • get_execution_result_json(p_exec_id) → CLOB           │ │
│  │  • can_rollback(p_exec_id) → BOOLEAN                     │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
├────────────────────────────────────────────────────────────────┤
│  Package Body (Private Implementation)                         │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Module 1: Pre-Execution Validation                      │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  validate_object_exists(...) → BOOLEAN                   │ │
│  │  validate_compression_type(...) → BOOLEAN                │ │
│  │  check_object_lock(...) → BOOLEAN                        │ │
│  │  validate_privileges(...) → BOOLEAN                      │ │
│  │  check_tablespace_space(...) → BOOLEAN                   │ │
│  │  validate_parallel_degree(...) → NUMBER                  │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Module 2: Size Capture                                  │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  get_object_size_bytes(...) → NUMBER                     │ │
│  │  get_segment_blocks(...) → NUMBER                        │ │
│  │  get_row_count(...) → NUMBER                             │ │
│  │  capture_before_metrics(...) → metrics_t                 │ │
│  │  capture_after_metrics(...) → metrics_t                  │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Module 3: DDL Generation                                │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  build_compression_clause(...) → VARCHAR2                │ │
│  │  generate_table_compress_ddl(...) → VARCHAR2             │ │
│  │  generate_index_compress_ddl(...) → VARCHAR2             │ │
│  │  generate_lob_compress_ddl(...) → VARCHAR2               │ │
│  │  generate_iot_compress_ddl(...) → VARCHAR2               │ │
│  │  add_online_clause(p_ddl, p_online) → VARCHAR2           │ │
│  │  add_parallel_clause(p_ddl, p_degree) → VARCHAR2         │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Module 4: Execution Engine                              │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  execute_ddl_with_monitoring(...) → BOOLEAN              │ │
│  │  set_longops_context(...) → BOOLEAN                      │ │
│  │  update_execution_progress(...) → BOOLEAN                │ │
│  │  handle_execution_error(...) → BOOLEAN                   │ │
│  │  verify_execution_success(...) → BOOLEAN                 │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Module 5: Index Rebuild Manager                         │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  get_dependent_indexes(...) → index_list_t               │ │
│  │  rebuild_index_online(...) → BOOLEAN                     │ │
│  │  rebuild_all_indexes(...) → rebuild_summary_t            │ │
│  │  validate_index_rebuild(...) → BOOLEAN                   │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Module 6: Batch Processing                              │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  get_compression_candidates(...) → candidate_list_t      │ │
│  │  prioritize_candidates(...) → prioritized_list_t         │ │
│  │  create_compression_job(...) → job_id                    │ │
│  │  monitor_job_queue(...) → job_status_t                   │ │
│  │  throttle_concurrent_jobs(...) → BOOLEAN                 │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Module 7: Rollback Manager                              │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  generate_rollback_ddl(...) → VARCHAR2                   │ │
│  │  execute_rollback(...) → BOOLEAN                         │ │
│  │  validate_rollback_success(...) → BOOLEAN                │ │
│  │  log_rollback_operation(...) → BOOLEAN                   │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Module 8: History Tracking                              │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  create_history_record(...) → execution_id               │ │
│  │  update_history_metrics(...) → BOOLEAN                   │ │
│  │  finalize_history_record(...) → BOOLEAN                  │ │
│  │  calculate_space_savings(...) → savings_t                │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

## Utility Packages

### COMMON_PKG - Common Utilities

```
┌────────────────────────────────────────────────────────────────┐
│                        COMMON_PKG                               │
├────────────────────────────────────────────────────────────────┤
│  Constants                                                      │
├────────────────────────────────────────────────────────────────┤
│  c_version               CONSTANT VARCHAR2(20) := '1.0.0'      │
│  c_package_owner         CONSTANT VARCHAR2(30) := 'COMPRESSION_MGR' │
│  c_default_parallel      CONSTANT NUMBER := 4                  │
│  c_default_sample_size   CONSTANT NUMBER := 1000000            │
│  c_min_compression_ratio CONSTANT NUMBER := 1.5                │
│  c_bytes_per_mb          CONSTANT NUMBER := 1048576            │
├────────────────────────────────────────────────────────────────┤
│  Helper Functions                                               │
├────────────────────────────────────────────────────────────────┤
│  format_bytes(p_bytes NUMBER) → VARCHAR2                       │
│  format_duration(p_seconds NUMBER) → VARCHAR2                  │
│  format_ratio(p_ratio NUMBER) → VARCHAR2                       │
│  format_percentage(p_pct NUMBER) → VARCHAR2                    │
│  is_system_schema(p_schema VARCHAR2) → BOOLEAN                 │
│  get_current_timestamp → TIMESTAMP                             │
│  get_session_info → session_info_t                             │
└────────────────────────────────────────────────────────────────┘
```

### LOGGING_PKG - Logging and Audit

```
┌────────────────────────────────────────────────────────────────┐
│                       LOGGING_PKG                               │
├────────────────────────────────────────────────────────────────┤
│  Logging Procedures                                             │
├────────────────────────────────────────────────────────────────┤
│  log_operation(                                                 │
│    p_operation_type VARCHAR2,                                  │
│    p_operation_details CLOB,                                   │
│    p_success_flag BOOLEAN,                                     │
│    p_error_msg VARCHAR2 := NULL                                │
│  )                                                              │
│                                                                 │
│  log_error(                                                     │
│    p_error_code NUMBER,                                        │
│    p_error_msg VARCHAR2,                                       │
│    p_error_context VARCHAR2,                                   │
│    p_sql_stmt CLOB := NULL                                     │
│  )                                                              │
│                                                                 │
│  log_performance_metric(                                        │
│    p_metric_type VARCHAR2,                                     │
│    p_metric_value NUMBER,                                      │
│    p_context VARCHAR2                                          │
│  )                                                              │
├────────────────────────────────────────────────────────────────┤
│  Query Functions                                                │
├────────────────────────────────────────────────────────────────┤
│  get_recent_errors(p_hours NUMBER := 24) → error_list_t       │
│  get_operation_history(p_days NUMBER := 7) → op_list_t        │
│  get_performance_trends(p_metric VARCHAR2) → trend_list_t     │
└────────────────────────────────────────────────────────────────┘
```

### VALIDATION_PKG - Validation Utilities

```
┌────────────────────────────────────────────────────────────────┐
│                      VALIDATION_PKG                             │
├────────────────────────────────────────────────────────────────┤
│  Privilege Validation                                           │
├────────────────────────────────────────────────────────────────┤
│  has_select_privilege(p_schema, p_object) → BOOLEAN            │
│  has_alter_privilege(p_schema, p_object) → BOOLEAN             │
│  has_dba_privilege → BOOLEAN                                   │
│  can_execute_compression(p_schema, p_object) → BOOLEAN         │
├────────────────────────────────────────────────────────────────┤
│  Syntax Validation                                              │
├────────────────────────────────────────────────────────────────┤
│  is_valid_schema_name(p_schema VARCHAR2) → BOOLEAN             │
│  is_valid_object_name(p_object VARCHAR2) → BOOLEAN             │
│  is_valid_compression_type(p_type VARCHAR2) → BOOLEAN          │
│  validate_ddl_syntax(p_ddl VARCHAR2) → validation_result_t     │
├────────────────────────────────────────────────────────────────┤
│  Threshold Validation                                           │
├────────────────────────────────────────────────────────────────┤
│  validate_parallel_degree(p_degree NUMBER) → NUMBER            │
│  validate_sample_size(p_size NUMBER) → NUMBER                  │
│  check_tablespace_threshold(p_tbs VARCHAR2) → BOOLEAN          │
└────────────────────────────────────────────────────────────────┘
```

### JSON_PKG - JSON Processing

```
┌────────────────────────────────────────────────────────────────┐
│                         JSON_PKG                                │
├────────────────────────────────────────────────────────────────┤
│  JSON Generation                                                │
├────────────────────────────────────────────────────────────────┤
│  analysis_result_to_json(p_fact_id NUMBER) → CLOB              │
│  execution_result_to_json(p_exec_id NUMBER) → CLOB             │
│  recommendation_list_to_json(p_schema VARCHAR2) → CLOB         │
│  error_response_json(p_code NUMBER, p_msg VARCHAR2) → CLOB     │
│  success_response_json(p_data CLOB) → CLOB                     │
├────────────────────────────────────────────────────────────────┤
│  JSON Parsing                                                   │
├────────────────────────────────────────────────────────────────┤
│  parse_compress_request(p_json CLOB) → compress_params_t       │
│  parse_analyze_request(p_json CLOB) → analyze_params_t         │
│  extract_json_value(p_json CLOB, p_path VARCHAR2) → VARCHAR2   │
└────────────────────────────────────────────────────────────────┘
```

## Type Definitions

### Custom Types and Collections

```sql
-- Object analysis result type
CREATE OR REPLACE TYPE compression_analysis_t AS OBJECT (
    owner               VARCHAR2(128),
    object_name         VARCHAR2(128),
    object_type         VARCHAR2(30),
    partition_name      VARCHAR2(128),
    oltp_ratio          NUMBER,
    query_low_ratio     NUMBER,
    query_high_ratio    NUMBER,
    archive_low_ratio   NUMBER,
    archive_high_ratio  NUMBER,
    hotness_score       NUMBER,
    recommendation      VARCHAR2(30),
    confidence_score    NUMBER
);
/

CREATE OR REPLACE TYPE compression_analysis_list_t
    AS TABLE OF compression_analysis_t;
/

-- Execution result type
CREATE OR REPLACE TYPE compression_execution_t AS OBJECT (
    execution_id            NUMBER,
    object_name             VARCHAR2(128),
    compression_type        VARCHAR2(30),
    original_size_mb        NUMBER,
    compressed_size_mb      NUMBER,
    space_saved_mb          NUMBER,
    compression_ratio       NUMBER,
    execution_status        VARCHAR2(30),
    duration_minutes        NUMBER
);
/

CREATE OR REPLACE TYPE compression_execution_list_t
    AS TABLE OF compression_execution_t;
/

-- Strategy parameters type
CREATE OR REPLACE TYPE strategy_params_t AS OBJECT (
    dml_threshold_high      NUMBER,
    dml_threshold_low       NUMBER,
    size_threshold_gb       NUMBER,
    age_threshold_days      NUMBER,
    hotness_threshold       NUMBER,
    min_compression_ratio   NUMBER
);
/

-- DML statistics type
CREATE OR REPLACE TYPE dml_stats_t AS OBJECT (
    insert_count    NUMBER,
    update_count    NUMBER,
    delete_count    NUMBER,
    total_operations NUMBER,
    last_modified   DATE
);
/

-- Access pattern type
CREATE OR REPLACE TYPE access_pattern_t AS OBJECT (
    logical_reads       NUMBER,
    physical_reads      NUMBER,
    access_frequency    NUMBER,
    last_access_date    DATE
);
/
```

## Interface Contracts

### ADVISOR_PKG Public Interface Contract

```sql
-- Analysis procedure contract
PROCEDURE analyse_tables_p(
    p_owner             IN VARCHAR2 DEFAULT NULL,
    p_sample_size       IN NUMBER DEFAULT 1000000,
    p_parallel_degree   IN NUMBER DEFAULT 4,
    p_strategy_id       IN NUMBER DEFAULT NULL,
    p_incremental       IN BOOLEAN DEFAULT FALSE
) RETURN NUMBER;  -- Returns run_id
/*
Purpose: Analyze tables for compression opportunities
Pre-conditions:
  - Caller must have SELECT privilege on target schema
  - Target schema must contain valid user tables
Post-conditions:
  - Analysis results stored in COMPRESSION_ANALYSIS_RESULTS
  - ADVISOR_RUN record created with status
Exceptions:
  - INSUFFICIENT_PRIVILEGES (-1031)
  - INVALID_SCHEMA (-20001)
  - ANALYSIS_FAILED (-20002)
*/
```

### EXECUTOR_PKG Public Interface Contract

```sql
-- Compression execution contract
PROCEDURE compress_segment_p(
    p_owner             IN VARCHAR2,
    p_object_name       IN VARCHAR2,
    p_object_type       IN VARCHAR2,
    p_partition_name    IN VARCHAR2 DEFAULT NULL,
    p_compression_type  IN VARCHAR2,
    p_parallel          IN NUMBER DEFAULT 2,
    p_verify_only       IN VARCHAR2 DEFAULT 'N'
) RETURN NUMBER;  -- Returns execution_id
/*
Purpose: Execute compression on specified object
Pre-conditions:
  - Object must exist and be accessible
  - Caller must have ALTER privilege
  - Sufficient tablespace available
Post-conditions:
  - Object compressed with specified type
  - Indexes rebuilt
  - History record created
Exceptions:
  - OBJECT_NOT_FOUND (-942)
  - INSUFFICIENT_SPACE (-1652)
  - OBJECT_LOCKED (-54)
  - COMPRESSION_FAILED (-20003)
*/
```

## Dependency Graph

```
External Systems
    ↓
ORDS REST Layer
    ↓
┌─────────────────────────────────────────┐
│  Main Packages                          │
│  ┌──────────────┐    ┌──────────────┐  │
│  │ ADVISOR_PKG  │    │ EXECUTOR_PKG │  │
│  └──────┬───────┘    └──────┬───────┘  │
│         │                   │           │
│         └──────────┬────────┘           │
│                    ↓                    │
│  ┌─────────────────────────────────┐   │
│  │  Utility Packages               │   │
│  │  ┌──────────┐  ┌────────────┐  │   │
│  │  │COMMON_PKG│  │LOGGING_PKG │  │   │
│  │  └──────────┘  └────────────┘  │   │
│  │  ┌────────────┐ ┌───────────┐  │   │
│  │  │VALIDATION_ │ │ JSON_PKG  │  │   │
│  │  │PKG         │ └───────────┘  │   │
│  │  └────────────┘                │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│  Oracle Built-in Packages               │
│  • DBMS_COMPRESSION                     │
│  • DBMS_SCHEDULER                       │
│  • DBMS_APPLICATION_INFO                │
│  • DBMS_UTILITY                         │
│  • DBMS_STATS                           │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│  Data Dictionary Views                  │
│  • ALL_TABLES, ALL_TAB_PARTITIONS       │
│  • ALL_SEGMENTS, ALL_INDEXES            │
│  • ALL_TAB_MODIFICATIONS                │
│  • DBA_HIST_SEG_STAT                    │
│  • V$SEGMENT_STATISTICS                 │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│  Repository Tables                      │
│  • COMPRESSION_ANALYSIS_RESULTS         │
│  • COMPRESSION_HISTORY                  │
│  • ADVISOR_RUN                          │
│  • COMPRESSION_STRATEGIES               │
└─────────────────────────────────────────┘
```

## Configuration Management

### Global Configuration Package

```sql
CREATE OR REPLACE PACKAGE CONFIG_PKG AS
    -- Load active strategy
    PROCEDURE load_strategy(p_strategy_id NUMBER DEFAULT NULL);

    -- Get configuration values
    FUNCTION get_dml_threshold_high RETURN NUMBER;
    FUNCTION get_dml_threshold_low RETURN NUMBER;
    FUNCTION get_size_threshold_gb RETURN NUMBER;
    FUNCTION get_age_threshold_days RETURN NUMBER;
    FUNCTION get_active_strategy_id RETURN NUMBER;

    -- Update configuration
    PROCEDURE set_active_strategy(p_strategy_id NUMBER);
    PROCEDURE refresh_configuration;
END CONFIG_PKG;
/
```

## Error Handling Framework

### Custom Exception Definitions

```sql
-- Custom exceptions
DECLARE
    -- Analysis exceptions
    e_invalid_schema        EXCEPTION;
    e_analysis_failed       EXCEPTION;
    e_insufficient_privileges EXCEPTION;

    -- Execution exceptions
    e_compression_failed    EXCEPTION;
    e_object_locked         EXCEPTION;
    e_insufficient_space    EXCEPTION;
    e_validation_failed     EXCEPTION;

    -- Rollback exceptions
    e_rollback_not_possible EXCEPTION;
    e_rollback_failed       EXCEPTION;

    PRAGMA EXCEPTION_INIT(e_invalid_schema, -20001);
    PRAGMA EXCEPTION_INIT(e_analysis_failed, -20002);
    PRAGMA EXCEPTION_INIT(e_compression_failed, -20003);
    PRAGMA EXCEPTION_INIT(e_object_locked, -54);
    PRAGMA EXCEPTION_INIT(e_insufficient_space, -1652);
```

### Centralized Error Handler

```sql
CREATE OR REPLACE PACKAGE ERROR_HANDLER_PKG AS
    PROCEDURE handle_exception(
        p_error_code    IN NUMBER,
        p_error_msg     IN VARCHAR2,
        p_context       IN VARCHAR2,
        p_reraise       IN BOOLEAN DEFAULT TRUE
    );

    PROCEDURE log_and_continue(
        p_error_code    IN NUMBER,
        p_error_msg     IN VARCHAR2,
        p_context       IN VARCHAR2
    );

    FUNCTION get_friendly_error_msg(
        p_error_code    IN NUMBER
    ) RETURN VARCHAR2;
END ERROR_HANDLER_PKG;
/
```

## Module Organization Summary

| Package | Purpose | LOC Estimate | Dependencies |
|---------|---------|--------------|--------------|
| **ADVISOR_PKG** | Compression analysis engine | 2000-2500 | DBMS_COMPRESSION, COMMON_PKG, LOGGING_PKG |
| **EXECUTOR_PKG** | Compression execution engine | 1500-2000 | DBMS_SCHEDULER, COMMON_PKG, LOGGING_PKG |
| **COMMON_PKG** | Shared utilities and constants | 300-500 | None |
| **LOGGING_PKG** | Audit and error logging | 400-600 | None |
| **VALIDATION_PKG** | Input validation and security | 300-400 | COMMON_PKG |
| **JSON_PKG** | JSON formatting and parsing | 400-600 | None |
| **CONFIG_PKG** | Configuration management | 200-300 | None |
| **ERROR_HANDLER_PKG** | Centralized error handling | 200-300 | LOGGING_PKG |

**Total Estimated LOC**: 5,300 - 7,200 lines of PL/SQL code

## Component Interaction Sequence

### Analysis Workflow Sequence

```
User/Dashboard → ORDS REST API → ADVISOR_PKG.analyse_tables_p
    ↓
1. CONFIG_PKG.load_strategy
2. VALIDATION_PKG.validate_privileges
3. LOGGING_PKG.log_operation (START)
    ↓
4. Loop: For each table
    a. DBMS_COMPRESSION.GET_COMPRESSION_RATIO
    b. Calculate hotness score
    c. Apply recommendation logic
    d. Save to COMPRESSION_ANALYSIS_RESULTS
    ↓
5. LOGGING_PKG.log_operation (COMPLETE)
6. Return JSON response
```

### Execution Workflow Sequence

```
User/Dashboard → ORDS REST API → EXECUTOR_PKG.compress_segment_p
    ↓
1. VALIDATION_PKG.validate_object_exists
2. VALIDATION_PKG.validate_privileges
3. Capture before-size metrics
4. Create COMPRESSION_HISTORY record
    ↓
5. Generate and execute compression DDL
6. Rebuild dependent indexes
7. Capture after-size metrics
    ↓
8. Update COMPRESSION_HISTORY with results
9. LOGGING_PKG.log_operation
10. Return JSON response
```

## Conclusion

The component architecture provides:
- **Modular Design**: Clear separation of concerns across 8 packages
- **Reusability**: Shared utility packages reduce code duplication
- **Maintainability**: Well-defined interfaces and contracts
- **Testability**: Each module can be tested independently
- **Scalability**: Parallel processing and batch operations
- **Observability**: Comprehensive logging and monitoring

**Component Diagram Version**: 1.0.0
**Last Updated**: 2025-11-13
**Status**: Design Complete
