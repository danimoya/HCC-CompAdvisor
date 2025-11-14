# HCC Compression Advisor - Administrator Guide

## Table of Contents
1. [Installation](#installation)
2. [Database Setup](#database-setup)
3. [Configuration](#configuration)
4. [Maintenance Tasks](#maintenance-tasks)
5. [Monitoring Setup](#monitoring-setup)
6. [Security](#security)
7. [Performance Tuning](#performance-tuning)
8. [Backup and Recovery](#backup-and-recovery)

## Installation

### Prerequisites

#### System Requirements
- Oracle Database 19c Enterprise Edition or higher
- Exadata Cloud at Customer (ExaCC) or Exadata hardware for HCC features
- Minimum 4 CPU cores recommended for parallel processing
- 8 GB RAM minimum for compression analysis operations
- Dedicated scratch tablespace (500 MB - 2 GB)

#### Required Privileges
```sql
-- Grant required system privileges to compression manager user
GRANT CREATE TABLE TO COMPRESSION_MGR;
GRANT CREATE SEQUENCE TO COMPRESSION_MGR;
GRANT CREATE VIEW TO COMPRESSION_MGR;
GRANT CREATE PROCEDURE TO COMPRESSION_MGR;
GRANT CREATE JOB TO COMPRESSION_MGR;
GRANT SELECT ANY DICTIONARY TO COMPRESSION_MGR;
GRANT SELECT ON V$SEGMENT_STATISTICS TO COMPRESSION_MGR;
GRANT SELECT ON DBA_HIST_SEG_STAT TO COMPRESSION_MGR;
GRANT SELECT ON DBA_HIST_SNAPSHOT TO COMPRESSION_MGR;

-- For executing compression operations
GRANT ALTER ANY TABLE TO COMPRESSION_MGR;
GRANT ALTER ANY INDEX TO COMPRESSION_MGR;
```

### Installation Steps

#### Step 1: Create Dedicated Schema

```sql
-- Connect as SYS or DBA
CONN / AS SYSDBA

-- Create tablespace for compression manager objects
CREATE TABLESPACE COMPRESSION_MGR_DATA
DATAFILE SIZE 500M
AUTOEXTEND ON NEXT 100M MAXSIZE 5G
SEGMENT SPACE MANAGEMENT AUTO;

-- Create scratch tablespace for analysis
CREATE TABLESPACE SCRATCH
DATAFILE SIZE 500M
AUTOEXTEND ON NEXT 100M MAXSIZE 2G
SEGMENT SPACE MANAGEMENT MANUAL;

-- Create dedicated user
CREATE USER COMPRESSION_MGR IDENTIFIED BY <secure_password>
DEFAULT TABLESPACE COMPRESSION_MGR_DATA
TEMPORARY TABLESPACE TEMP
QUOTA UNLIMITED ON COMPRESSION_MGR_DATA
QUOTA UNLIMITED ON SCRATCH;

-- Grant privileges
GRANT CONNECT, RESOURCE TO COMPRESSION_MGR;
GRANT SELECT ANY DICTIONARY TO COMPRESSION_MGR;
GRANT CREATE JOB TO COMPRESSION_MGR;
GRANT SELECT ON V$SEGMENT_STATISTICS TO COMPRESSION_MGR;
```

#### Step 2: Deploy Database Objects

```sql
-- Connect as compression manager user
CONN COMPRESSION_MGR/<password>@<PDB>

-- Run installation script
@install_compression_system.sql

-- Verify installation
SELECT object_name, object_type, status
FROM user_objects
WHERE object_name LIKE '%COMPRESS%'
ORDER BY object_type, object_name;

-- Expected objects:
-- - 5 tables (COMPRESSION_ANALYSIS, COMPRESSION_HISTORY, INDEX_COMPRESSION_ANALYSIS, LOB_COMPRESSION_ANALYSIS, IOT_COMPRESSION_ANALYSIS)
-- - 2 packages (PKG_COMPRESSION_ANALYZER, PKG_COMPRESSION_EXECUTOR)
-- - 8 views (V_COMPRESSION_CANDIDATES, V_COMPRESSION_SUMMARY, V_COMPRESSION_HISTORY, etc.)
-- - 1 sequence (SEQ_COMPRESSION_OPERATION)
```

#### Step 3: Configure Initial Parameters

```sql
-- Create configuration table if not exists
CREATE TABLE COMPRESSION_CONFIG (
    strategy_name VARCHAR2(30) PRIMARY KEY,
    strategy_type VARCHAR2(30) NOT NULL,
    min_table_size_gb NUMBER DEFAULT 10,
    preferred_compression VARCHAR2(30),
    hot_score_threshold NUMBER DEFAULT 50,
    last_updated TIMESTAMP DEFAULT SYSTIMESTAMP
);

-- Insert default strategy
INSERT INTO COMPRESSION_CONFIG VALUES (
    'PRIMARY_STRATEGY',
    'BALANCED',
    10,
    NULL,
    50,
    SYSTIMESTAMP
);
COMMIT;

-- Create global parameters table
CREATE TABLE GLOBAL_PARAMS (
    param_name VARCHAR2(30) PRIMARY KEY,
    param_value VARCHAR2(100),
    param_description VARCHAR2(500),
    last_updated TIMESTAMP DEFAULT SYSTIMESTAMP
);

-- Insert default parameters
INSERT INTO GLOBAL_PARAMS VALUES ('MIN_COMPRESSION_RATIO', '1.5', 'Minimum acceptable compression ratio', SYSTIMESTAMP);
INSERT INTO GLOBAL_PARAMS VALUES ('PARALLEL_DEGREE', '4', 'Default parallel degree for analysis', SYSTIMESTAMP);
INSERT INTO GLOBAL_PARAMS VALUES ('MAX_CONCURRENT_COMPRESS', '2', 'Maximum concurrent compression operations', SYSTIMESTAMP);
INSERT INTO GLOBAL_PARAMS VALUES ('ANALYSIS_SAMPLE_SIZE', '1000', 'Sample size for compression ratio testing', SYSTIMESTAMP);
COMMIT;
```

#### Step 4: Configure ORDS (Optional but Recommended)

```sql
-- Enable schema for ORDS
BEGIN
    ORDS.ENABLE_SCHEMA(
        p_enabled => TRUE,
        p_schema => 'COMPRESSION_MGR',
        p_url_mapping_type => 'BASE_PATH',
        p_url_mapping_pattern => 'compression',
        p_auto_rest_auth => FALSE
    );
END;
/

-- Create REST module
@ords_compression_module.sql

-- Verify ORDS endpoints
SELECT module_name, uri_prefix, published
FROM user_ords_modules
WHERE module_name = 'compression.module';
```

#### Step 5: Validate Installation

```sql
-- Run validation script
SET SERVEROUTPUT ON

DECLARE
    v_count NUMBER;
    v_status VARCHAR2(10);
BEGIN
    -- Check tables
    SELECT COUNT(*) INTO v_count FROM user_tables WHERE table_name LIKE '%COMPRESS%';
    IF v_count >= 5 THEN
        DBMS_OUTPUT.PUT_LINE('✓ Tables created: ' || v_count);
    ELSE
        DBMS_OUTPUT.PUT_LINE('✗ Missing tables. Expected >= 5, Found: ' || v_count);
    END IF;

    -- Check packages
    SELECT COUNT(*) INTO v_count FROM user_objects
    WHERE object_type = 'PACKAGE' AND object_name LIKE 'PKG_COMPRESS%';
    IF v_count >= 2 THEN
        DBMS_OUTPUT.PUT_LINE('✓ Packages created: ' || v_count);
    ELSE
        DBMS_OUTPUT.PUT_LINE('✗ Missing packages. Expected >= 2, Found: ' || v_count);
    END IF;

    -- Check package validity
    SELECT COUNT(*) INTO v_count FROM user_objects
    WHERE object_type IN ('PACKAGE', 'PACKAGE BODY')
      AND object_name LIKE 'PKG_COMPRESS%'
      AND status = 'INVALID';
    IF v_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('✓ All packages are valid');
    ELSE
        DBMS_OUTPUT.PUT_LINE('✗ ' || v_count || ' invalid package objects found');
    END IF;

    -- Test basic functionality
    BEGIN
        PKG_COMPRESSION_ANALYZER.ANALYZE_SPECIFIC_TABLE(USER, 'COMPRESSION_CONFIG');
        DBMS_OUTPUT.PUT_LINE('✓ Basic analysis test successful');
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('✗ Analysis test failed: ' || SQLERRM);
    END;
END;
/
```

## Database Setup

### Oracle Database Configuration

#### Enable Advanced Compression

```sql
-- Verify Advanced Compression option is enabled
SELECT * FROM V$OPTION WHERE PARAMETER = 'Advanced Compression';

-- Must show VALUE = TRUE for HCC features
```

#### Configure Scratch Tablespace

```sql
-- Verify scratch tablespace settings
SELECT tablespace_name, block_size, extent_management,
       segment_space_management, status
FROM dba_tablespaces
WHERE tablespace_name = 'SCRATCH';

-- Adjust if needed
ALTER TABLESPACE SCRATCH
COALESCE;  -- Consolidate free space

-- Monitor scratch tablespace usage
SELECT tablespace_name,
       ROUND(used_space * 8192 / 1024 / 1024, 2) AS used_mb,
       ROUND(tablespace_size * 8192 / 1024 / 1024, 2) AS total_mb,
       ROUND(used_percent, 2) AS used_pct
FROM dba_tablespace_usage_metrics
WHERE tablespace_name = 'SCRATCH';
```

#### Enable Table Monitoring

```sql
-- Enable monitoring for all tables to capture DML statistics
BEGIN
    FOR t IN (SELECT owner, table_name
              FROM dba_tables
              WHERE owner NOT IN ('SYS', 'SYSTEM')
                AND monitoring = 'NO') LOOP
        EXECUTE IMMEDIATE 'ALTER TABLE ' || t.owner || '.' || t.table_name || ' MONITORING';
    END LOOP;
END;
/

-- Flush monitoring information periodically
EXEC DBMS_STATS.FLUSH_DATABASE_MONITORING_INFO;
```

### ExaCC-Specific Configuration

#### Verify HCC Availability

```sql
-- Check if running on Exadata/ExaCC
SELECT name, value
FROM v$parameter
WHERE name = 'cell_offload_processing';

-- Should be TRUE on Exadata

-- Verify HCC compression is available
SELECT compression_type
FROM dba_compression_levels
WHERE compression_type LIKE '%QUERY%' OR compression_type LIKE '%ARCHIVE%';
```

#### Configure Cell Flash Cache (Optional)

```sql
-- Enable flash cache for frequently accessed compressed tables
ALTER TABLE <schema>.<table>
STORAGE (CELL_FLASH_CACHE KEEP);

-- This keeps hot compressed data in flash cache for faster access
```

## Configuration

### Strategy Configuration

#### Configure Conservative Strategy

```sql
-- For high-transaction OLTP systems
UPDATE COMPRESSION_CONFIG
SET strategy_type = 'CONSERVATIVE',
    min_table_size_gb = 50,
    preferred_compression = 'OLTP',
    hot_score_threshold = 80
WHERE strategy_name = 'PRIMARY_STRATEGY';
COMMIT;
```

#### Configure Balanced Strategy

```sql
-- For mixed workloads (default)
UPDATE COMPRESSION_CONFIG
SET strategy_type = 'BALANCED',
    min_table_size_gb = 10,
    preferred_compression = NULL,  -- Auto-select
    hot_score_threshold = 50
WHERE strategy_name = 'PRIMARY_STRATEGY';
COMMIT;
```

#### Configure Aggressive Strategy

```sql
-- For data warehouses and analytics
UPDATE COMPRESSION_CONFIG
SET strategy_type = 'AGGRESSIVE',
    min_table_size_gb = 1,
    preferred_compression = 'ARCHIVE_HIGH',
    hot_score_threshold = 30
WHERE strategy_name = 'PRIMARY_STRATEGY';
COMMIT;
```

### Performance Parameters

```sql
-- Adjust parallel degree based on CPU count
UPDATE GLOBAL_PARAMS
SET param_value = '8'  -- Set to CPU count / 2
WHERE param_name = 'PARALLEL_DEGREE';

-- Set maximum concurrent compressions (monitor system load)
UPDATE GLOBAL_PARAMS
SET param_value = '4'
WHERE param_name = 'MAX_CONCURRENT_COMPRESS';

-- Adjust sample size for large tables (higher = more accurate, slower)
UPDATE GLOBAL_PARAMS
SET param_value = '5000'
WHERE param_name = 'ANALYSIS_SAMPLE_SIZE';

COMMIT;
```

### Email Notifications (Optional)

```sql
-- Configure email notifications for compression operations
CREATE TABLE EMAIL_CONFIG (
    config_key VARCHAR2(50) PRIMARY KEY,
    config_value VARCHAR2(500)
);

INSERT INTO EMAIL_CONFIG VALUES ('SMTP_HOST', 'smtp.example.com');
INSERT INTO EMAIL_CONFIG VALUES ('SMTP_PORT', '587');
INSERT INTO EMAIL_CONFIG VALUES ('FROM_EMAIL', 'compression-admin@example.com');
INSERT INTO EMAIL_CONFIG VALUES ('ADMIN_EMAIL', 'dba-team@example.com');
COMMIT;

-- Create notification procedure
CREATE OR REPLACE PROCEDURE SEND_COMPRESSION_NOTIFICATION(
    p_subject IN VARCHAR2,
    p_message IN VARCHAR2
) AS
    v_smtp_host VARCHAR2(500);
    v_smtp_port NUMBER;
    v_from_email VARCHAR2(500);
    v_to_email VARCHAR2(500);
BEGIN
    SELECT config_value INTO v_smtp_host FROM EMAIL_CONFIG WHERE config_key = 'SMTP_HOST';
    SELECT config_value INTO v_smtp_port FROM EMAIL_CONFIG WHERE config_key = 'SMTP_PORT';
    SELECT config_value INTO v_from_email FROM EMAIL_CONFIG WHERE config_key = 'FROM_EMAIL';
    SELECT config_value INTO v_to_email FROM EMAIL_CONFIG WHERE config_key = 'ADMIN_EMAIL';

    UTL_MAIL.SEND(
        sender => v_from_email,
        recipients => v_to_email,
        subject => p_subject,
        message => p_message
    );
END;
/
```

## Maintenance Tasks

### Regular Maintenance Schedule

#### Daily Tasks

```sql
-- Flush monitoring information
EXEC DBMS_STATS.FLUSH_DATABASE_MONITORING_INFO;

-- Check for failed compression operations
SELECT COUNT(*) AS failed_count
FROM COMPRESSION_HISTORY
WHERE operation_status = 'FAILED'
  AND start_time > SYSDATE - 1;

-- Alert if failures > 0
```

#### Weekly Tasks

```sql
-- Refresh analysis for active tables
EXEC PKG_COMPRESSION_ANALYZER.REFRESH_ANALYSIS(p_days_old => 7);

-- Clean up old analysis records (keep 90 days)
DELETE FROM COMPRESSION_ANALYSIS
WHERE analysis_date < SYSTIMESTAMP - INTERVAL '90' DAY;
COMMIT;

-- Gather statistics on compression tables
EXEC DBMS_STATS.GATHER_SCHEMA_STATS('COMPRESSION_MGR', cascade => TRUE);
```

#### Monthly Tasks

```sql
-- Full database analysis
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES(p_parallel_degree => 8);

-- Review space savings report
SELECT
    SUM(total_saved_mb) AS total_savings_mb,
    SUM(total_saved_mb) / 1024 AS total_savings_gb,
    COUNT(DISTINCT owner) AS schemas_compressed,
    SUM(objects_compressed) AS total_objects_compressed
FROM V_SPACE_SAVINGS;

-- Archive old history (keep 1 year, archive older)
CREATE TABLE COMPRESSION_HISTORY_ARCHIVE AS
SELECT * FROM COMPRESSION_HISTORY
WHERE start_time < ADD_MONTHS(SYSDATE, -12);

DELETE FROM COMPRESSION_HISTORY
WHERE start_time < ADD_MONTHS(SYSDATE, -12);
COMMIT;
```

#### Quarterly Tasks

```sql
-- Review and adjust compression strategies
-- Check effectiveness of current compressions
SELECT
    compression_type_applied,
    COUNT(*) AS count,
    ROUND(AVG(compression_ratio_achieved), 2) AS avg_ratio,
    ROUND(SUM(space_saved_mb) / 1024, 2) AS total_saved_gb,
    COUNT(CASE WHEN effectiveness_assessment = 'SUBOPTIMAL' THEN 1 END) AS suboptimal_count
FROM V_COMPRESSION_EFFECTIVENESS
GROUP BY compression_type_applied
ORDER BY total_saved_gb DESC;

-- Re-compress suboptimal tables
SELECT owner, object_name, compression_type_applied, hotness_score
FROM V_COMPRESSION_EFFECTIVENESS
WHERE effectiveness_assessment = 'SUBOPTIMAL'
ORDER BY space_saved_mb DESC;
```

### Database Reorganization

```sql
-- After major compression operations, reorganize scratch tablespace
ALTER TABLESPACE SCRATCH COALESCE;

-- Rebuild fragmented indexes in compression manager schema
BEGIN
    FOR idx IN (SELECT index_name
                FROM user_indexes
                WHERE tablespace_name = 'COMPRESSION_MGR_DATA') LOOP
        EXECUTE IMMEDIATE 'ALTER INDEX ' || idx.index_name || ' REBUILD ONLINE';
    END LOOP;
END;
/
```

### Cleanup Scripts

```sql
-- Remove orphaned analysis records (table no longer exists)
DELETE FROM COMPRESSION_ANALYSIS ca
WHERE NOT EXISTS (
    SELECT 1 FROM dba_tables dt
    WHERE dt.owner = ca.owner
      AND dt.table_name = ca.table_name
);

-- Clean up IN_PROGRESS operations stuck > 24 hours
UPDATE COMPRESSION_HISTORY
SET execution_status = 'FAILED',
    error_message = 'Operation timed out',
    end_time = SYSTIMESTAMP
WHERE execution_status = 'IN_PROGRESS'
  AND start_time < SYSTIMESTAMP - INTERVAL '24' HOUR;
COMMIT;
```

## Monitoring Setup

### Create Monitoring Views

```sql
-- Real-time compression operations
CREATE OR REPLACE VIEW V_ACTIVE_COMPRESSIONS AS
SELECT
    h.operation_id,
    h.owner,
    h.object_name,
    h.compression_type,
    h.start_time,
    ROUND((SYSTIMESTAMP - h.start_time) * 24 * 60, 2) AS elapsed_minutes,
    s.sid,
    s.serial#,
    s.username,
    s.sql_id,
    s.event,
    s.wait_class
FROM COMPRESSION_HISTORY h
JOIN v$session s ON s.module LIKE '%PKG_COMPRESSION_%'
WHERE h.execution_status = 'IN_PROGRESS'
  AND s.status = 'ACTIVE';

-- Daily statistics
CREATE OR REPLACE VIEW V_DAILY_COMPRESSION_STATS AS
SELECT
    TRUNC(start_time) AS operation_date,
    COUNT(*) AS total_operations,
    SUM(CASE WHEN execution_status = 'SUCCESS' THEN 1 ELSE 0 END) AS successful,
    SUM(CASE WHEN execution_status = 'FAILED' THEN 1 ELSE 0 END) AS failed,
    ROUND(SUM(space_saved_mb) / 1024, 2) AS total_saved_gb,
    ROUND(AVG(compression_ratio_achieved), 2) AS avg_compression_ratio
FROM COMPRESSION_HISTORY
WHERE start_time > SYSDATE - 30
GROUP BY TRUNC(start_time)
ORDER BY operation_date DESC;
```

### Set Up Alerts

```sql
-- Create alerting package
CREATE OR REPLACE PACKAGE PKG_COMPRESSION_ALERTS AS
    PROCEDURE CHECK_FAILED_OPERATIONS;
    PROCEDURE CHECK_SCRATCH_SPACE;
    PROCEDURE CHECK_LONG_RUNNING_OPS;
END;
/

CREATE OR REPLACE PACKAGE BODY PKG_COMPRESSION_ALERTS AS

    PROCEDURE CHECK_FAILED_OPERATIONS AS
        v_count NUMBER;
    BEGIN
        SELECT COUNT(*) INTO v_count
        FROM COMPRESSION_HISTORY
        WHERE execution_status = 'FAILED'
          AND start_time > SYSDATE - 1;

        IF v_count > 0 THEN
            SEND_COMPRESSION_NOTIFICATION(
                'ALERT: Failed Compression Operations',
                v_count || ' compression operation(s) failed in the last 24 hours'
            );
        END IF;
    END;

    PROCEDURE CHECK_SCRATCH_SPACE AS
        v_used_pct NUMBER;
    BEGIN
        SELECT used_percent INTO v_used_pct
        FROM dba_tablespace_usage_metrics
        WHERE tablespace_name = 'SCRATCH';

        IF v_used_pct > 80 THEN
            SEND_COMPRESSION_NOTIFICATION(
                'WARNING: Scratch Tablespace Usage High',
                'Scratch tablespace is ' || ROUND(v_used_pct, 1) || '% full'
            );
        END IF;
    END;

    PROCEDURE CHECK_LONG_RUNNING_OPS AS
        v_count NUMBER;
    BEGIN
        SELECT COUNT(*) INTO v_count
        FROM COMPRESSION_HISTORY
        WHERE execution_status = 'IN_PROGRESS'
          AND (SYSTIMESTAMP - start_time) * 24 > 4;  -- > 4 hours

        IF v_count > 0 THEN
            SEND_COMPRESSION_NOTIFICATION(
                'WARNING: Long-Running Compression Operations',
                v_count || ' compression operation(s) running > 4 hours'
            );
        END IF;
    END;

END PKG_COMPRESSION_ALERTS;
/

-- Schedule alert checks
BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name => 'HOURLY_COMPRESSION_ALERTS',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN
                         PKG_COMPRESSION_ALERTS.CHECK_FAILED_OPERATIONS;
                         PKG_COMPRESSION_ALERTS.CHECK_SCRATCH_SPACE;
                         PKG_COMPRESSION_ALERTS.CHECK_LONG_RUNNING_OPS;
                       END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=HOURLY',
        enabled => TRUE
    );
END;
/
```

### AWR Integration

```sql
-- Create custom AWR report for compression metrics
CREATE OR REPLACE PROCEDURE GENERATE_COMPRESSION_AWR_REPORT(
    p_begin_snap IN NUMBER,
    p_end_snap IN NUMBER
) AS
    v_report CLOB;
BEGIN
    -- Generate custom AWR-style report for compression operations
    DBMS_LOB.CREATETEMPORARY(v_report, TRUE);

    DBMS_LOB.APPEND(v_report,
        'COMPRESSION ADVISOR AWR REPORT' || CHR(10) ||
        'Snapshot Range: ' || p_begin_snap || ' to ' || p_end_snap || CHR(10) ||
        '================================' || CHR(10) || CHR(10)
    );

    -- Add sections for operations, space savings, performance impact
    -- (Implementation details omitted for brevity)

    DBMS_OUTPUT.PUT_LINE(v_report);
END;
/
```

## Security

### Role-Based Access Control

```sql
-- Create roles for different access levels
CREATE ROLE COMPRESSION_ADMIN;
CREATE ROLE COMPRESSION_OPERATOR;
CREATE ROLE COMPRESSION_VIEWER;

-- Admin: Full access
GRANT ALL ON COMPRESSION_ANALYSIS TO COMPRESSION_ADMIN;
GRANT ALL ON COMPRESSION_HISTORY TO COMPRESSION_ADMIN;
GRANT EXECUTE ON PKG_COMPRESSION_ANALYZER TO COMPRESSION_ADMIN;
GRANT EXECUTE ON PKG_COMPRESSION_EXECUTOR TO COMPRESSION_ADMIN;

-- Operator: Execute compression only
GRANT SELECT ON V_COMPRESSION_CANDIDATES TO COMPRESSION_OPERATOR;
GRANT SELECT ON V_COMPRESSION_HISTORY TO COMPRESSION_OPERATOR;
GRANT EXECUTE ON PKG_COMPRESSION_EXECUTOR TO COMPRESSION_OPERATOR;

-- Viewer: Read-only access
GRANT SELECT ON V_COMPRESSION_CANDIDATES TO COMPRESSION_VIEWER;
GRANT SELECT ON V_COMPRESSION_SUMMARY TO COMPRESSION_VIEWER;
GRANT SELECT ON V_COMPRESSION_HISTORY TO COMPRESSION_VIEWER;
GRANT SELECT ON V_SPACE_SAVINGS TO COMPRESSION_VIEWER;

-- Assign roles to users
GRANT COMPRESSION_ADMIN TO dba_user;
GRANT COMPRESSION_OPERATOR TO app_dba;
GRANT COMPRESSION_VIEWER TO reporting_user;
```

### Audit Configuration

```sql
-- Enable auditing for compression operations
AUDIT EXECUTE ON PKG_COMPRESSION_EXECUTOR BY ACCESS;
AUDIT ALTER TABLE BY COMPRESSION_OPERATOR BY ACCESS;

-- Create audit trail view
CREATE OR REPLACE VIEW V_COMPRESSION_AUDIT AS
SELECT
    timestamp,
    username,
    action_name,
    object_schema,
    object_name,
    sql_text
FROM dba_audit_trail
WHERE object_name IN ('PKG_COMPRESSION_EXECUTOR', 'PKG_COMPRESSION_ANALYZER')
   OR sql_text LIKE '%COMPRESS%'
ORDER BY timestamp DESC;
```

### Encryption

```sql
-- Encrypt sensitive columns in configuration tables
ALTER TABLE COMPRESSION_CONFIG MODIFY (preferred_compression ENCRYPT);
ALTER TABLE EMAIL_CONFIG MODIFY (config_value ENCRYPT);
```

## Performance Tuning

### Optimize Analysis Performance

```sql
-- Create function-based indexes for faster queries
CREATE INDEX IDX_COMP_ANALYSIS_SAVINGS ON COMPRESSION_ANALYSIS(
    estimated_savings_mb DESC,
    analysis_date
);

CREATE INDEX IDX_COMP_HISTORY_DATE_STATUS ON COMPRESSION_HISTORY(
    start_time DESC,
    execution_status
);

-- Gather optimizer statistics
EXEC DBMS_STATS.GATHER_TABLE_STATS('COMPRESSION_MGR', 'COMPRESSION_ANALYSIS', CASCADE => TRUE);
EXEC DBMS_STATS.GATHER_TABLE_STATS('COMPRESSION_MGR', 'COMPRESSION_HISTORY', CASCADE => TRUE);
```

### Resource Governor

```sql
-- Create resource consumer group for compression operations
BEGIN
    DBMS_RESOURCE_MANAGER.CREATE_PENDING_AREA();

    DBMS_RESOURCE_MANAGER.CREATE_CONSUMER_GROUP(
        consumer_group => 'COMPRESSION_GROUP',
        comment => 'Resource group for compression operations'
    );

    DBMS_RESOURCE_MANAGER.CREATE_PLAN_DIRECTIVE(
        plan => 'DEFAULT_PLAN',
        group_or_subplan => 'COMPRESSION_GROUP',
        comment => 'Limit compression to 30% CPU',
        mgmt_p1 => 30,
        parallel_degree_limit_p1 => 4
    );

    DBMS_RESOURCE_MANAGER.SUBMIT_PENDING_AREA();
END;
/

-- Assign sessions to resource group
EXEC DBMS_RESOURCE_MANAGER.SET_CONSUMER_GROUP_MAPPING(
    attribute => 'MODULE_NAME',
    value => 'PKG_COMPRESSION%',
    consumer_group => 'COMPRESSION_GROUP'
);
```

## Backup and Recovery

### Backup Strategy

```sql
-- Back up compression manager schema
-- Using RMAN
RMAN> BACKUP TABLESPACE COMPRESSION_MGR_DATA;

-- Using Data Pump
expdp compression_mgr/password \
  DIRECTORY=dpump_dir \
  DUMPFILE=compression_mgr_%U.dmp \
  LOGFILE=compression_mgr_export.log \
  SCHEMAS=COMPRESSION_MGR \
  COMPRESSION=ALL

-- Schedule weekly backups
BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name => 'WEEKLY_COMPRESSION_BACKUP',
        job_type => 'EXECUTABLE',
        job_action => '/scripts/backup_compression_mgr.sh',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=WEEKLY;BYDAY=SUN;BYHOUR=2',
        enabled => TRUE
    );
END;
/
```

### Recovery Procedures

```sql
-- Restore from Data Pump
impdp compression_mgr/password \
  DIRECTORY=dpump_dir \
  DUMPFILE=compression_mgr_01.dmp \
  LOGFILE=compression_mgr_import.log \
  SCHEMAS=COMPRESSION_MGR \
  TABLE_EXISTS_ACTION=REPLACE

-- Restore analysis data only
impdp compression_mgr/password \
  DIRECTORY=dpump_dir \
  DUMPFILE=compression_mgr_01.dmp \
  TABLES=COMPRESSION_ANALYSIS,COMPRESSION_HISTORY \
  TABLE_EXISTS_ACTION=TRUNCATE
```

### Disaster Recovery

```sql
-- Export compression recommendations for DR site
CREATE OR REPLACE PROCEDURE EXPORT_COMPRESSION_RECOMMENDATIONS AS
    v_file UTL_FILE.FILE_TYPE;
BEGIN
    v_file := UTL_FILE.FOPEN('DPUMP_DIR', 'compression_recommendations.csv', 'W');

    FOR rec IN (SELECT * FROM V_COMPRESSION_CANDIDATES) LOOP
        UTL_FILE.PUT_LINE(v_file,
            rec.owner || ',' ||
            rec.object_name || ',' ||
            rec.advisable_compression || ',' ||
            rec.estimated_savings_mb
        );
    END LOOP;

    UTL_FILE.FCLOSE(v_file);
END;
/
```

---

**Document Version**: 1.0
**Last Updated**: 2025-01-13
**Oracle Version**: 19c and higher
