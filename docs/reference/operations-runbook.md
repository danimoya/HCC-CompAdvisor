# HCC Compression Advisor - Operations Runbook

## Table of Contents
1. [Deployment Procedures](#deployment-procedures)
2. [Health Checks](#health-checks)
3. [Common Issues Resolution](#common-issues-resolution)
4. [Performance Tuning](#performance-tuning)
5. [Backup and Recovery](#backup-and-recovery)
6. [Emergency Procedures](#emergency-procedures)
7. [Monitoring and Alerting](#monitoring-and-alerting)

## Deployment Procedures

### Initial Deployment

#### Pre-Deployment Checklist

- [ ] Oracle Database 19c or higher installed
- [ ] Advanced Compression feature licensed and enabled
- [ ] ExaCC or Exadata environment configured (for HCC)
- [ ] Dedicated PDB created for application
- [ ] Network connectivity verified
- [ ] Required privileges granted
- [ ] Scratch tablespace created (500 MB minimum)
- [ ] Backup strategy in place

#### Deployment Steps

**Step 1: Validate Environment**

```bash
#!/bin/bash
# validate_environment.sh

echo "=== Environment Validation ==="

# Check Oracle version
sqlplus -s / as sysdba <<EOF
SET PAGESIZE 0 FEEDBACK OFF
SELECT BANNER FROM v\$version WHERE BANNER LIKE 'Oracle Database%';
EXIT
EOF

# Check Advanced Compression license
sqlplus -s / as sysdba <<EOF
SET PAGESIZE 0 FEEDBACK OFF
SELECT PARAMETER, VALUE FROM v\$option WHERE PARAMETER = 'Advanced Compression';
EXIT
EOF

# Verify PDB status
sqlplus -s / as sysdba <<EOF
SET PAGESIZE 0 FEEDBACK OFF
SELECT name, open_mode FROM v\$pdbs WHERE name = 'PDB_PROD';
EXIT
EOF

echo "=== Validation Complete ==="
```

**Step 2: Deploy Database Objects**

```bash
#!/bin/bash
# deploy_database.sh

echo "=== Deploying HCC Compression Advisor ==="

# Set connection details
export ORACLE_SID=ORCL
export TNS_ADMIN=/opt/oracle/network/admin

# Deploy as SYS
sqlplus / as sysdba <<EOF
-- Create schema and tablespaces
@scripts/create_schema.sql

-- Grant privileges
@scripts/grant_privileges.sql
EXIT
EOF

# Deploy as application user
sqlplus compression_mgr/<password>@PDB_PROD <<EOF
-- Deploy tables
@database/schema/01_tables.sql

-- Deploy sequences
@database/schema/02_sequences.sql

-- Deploy indexes
@database/schema/03_indexes.sql

-- Deploy packages
@database/packages/pkg_compression_analyzer_spec.sql
@database/packages/pkg_compression_analyzer_body.sql
@database/packages/pkg_compression_executor_spec.sql
@database/packages/pkg_compression_executor_body.sql

-- Deploy views
@database/schema/04_views.sql

-- Deploy ORDS module
@database/ords/compression_module.sql

EXIT
EOF

echo "=== Deployment Complete ==="
```

**Step 3: Validate Deployment**

```sql
-- validate_deployment.sql
SET SERVEROUTPUT ON

DECLARE
    v_errors NUMBER := 0;

    PROCEDURE check_object(p_name VARCHAR2, p_type VARCHAR2) IS
        v_status VARCHAR2(20);
    BEGIN
        SELECT status INTO v_status
        FROM user_objects
        WHERE object_name = p_name AND object_type = p_type;

        IF v_status = 'VALID' THEN
            DBMS_OUTPUT.PUT_LINE('✓ ' || p_type || ' ' || p_name || ' is VALID');
        ELSE
            DBMS_OUTPUT.PUT_LINE('✗ ' || p_type || ' ' || p_name || ' is INVALID');
            v_errors := v_errors + 1;
        END IF;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            DBMS_OUTPUT.PUT_LINE('✗ ' || p_type || ' ' || p_name || ' NOT FOUND');
            v_errors := v_errors + 1;
    END;

BEGIN
    DBMS_OUTPUT.PUT_LINE('=== Deployment Validation ===');

    -- Check tables
    check_object('COMPRESSION_ANALYSIS', 'TABLE');
    check_object('COMPRESSION_HISTORY', 'TABLE');

    -- Check packages
    check_object('PKG_COMPRESSION_ANALYZER', 'PACKAGE');
    check_object('PKG_COMPRESSION_ANALYZER', 'PACKAGE BODY');
    check_object('PKG_COMPRESSION_EXECUTOR', 'PACKAGE');
    check_object('PKG_COMPRESSION_EXECUTOR', 'PACKAGE BODY');

    -- Check views
    check_object('V_COMPRESSION_CANDIDATES', 'VIEW');
    check_object('V_COMPRESSION_SUMMARY', 'VIEW');
    check_object('V_COMPRESSION_HISTORY', 'VIEW');

    -- Summary
    DBMS_OUTPUT.PUT_LINE('');
    IF v_errors = 0 THEN
        DBMS_OUTPUT.PUT_LINE('=== DEPLOYMENT SUCCESSFUL ===');
    ELSE
        DBMS_OUTPUT.PUT_LINE('=== DEPLOYMENT FAILED: ' || v_errors || ' errors ===');
    END IF;
END;
/
```

**Step 4: Configure ORDS**

```bash
# configure_ords.sh

cd /opt/oracle/ords/config

# Create connection pool for PDB
cat > pool_compression.xml <<EOF
<pool>
    <name>compression</name>
    <description>Connection pool for Compression Advisor</description>
    <server>jdbc:oracle:thin:@//localhost:1521/PDB_PROD</server>
    <user>compression_mgr</user>
    <password><![CDATA[<password>]]></password>
    <min-limit>2</min-limit>
    <max-limit>10</max-limit>
</pool>
EOF

# Restart ORDS
systemctl restart ords
sleep 10

# Test endpoint
curl -X GET https://localhost:8443/ords/compression/v1/recommendations
```

**Step 5: Deploy Dashboard**

```bash
# deploy_dashboard.sh

# Navigate to dashboard directory
cd /opt/hcc-compression-advisor/dashboard

# Create systemd service
cat > /etc/systemd/system/compression-dashboard.service <<EOF
[Unit]
Description=HCC Compression Advisor Dashboard
After=network.target

[Service]
Type=simple
User=streamlit
WorkingDirectory=/opt/hcc-compression-advisor/dashboard
Environment="PATH=/usr/local/bin:/usr/bin"
ExecStart=/usr/local/bin/streamlit run app.py --server.port 8501
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
systemctl daemon-reload
systemctl enable compression-dashboard
systemctl start compression-dashboard

# Verify service status
systemctl status compression-dashboard
```

### Upgrade Procedures

**Step 1: Backup Current Version**

```bash
# backup_before_upgrade.sh

BACKUP_DIR=/backup/compression_advisor_$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR

# Export schema
expdp compression_mgr/<password>@PDB_PROD \
    DIRECTORY=dpump_dir \
    DUMPFILE=${BACKUP_DIR}/compression_mgr_export.dmp \
    LOGFILE=${BACKUP_DIR}/compression_mgr_export.log \
    SCHEMAS=COMPRESSION_MGR

# Backup configuration
cp -r /opt/hcc-compression-advisor $BACKUP_DIR/application

echo "Backup completed in $BACKUP_DIR"
```

**Step 2: Apply Upgrade**

```sql
-- upgrade_to_v2.sql
-- Example upgrade script

SET SERVEROUTPUT ON

DECLARE
    v_current_version VARCHAR2(20);
BEGIN
    -- Check current version
    SELECT PKG_COMPRESSION_ANALYZER.VERSION INTO v_current_version FROM DUAL;
    DBMS_OUTPUT.PUT_LINE('Current version: ' || v_current_version);

    -- Add new columns for v2 features
    BEGIN
        EXECUTE IMMEDIATE 'ALTER TABLE COMPRESSION_ANALYSIS ADD (
            predicted_ratio NUMBER,
            ml_confidence NUMBER(5,2)
        )';
        DBMS_OUTPUT.PUT_LINE('✓ Added new columns');
    EXCEPTION
        WHEN OTHERS THEN
            IF SQLCODE = -1430 THEN  -- Column already exists
                DBMS_OUTPUT.PUT_LINE('⚠ Columns already exist, skipping');
            ELSE
                RAISE;
            END IF;
    END;

    -- Update package bodies
    @database/packages/pkg_compression_analyzer_body_v2.sql
    @database/packages/pkg_compression_executor_body_v2.sql

    DBMS_OUTPUT.PUT_LINE('✓ Upgrade complete');
END;
/
```

**Step 3: Validate Upgrade**

```sql
-- Verify new version
SELECT PKG_COMPRESSION_ANALYZER.VERSION FROM DUAL;

-- Test new functionality
EXEC test_compression_analyzer.test_new_features;

-- Verify backward compatibility
EXEC test_compression_analyzer.test_legacy_functions;
```

## Health Checks

### Daily Health Check Script

```sql
-- daily_health_check.sql
SET SERVEROUTPUT ON

DECLARE
    v_status VARCHAR2(10) := 'HEALTHY';
    v_failed_count NUMBER;
    v_scratch_usage NUMBER;
    v_stale_analysis NUMBER;

BEGIN
    DBMS_OUTPUT.PUT_LINE('=== Daily Health Check: ' || TO_CHAR(SYSDATE, 'YYYY-MM-DD HH24:MI:SS') || ' ===');
    DBMS_OUTPUT.PUT_LINE('');

    -- Check 1: Failed compression operations
    SELECT COUNT(*) INTO v_failed_count
    FROM COMPRESSION_HISTORY
    WHERE execution_status = 'FAILED'
      AND start_time > SYSDATE - 1;

    DBMS_OUTPUT.PUT_LINE('Failed compressions (24h): ' || v_failed_count);
    IF v_failed_count > 5 THEN
        v_status := 'WARNING';
        DBMS_OUTPUT.PUT_LINE('⚠ WARNING: High failure rate');
    END IF;

    -- Check 2: Scratch tablespace usage
    SELECT used_percent INTO v_scratch_usage
    FROM dba_tablespace_usage_metrics
    WHERE tablespace_name = 'SCRATCH';

    DBMS_OUTPUT.PUT_LINE('Scratch tablespace usage: ' || ROUND(v_scratch_usage, 1) || '%');
    IF v_scratch_usage > 80 THEN
        v_status := 'WARNING';
        DBMS_OUTPUT.PUT_LINE('⚠ WARNING: Scratch tablespace > 80% full');
    END IF;

    -- Check 3: Stale analysis data
    SELECT COUNT(*) INTO v_stale_analysis
    FROM COMPRESSION_ANALYSIS
    WHERE analysis_date < SYSTIMESTAMP - INTERVAL '30' DAY;

    DBMS_OUTPUT.PUT_LINE('Stale analysis records (>30 days): ' || v_stale_analysis);
    IF v_stale_analysis > 100 THEN
        DBMS_OUTPUT.PUT_LINE('ℹ INFO: Consider running refresh_analysis');
    END IF;

    -- Check 4: Invalid objects
    SELECT COUNT(*) INTO v_failed_count
    FROM user_objects
    WHERE object_name LIKE 'PKG_COMPRESS%'
      AND status = 'INVALID';

    DBMS_OUTPUT.PUT_LINE('Invalid objects: ' || v_failed_count);
    IF v_failed_count > 0 THEN
        v_status := 'CRITICAL';
        DBMS_OUTPUT.PUT_LINE('✗ CRITICAL: Invalid package objects found');
    END IF;

    -- Check 5: Long-running operations
    SELECT COUNT(*) INTO v_failed_count
    FROM COMPRESSION_HISTORY
    WHERE execution_status = 'IN_PROGRESS'
      AND (SYSTIMESTAMP - start_time) * 24 > 4;  -- > 4 hours

    DBMS_OUTPUT.PUT_LINE('Long-running operations (>4h): ' || v_failed_count);
    IF v_failed_count > 0 THEN
        v_status := 'WARNING';
        DBMS_OUTPUT.PUT_LINE('⚠ WARNING: Operations running > 4 hours');
    END IF;

    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE('=== Overall Status: ' || v_status || ' ===');
END;
/
```

### Component Health Checks

```bash
#!/bin/bash
# check_components.sh

echo "=== Component Health Checks ==="

# 1. Database connectivity
echo "Checking database..."
sqlplus -s compression_mgr/<password>@PDB_PROD <<EOF > /dev/null 2>&1
SELECT 1 FROM DUAL;
EXIT
EOF

if [ $? -eq 0 ]; then
    echo "✓ Database: ONLINE"
else
    echo "✗ Database: OFFLINE"
fi

# 2. ORDS connectivity
echo "Checking ORDS..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    https://localhost:8443/ords/compression/v1/recommendations)

if [ "$HTTP_CODE" = "200" ]; then
    echo "✓ ORDS: ONLINE"
else
    echo "✗ ORDS: OFFLINE (HTTP $HTTP_CODE)"
fi

# 3. Streamlit dashboard
echo "Checking dashboard..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8501)

if [ "$HTTP_CODE" = "200" ]; then
    echo "✓ Dashboard: ONLINE"
else
    echo "✗ Dashboard: OFFLINE"
fi

# 4. Disk space
echo "Checking disk space..."
USAGE=$(df -h /opt/oracle | tail -1 | awk '{print $5}' | sed 's/%//')
if [ $USAGE -lt 90 ]; then
    echo "✓ Disk space: ${USAGE}% used"
else
    echo "⚠ Disk space: ${USAGE}% used (WARNING)"
fi

echo "=== Health Check Complete ==="
```

## Common Issues Resolution

### Issue 1: ORA-01652 - Unable to extend temp segment

**Symptoms**:
- Compression analysis fails
- Error: `ORA-01652: unable to extend temp segment in tablespace SCRATCH`

**Diagnosis**:
```sql
-- Check scratch tablespace usage
SELECT
    tablespace_name,
    ROUND(used_space * 8192 / 1024 / 1024, 2) AS used_mb,
    ROUND(tablespace_size * 8192 / 1024 / 1024, 2) AS total_mb,
    ROUND(used_percent, 2) AS used_pct
FROM dba_tablespace_usage_metrics
WHERE tablespace_name = 'SCRATCH';
```

**Resolution**:
```sql
-- Option 1: Resize existing datafile
ALTER DATABASE DATAFILE '/path/to/scratch01.dbf' RESIZE 2G;

-- Option 2: Add new datafile
ALTER TABLESPACE SCRATCH
ADD DATAFILE '/path/to/scratch02.dbf' SIZE 1G AUTOEXTEND ON MAXSIZE 5G;

-- Option 3: Clean up scratch tablespace
ALTER TABLESPACE SCRATCH COALESCE;
```

### Issue 2: Compression Analysis Takes Too Long

**Symptoms**:
- `ANALYZE_ALL_TABLES` runs > 2 hours
- High CPU usage during analysis

**Diagnosis**:
```sql
-- Check active analysis sessions
SELECT
    s.sid,
    s.serial#,
    s.username,
    s.sql_id,
    s.event,
    ROUND((SYSDATE - s.sql_exec_start) * 24 * 60, 2) AS elapsed_minutes
FROM v$session s
WHERE s.module LIKE '%PKG_COMPRESSION%'
  AND s.status = 'ACTIVE';

-- Check parallel degree
SELECT param_value
FROM GLOBAL_PARAMS
WHERE param_name = 'PARALLEL_DEGREE';
```

**Resolution**:
```sql
-- Increase parallel degree (adjust based on CPU count)
UPDATE GLOBAL_PARAMS
SET param_value = '8'
WHERE param_name = 'PARALLEL_DEGREE';
COMMIT;

-- Reduce sample size for faster (less accurate) analysis
UPDATE GLOBAL_PARAMS
SET param_value = '500'
WHERE param_name = 'ANALYSIS_SAMPLE_SIZE';
COMMIT;

-- Analyze specific schemas instead of all
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES(p_schema_filter => 'SALES');
```

### Issue 3: Indexes Become Unusable After Compression

**Symptoms**:
- Queries fail after compression
- Error: `ORA-01502: index is in UNUSABLE state`

**Diagnosis**:
```sql
-- Find unusable indexes
SELECT owner, index_name, table_name, status
FROM dba_indexes
WHERE status = 'UNUSABLE'
  AND owner = '<schema>';
```

**Resolution**:
```sql
-- Rebuild unusable indexes
BEGIN
    FOR idx IN (SELECT owner, index_name
                FROM dba_indexes
                WHERE status = 'UNUSABLE'
                  AND owner = '<schema>') LOOP
        EXECUTE IMMEDIATE 'ALTER INDEX ' || idx.owner || '.' || idx.index_name || ' REBUILD ONLINE';
    END LOOP;
END;
/

-- Prevention: Always use online compression
EXEC PKG_COMPRESSION_EXECUTOR.COMPRESS_TABLE(
    p_owner => 'SCHEMA',
    p_table_name => 'TABLE',
    p_online => TRUE  -- Prevents index invalidation
);
```

### Issue 4: Performance Degraded After Compression

**Symptoms**:
- Queries slower after compression
- High CPU usage

**Diagnosis**:
```sql
-- Check compression type applied
SELECT
    owner,
    object_name,
    compression_type_applied,
    hotness_score,
    effectiveness_assessment
FROM V_COMPRESSION_EFFECTIVENESS
WHERE effectiveness_assessment = 'SUBOPTIMAL'
ORDER BY space_saved_mb DESC;

-- Compare AWR metrics before/after
-- (Requires Diagnostics Pack license)
@?/rdbms/admin/awrddrpt.sql
```

**Resolution**:
```sql
-- Rollback aggressive compression on hot tables
EXEC PKG_COMPRESSION_EXECUTOR.ROLLBACK_COMPRESSION(p_operation_id => <id>);

-- Re-compress with lighter compression
EXEC PKG_COMPRESSION_EXECUTOR.COMPRESS_TABLE(
    p_owner => 'SCHEMA',
    p_table_name => 'HOT_TABLE',
    p_compression_type => 'OLTP'  -- Lighter than Query/Archive
);

-- Gather fresh statistics
EXEC DBMS_STATS.GATHER_TABLE_STATS('SCHEMA', 'TABLE', CASCADE => TRUE);
```

### Issue 5: ORDS Endpoints Return 404

**Symptoms**:
- REST API calls fail
- HTTP 404 Not Found errors

**Diagnosis**:
```sql
-- Check ORDS module status
SELECT module_name, uri_prefix, published
FROM user_ords_modules
WHERE module_name LIKE '%compression%';

-- Verify handlers
SELECT module_name, pattern, method, source_type
FROM user_ords_handlers
WHERE module_name LIKE '%compression%';
```

**Resolution**:
```sql
-- Re-enable schema
BEGIN
    ORDS.ENABLE_SCHEMA(
        p_enabled => TRUE,
        p_schema => 'COMPRESSION_MGR',
        p_url_mapping_type => 'BASE_PATH',
        p_url_mapping_pattern => 'compression'
    );
END;
/

-- Redeploy ORDS module
@database/ords/compression_module.sql

-- Restart ORDS
-- (Execute on application server)
systemctl restart ords
```

## Performance Tuning

### Database Tuning

```sql
-- 1. Gather optimizer statistics
EXEC DBMS_STATS.GATHER_SCHEMA_STATS('COMPRESSION_MGR', CASCADE => TRUE);

-- 2. Analyze execution plans for slow queries
EXPLAIN PLAN FOR
SELECT * FROM V_COMPRESSION_CANDIDATES
WHERE estimated_savings_mb > 1000;

SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY);

-- 3. Add missing indexes
CREATE INDEX idx_comp_analysis_savings ON COMPRESSION_ANALYSIS(
    estimated_savings_mb DESC,
    advisable_compression
) COMPRESS;

-- 4. Tune parallel execution
ALTER SESSION FORCE PARALLEL DML PARALLEL 8;
ALTER SESSION FORCE PARALLEL QUERY PARALLEL 8;

-- 5. Configure result cache
ALTER SYSTEM SET RESULT_CACHE_MAX_SIZE = 500M SCOPE=BOTH;
```

### Application Tuning

```python
# Dashboard performance optimization

# 1. Use connection pooling
@st.cache_resource
def get_connection_pool():
    return oracledb.create_pool(
        min=5,      # Increased from 2
        max=20,     # Increased from 10
        increment=2
    )

# 2. Cache expensive queries
@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_recommendations():
    with pool.acquire() as conn:
        # Expensive query
        return fetch_recommendations(conn)

# 3. Use batch fetching
cursor.arraysize = 1000  # Fetch 1000 rows at a time

# 4. Optimize SQL queries
# Use bind variables
cursor.execute("""
    SELECT * FROM v_compression_candidates
    WHERE estimated_savings_mb > :threshold
""", [threshold])
```

## Backup and Recovery

### Backup Procedures

```bash
#!/bin/bash
# backup_compression_system.sh

BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=/backup/compression_advisor/$BACKUP_DATE

mkdir -p $BACKUP_DIR

echo "Starting backup at $(date)"

# 1. Export schema
expdp compression_mgr/<password>@PDB_PROD \
    DIRECTORY=dpump_dir \
    DUMPFILE=compression_mgr_${BACKUP_DATE}.dmp \
    LOGFILE=${BACKUP_DIR}/export.log \
    SCHEMAS=COMPRESSION_MGR \
    COMPRESSION=ALL

# 2. Backup application files
tar -czf ${BACKUP_DIR}/application.tar.gz /opt/hcc-compression-advisor

# 3. Backup configuration
cp /opt/hcc-compression-advisor/.env ${BACKUP_DIR}/

# 4. Backup ORDS configuration
cp -r /opt/oracle/ords/config ${BACKUP_DIR}/ords_config

echo "Backup completed: $BACKUP_DIR"

# 5. Cleanup old backups (keep 30 days)
find /backup/compression_advisor -type d -mtime +30 -exec rm -rf {} \;
```

### Recovery Procedures

```bash
#!/bin/bash
# restore_compression_system.sh

BACKUP_DIR=$1

if [ -z "$BACKUP_DIR" ]; then
    echo "Usage: $0 <backup_directory>"
    exit 1
fi

echo "Restoring from: $BACKUP_DIR"

# 1. Restore database schema
impdp compression_mgr/<password>@PDB_PROD \
    DIRECTORY=dpump_dir \
    DUMPFILE=$(ls $BACKUP_DIR/*.dmp) \
    LOGFILE=/tmp/restore.log \
    TABLE_EXISTS_ACTION=REPLACE

# 2. Restore application files
tar -xzf ${BACKUP_DIR}/application.tar.gz -C /

# 3. Restore configuration
cp ${BACKUP_DIR}/.env /opt/hcc-compression-advisor/

# 4. Restart services
systemctl restart ords
systemctl restart compression-dashboard

echo "Restore completed. Verify system status."
```

## Emergency Procedures

### Emergency Contacts

- **Database Team**: dba-team@example.com, +1-555-0100
- **Application Team**: app-team@example.com, +1-555-0200
- **On-Call DBA**: oncall-dba@example.com, +1-555-0300

### Critical Issue Response

**Step 1: Assess Severity**

| Severity | Description | Response Time |
|----------|-------------|---------------|
| P1 - Critical | System down, data loss | 15 minutes |
| P2 - High | Major functionality impaired | 1 hour |
| P3 - Medium | Minor functionality affected | 4 hours |
| P4 - Low | Cosmetic issues | Next business day |

**Step 2: Emergency Rollback**

```sql
-- Stop all running compressions
BEGIN
    FOR rec IN (SELECT operation_id
                FROM COMPRESSION_HISTORY
                WHERE execution_status = 'IN_PROGRESS') LOOP
        -- Kill session
        -- (Requires additional privileges)
        NULL;  -- Implementation depends on environment
    END LOOP;
END;
/

-- Rollback recent compressions
DECLARE
    v_cutoff_time TIMESTAMP := SYSTIMESTAMP - INTERVAL '1' HOUR;
BEGIN
    FOR rec IN (SELECT operation_id
                FROM COMPRESSION_HISTORY
                WHERE execution_status = 'SUCCESS'
                  AND start_time > v_cutoff_time) LOOP
        BEGIN
            PKG_COMPRESSION_EXECUTOR.ROLLBACK_COMPRESSION(rec.operation_id);
        EXCEPTION
            WHEN OTHERS THEN
                DBMS_OUTPUT.PUT_LINE('Failed to rollback: ' || rec.operation_id);
        END;
    END LOOP;
END;
/
```

**Step 3: Service Restoration**

```bash
# Stop all services
systemctl stop compression-dashboard
systemctl stop ords

# Restore from last known good backup
./restore_compression_system.sh /backup/compression_advisor/last_good

# Restart services
systemctl start ords
systemctl start compression-dashboard

# Verify health
./check_components.sh
```

## Monitoring and Alerting

### Prometheus Metrics Export

```python
# metrics_exporter.py
from prometheus_client import start_http_server, Gauge
import oracledb
import time

# Define metrics
compression_success_rate = Gauge('compression_success_rate', 'Success rate of compression operations')
space_saved_gb = Gauge('compression_space_saved_gb', 'Total space saved in GB')
active_compressions = Gauge('compression_active_operations', 'Number of active compression operations')

def collect_metrics():
    """Collect metrics from database"""
    with pool.acquire() as conn:
        cursor = conn.cursor()

        # Success rate (last 24h)
        cursor.execute("""
            SELECT
                COUNT(CASE WHEN execution_status = 'SUCCESS' THEN 1 END) /
                NULLIF(COUNT(*), 0) * 100
            FROM COMPRESSION_HISTORY
            WHERE start_time > SYSDATE - 1
        """)
        success_rate = cursor.fetchone()[0] or 0
        compression_success_rate.set(success_rate)

        # Space saved (total)
        cursor.execute("SELECT SUM(space_saved_mb)/1024 FROM V_SPACE_SAVINGS")
        saved = cursor.fetchone()[0] or 0
        space_saved_gb.set(saved)

        # Active operations
        cursor.execute("""
            SELECT COUNT(*) FROM COMPRESSION_HISTORY
            WHERE execution_status = 'IN_PROGRESS'
        """)
        active = cursor.fetchone()[0]
        active_compressions.set(active)

if __name__ == '__main__':
    # Start Prometheus HTTP server
    start_http_server(9090)

    # Collect metrics every 60 seconds
    while True:
        collect_metrics()
        time.sleep(60)
```

### Grafana Dashboard Configuration

```json
{
  "dashboard": {
    "title": "HCC Compression Advisor",
    "panels": [
      {
        "title": "Compression Success Rate",
        "targets": [
          {
            "expr": "compression_success_rate",
            "legendFormat": "Success Rate %"
          }
        ]
      },
      {
        "title": "Space Saved",
        "targets": [
          {
            "expr": "compression_space_saved_gb",
            "legendFormat": "Total Saved (GB)"
          }
        ]
      },
      {
        "title": "Active Operations",
        "targets": [
          {
            "expr": "compression_active_operations",
            "legendFormat": "Active Compressions"
          }
        ]
      }
    ]
  }
}
```

---

**Document Version**: 1.0
**Last Updated**: 2025-01-13
**Contact**: operations-team@example.com
