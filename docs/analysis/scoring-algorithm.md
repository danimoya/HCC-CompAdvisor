# HCC Compression Scoring Algorithm

## Executive Summary

This document defines the multi-dimensional scoring algorithm that evaluates Oracle database objects for Hybrid Columnar Compression (HCC) suitability. The algorithm synthesizes compression ratios, access patterns, DML activity, and storage metrics to produce actionable recommendations with confidence scores.

## Scoring Framework Architecture

### 1. Core Scoring Dimensions

The algorithm evaluates four primary dimensions:

#### A. Compression Efficiency Score (CES)
**Weight: 35%**

Measures the potential storage savings across all compression types:

```
CES = (
  (OLTP_RATIO × 0.15) +
  (QUERY_LOW_RATIO × 0.20) +
  (QUERY_HIGH_RATIO × 0.25) +
  (ARCHIVE_LOW_RATIO × 0.20) +
  (ARCHIVE_HIGH_RATIO × 0.20)
) / 5

Normalization: CES_NORMALIZED = MIN(100, CES × 20)
```

**Rationale**: Query High and Archive ratios receive higher weights as they typically yield superior compression for analytical workloads. OLTP receives lower weight as it's primarily for transactional patterns.

#### B. Activity Hotness Score (AHS)
**Weight: 30%**

Quantifies object access intensity and DML frequency:

```
DML_HEAT = (INSERTS + UPDATES + DELETES) / TIME_WINDOW_HOURS

ACCESS_INTENSITY = LOG10(1 + LOGICAL_READS + PHYSICAL_READS) / LOG10(1000000)

RECENCY_FACTOR = EXP(-DAYS_SINCE_LAST_ACCESS / 30)

AHS = (
  (DML_HEAT × 0.40) +
  (ACCESS_INTENSITY × 0.35) +
  (RECENCY_FACTOR × 0.25)
) × 100

Range: 0-100 (0=cold, 100=extremely hot)
```

**Data Sources**:
- `ALL_TAB_MODIFICATIONS`: DML statistics
- `DBA_HIST_SEG_STAT`: Historical segment access patterns
- `V$SEGMENT_STATISTICS`: Real-time access counters
- `DBA_TAB_STATISTICS`: Last analysis timestamps

#### C. Storage Impact Score (SIS)
**Weight: 25%**

Evaluates the business value of compressing based on size and growth:

```
SIZE_FACTOR = LOG10(SIZE_GB + 1) / LOG10(1000)

GROWTH_RATE = (CURRENT_SIZE - SIZE_30_DAYS_AGO) / SIZE_30_DAYS_AGO

TABLESPACE_PRESSURE = TABLESPACE_USED_PCT / 100

SIS = (
  (SIZE_FACTOR × 0.50) +
  (MIN(1.0, GROWTH_RATE) × 0.30) +
  (TABLESPACE_PRESSURE × 0.20)
) × 100

Range: 0-100 (higher = greater storage impact)
```

**Rationale**: Larger objects with rapid growth in constrained tablespaces receive higher priority.

#### D. Performance Risk Score (PRS)
**Weight: 10%**

Assesses potential query performance degradation:

```
READ_WRITE_RATIO = SELECT_COUNT / NULLIF(DML_COUNT, 0)

CPU_OVERHEAD_FACTOR = CASE COMPRESSION_TYPE
  WHEN 'OLTP' THEN 0.05
  WHEN 'QUERY_LOW' THEN 0.15
  WHEN 'QUERY_HIGH' THEN 0.25
  WHEN 'ARCHIVE_LOW' THEN 0.30
  WHEN 'ARCHIVE_HIGH' THEN 0.40
END

INDEX_DENSITY = INDEX_COUNT / COLUMN_COUNT

PRS = (
  (1 / (READ_WRITE_RATIO + 1) × 0.40) +
  (CPU_OVERHEAD_FACTOR × 0.35) +
  (MIN(1.0, INDEX_DENSITY) × 0.25)
) × 100

Range: 0-100 (lower = lower risk)
```

**Rationale**: Write-heavy tables with many indexes face higher compression risks.

### 2. Composite Compression Candidate Score (CCCS)

The final scoring formula combines all dimensions:

```
CCCS = (
  (CES_NORMALIZED × 0.35) +
  ((100 - AHS) × 0.30) +        -- Invert: colder = better candidate
  (SIS × 0.25) +
  ((100 - PRS) × 0.10)          -- Invert: lower risk = better
)

Final Score Range: 0-100
```

### 3. Recommendation Thresholds

Based on CCCS, objects are classified:

| Score Range | Classification | Action | Priority |
|------------|----------------|---------|----------|
| 85-100 | Excellent Candidate | Immediate compression | P0 |
| 70-84 | Good Candidate | Compress within 1 week | P1 |
| 55-69 | Moderate Candidate | Compress within 1 month | P2 |
| 40-54 | Marginal Candidate | Monitor, compress if space critical | P3 |
| 0-39 | Poor Candidate | Do not compress | P4 |

### 4. Compression Type Selection Algorithm

For objects scoring ≥55, determine optimal compression type:

```sql
OPTIMAL_COMPRESSION = CASE
  -- High DML activity → OLTP only
  WHEN DML_TOTAL_24H > 100000 THEN 'OLTP'
  WHEN AHS > 75 AND DML_TOTAL_24H > 10000 THEN 'OLTP'

  -- Medium activity, mixed workload
  WHEN AHS BETWEEN 50 AND 75 THEN
    CASE WHEN READ_WRITE_RATIO > 10 THEN 'QUERY_LOW' ELSE 'OLTP' END

  -- Low activity, read-heavy
  WHEN AHS BETWEEN 25 AND 50 AND READ_WRITE_RATIO > 50 THEN 'QUERY_HIGH'

  -- Very low activity, large size
  WHEN AHS < 25 AND SIZE_GB > 10 THEN
    CASE
      WHEN DML_TOTAL_24H = 0 THEN 'ARCHIVE_HIGH'
      WHEN DML_TOTAL_24H < 100 THEN 'ARCHIVE_LOW'
      ELSE 'QUERY_HIGH'
    END

  -- Archive candidates
  WHEN DAYS_SINCE_LAST_ACCESS > 90 THEN 'ARCHIVE_HIGH'
  WHEN DAYS_SINCE_LAST_ACCESS > 30 THEN 'ARCHIVE_LOW'

  -- Default safe choice
  ELSE 'QUERY_LOW'
END
```

### 5. Confidence Score

Each recommendation includes a confidence metric:

```
CONFIDENCE = (
  (DATA_QUALITY_SCORE × 0.30) +
  (SAMPLE_SIZE_ADEQUACY × 0.25) +
  (STATISTICS_FRESHNESS × 0.25) +
  (PATTERN_CONSISTENCY × 0.20)
) × 100

Where:
  DATA_QUALITY_SCORE = 1.0 if all required statistics exist, else 0.7
  SAMPLE_SIZE_ADEQUACY = MIN(1.0, ROWS_SAMPLED / 1000000)
  STATISTICS_FRESHNESS = EXP(-DAYS_SINCE_LAST_ANALYZE / 7)
  PATTERN_CONSISTENCY = 1 - STDDEV(DAILY_ACCESS_PATTERN) / MEAN(DAILY_ACCESS_PATTERN)

Range: 0-100 (higher = more reliable recommendation)
```

## Implementation Considerations

### Scoring Table Schema

```sql
CREATE TABLE COMPRESSION_CANDIDATE_SCORES (
  SCORE_ID              NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  OWNER                 VARCHAR2(128) NOT NULL,
  OBJECT_NAME           VARCHAR2(128) NOT NULL,
  OBJECT_TYPE           VARCHAR2(30) NOT NULL,
  PARTITION_NAME        VARCHAR2(128),

  -- Dimension Scores
  COMPRESSION_EFF_SCORE NUMBER(5,2),
  ACTIVITY_HOTNESS_SCORE NUMBER(5,2),
  STORAGE_IMPACT_SCORE  NUMBER(5,2),
  PERFORMANCE_RISK_SCORE NUMBER(5,2),

  -- Composite Score
  CANDIDATE_SCORE       NUMBER(5,2),
  CONFIDENCE_SCORE      NUMBER(5,2),

  -- Recommendation
  RECOMMENDED_COMPRESSION VARCHAR2(30),
  RECOMMENDATION_CLASS  VARCHAR2(20),
  PRIORITY_LEVEL        VARCHAR2(2),

  -- Metadata
  SCORE_DATE            TIMESTAMP DEFAULT SYSTIMESTAMP,
  EXPIRES_DATE          TIMESTAMP,

  CONSTRAINT CHK_SCORES CHECK (
    COMPRESSION_EFF_SCORE BETWEEN 0 AND 100 AND
    ACTIVITY_HOTNESS_SCORE BETWEEN 0 AND 100 AND
    STORAGE_IMPACT_SCORE BETWEEN 0 AND 100 AND
    PERFORMANCE_RISK_SCORE BETWEEN 0 AND 100 AND
    CANDIDATE_SCORE BETWEEN 0 AND 100 AND
    CONFIDENCE_SCORE BETWEEN 0 AND 100
  )
);

CREATE INDEX IDX_CAND_SCORE ON COMPRESSION_CANDIDATE_SCORES(CANDIDATE_SCORE DESC, CONFIDENCE_SCORE DESC);
CREATE INDEX IDX_PRIORITY ON COMPRESSION_CANDIDATE_SCORES(PRIORITY_LEVEL, CANDIDATE_SCORE DESC);
```

### Scoring Procedure Signature

```sql
PROCEDURE CALCULATE_COMPRESSION_SCORES(
  p_owner              IN VARCHAR2 DEFAULT NULL,
  p_recalculate_all    IN BOOLEAN DEFAULT FALSE,
  p_min_size_gb        IN NUMBER DEFAULT 0.1,
  p_parallel_degree    IN NUMBER DEFAULT 4,
  p_score_validity_days IN NUMBER DEFAULT 7
);
```

### Performance Optimization

- **Incremental Scoring**: Only recalculate scores for objects with material changes
- **Parallel Execution**: Leverage Oracle parallel query for multi-table scoring
- **Materialized Views**: Pre-compute expensive statistical aggregations
- **Partitioned Storage**: Partition score tables by date for efficient purging

### Score Refresh Strategy

```sql
-- Score expiration logic
EXPIRES_DATE = SCORE_DATE + INTERVAL '7' DAY

-- Trigger recalculation when:
1. Object statistics refreshed (DBA_TAB_STATISTICS.LAST_ANALYZED)
2. Significant DML activity (>10% row change)
3. Manual request
4. Score expired
```

## Validation Metrics

### Algorithm Accuracy KPIs

Monitor these metrics to validate scoring effectiveness:

1. **Precision**: % of high-scored candidates achieving ≥2:1 compression
   - Target: ≥90%

2. **Recall**: % of compressible objects (≥2:1 ratio) correctly identified
   - Target: ≥85%

3. **Performance Impact**: Query degradation post-compression
   - Target: <5% for OLTP, <2% for Query/Archive

4. **False Positive Rate**: High-scored objects with <1.5:1 compression
   - Target: <5%

### Continuous Improvement

```sql
CREATE TABLE SCORE_VALIDATION_METRICS (
  METRIC_DATE           DATE,
  TOTAL_SCORED          NUMBER,
  HIGH_SCORE_COUNT      NUMBER,
  ACTUAL_COMPRESSED     NUMBER,
  AVG_COMPRESSION_RATIO NUMBER(5,2),
  AVG_PERF_IMPACT_PCT   NUMBER(5,2),
  FALSE_POSITIVE_COUNT  NUMBER,
  PRECISION_PCT         NUMBER(5,2),
  RECALL_PCT            NUMBER(5,2)
);
```

## Algorithm Tuning Parameters

These weights can be adjusted based on organizational priorities:

```sql
CREATE TABLE SCORING_PARAMETERS (
  PARAMETER_NAME  VARCHAR2(50) PRIMARY KEY,
  PARAMETER_VALUE NUMBER(5,3),
  DESCRIPTION     VARCHAR2(500),
  EFFECTIVE_DATE  TIMESTAMP,
  MODIFIED_BY     VARCHAR2(100)
);

-- Default values
INSERT INTO SCORING_PARAMETERS VALUES
  ('CES_WEIGHT', 0.35, 'Compression Efficiency Score weight', SYSTIMESTAMP, 'SYSTEM'),
  ('AHS_WEIGHT', 0.30, 'Activity Hotness Score weight', SYSTIMESTAMP, 'SYSTEM'),
  ('SIS_WEIGHT', 0.25, 'Storage Impact Score weight', SYSTIMESTAMP, 'SYSTEM'),
  ('PRS_WEIGHT', 0.10, 'Performance Risk Score weight', SYSTIMESTAMP, 'SYSTEM');
```

## Example Score Calculation

**Object**: SALES.ORDERS_2023 (Partitioned Table)

**Input Metrics**:
- Size: 50 GB
- Compression ratios: OLTP=2.3, Query Low=3.5, Query High=5.2, Archive Low=6.1, Archive High=7.8
- DML last 24h: 1,500 operations
- Logical reads: 2,500,000
- Last access: 2 days ago
- Read/write ratio: 85:1

**Calculation**:

```
CES = (2.3×0.15 + 3.5×0.20 + 5.2×0.25 + 6.1×0.20 + 7.8×0.20) / 5 = 5.04
CES_NORMALIZED = MIN(100, 5.04 × 20) = 100

DML_HEAT = 1500/24 = 62.5
ACCESS_INTENSITY = LOG10(1 + 2500000) / LOG10(1000000) = 1.05
RECENCY_FACTOR = EXP(-2/30) = 0.935
AHS = (62.5×0.40 + 1.05×0.35 + 0.935×0.25) × 100 = 48.2

SIZE_FACTOR = LOG10(51) / LOG10(1000) = 0.568
GROWTH_RATE = 0.12 (12% monthly growth)
TABLESPACE_PRESSURE = 0.75
SIS = (0.568×0.50 + 0.12×0.30 + 0.75×0.20) × 100 = 46.4

READ_WRITE_RATIO = 85
CPU_OVERHEAD (Query High) = 0.25
INDEX_DENSITY = 5/12 = 0.417
PRS = (1/86×0.40 + 0.25×0.35 + 0.417×0.25) × 100 = 19.3

CCCS = (100×0.35 + 51.8×0.30 + 46.4×0.25 + 80.7×0.10) = 74.7
```

**Result**: Score 74.7 → "Good Candidate" (P1), Recommended: QUERY_HIGH, Confidence: 92%

## Conclusion

This multi-dimensional scoring algorithm provides objective, data-driven compression recommendations that balance storage efficiency, performance impact, and operational risk. The configurable weighting system allows tuning to organizational priorities while maintaining algorithmic consistency.
