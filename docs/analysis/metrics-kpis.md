# Metrics & KPIs for HCC Compression Management

## Executive Summary

This document defines the comprehensive metrics, key performance indicators (KPIs), and monitoring framework for measuring the success and health of the HCC Compression Advisor system. These metrics drive operational excellence, validate business value, and enable continuous improvement.

## Metric Categories

### 1. Compression Effectiveness Metrics

#### A. Storage Efficiency KPIs

```sql
CREATE OR REPLACE VIEW V_STORAGE_EFFICIENCY_KPIS AS
SELECT
  -- Overall compression effectiveness
  ROUND(SUM(original_size_mb) / 1024, 2) as total_original_tb,
  ROUND(SUM(compressed_size_mb) / 1024, 2) as total_compressed_tb,
  ROUND(SUM(space_saved_mb) / 1024, 2) as total_saved_tb,

  -- Aggregate compression ratio
  ROUND(SUM(original_size_mb) / NULLIF(SUM(compressed_size_mb), 0), 2)
    as overall_compression_ratio,

  -- Space savings percentage
  ROUND(SUM(space_saved_mb) / NULLIF(SUM(original_size_mb), 0) * 100, 2)
    as space_reduction_pct,

  -- By compression type
  compression_type_applied,
  COUNT(*) as objects_compressed,
  ROUND(AVG(compression_ratio_achieved), 2) as avg_compression_ratio,
  MIN(compression_ratio_achieved) as min_compression_ratio,
  MAX(compression_ratio_achieved) as max_compression_ratio,
  STDDEV(compression_ratio_achieved) as compression_ratio_stddev,

  -- Temporal metrics
  MIN(start_time) as first_compression_date,
  MAX(end_time) as last_compression_date,
  COUNT(DISTINCT TRUNC(start_time)) as active_compression_days

FROM COMPRESSION_HISTORY
WHERE execution_status = 'SUCCESS'
GROUP BY ROLLUP(compression_type_applied);
```

**Target KPIs**:
- Overall compression ratio: ≥3.0:1
- Space reduction: ≥65%
- OLTP compression: 2.0-3.0:1
- Query High compression: 4.0-6.0:1
- Archive High compression: 6.0-10.0:1

#### B. Compression Quality Score

```
COMPRESSION_QUALITY_SCORE = (
  (ACTUAL_RATIO / PREDICTED_RATIO × 0.40) +
  (SPACE_SAVED_PCT / 80 × 0.30) +
  (1 - ERROR_RATE × 0.20) +
  (CONSISTENCY_SCORE × 0.10)
) × 100

Where:
  ACTUAL_RATIO: Achieved compression ratio
  PREDICTED_RATIO: Ratio from DBMS_COMPRESSION analysis
  SPACE_SAVED_PCT: Percentage space reduction
  ERROR_RATE: Failed compressions / Total attempts
  CONSISTENCY_SCORE: 1 - (STDDEV/MEAN) of compression ratios

Target: ≥85/100
```

### 2. Performance Impact Metrics

#### A. Query Performance KPIs

```sql
CREATE TABLE QUERY_PERFORMANCE_BASELINE (
  BASELINE_ID           NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  OWNER                 VARCHAR2(128),
  OBJECT_NAME           VARCHAR2(128),
  SQL_ID                VARCHAR2(13),
  OPERATION             VARCHAR2(50),

  -- Pre-compression metrics
  PRE_AVG_ELAPSED_SEC   NUMBER(12,3),
  PRE_AVG_CPU_SEC       NUMBER(12,3),
  PRE_AVG_IO_MB         NUMBER(12,2),
  PRE_AVG_BUFFER_GETS   NUMBER(12,0),

  -- Post-compression metrics
  POST_AVG_ELAPSED_SEC  NUMBER(12,3),
  POST_AVG_CPU_SEC      NUMBER(12,3),
  POST_AVG_IO_MB        NUMBER(12,2),
  POST_AVG_BUFFER_GETS  NUMBER(12,0),

  -- Impact calculations
  ELAPSED_TIME_CHANGE_PCT NUMBER(6,2),
  CPU_TIME_CHANGE_PCT   NUMBER(6,2),
  IO_CHANGE_PCT         NUMBER(6,2),
  BUFFER_GETS_CHANGE_PCT NUMBER(6,2),

  COMPRESSION_TYPE      VARCHAR2(30),
  BASELINE_DATE         TIMESTAMP,
  POST_COMPRESSION_DATE TIMESTAMP
);

CREATE OR REPLACE VIEW V_PERFORMANCE_IMPACT_SUMMARY AS
SELECT
  compression_type,
  COUNT(DISTINCT object_name) as objects_monitored,
  COUNT(DISTINCT sql_id) as unique_queries,

  -- Performance changes
  ROUND(AVG(elapsed_time_change_pct), 2) as avg_elapsed_change_pct,
  ROUND(AVG(cpu_time_change_pct), 2) as avg_cpu_change_pct,
  ROUND(AVG(io_change_pct), 2) as avg_io_change_pct,

  -- Performance improvement cases
  SUM(CASE WHEN elapsed_time_change_pct < 0 THEN 1 ELSE 0 END) as queries_improved,
  SUM(CASE WHEN elapsed_time_change_pct > 10 THEN 1 ELSE 0 END) as queries_degraded_10pct,
  SUM(CASE WHEN elapsed_time_change_pct > 25 THEN 1 ELSE 0 END) as queries_degraded_25pct,

  -- IO improvements (almost always better with compression)
  ROUND(AVG(CASE WHEN io_change_pct < 0 THEN ABS(io_change_pct) END), 2)
    as avg_io_improvement_pct

FROM QUERY_PERFORMANCE_BASELINE
WHERE post_compression_date IS NOT NULL
GROUP BY compression_type;
```

**Target KPIs**:
- Queries with <5% performance degradation: ≥90%
- Queries with >10% degradation: <5%
- Queries with >25% degradation: <1%
- Average I/O reduction: ≥40%
- CPU increase for scan queries: <20%

#### B. System-Level Performance Metrics

```sql
CREATE TABLE SYSTEM_PERFORMANCE_METRICS (
  METRIC_DATE           DATE,
  METRIC_HOUR           NUMBER(2),

  -- Database-wide metrics
  TOTAL_DB_SIZE_GB      NUMBER(12,2),
  COMPRESSED_SIZE_GB    NUMBER(12,2),
  COMPRESSION_RATIO     NUMBER(5,2),

  -- Performance indicators
  AVG_ACTIVE_SESSIONS   NUMBER(8,2),
  CPU_UTILIZATION_PCT   NUMBER(5,2),
  IO_THROUGHPUT_MBPS    NUMBER(12,2),
  BUFFER_CACHE_HIT_PCT  NUMBER(5,2),

  -- Compression-specific
  DECOMPRESS_CPU_SEC    NUMBER(12,2),
  DECOMPRESS_PCT_TOTAL_CPU NUMBER(5,2),

  -- Capacity metrics
  TABLESPACE_USED_PCT   NUMBER(5,2),
  BACKUP_SIZE_GB        NUMBER(12,2),
  BACKUP_DURATION_MIN   NUMBER(8,2)
);
```

**Target KPIs**:
- Buffer cache hit rate: ≥95% (improved due to more data in cache)
- Decompression CPU overhead: <15% of total CPU
- Tablespace utilization: <80% (reduced due to compression)
- Backup duration reduction: ≥30%

### 3. Operational Efficiency Metrics

#### A. Analysis Performance KPIs

```sql
CREATE TABLE ANALYSIS_PERFORMANCE_METRICS (
  ANALYSIS_RUN_ID       NUMBER,
  START_TIME            TIMESTAMP,
  END_TIME              TIMESTAMP,
  DURATION_MINUTES      NUMBER(8,2),

  -- Scope metrics
  TABLES_ANALYZED       NUMBER,
  PARTITIONS_ANALYZED   NUMBER,
  INDEXES_ANALYZED      NUMBER,
  TOTAL_OBJECTS_ANALYZED NUMBER,
  TOTAL_SIZE_ANALYZED_GB NUMBER(12,2),

  -- Performance metrics
  OBJECTS_PER_MINUTE    NUMBER(8,2),
  GB_PER_MINUTE         NUMBER(8,2),
  PARALLEL_DEGREE       NUMBER(3),

  -- Resource consumption
  CPU_SECONDS_USED      NUMBER(12,2),
  TEMP_SPACE_USED_MB    NUMBER(12,2),

  -- Quality metrics
  ANALYSIS_ERRORS       NUMBER,
  ERROR_RATE_PCT        NUMBER(5,2),
  RECOMMENDATIONS_GENERATED NUMBER
);

CREATE OR REPLACE VIEW V_ANALYSIS_EFFICIENCY AS
SELECT
  TRUNC(start_time) as analysis_date,
  COUNT(*) as analysis_runs,
  SUM(tables_analyzed) as total_tables,
  SUM(total_size_analyzed_gb) as total_size_gb,

  -- Performance targets
  ROUND(AVG(duration_minutes), 2) as avg_duration_min,
  ROUND(AVG(objects_per_minute), 2) as avg_objects_per_min,
  ROUND(AVG(gb_per_minute), 2) as avg_gb_per_min,

  -- Quality metrics
  ROUND(AVG(error_rate_pct), 2) as avg_error_rate_pct,
  SUM(recommendations_generated) as total_recommendations

FROM ANALYSIS_PERFORMANCE_METRICS
GROUP BY TRUNC(start_time)
ORDER BY analysis_date DESC;
```

**Target KPIs**:
- Analysis throughput: ≥50 objects/minute
- Analysis throughput: ≥20 GB/minute
- Analysis completion for 1000 tables: <30 minutes
- Analysis error rate: <2%
- Recommendation coverage: ≥80% of analyzed objects

#### B. Compression Execution KPIs

```sql
CREATE OR REPLACE VIEW V_COMPRESSION_EXECUTION_KPIS AS
SELECT
  TRUNC(start_time) as compression_date,
  compression_type_applied,

  -- Volume metrics
  COUNT(*) as total_compressions,
  SUM(original_size_mb) / 1024 as total_compressed_tb,

  -- Success metrics
  SUM(CASE WHEN execution_status = 'SUCCESS' THEN 1 ELSE 0 END) as successful,
  SUM(CASE WHEN execution_status = 'FAILED' THEN 1 ELSE 0 END) as failed,
  ROUND(SUM(CASE WHEN execution_status = 'SUCCESS' THEN 1 ELSE 0 END) /
    NULLIF(COUNT(*), 0) * 100, 2) as success_rate_pct,

  -- Performance metrics
  ROUND(AVG(EXTRACT(HOUR FROM (end_time - start_time)) * 60 +
            EXTRACT(MINUTE FROM (end_time - start_time))), 2) as avg_duration_min,
  ROUND(AVG(original_size_mb / NULLIF(
            EXTRACT(HOUR FROM (end_time - start_time)) * 60 +
            EXTRACT(MINUTE FROM (end_time - start_time)), 0)), 2)
    as avg_mb_per_minute,

  -- Business value
  ROUND(SUM(space_saved_mb) / 1024, 2) as total_saved_tb,
  ROUND(AVG(compression_ratio_achieved), 2) as avg_compression_ratio

FROM COMPRESSION_HISTORY
GROUP BY TRUNC(start_time), compression_type_applied
ORDER BY compression_date DESC, compression_type_applied;
```

**Target KPIs**:
- Compression success rate: ≥98%
- Average compression speed: ≥100 MB/minute
- Downtime per compression (if applicable): <5 minutes
- Index rebuild success rate: 100%

### 4. Recommendation Quality Metrics

#### A. Prediction Accuracy KPIs

```sql
CREATE TABLE RECOMMENDATION_VALIDATION (
  VALIDATION_ID         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  OWNER                 VARCHAR2(128),
  OBJECT_NAME           VARCHAR2(128),

  -- Recommendation
  RECOMMENDED_COMPRESSION VARCHAR2(30),
  PREDICTED_RATIO       NUMBER(5,2),
  CONFIDENCE_SCORE      NUMBER(5,2),
  CANDIDATE_SCORE       NUMBER(5,2),

  -- Actual outcome
  ACTUAL_COMPRESSION    VARCHAR2(30),
  ACTUAL_RATIO          NUMBER(5,2),
  COMPRESSION_SUCCESS   VARCHAR2(1),

  -- Validation metrics
  RATIO_ACCURACY_PCT    NUMBER(5,2),
  RECOMMENDATION_MATCH  VARCHAR2(1),

  RECOMMENDATION_DATE   TIMESTAMP,
  COMPRESSION_DATE      TIMESTAMP
);

CREATE OR REPLACE VIEW V_RECOMMENDATION_ACCURACY AS
SELECT
  recommended_compression,
  COUNT(*) as total_recommendations,

  -- Match rate
  SUM(CASE WHEN recommendation_match = 'Y' THEN 1 ELSE 0 END) as matches,
  ROUND(SUM(CASE WHEN recommendation_match = 'Y' THEN 1 ELSE 0 END) /
    NULLIF(COUNT(*), 0) * 100, 2) as match_rate_pct,

  -- Ratio accuracy
  ROUND(AVG(ratio_accuracy_pct), 2) as avg_ratio_accuracy_pct,
  ROUND(STDDEV(ratio_accuracy_pct), 2) as ratio_accuracy_stddev,

  -- By confidence band
  SUM(CASE WHEN confidence_score >= 90 THEN 1 ELSE 0 END) as high_confidence,
  SUM(CASE WHEN confidence_score BETWEEN 75 AND 89 THEN 1 ELSE 0 END) as medium_confidence,
  SUM(CASE WHEN confidence_score < 75 THEN 1 ELSE 0 END) as low_confidence,

  -- Accuracy by confidence
  ROUND(AVG(CASE WHEN confidence_score >= 90 THEN ratio_accuracy_pct END), 2)
    as high_conf_accuracy,
  ROUND(AVG(CASE WHEN confidence_score < 75 THEN ratio_accuracy_pct END), 2)
    as low_conf_accuracy

FROM RECOMMENDATION_VALIDATION
WHERE compression_success = 'Y'
GROUP BY recommended_compression;
```

**Target KPIs**:
- Overall recommendation accuracy: ≥90%
- High-confidence (≥90) accuracy: ≥95%
- Compression ratio prediction accuracy: ±15%
- False positive rate (poor compression): <5%

#### B. Business Value Realization

```sql
CREATE OR REPLACE VIEW V_VALUE_REALIZATION_METRICS AS
SELECT
  TRUNC(analysis_date, 'MM') as month,

  -- Prediction vs. reality
  SUM(predicted_annual_savings) as predicted_savings,
  SUM(actual_annual_savings) as actual_savings,
  ROUND(SUM(actual_annual_savings) / NULLIF(SUM(predicted_annual_savings), 0) * 100, 2)
    as realization_rate_pct,

  -- ROI metrics
  SUM(predicted_break_even_months) as predicted_payback,
  SUM(actual_break_even_months) as actual_payback,

  COUNT(*) as total_projects,
  SUM(CASE WHEN actual_roi_pct > predicted_roi_pct THEN 1 ELSE 0 END) as exceeds_prediction,
  SUM(CASE WHEN actual_roi_pct < predicted_roi_pct * 0.8 THEN 1 ELSE 0 END) as underperforms

FROM (
  SELECT
    r.analysis_date,
    r.annual_storage_savings as predicted_annual_savings,
    r.break_even_months as predicted_break_even_months,
    r.annual_roi_pct as predicted_roi_pct,

    -- Actual values from execution
    (ch.space_saved_mb / 1024) * 12000 as actual_annual_savings,  -- $12K/TB/year
    ch.execution_id / ch.space_saved_mb as actual_break_even_months,
    (ch.space_saved_mb * 12000) / NULLIF(ch.original_size_mb, 0) * 100 as actual_roi_pct

  FROM ROI_ANALYSIS r
  JOIN COMPRESSION_HISTORY ch
    ON r.owner = ch.owner
    AND r.object_name = ch.object_name
  WHERE ch.execution_status = 'SUCCESS'
)
GROUP BY TRUNC(analysis_date, 'MM');
```

**Target KPIs**:
- Value realization rate: ≥85%
- Projects exceeding predictions: ≥40%
- Projects underperforming by >20%: <10%

### 5. Alert Thresholds & Health Indicators

#### A. System Health Scorecard

```sql
CREATE OR REPLACE VIEW V_SYSTEM_HEALTH_SCORECARD AS
SELECT
  SYSDATE as scorecard_date,

  -- Overall health score (0-100)
  ROUND((
    (compression_success_rate * 0.25) +
    (analysis_performance_score * 0.20) +
    (recommendation_accuracy_score * 0.25) +
    (value_realization_score * 0.20) +
    (system_performance_score * 0.10)
  ), 2) as overall_health_score,

  -- Component scores
  compression_success_rate,
  analysis_performance_score,
  recommendation_accuracy_score,
  value_realization_score,
  system_performance_score,

  -- Health status
  CASE
    WHEN overall_health_score >= 90 THEN 'EXCELLENT'
    WHEN overall_health_score >= 75 THEN 'GOOD'
    WHEN overall_health_score >= 60 THEN 'FAIR'
    WHEN overall_health_score >= 45 THEN 'POOR'
    ELSE 'CRITICAL'
  END as health_status

FROM (
  SELECT
    -- Compression success (last 30 days)
    (SELECT AVG(CASE WHEN execution_status = 'SUCCESS' THEN 100 ELSE 0 END)
     FROM COMPRESSION_HISTORY
     WHERE start_time > SYSDATE - 30) as compression_success_rate,

    -- Analysis performance (last 10 runs)
    (SELECT 100 - AVG(LEAST(error_rate_pct, 100))
     FROM (
       SELECT error_rate_pct
       FROM ANALYSIS_PERFORMANCE_METRICS
       ORDER BY start_time DESC
       FETCH FIRST 10 ROWS ONLY
     )) as analysis_performance_score,

    -- Recommendation accuracy (last 30 days)
    (SELECT AVG(ratio_accuracy_pct)
     FROM RECOMMENDATION_VALIDATION
     WHERE compression_date > SYSDATE - 30) as recommendation_accuracy_score,

    -- Value realization (last quarter)
    (SELECT AVG(realization_rate_pct)
     FROM V_VALUE_REALIZATION_METRICS
     WHERE month > ADD_MONTHS(TRUNC(SYSDATE, 'MM'), -3)) as value_realization_score,

    -- System performance (current)
    (SELECT 100 - AVG(decompress_pct_total_cpu)
     FROM SYSTEM_PERFORMANCE_METRICS
     WHERE metric_date = TRUNC(SYSDATE)) as system_performance_score

  FROM DUAL
);
```

#### B. Alert Definitions

```sql
CREATE TABLE ALERT_THRESHOLDS (
  ALERT_NAME            VARCHAR2(100) PRIMARY KEY,
  METRIC_NAME           VARCHAR2(100),
  THRESHOLD_TYPE        VARCHAR2(20),  -- UPPER, LOWER
  WARNING_THRESHOLD     NUMBER,
  CRITICAL_THRESHOLD    NUMBER,
  ENABLED               VARCHAR2(1) DEFAULT 'Y'
);

-- Example alert thresholds
INSERT INTO ALERT_THRESHOLDS VALUES
  ('COMPRESSION_FAILURE_RATE', 'EXECUTION_FAILURE_PCT', 'UPPER', 5, 10, 'Y'),
  ('ANALYSIS_ERROR_RATE', 'ANALYSIS_ERROR_PCT', 'UPPER', 3, 7, 'Y'),
  ('RECOMMENDATION_ACCURACY', 'RATIO_ACCURACY_PCT', 'LOWER', 85, 75, 'Y'),
  ('QUERY_DEGRADATION', 'PCT_QUERIES_DEGRADED_10PCT', 'UPPER', 8, 15, 'Y'),
  ('VALUE_REALIZATION', 'REALIZATION_RATE_PCT', 'LOWER', 80, 65, 'Y'),
  ('DECOMPRESSION_CPU', 'DECOMPRESS_PCT_TOTAL_CPU', 'UPPER', 20, 30, 'Y'),
  ('HEALTH_SCORE', 'OVERALL_HEALTH_SCORE', 'LOWER', 75, 60, 'Y');
```

### 6. Dashboard Metric Refresh Schedule

```sql
CREATE TABLE METRIC_REFRESH_SCHEDULE (
  METRIC_VIEW_NAME      VARCHAR2(100) PRIMARY KEY,
  REFRESH_FREQUENCY     VARCHAR2(50),
  LAST_REFRESH          TIMESTAMP,
  NEXT_REFRESH          TIMESTAMP,
  REFRESH_DURATION_SEC  NUMBER(8,2),
  IS_MATERIALIZED       VARCHAR2(1)
);

-- Recommended refresh frequencies
INSERT INTO METRIC_REFRESH_SCHEDULE VALUES
  ('V_STORAGE_EFFICIENCY_KPIS', 'HOURLY', NULL, NULL, NULL, 'N'),
  ('V_PERFORMANCE_IMPACT_SUMMARY', 'DAILY', NULL, NULL, NULL, 'Y'),
  ('V_COMPRESSION_EXECUTION_KPIS', 'REAL-TIME', NULL, NULL, NULL, 'N'),
  ('V_RECOMMENDATION_ACCURACY', 'DAILY', NULL, NULL, NULL, 'Y'),
  ('V_VALUE_REALIZATION_METRICS', 'WEEKLY', NULL, NULL, NULL, 'Y'),
  ('V_SYSTEM_HEALTH_SCORECARD', 'EVERY 5 MINUTES', NULL, NULL, NULL, 'N');
```

## Monitoring & Reporting Strategy

### Critical Daily Metrics
1. Compression success rate
2. Space savings (daily delta)
3. Analysis completion rate
4. System health score
5. Active alerts

### Weekly Review Metrics
1. Recommendation accuracy trends
2. Performance impact summary
3. ROI realization vs. forecast
4. Top compression opportunities
5. Capacity forecasting

### Monthly Business Metrics
1. Total cost savings achieved
2. Storage growth rate
3. Compression coverage percentage
4. Operational efficiency gains
5. Strategic roadmap progress

## Conclusion

This comprehensive metrics framework enables data-driven management of the HCC Compression Advisor system through:

- **Real-time operational monitoring** via health scores and alerts
- **Quality assurance** through recommendation accuracy tracking
- **Business value validation** via ROI realization metrics
- **Continuous improvement** driven by performance trend analysis
- **Executive reporting** with clear KPIs and success criteria

Regular monitoring of these metrics ensures the compression program delivers sustained business value while maintaining system performance and operational excellence.
