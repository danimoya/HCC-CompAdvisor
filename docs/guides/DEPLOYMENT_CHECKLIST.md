# HCC Compression Advisor - Deployment Checklist

## Pre-Deployment Validation

### Environment Requirements
- [ ] Oracle Database 19c or higher installed
- [ ] Oracle 23c Free Edition (recommended) or Enterprise Edition
- [ ] Minimum 8GB RAM available
- [ ] 50GB disk space for database
- [ ] SCRATCH_TS tablespace created (10GB minimum)
- [ ] Python 3.8+ installed (for dashboard)
- [ ] Docker 20.10+ installed (if using Docker deployment)

### Database Prerequisites
- [ ] Schema user created (COMPRESSION_MGR recommended)
- [ ] Required privileges granted:
  - CREATE TABLE, CREATE SEQUENCE, CREATE PROCEDURE, CREATE VIEW
  - SELECT on DBA_TABLES, DBA_INDEXES, DBA_SEGMENTS, DBA_TAB_PARTITIONS
  - SELECT on V$DATABASE, V$SESSION, V$PARAMETER
  - EXECUTE on DBMS_COMPRESSION, DBMS_STATS
  - CREATE ANY INDEX (for index rebuilds)
  - ALTER ANY TABLE (for compression operations)
- [ ] Sufficient tablespace quotas assigned
- [ ] Network access configured (for ORDS if using REST API)

### Installation Files
- [ ] All SQL scripts present in sql/ directory:
  - 01_schema.sql
  - 01a_schema_fixes.sql (NEW)
  - 02_strategies.sql
  - 02a_logging_pkg.sql (NEW)
  - 02b_exadata_detection.sql (NEW)
  - 03_advisor_pkg.sql
  - 04_executor_pkg.sql
  - 05_views.sql
  - 06_ords.sql (optional)
  - install_full.sql
  - validate_installation.sql (NEW)
  - uninstall.sql

## Installation Steps

### Option 1: Docker Deployment (Recommended)

#### Step 1: Docker Environment Setup
- [ ] Navigate to docker directory: `cd docker/`
- [ ] Copy environment template: `cp .env.example .env`
- [ ] Edit .env file with your settings:
  - ORACLE_PASSWORD
  - COMPRESSION_MGR_PASSWORD
  - STREAMLIT_PASSWORD
  - ORDS_PASSWORD (if using ORDS)

#### Step 2: Launch Docker Environment
- [ ] Run quick start script: `./quick-start.sh`
- [ ] Wait for initialization (10-15 minutes first time)
- [ ] Monitor logs: `docker-compose logs -f`
- [ ] Verify containers running: `docker-compose ps`

#### Step 3: Verify Installation
- [ ] Access Streamlit dashboard: https://localhost:8501
- [ ] Login with configured password
- [ ] Check database connection on Analysis page
- [ ] Verify ORDS API (if configured): https://localhost:8080/ords

### Option 2: Manual Installation

#### Step 1: Database Installation
```bash
# Connect to database
sqlplus COMPRESSION_MGR/password@database

# Run master installation script
@sql/install_full.sql

# Review installation log
# Check for any errors or warnings
```

#### Step 2: Validation
```bash
# Run validation script
@sql/validate_installation.sql

# Expected output: "Validation Status: SUCCESS"
# Exit code should be 0
```

#### Step 3: Python Dashboard Setup
```bash
cd python/

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your database credentials

# Generate SSL certificates (production)
cd ssl/
./generate_cert.sh
cd ..

# Start dashboard
streamlit run app.py --server.port=8501 --server.address=0.0.0.0
```

## Post-Installation Verification

### Database Objects
- [ ] Run validation script shows SUCCESS status
- [ ] All packages are VALID:
  ```sql
  SELECT object_name, status FROM user_objects WHERE object_type IN ('PACKAGE', 'PACKAGE BODY');
  ```
- [ ] All tables created (4 tables):
  - T_COMPRESSION_ANALYSIS
  - T_COMPRESSION_HISTORY
  - T_COMPRESSION_STRATEGIES
  - T_STRATEGY_RULES
- [ ] All views accessible (10 views):
  - V_COMPRESSION_CANDIDATES
  - V_COMPRESSION_SUMMARY
  - And 8 others
- [ ] Logging package functional:
  ```sql
  EXEC PKG_COMPRESSION_LOG.log_info('TEST', 'DEPLOY', 'Installation test');
  SELECT * FROM T_COMPRESSION_LOG WHERE package_name = 'TEST';
  ```

### Platform Detection
- [ ] Exadata detection working:
  ```sql
  SELECT PKG_EXADATA_DETECTION.get_platform_type() AS platform FROM DUAL;
  -- Expected: EXADATA or STANDARD
  ```
- [ ] Compression type mapping loaded:
  ```sql
  SELECT * FROM T_COMPRESSION_TYPE_MAP;
  -- Should show 6 compression type mappings
  ```
- [ ] HCC availability check:
  ```sql
  SELECT CASE WHEN PKG_EXADATA_DETECTION.is_hcc_available()
         THEN 'HCC Available' ELSE 'Standard Only' END FROM DUAL;
  ```

### Compression Strategies
- [ ] Three strategies loaded:
  ```sql
  SELECT strategy_id, strategy_name FROM T_COMPRESSION_STRATEGIES;
  -- Expected: 1=HIGH_PERFORMANCE, 2=BALANCED, 3=MAXIMUM_COMPRESSION
  ```
- [ ] Strategy rules loaded (27 rules minimum):
  ```sql
  SELECT COUNT(*) FROM T_STRATEGY_RULES;
  -- Expected: >= 27
  ```

### Functional Testing
- [ ] Run basic analysis:
  ```sql
  EXEC PKG_COMPRESSION_ADVISOR.run_analysis(p_owner => USER, p_strategy_id => 2);
  ```
- [ ] Check analysis results:
  ```sql
  SELECT * FROM V_COMPRESSION_CANDIDATES;
  ```
- [ ] View recommendations:
  ```sql
  SELECT object_name, advisable_compression, potential_savings_mb
  FROM V_COMPRESSION_CANDIDATES
  WHERE ROWNUM <= 10;
  ```

### Dashboard Verification
- [ ] Dashboard accessible on configured port
- [ ] Authentication working
- [ ] Database connection successful
- [ ] All 5 pages load without errors:
  - Analysis
  - Recommendations
  - Execution
  - History
  - Strategies
- [ ] Charts and visualizations render correctly
- [ ] API integration working (if ORDS configured)

### ORDS API Verification (Optional)
- [ ] ORDS module installed and enabled
- [ ] Test health endpoint:
  ```bash
  curl -k https://localhost:8080/ords/compression/compression/v1/health
  ```
- [ ] Test analyze endpoint:
  ```bash
  curl -k -X POST https://localhost:8080/ords/compression/compression/v1/analyze \
    -H "Content-Type: application/json" \
    -d '{"owner":"COMPRESSION_MGR","strategy_id":2}'
  ```

## Security Verification

### Database Security
- [ ] Strong passwords configured for all accounts
- [ ] Least privilege principle applied (user only has required privileges)
- [ ] Audit trail enabled (T_COMPRESSION_LOG captures all operations)
- [ ] No hardcoded credentials in code
- [ ] Environment variables used for sensitive data

### Application Security
- [ ] SSL/TLS certificates configured for dashboard
- [ ] HTTPS enforced (no HTTP access)
- [ ] Strong authentication password required
- [ ] Session timeout configured
- [ ] API keys secured (if using ORDS)
- [ ] Rate limiting configured (if applicable)

### Network Security
- [ ] Firewall rules configured for required ports only:
  - 1521 (Oracle Database) - internal only
  - 8501 (Streamlit) - restricted access
  - 8080 (ORDS) - optional, restricted access
- [ ] Database listener configured securely
- [ ] No default passwords in use

## Performance Validation

### Database Performance
- [ ] SCRATCH_TS tablespace has sufficient space (10GB+)
- [ ] Database optimizer statistics current
- [ ] No invalid objects
- [ ] Indexes on key columns verified
- [ ] Parallel execution configured (if available)

### Application Performance
- [ ] Dashboard loads in < 3 seconds
- [ ] Analysis completes in reasonable time (varies by database size)
- [ ] Charts render smoothly
- [ ] No memory leaks observed
- [ ] Connection pooling working (if configured)

## Backup and Recovery

### Backup Configuration
- [ ] Database backup schedule configured
- [ ] Application code backed up
- [ ] Configuration files backed up
- [ ] SSL certificates backed up
- [ ] Rollback procedure documented and tested

### Recovery Testing
- [ ] Uninstall script tested:
  ```sql
  @sql/uninstall.sql
  ```
- [ ] Reinstallation verified to work correctly
- [ ] Data recovery procedure documented

## Documentation Review

### User Documentation
- [ ] README.md reviewed and accurate
- [ ] INSTALLATION.md accessible and current
- [ ] USER_GUIDE.md available for end users
- [ ] API_REFERENCE.md complete (if using ORDS)
- [ ] STRATEGY_GUIDE.md explains compression strategies
- [ ] All internal links working
- [ ] All external links verified

### Technical Documentation
- [ ] System architecture documented
- [ ] Database schema documented
- [ ] API endpoints documented
- [ ] Troubleshooting guide available
- [ ] Known limitations documented

## Testing Validation

### SQL Tests
- [ ] Test framework installed
- [ ] Unit tests pass:
  ```sql
  @sql/tests/run_all_tests.sql
  ```
- [ ] All 90 tests passing
- [ ] No errors or warnings in test output

### Python Tests (if applicable)
- [ ] Test dependencies installed:
  ```bash
  pip install -r requirements-test.txt
  ```
- [ ] All tests passing:
  ```bash
  pytest -v
  ```
- [ ] Code coverage >= 80%

## Production Readiness

### Monitoring Setup
- [ ] Database monitoring configured
- [ ] Application logging configured
- [ ] Error alerting configured
- [ ] Performance metrics tracked
- [ ] Disk space monitoring for SCRATCH_TS

### Operational Procedures
- [ ] Maintenance windows scheduled
- [ ] Log rotation configured
- [ ] Purge old logs procedure documented:
  ```sql
  SELECT PKG_COMPRESSION_LOG.purge_logs(90) FROM DUAL;
  ```
- [ ] Escalation procedures documented
- [ ] On-call rotation defined (if applicable)

### Training
- [ ] Administrators trained on installation
- [ ] End users trained on dashboard usage
- [ ] Support team familiar with troubleshooting
- [ ] Documentation accessible to all stakeholders

## Final Sign-Off

### Stakeholder Approvals
- [ ] Database Administrator approval
- [ ] Security team approval
- [ ] Operations team approval
- [ ] Business owner approval

### Go-Live Checklist
- [ ] All items above verified
- [ ] Change management request approved
- [ ] Rollback plan documented and tested
- [ ] Communication plan executed
- [ ] Support team on standby
- [ ] Deployment window scheduled

### Post-Deployment
- [ ] Verify system stability (24 hours)
- [ ] Monitor error logs
- [ ] Review performance metrics
- [ ] Collect user feedback
- [ ] Document lessons learned

## Troubleshooting Common Issues

### Installation Failures
**Issue**: Package compilation errors referencing PKG_COMPRESSION_LOG
- **Fix**: Ensure 02a_logging_pkg.sql runs before other packages
- **Verify**: Check package status in user_objects

**Issue**: Schema mismatch errors
- **Fix**: Run 01a_schema_fixes.sql after 01_schema.sql
- **Verify**: Query T_STRATEGY_RULES to confirm new columns exist

**Issue**: Sequence not found (SEQ_STRATEGY_RULES)
- **Fix**: Included in 01a_schema_fixes.sql
- **Verify**: `SELECT sequence_name FROM user_sequences;`

### Runtime Issues
**Issue**: Exadata detection always returns STANDARD
- **Check**: Query V$PARAMETER for cell_offload_processing
- **Fix**: Verify GV$CELL_CONFIG accessible
- **Verify**: Run PKG_EXADATA_DETECTION.verify_platform()

**Issue**: Compressed objects moving to wrong tablespace
- **Check**: Review DDL in T_COMPRESSION_HISTORY
- **Fix**: Executor package now preserves tablespaces
- **Verify**: Query DBA_TABLES before/after compression

**Issue**: Dashboard cannot connect to database
- **Check**: Environment variables in .env file
- **Fix**: Verify credentials, TNS names, network connectivity
- **Test**: Use test_connection.py script

### Performance Issues
**Issue**: Analysis taking too long
- **Check**: Database size and current load
- **Fix**: Run during maintenance window, use parallel execution
- **Tune**: Adjust strategy rules for faster execution

**Issue**: SCRATCH_TS full
- **Fix**: Add datafile or increase autoextend size
- **Monitor**: Set up alerts for tablespace usage

## Support Information

### Log Locations
- **Database Logs**: T_COMPRESSION_LOG table
- **Installation Log**: sql/install_full.log (if spooling)
- **Dashboard Logs**: python/logs/streamlit.log
- **Docker Logs**: `docker-compose logs`

### Useful Queries
```sql
-- Check installation status
@sql/validate_installation.sql

-- View recent activity
SELECT * FROM T_COMPRESSION_LOG ORDER BY log_date DESC FETCH FIRST 20 ROWS ONLY;

-- Check compression history
SELECT * FROM V_COMPRESSION_SUMMARY;

-- Platform details
SELECT * FROM PKG_EXADATA_DETECTION.get_detection_details();
```

### Getting Help
- Review documentation in docs/ directory
- Check logs for error messages
- Run validation script for diagnostics
- Review troubleshooting guides

---

**Deployment Date**: _______________
**Deployed By**: _______________
**Sign-off**: _______________
