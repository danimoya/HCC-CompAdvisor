# ROI Analysis Framework for HCC Compression

## Executive Summary

This framework quantifies the Return on Investment (ROI) for implementing Hybrid Columnar Compression (HCC) in Oracle Database environments. It provides methodologies for calculating storage cost savings, performance impacts, and break-even analysis to support data-driven compression decisions.

## Financial Impact Model

### 1. Storage Cost Calculation

#### A. Raw Storage Costs

```
STORAGE_COST_MODEL:

Annual Storage Cost Per TB = BASE_STORAGE_COST + PREMIUM_FACTORS

Where:
  BASE_STORAGE_COST = Hardware cost per TB / Useful life years

  PREMIUM_FACTORS include:
    - Data center costs (power, cooling, space)
    - Backup storage multiplication (typically 2-3x)
    - Disaster recovery replication (typically 1-2x)
    - Storage management overhead (15-20% of base)
    - RAID/redundancy overhead (20-50% depending on level)

Example for ExaCC (Exadata Cloud Customer):
  Primary storage: $2,500/TB/year
  Backup multiplication: 2x → $5,000/TB/year
  DR replication: 1x → $2,500/TB/year
  Management overhead: 20% → $2,000/TB/year
  ────────────────────────────────────────
  TOTAL: $12,000/TB/year or $1,000/TB/month
```

#### B. Compression Savings Formula

```sql
CREATE OR REPLACE FUNCTION calculate_storage_savings(
  p_original_size_gb IN NUMBER,
  p_compression_ratio IN NUMBER,
  p_cost_per_tb_monthly IN NUMBER DEFAULT 1000
) RETURN NUMBER IS
  v_compressed_size_gb NUMBER;
  v_space_saved_gb NUMBER;
  v_space_saved_tb NUMBER;
  v_monthly_savings NUMBER;
BEGIN
  v_compressed_size_gb := p_original_size_gb / p_compression_ratio;
  v_space_saved_gb := p_original_size_gb - v_compressed_size_gb;
  v_space_saved_tb := v_space_saved_gb / 1024;

  v_monthly_savings := v_space_saved_tb * p_cost_per_tb_monthly;

  RETURN v_monthly_savings;
END;
```

#### C. Multi-Factor Storage Economics

```
TOTAL_STORAGE_SAVINGS =
  PRIMARY_SAVINGS +
  BACKUP_SAVINGS +
  DR_SAVINGS +
  NETWORK_SAVINGS +
  OPERATIONAL_SAVINGS

Where:
  PRIMARY_SAVINGS = (Original_GB - Compressed_GB) / 1024 × Primary_Rate

  BACKUP_SAVINGS = PRIMARY_SAVINGS × BACKUP_MULTIPLIER
    - Faster backup windows
    - Reduced backup storage
    - Lower backup network bandwidth

  DR_SAVINGS = PRIMARY_SAVINGS × DR_MULTIPLIER
    - Reduced replication bandwidth
    - Lower DR site storage
    - Faster recovery times

  NETWORK_SAVINGS =
    (Data_Transferred_GB / 1024) × Network_Cost_Per_TB ×
    (1 - 1/Compression_Ratio)

  OPERATIONAL_SAVINGS =
    - Reduced storage administration time
    - Fewer disk replacements
    - Lower cooling requirements
    - Smaller data center footprint
```

### 2. Performance Impact Cost Model

#### A. CPU Overhead Estimation

```
CPU_COST_IMPACT:

Additional CPU for decompression =
  (Query_CPU_Seconds × CPU_OVERHEAD_FACTOR) × CPU_CORE_HOURLY_COST

CPU_OVERHEAD_FACTOR by compression type:
  OLTP:         5-8%   → 0.065 average
  QUERY LOW:    10-15% → 0.125 average
  QUERY HIGH:   15-25% → 0.200 average
  ARCHIVE LOW:  20-30% → 0.250 average
  ARCHIVE HIGH: 30-45% → 0.375 average

Example:
  Table scans: 1000 hours/month at $0.50/CPU-hour
  Compression: QUERY HIGH (20% overhead)
  Additional cost: 1000 × 0.20 × $0.50 = $100/month
```

#### B. I/O Performance Benefits

```
IO_BENEFIT_MODEL:

Reduced I/O cost =
  (Original_IO_GB - Compressed_IO_GB) × IO_COST_PER_GB

Benefits include:
  - Fewer disk IOPS required
  - Reduced SAN/NAS bandwidth
  - Lower storage tier requirements
  - Improved buffer cache efficiency

Quantification:
  Original table: 100 GB, scanned 50 times/month = 5,000 GB I/O
  Compressed 5:1: 20 GB, scanned 50 times/month = 1,000 GB I/O
  I/O reduction: 4,000 GB/month

  At $0.10/GB I/O cost: $400/month savings
```

#### C. Query Performance Impact Matrix

| Workload Type | Compression | Performance Impact | Cost Effect |
|--------------|-------------|-------------------|-------------|
| OLTP (row-by-row) | OLTP | +2-5% latency | Minimal |
| OLTP (row-by-row) | Query/Archive | +50-200% latency | Significant |
| Full table scans | OLTP | -10-15% time | Small benefit |
| Full table scans | Query High | -40-60% time | Large benefit |
| Full table scans | Archive High | -60-80% time | Very large benefit |
| Index range scans | Any HCC | +10-30% time | Moderate cost |
| Analytics/Reporting | Query/Archive | -50-75% time | Large benefit |

### 3. Comprehensive ROI Calculation

#### A. Monthly ROI Formula

```
MONTHLY_ROI = (MONTHLY_SAVINGS - MONTHLY_COSTS) / IMPLEMENTATION_COST

Where:
  MONTHLY_SAVINGS =
    Storage_Savings +
    Backup_Savings +
    DR_Savings +
    Network_Savings +
    IO_Performance_Benefit +
    Operational_Efficiency_Gains

  MONTHLY_COSTS =
    CPU_Overhead_Cost +
    Query_Performance_Degradation_Cost +
    Additional_Monitoring_Cost

  IMPLEMENTATION_COST =
    One_Time_Compression_CPU +
    Index_Rebuild_CPU +
    Testing_Resources +
    DBA_Time +
    Downtime_Cost (if applicable)
```

#### B. Break-Even Analysis

```sql
CREATE TABLE ROI_ANALYSIS (
  ANALYSIS_ID           NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  OWNER                 VARCHAR2(128),
  OBJECT_NAME           VARCHAR2(128),
  COMPRESSION_TYPE      VARCHAR2(30),

  -- Storage Economics
  ORIGINAL_SIZE_GB      NUMBER(12,2),
  COMPRESSED_SIZE_GB    NUMBER(12,2),
  COMPRESSION_RATIO     NUMBER(5,2),
  MONTHLY_STORAGE_SAVINGS NUMBER(12,2),
  ANNUAL_STORAGE_SAVINGS NUMBER(12,2),

  -- Performance Economics
  MONTHLY_CPU_OVERHEAD_COST NUMBER(12,2),
  MONTHLY_IO_SAVINGS    NUMBER(12,2),
  QUERY_PERF_IMPACT_PCT NUMBER(5,2),
  QUERY_PERF_COST_IMPACT NUMBER(12,2),

  -- Implementation Costs
  COMPRESSION_CPU_COST  NUMBER(12,2),
  INDEX_REBUILD_COST    NUMBER(12,2),
  TESTING_COST          NUMBER(12,2),
  DBA_TIME_COST         NUMBER(12,2),
  DOWNTIME_COST         NUMBER(12,2),
  TOTAL_IMPLEMENTATION_COST NUMBER(12,2),

  -- ROI Metrics
  NET_MONTHLY_BENEFIT   NUMBER(12,2),
  BREAK_EVEN_MONTHS     NUMBER(5,2),
  ANNUAL_ROI_PCT        NUMBER(6,2),
  NPV_3_YEAR            NUMBER(12,2),

  -- Risk Factors
  RISK_SCORE            NUMBER(3,0),
  RISK_CATEGORY         VARCHAR2(20),

  ANALYSIS_DATE         TIMESTAMP DEFAULT SYSTIMESTAMP
);

-- Break-even calculation
CREATE OR REPLACE FUNCTION calculate_break_even(
  p_implementation_cost IN NUMBER,
  p_monthly_net_benefit IN NUMBER
) RETURN NUMBER IS
BEGIN
  IF p_monthly_net_benefit <= 0 THEN
    RETURN NULL; -- Never breaks even
  ELSE
    RETURN p_implementation_cost / p_monthly_net_benefit;
  END IF;
END;
```

#### C. Net Present Value (NPV) Model

```
NPV = Σ(t=1 to n) [Net_Monthly_Benefit_t / (1 + DISCOUNT_RATE)^t] - Initial_Cost

Where:
  n = Analysis period (typically 36 months)
  DISCOUNT_RATE = Monthly cost of capital (typically 0.5-1%)
  Net_Monthly_Benefit = Monthly_Savings - Monthly_Costs

Example:
  Initial cost: $5,000
  Monthly benefit: $1,200
  Discount rate: 0.6% monthly
  Period: 36 months

  NPV = $1,200 × [(1 - (1.006)^-36) / 0.006] - $5,000
      = $1,200 × 32.87 - $5,000
      = $39,444 - $5,000
      = $34,444
```

### 4. Risk-Adjusted ROI

#### A. Risk Factors

```
RISK_SCORE =
  (COMPLEXITY_RISK × 0.25) +
  (PERFORMANCE_RISK × 0.30) +
  (OPERATIONAL_RISK × 0.20) +
  (BUSINESS_RISK × 0.25)

Where each risk scored 0-100:

COMPLEXITY_RISK:
  - Object dependencies (triggers, views, materialized views)
  - Partitioning complexity
  - Application coupling
  - Number of related indexes

PERFORMANCE_RISK:
  - Query pattern sensitivity
  - SLA requirements
  - Peak load impact
  - Compression type aggressiveness

OPERATIONAL_RISK:
  - Backup window constraints
  - Maintenance window availability
  - Team expertise level
  - Rollback complexity

BUSINESS_RISK:
  - Business criticality
  - User visibility
  - Downtime tolerance
  - Regulatory requirements
```

#### B. Risk-Adjusted Return Formula

```
RISK_ADJUSTED_ROI = BASE_ROI × (1 - RISK_FACTOR)

Where:
  RISK_FACTOR = MIN(0.5, RISK_SCORE / 200)

  Risk Score 0-20   → Risk Factor 0.00-0.10 (minimal adjustment)
  Risk Score 21-50  → Risk Factor 0.11-0.25 (low adjustment)
  Risk Score 51-80  → Risk Factor 0.26-0.40 (moderate adjustment)
  Risk Score 81-100 → Risk Factor 0.41-0.50 (high adjustment)

Example:
  Base ROI: 450% (3-year)
  Risk Score: 65
  Risk Factor: 0.325
  Risk-Adjusted ROI: 450% × (1 - 0.325) = 304%
```

### 5. Scenario Analysis Templates

#### A. Conservative Scenario

```
Assumptions:
  - Lower compression ratios (pessimistic)
  - Higher CPU overhead estimates
  - Higher implementation costs
  - Longer compression windows
  - Performance degradation at high end of range

Use case: Risk-averse environments, mission-critical systems
```

#### B. Expected Scenario

```
Assumptions:
  - Average compression ratios from analysis
  - Typical CPU overhead
  - Standard implementation timeline
  - Normal performance impact

Use case: Standard business case, most common scenario
```

#### C. Optimistic Scenario

```
Assumptions:
  - Higher compression ratios (best case)
  - Lower CPU overhead (modern hardware)
  - Efficient implementation
  - Minimal performance impact
  - Additional operational benefits

Use case: Ideal conditions, modern infrastructure, read-heavy workloads
```

### 6. Cost-Benefit Dashboard Metrics

```sql
CREATE OR REPLACE VIEW V_ROI_DASHBOARD AS
SELECT
  owner,
  COUNT(*) as total_candidates,
  SUM(original_size_gb) as total_original_gb,
  SUM(compressed_size_gb) as total_compressed_gb,
  SUM(monthly_storage_savings) as monthly_savings,
  SUM(annual_storage_savings) as annual_savings,
  SUM(total_implementation_cost) as total_investment,
  AVG(break_even_months) as avg_break_even_months,
  AVG(annual_roi_pct) as avg_annual_roi_pct,
  SUM(npv_3_year) as total_npv_3year,

  -- Quick metrics
  ROUND(SUM(annual_storage_savings) / NULLIF(SUM(total_implementation_cost), 0) * 100, 2)
    as simple_roi_pct,

  ROUND(SUM(total_implementation_cost) / NULLIF(SUM(monthly_storage_savings), 0), 2)
    as payback_months

FROM ROI_ANALYSIS
WHERE break_even_months IS NOT NULL
  AND break_even_months < 24  -- Only include reasonable ROI
GROUP BY owner;
```

## Implementation Cost Breakdown

### Compression Execution Costs

```
COMPRESSION_COST = CPU_COST + TIME_COST + RISK_COST

CPU_COST =
  (Table_Size_GB / Compression_Speed_GB_per_hour) × CPU_Core_Hours × Rate

Where:
  Compression_Speed: 50-200 GB/hour (depends on CPU, I/O, compression type)
  CPU_Core_Hours: Typically 2-4 cores during compression
  Rate: Cloud OCPU rate or internal cost

Example:
  500 GB table
  Compression speed: 100 GB/hour
  4 OCPUs at $0.50/OCPU-hour

  Time: 500/100 = 5 hours
  CPU cost: 5 hours × 4 OCPUs × $0.50 = $10

TIME_COST =
  Elapsed_Hours × Business_Value_Per_Hour

  For non-production: typically minimal
  For production: potential revenue impact during compression

RISK_COST =
  Probability_of_Issues × Average_Issue_Cost

  Typical: 5-10% probability × $1,000-$5,000 = $50-$500
```

### Index Rebuild Costs

```
INDEX_REBUILD_COST =
  Σ(Index_Size_GB × Rebuild_Time_Factor × CPU_Rate)

Where:
  Rebuild_Time_Factor: 0.5-2.0 hours per GB (depends on complexity)

Example:
  Table with 5 indexes totaling 100 GB
  Average rebuild time: 1 hour/GB
  4 OCPUs at $0.50/hour

  Cost: 100 GB × 1 hour/GB × 4 × $0.50 = $200
```

## ROI Report Template

```sql
CREATE OR REPLACE PROCEDURE generate_roi_report(
  p_owner IN VARCHAR2,
  p_output_format IN VARCHAR2 DEFAULT 'JSON'
) IS
  v_report CLOB;
BEGIN
  SELECT JSON_OBJECT(
    'executive_summary' VALUE JSON_OBJECT(
      'total_objects' VALUE COUNT(*),
      'total_original_size_tb' VALUE ROUND(SUM(original_size_gb)/1024, 2),
      'total_compressed_size_tb' VALUE ROUND(SUM(compressed_size_gb)/1024, 2),
      'total_space_saved_tb' VALUE ROUND(SUM(original_size_gb - compressed_size_gb)/1024, 2),
      'annual_cost_savings' VALUE ROUND(SUM(annual_storage_savings), 2),
      'total_investment' VALUE ROUND(SUM(total_implementation_cost), 2),
      'overall_roi_pct' VALUE ROUND(
        SUM(annual_storage_savings) / NULLIF(SUM(total_implementation_cost), 0) * 100, 2
      ),
      'average_payback_months' VALUE ROUND(AVG(break_even_months), 1)
    ),

    'by_compression_type' VALUE (
      SELECT JSON_ARRAYAGG(
        JSON_OBJECT(
          'compression_type' VALUE compression_type,
          'object_count' VALUE cnt,
          'annual_savings' VALUE annual_savings,
          'avg_roi_pct' VALUE avg_roi
        )
      )
      FROM (
        SELECT
          compression_type,
          COUNT(*) as cnt,
          ROUND(SUM(annual_storage_savings), 2) as annual_savings,
          ROUND(AVG(annual_roi_pct), 2) as avg_roi
        FROM ROI_ANALYSIS
        WHERE owner = p_owner
        GROUP BY compression_type
      )
    ),

    'top_opportunities' VALUE (
      SELECT JSON_ARRAYAGG(
        JSON_OBJECT(
          'object_name' VALUE object_name,
          'compression_type' VALUE compression_type,
          'annual_savings' VALUE annual_savings,
          'break_even_months' VALUE break_even_months,
          'roi_pct' VALUE annual_roi_pct
        )
        ORDER BY annual_storage_savings DESC
      )
      FROM (
        SELECT *
        FROM ROI_ANALYSIS
        WHERE owner = p_owner
          AND annual_roi_pct > 100
        ORDER BY annual_storage_savings DESC
        FETCH FIRST 20 ROWS ONLY
      )
    )
  )
  INTO v_report
  FROM ROI_ANALYSIS
  WHERE owner = p_owner;

  DBMS_OUTPUT.PUT_LINE(v_report);
END;
```

## Conclusion

This ROI framework provides comprehensive financial analysis for HCC compression decisions, balancing:

- **Storage cost savings** across primary, backup, and DR environments
- **Performance impacts** from CPU overhead and I/O improvements
- **Implementation costs** including compression, rebuilds, and testing
- **Risk factors** that may affect actual outcomes

By calculating NPV, break-even points, and risk-adjusted returns, organizations can make data-driven compression decisions that maximize business value while managing operational risk.
