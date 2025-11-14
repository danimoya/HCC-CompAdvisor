# Reporting Specifications for HCC Compression Advisor

## Executive Summary

This document defines comprehensive reporting requirements for the HCC Compression Advisor system, including executive dashboards, operational reports, analytical views, and integration specifications for Streamlit-based visualization and ORDS RESTful endpoints.

## Report Architecture

### 1. Report Hierarchy

```
├── Executive Summary Reports (C-Level)
│   ├── Strategic ROI Dashboard
│   ├── Capacity Forecast Report
│   └── Quarterly Business Review
│
├── Management Reports (Director/Manager)
│   ├── Compression Program Status
│   ├── Performance Impact Analysis
│   ├── Resource Utilization Dashboard
│   └── Trend Analysis Reports
│
├── Operational Reports (DBA/Engineer)
│   ├── Daily Compression Activity
│   ├── Object Recommendation Queue
│   ├── Execution Status Monitor
│   ├── Error & Exception Report
│   └── Performance Baseline Comparisons
│
└── Analytical Reports (Analysts)
    ├── Historical Trend Analysis
    ├── Pattern Recognition Reports
    ├── Scenario Simulation Results
    └── Ad-hoc Query Interface
```

## Executive Reports

### 1. Strategic ROI Dashboard

**Purpose**: High-level business value summary for executives
**Refresh Frequency**: Daily
**Data Retention**: 24 months

#### Report Schema

```sql
CREATE OR REPLACE VIEW V_EXECUTIVE_ROI_DASHBOARD AS
SELECT
  -- Time period
  SYSDATE as report_date,
  'LAST_30_DAYS' as period_label,

  -- Storage metrics
  ROUND(SUM(CASE WHEN ch.start_time > SYSDATE - 30
    THEN ch.space_saved_mb END) / 1024, 2) as space_saved_tb_30d,
  ROUND(SUM(ch.space_saved_mb) / 1024, 2) as space_saved_tb_total,

  -- Financial metrics
  ROUND(SUM(CASE WHEN ch.start_time > SYSDATE - 30
    THEN (ch.space_saved_mb / 1024) * 1000 END), 0) as monthly_savings_usd,
  ROUND(SUM((ch.space_saved_mb / 1024) * 12000), 0) as annual_savings_usd,

  -- Compression coverage
  ROUND(SUM(ch.compressed_size_mb) / NULLIF(
    (SELECT SUM(bytes) FROM dba_segments WHERE owner NOT IN
      ('SYS','SYSTEM','ORACLE_OCM','XDB')) / 1024 / 1024, 0) * 100, 2)
    as compression_coverage_pct,

  -- Performance summary
  ROUND(AVG(CASE WHEN ch.start_time > SYSDATE - 30
    THEN ch.compression_ratio_achieved END), 2) as avg_compression_ratio_30d,

  -- Success metrics
  ROUND(SUM(CASE WHEN ch.execution_status = 'SUCCESS'
    AND ch.start_time > SYSDATE - 30 THEN 1 ELSE 0 END) /
    NULLIF(SUM(CASE WHEN ch.start_time > SYSDATE - 30 THEN 1 ELSE 0 END), 0) * 100, 2)
    as success_rate_30d_pct,

  -- Capacity forecast
  ROUND((SELECT SUM(bytes)/1024/1024/1024 FROM dba_segments) -
    SUM(ch.space_saved_mb)/1024, 2) as current_capacity_gb,
  ROUND(SUM(CASE WHEN scs.candidate_score >= 70
    THEN car.original_size_gb * (1 - 1/car.query_high_ratio) END), 2)
    as potential_savings_gb

FROM COMPRESSION_HISTORY ch
LEFT JOIN COMPRESSION_ANALYSIS_RESULTS car
  ON ch.owner = car.owner AND ch.object_name = car.object_name
LEFT JOIN COMPRESSION_CANDIDATE_SCORES scs
  ON ch.owner = scs.owner AND ch.object_name = scs.object_name;
```

#### Report Output Format (JSON)

```json
{
  "executive_summary": {
    "report_date": "2025-11-13",
    "period": "Last 30 Days",
    "key_metrics": {
      "space_saved_tb": 45.7,
      "monthly_savings_usd": 45700,
      "annual_run_rate_usd": 548400,
      "compression_coverage_pct": 62.3,
      "avg_compression_ratio": 4.8,
      "success_rate_pct": 97.5
    },
    "capacity_forecast": {
      "current_utilization_gb": 1247,
      "potential_savings_gb": 312,
      "months_growth_absorbed": 18
    },
    "trend": {
      "vs_last_month": "+12.3%",
      "vs_last_quarter": "+34.7%"
    }
  }
}
```

#### Streamlit Dashboard Component

```python
import streamlit as st
import oracledb
import plotly.graph_objects as go

def render_executive_dashboard(connection):
    """Executive ROI Dashboard"""

    st.title("🎯 HCC Compression - Executive Dashboard")

    # Fetch data
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM V_EXECUTIVE_ROI_DASHBOARD")
    data = cursor.fetchone()

    # KPI Cards
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Monthly Savings",
            f"${data[3]:,.0f}",
            delta=f"{data[10]} vs last month"
        )

    with col2:
        st.metric(
            "Space Saved (TB)",
            f"{data[1]:.1f}",
            delta=f"+{data[1]-data[0]:.1f} TB this month"
        )

    with col3:
        st.metric(
            "Compression Ratio",
            f"{data[6]:.1f}:1",
            delta="Target: 4.0:1"
        )

    with col4:
        st.metric(
            "Success Rate",
            f"{data[7]:.1f}%",
            delta="Target: 95%"
        )

    # Trend chart
    st.subheader("Cumulative Savings Trend")

    cursor.execute("""
        SELECT TRUNC(end_time, 'MM') as month,
               SUM(space_saved_mb)/1024 as saved_tb,
               SUM((space_saved_mb/1024) * 1000) as savings_usd
        FROM COMPRESSION_HISTORY
        WHERE execution_status = 'SUCCESS'
          AND end_time > ADD_MONTHS(SYSDATE, -12)
        GROUP BY TRUNC(end_time, 'MM')
        ORDER BY month
    """)

    trend_data = cursor.fetchall()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[row[0] for row in trend_data],
        y=[row[2] for row in trend_data],
        name='Monthly Savings ($)',
        yaxis='y1'
    ))
    fig.add_trace(go.Scatter(
        x=[row[0] for row in trend_data],
        y=[sum(r[1] for r in trend_data[:i+1])
           for i in range(len(trend_data))],
        name='Cumulative Savings (TB)',
        yaxis='y2',
        line=dict(color='red', width=3)
    ))

    fig.update_layout(
        yaxis=dict(title='Monthly Savings ($)'),
        yaxis2=dict(title='Cumulative TB Saved', overlaying='y', side='right')
    )

    st.plotly_chart(fig, use_container_width=True)
```

### 2. Compression Program Status Report

**Purpose**: Management-level operational summary
**Refresh Frequency**: Daily
**Data Retention**: 12 months

```sql
CREATE OR REPLACE VIEW V_PROGRAM_STATUS_REPORT AS
SELECT
  -- Period summary
  TRUNC(SYSDATE) as report_date,

  -- Pipeline metrics
  (SELECT COUNT(*) FROM COMPRESSION_CANDIDATE_SCORES
   WHERE candidate_score >= 85) as tier1_candidates,
  (SELECT COUNT(*) FROM COMPRESSION_CANDIDATE_SCORES
   WHERE candidate_score BETWEEN 70 AND 84) as tier2_candidates,
  (SELECT COUNT(*) FROM COMPRESSION_CANDIDATE_SCORES
   WHERE candidate_score BETWEEN 55 AND 69) as tier3_candidates,

  -- Execution status
  (SELECT COUNT(*) FROM COMPRESSION_HISTORY
   WHERE start_time > SYSDATE - 7
     AND execution_status = 'IN_PROGRESS') as active_compressions,
  (SELECT COUNT(*) FROM COMPRESSION_HISTORY
   WHERE start_time > SYSDATE - 7
     AND execution_status = 'SUCCESS') as completed_last_7d,
  (SELECT COUNT(*) FROM COMPRESSION_HISTORY
   WHERE start_time > SYSDATE - 7
     AND execution_status = 'FAILED') as failed_last_7d,

  -- Resource utilization
  (SELECT SUM(EXTRACT(HOUR FROM (end_time - start_time)) * 60 +
              EXTRACT(MINUTE FROM (end_time - start_time)))
   FROM COMPRESSION_HISTORY
   WHERE start_time > SYSDATE - 7
     AND execution_status = 'SUCCESS') as total_compression_minutes_7d,

  -- Quality metrics
  (SELECT AVG(confidence_score) FROM COMPRESSION_CANDIDATE_SCORES
   WHERE score_date > SYSDATE - 7) as avg_confidence_score,
  (SELECT AVG(ratio_accuracy_pct) FROM RECOMMENDATION_VALIDATION
   WHERE compression_date > SYSDATE - 7) as avg_prediction_accuracy,

  -- Upcoming work
  (SELECT COUNT(*) FROM COMPRESSION_CANDIDATE_SCORES
   WHERE candidate_score >= 70
     AND NOT EXISTS (
       SELECT 1 FROM COMPRESSION_HISTORY ch
       WHERE ch.owner = COMPRESSION_CANDIDATE_SCORES.owner
         AND ch.object_name = COMPRESSION_CANDIDATE_SCORES.object_name
     )) as pending_recommendations,

  -- Risk indicators
  (SELECT COUNT(*) FROM COMPRESSION_HISTORY
   WHERE start_time > SYSDATE - 7
     AND execution_status = 'FAILED') as failure_count_7d,
  (SELECT COUNT(*) FROM QUERY_PERFORMANCE_BASELINE
   WHERE post_compression_date > SYSDATE - 7
     AND elapsed_time_change_pct > 25) as perf_degradation_count

FROM DUAL;
```

## Operational Reports

### 3. Daily Compression Activity Report

**Purpose**: DBA operational monitoring
**Refresh Frequency**: Real-time
**Data Retention**: 90 days

```sql
CREATE OR REPLACE VIEW V_DAILY_ACTIVITY_REPORT AS
SELECT
  ch.execution_id,
  ch.owner,
  ch.object_name,
  ch.object_type,
  ch.compression_type_applied,

  -- Size metrics
  ROUND(ch.original_size_mb / 1024, 2) as original_size_gb,
  ROUND(ch.compressed_size_mb / 1024, 2) as compressed_size_gb,
  ROUND(ch.space_saved_mb / 1024, 2) as space_saved_gb,
  ch.compression_ratio_achieved,

  -- Time metrics
  ch.start_time,
  ch.end_time,
  ROUND(EXTRACT(HOUR FROM (ch.end_time - ch.start_time)) * 60 +
        EXTRACT(MINUTE FROM (ch.end_time - ch.start_time)), 2) as duration_minutes,

  -- Status
  ch.execution_status,
  CASE
    WHEN ch.execution_status = 'SUCCESS' THEN '✓'
    WHEN ch.execution_status = 'FAILED' THEN '✗'
    WHEN ch.execution_status = 'IN_PROGRESS' THEN '⟳'
    ELSE '?'
  END as status_icon,

  ch.error_message,

  -- Performance comparison
  qpb.elapsed_time_change_pct,
  qpb.cpu_time_change_pct,
  qpb.io_change_pct,

  -- Financial impact
  ROUND((ch.space_saved_mb / 1024) * 1000, 2) as monthly_savings_usd,

  -- Metadata
  (SELECT username FROM dba_users WHERE user_id = USERENV('SESSIONID')) as executed_by

FROM COMPRESSION_HISTORY ch
LEFT JOIN QUERY_PERFORMANCE_BASELINE qpb
  ON ch.owner = qpb.owner
  AND ch.object_name = qpb.object_name
  AND ch.compression_type_applied = qpb.compression_type
WHERE ch.start_time > TRUNC(SYSDATE)
ORDER BY ch.start_time DESC;
```

#### Streamlit Operational Dashboard

```python
def render_operational_dashboard(connection):
    """Daily operational monitoring"""

    st.title("📊 Daily Compression Activity")

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        date_filter = st.date_input("Date", value=datetime.today())
    with col2:
        status_filter = st.selectbox("Status",
            ["All", "Success", "Failed", "In Progress"])
    with col3:
        owner_filter = st.text_input("Schema Owner")

    # Build query
    query = "SELECT * FROM V_DAILY_ACTIVITY_REPORT WHERE 1=1"
    params = {}

    if status_filter != "All":
        query += " AND execution_status = :status"
        params['status'] = status_filter.upper()

    if owner_filter:
        query += " AND owner LIKE :owner"
        params['owner'] = f"%{owner_filter}%"

    # Fetch data
    df = pd.read_sql(query, connection, params=params)

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Compressions", len(df))
    with col2:
        st.metric("Success Rate",
            f"{(df['EXECUTION_STATUS']=='SUCCESS').sum()/len(df)*100:.1f}%")
    with col3:
        st.metric("Total Saved (GB)", f"{df['SPACE_SAVED_GB'].sum():.1f}")
    with col4:
        st.metric("Avg Ratio", f"{df['COMPRESSION_RATIO_ACHIEVED'].mean():.1f}:1")

    # Detailed table
    st.subheader("Compression Details")
    st.dataframe(
        df[['OBJECT_NAME', 'COMPRESSION_TYPE_APPLIED', 'ORIGINAL_SIZE_GB',
            'COMPRESSED_SIZE_GB', 'COMPRESSION_RATIO_ACHIEVED', 'STATUS_ICON',
            'DURATION_MINUTES', 'MONTHLY_SAVINGS_USD']],
        use_container_width=True
    )

    # Download option
    csv = df.to_csv(index=False)
    st.download_button(
        "Download Report (CSV)",
        csv,
        f"compression_report_{date_filter}.csv",
        "text/csv"
    )
```

### 4. Object Recommendation Queue

**Purpose**: Prioritized list of compression candidates
**Refresh Frequency**: Daily
**Data Retention**: Current snapshot only

```sql
CREATE OR REPLACE VIEW V_RECOMMENDATION_QUEUE AS
SELECT
  ROWNUM as queue_position,
  scs.owner,
  scs.object_name,
  scs.object_type,
  scs.partition_name,

  -- Scoring
  scs.candidate_score,
  scs.confidence_score,
  scs.priority_level,
  scs.recommendation_class,

  -- Compression details
  scs.recommended_compression,
  CASE scs.recommended_compression
    WHEN 'OLTP' THEN car.oltp_ratio
    WHEN 'QUERY_LOW' THEN car.query_low_ratio
    WHEN 'QUERY_HIGH' THEN car.query_high_ratio
    WHEN 'ARCHIVE_LOW' THEN car.archive_low_ratio
    WHEN 'ARCHIVE_HIGH' THEN car.archive_high_ratio
  END as expected_compression_ratio,

  -- Size and savings
  car.original_size_gb,
  ROUND(car.original_size_gb * (1 - 1/CASE scs.recommended_compression
    WHEN 'OLTP' THEN car.oltp_ratio
    WHEN 'QUERY_LOW' THEN car.query_low_ratio
    WHEN 'QUERY_HIGH' THEN car.query_high_ratio
    WHEN 'ARCHIVE_LOW' THEN car.archive_low_ratio
    WHEN 'ARCHIVE_HIGH' THEN car.archive_high_ratio
  END), 2) as projected_savings_gb,

  -- Financial impact
  ROUND((car.original_size_gb * (1 - 1/CASE scs.recommended_compression
    WHEN 'OLTP' THEN car.oltp_ratio
    WHEN 'QUERY_LOW' THEN car.query_low_ratio
    WHEN 'QUERY_HIGH' THEN car.query_high_ratio
    WHEN 'ARCHIVE_LOW' THEN car.archive_low_ratio
    WHEN 'ARCHIVE_HIGH' THEN car.archive_high_ratio
  END)) * 1000, 2) as monthly_savings_usd,

  -- Activity metrics
  scs.activity_hotness_score,
  car.total_operations,
  car.hotness_score,

  -- Risk assessment
  scs.performance_risk_score,
  CASE
    WHEN scs.performance_risk_score < 20 THEN 'LOW'
    WHEN scs.performance_risk_score < 40 THEN 'MEDIUM'
    ELSE 'HIGH'
  END as risk_category,

  -- Estimated effort
  ROUND(car.original_size_gb / 100, 2) as estimated_hours,

  -- Status
  CASE
    WHEN EXISTS (SELECT 1 FROM COMPRESSION_HISTORY ch
                 WHERE ch.owner = scs.owner
                   AND ch.object_name = scs.object_name
                   AND ch.execution_status = 'SUCCESS')
    THEN 'COMPLETED'
    WHEN EXISTS (SELECT 1 FROM COMPRESSION_HISTORY ch
                 WHERE ch.owner = scs.owner
                   AND ch.object_name = scs.object_name
                   AND ch.execution_status = 'IN_PROGRESS')
    THEN 'IN_PROGRESS'
    ELSE 'PENDING'
  END as execution_status,

  scs.score_date,
  scs.expires_date

FROM COMPRESSION_CANDIDATE_SCORES scs
JOIN COMPRESSION_ANALYSIS_RESULTS car
  ON scs.owner = car.owner
  AND scs.object_name = car.object_name
  AND NVL(scs.partition_name, 'NULL') = NVL(car.partition_name, 'NULL')
WHERE scs.candidate_score >= 55  -- Only good+ candidates
  AND scs.expires_date > SYSDATE  -- Valid scores only
  AND NOT EXISTS (
    SELECT 1 FROM COMPRESSION_HISTORY ch
    WHERE ch.owner = scs.owner
      AND ch.object_name = scs.object_name
      AND ch.execution_status = 'SUCCESS'
  )
ORDER BY
  scs.priority_level,
  scs.candidate_score DESC,
  projected_savings_gb DESC;
```

## Analytical Reports

### 5. Historical Trend Analysis

**Purpose**: Pattern recognition and forecasting
**Refresh Frequency**: Weekly
**Data Retention**: 24 months

```sql
CREATE OR REPLACE VIEW V_HISTORICAL_TRENDS AS
WITH monthly_metrics AS (
  SELECT
    TRUNC(end_time, 'MM') as month,
    compression_type_applied,
    COUNT(*) as compression_count,
    SUM(space_saved_mb)/1024 as space_saved_tb,
    AVG(compression_ratio_achieved) as avg_ratio,
    SUM((space_saved_mb/1024) * 1000) as monthly_savings
  FROM COMPRESSION_HISTORY
  WHERE execution_status = 'SUCCESS'
  GROUP BY TRUNC(end_time, 'MM'), compression_type_applied
)
SELECT
  month,
  compression_type_applied,
  compression_count,
  space_saved_tb,
  avg_ratio,
  monthly_savings,

  -- Running totals
  SUM(space_saved_tb) OVER (
    PARTITION BY compression_type_applied
    ORDER BY month
  ) as cumulative_saved_tb,

  SUM(monthly_savings) OVER (
    PARTITION BY compression_type_applied
    ORDER BY month
  ) as cumulative_savings_usd,

  -- Month-over-month growth
  ROUND((space_saved_tb - LAG(space_saved_tb) OVER (
    PARTITION BY compression_type_applied ORDER BY month
  )) / NULLIF(LAG(space_saved_tb) OVER (
    PARTITION BY compression_type_applied ORDER BY month
  ), 0) * 100, 2) as mom_growth_pct,

  -- Moving averages
  ROUND(AVG(space_saved_tb) OVER (
    PARTITION BY compression_type_applied
    ORDER BY month
    ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
  ), 2) as ma3_saved_tb,

  -- Trend indicator
  CASE
    WHEN space_saved_tb > LAG(space_saved_tb) OVER (
      PARTITION BY compression_type_applied ORDER BY month
    ) THEN '↑'
    WHEN space_saved_tb < LAG(space_saved_tb) OVER (
      PARTITION BY compression_type_applied ORDER BY month
    ) THEN '↓'
    ELSE '→'
  END as trend

FROM monthly_metrics
ORDER BY month DESC, compression_type_applied;
```

## ORDS REST API Endpoints

### 6. RESTful Report Access

```sql
-- Report catalog endpoint
BEGIN
  ORDS.DEFINE_MODULE(
    p_module_name => 'compression.reports',
    p_base_path => 'reports/',
    p_items_per_page => 100
  );

  -- Executive dashboard
  ORDS.DEFINE_TEMPLATE(
    p_module_name => 'compression.reports',
    p_pattern => 'executive/dashboard'
  );

  ORDS.DEFINE_HANDLER(
    p_module_name => 'compression.reports',
    p_pattern => 'executive/dashboard',
    p_method => 'GET',
    p_source_type => ORDS.source_type_query,
    p_source => 'SELECT * FROM V_EXECUTIVE_ROI_DASHBOARD'
  );

  -- Daily activity report
  ORDS.DEFINE_TEMPLATE(
    p_module_name => 'compression.reports',
    p_pattern => 'activity/daily/:report_date'
  );

  ORDS.DEFINE_HANDLER(
    p_module_name => 'compression.reports',
    p_pattern => 'activity/daily/:report_date',
    p_method => 'GET',
    p_source_type => ORDS.source_type_query,
    p_source => q'[
      SELECT * FROM V_DAILY_ACTIVITY_REPORT
      WHERE TRUNC(start_time) = TO_DATE(:report_date, 'YYYY-MM-DD')
    ]'
  );

  -- Recommendation queue
  ORDS.DEFINE_TEMPLATE(
    p_module_name => 'compression.reports',
    p_pattern => 'recommendations/queue'
  );

  ORDS.DEFINE_HANDLER(
    p_module_name => 'compression.reports',
    p_pattern => 'recommendations/queue',
    p_method => 'GET',
    p_source_type => ORDS.source_type_query,
    p_source => q'[
      SELECT * FROM V_RECOMMENDATION_QUEUE
      WHERE queue_position <= NVL(:limit, 100)
      ORDER BY queue_position
    ]'
  );

  COMMIT;
END;
/
```

### Example cURL Commands

```bash
# Get executive dashboard
curl -X GET "https://your-ords-host/ords/compression/reports/executive/dashboard" \
  -H "Content-Type: application/json"

# Get daily activity for specific date
curl -X GET "https://your-ords-host/ords/compression/reports/activity/daily/2025-11-13" \
  -H "Content-Type: application/json"

# Get top 50 recommendations
curl -X GET "https://your-ords-host/ords/compression/reports/recommendations/queue?limit=50" \
  -H "Content-Type: application/json"

# Get historical trends
curl -X GET "https://your-ords-host/ords/compression/reports/trends/historical?months=12" \
  -H "Content-Type: application/json"
```

## Streamlit Dashboard Integration

### Complete Dashboard Application Structure

```python
# app/main.py
import streamlit as st
import oracledb
from pages import executive, operational, analytical

st.set_page_config(
    page_title="HCC Compression Advisor",
    page_icon="📊",
    layout="wide"
)

# Database connection
@st.cache_resource
def get_database_connection():
    return oracledb.connect(
        user=st.secrets["db_user"],
        password=st.secrets["db_password"],
        dsn=st.secrets["db_dsn"]
    )

# Navigation
page = st.sidebar.selectbox(
    "Report Category",
    ["Executive Dashboard", "Operational Reports", "Analytical Reports"]
)

conn = get_database_connection()

if page == "Executive Dashboard":
    executive.render(conn)
elif page == "Operational Reports":
    operational.render(conn)
elif page == "Analytical Reports":
    analytical.render(conn)
```

## Conclusion

This comprehensive reporting framework provides:

- **Multi-level visibility**: From executive summaries to operational details
- **Real-time monitoring**: Live dashboards for active operations
- **Historical analysis**: Trend identification and forecasting
- **RESTful access**: API endpoints for integration
- **Interactive visualization**: Streamlit-based dashboards
- **Export capabilities**: CSV, PDF, and JSON outputs

The reporting system ensures all stakeholders have access to relevant, timely, and actionable compression program insights.
