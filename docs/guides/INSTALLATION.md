# Installation Guide - HCC Compression Advisor

This guide provides complete step-by-step instructions for installing and configuring the HCC Compression Advisor system.

## Table of Contents

- [System Requirements](#system-requirements)
- [Prerequisites](#prerequisites)
- [Installation Methods](#installation-methods)
  - [Method 1: Docker Installation (Recommended)](#method-1-docker-installation-recommended)
  - [Method 2: Manual Installation](#method-2-manual-installation)
  - [Method 3: Cloud Deployment](#method-3-cloud-deployment)
- [Post-Installation Configuration](#post-installation-configuration)
- [Verification](#verification)
- [Troubleshooting](#troubleshooting)
- [Uninstallation](#uninstallation)

---

## System Requirements

### Minimum Requirements

| Component | Requirement |
|-----------|-------------|
| **Operating System** | Linux (RHEL 7+, Ubuntu 18.04+, OEL 7+), Windows 10+ (with WSL2 for Docker) |
| **CPU** | 4 cores (x86_64) |
| **Memory** | 8GB RAM |
| **Disk Space** | 50GB available |
| **Database** | Oracle Database 19c or higher |
| **Python** | 3.8+ (for Streamlit dashboard) |
| **Docker** | 20.10+ (if using Docker method) |
| **Docker Compose** | 2.0+ (if using Docker method) |

### Recommended Requirements

| Component | Requirement |
|-----------|-------------|
| **Operating System** | Linux (RHEL 8+, Ubuntu 20.04+, OEL 8+) |
| **CPU** | 8 cores |
| **Memory** | 16GB RAM |
| **Disk Space** | 100GB available (SSD recommended) |
| **Database** | Oracle Database 23c Free Edition |
| **Python** | 3.11+ |
| **Network** | 1Gbps network interface |

### Oracle Database Requirements

- **Edition**: Oracle Database 19c, 21c, or 23c (Free Edition supported)
- **Tablespace**: COMPRESSION_DATA (minimum 10GB) and SCRATCH_TS (minimum 50GB)
- **Privileges**: DBA role or equivalent for COMPRESSION_MGR user
- **ORDS** (Optional): Oracle REST Data Services 20.4+ for REST API functionality

---

## Prerequisites

### 1. Oracle Database Setup

#### For Oracle 23c Free Edition (Recommended)

```bash
# Download Oracle 23c Free Edition
wget https://download.oracle.com/otn-pub/otn_software/db-free/oracle-database-free-23c-1.0-1.el8.x86_64.rpm

# Install Oracle Database
sudo yum -y localinstall oracle-database-free-23c-1.0-1.el8.x86_64.rpm

# Configure database
sudo /etc/init.d/oracle-free-23c configure

# Set environment variables
export ORACLE_HOME=/opt/oracle/product/23c/dbhomeFree
export ORACLE_SID=FREE
export PATH=$ORACLE_HOME/bin:$PATH
```

#### For Existing Oracle Database

Ensure your Oracle database is running and accessible:

```bash
# Test connection
sqlplus sys/<password>@<host>:<port>/<service_name> as sysdba

# Verify version (must be 19c or higher)
SELECT banner FROM v$version;
```

### 2. Python Environment

```bash
# Install Python 3.8+ (if not present)
sudo yum install python3.11  # RHEL/OEL
# OR
sudo apt install python3.11  # Ubuntu

# Verify installation
python3 --version

# Install pip
sudo python3 -m ensurepip --upgrade
```

### 3. Docker Environment (for Docker installation)

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verify installation
docker --version
docker-compose --version

# Start Docker service
sudo systemctl start docker
sudo systemctl enable docker

# Add user to docker group (optional, to run without sudo)
sudo usermod -aG docker $USER
newgrp docker
```

---

## Installation Methods

## Method 1: Docker Installation (Recommended)

This is the fastest and easiest installation method. It includes Oracle 23c Free Edition, all dependencies, and automated setup.

### Step 1: Clone or Download Project

```bash
# Clone the project (if using git)
git clone https://github.com/yourusername/HCC-CompAdvisor.git
cd HCC-CompAdvisor

# OR extract from archive
tar -xzf HCC-CompAdvisor.tar.gz
cd HCC-CompAdvisor
```

### Step 2: Configure Environment Variables

```bash
# Navigate to docker directory
cd docker

# Create .env file (or use provided template)
cat > .env << 'EOF'
# Oracle Database Configuration
ORACLE_PWD=YourStrongPassword123!
ORACLE_EDITION=free
ORACLE_CHARACTERSET=AL32UTF8

# Compression Manager User
COMPRESSION_USER=COMPRESSION_MGR
COMPRESSION_PASSWORD=CompressPass123!

# Streamlit Dashboard
STREAMLIT_PASSWORD=DashboardPass123!
STREAMLIT_PORT=8501

# ORDS Configuration (Optional)
ORDS_BASE_URL=http://localhost:8080/ords

# Resource Limits
ORACLE_MEMORY=4G
ORACLE_SGA=2G
ORACLE_PGA=1G
EOF

# Secure the file
chmod 600 .env
```

### Step 3: Run Quick Start Script

```bash
# Make script executable
chmod +x quick-start.sh

# Run installation
./quick-start.sh

# Expected output:
# [1/5] Checking prerequisites...
# [2/5] Starting Oracle Database container...
# [3/5] Waiting for database initialization (this may take 10-15 minutes)...
# [4/5] Installing compression advisor schema...
# [5/5] Starting Streamlit dashboard...
#
# ✅ Installation Complete!
#
# 🌐 Dashboard URL: https://localhost:8501
# 📊 ORDS API: http://localhost:8080/ords/compression/v1/
# 🗄️  Database: localhost:1521/FREEPDB1
# 👤 User: COMPRESSION_MGR
```

### Step 4: Verify Docker Installation

```bash
# Check running containers
docker-compose ps

# Expected output:
# NAME                 SERVICE    STATUS      PORTS
# oracle-23c-free      oracle     running     0.0.0.0:1521->1521/tcp
# streamlit-dashboard  dashboard  running     0.0.0.0:8501->8501/tcp

# Check database logs
docker-compose logs -f oracle

# Check dashboard logs
docker-compose logs -f dashboard
```

### Step 5: Access the System

```bash
# Open dashboard in browser
open https://localhost:8501

# Login with credentials from .env file
# Username: admin
# Password: <STREAMLIT_PASSWORD>

# Test database connection
docker exec -it oracle-23c-free sqlplus COMPRESSION_MGR/CompressPass123!@FREEPDB1
```

---

## Method 2: Manual Installation

Use this method if you have an existing Oracle database or prefer manual control.

### Step 1: Create Database User and Tablespaces

```sql
-- Connect as SYSDBA
sqlplus sys/<password>@<service_name> as sysdba

-- Create tablespaces
CREATE TABLESPACE COMPRESSION_DATA
  DATAFILE '/u01/app/oracle/oradata/FREEPDB1/compression_data01.dbf'
  SIZE 1G
  AUTOEXTEND ON
  NEXT 100M
  MAXSIZE 10G
  EXTENT MANAGEMENT LOCAL
  SEGMENT SPACE MANAGEMENT AUTO;

CREATE TABLESPACE SCRATCH_TS
  DATAFILE '/u01/app/oracle/oradata/FREEPDB1/scratch_ts01.dbf'
  SIZE 5G
  AUTOEXTEND ON
  NEXT 1G
  MAXSIZE 50G
  EXTENT MANAGEMENT LOCAL
  SEGMENT SPACE MANAGEMENT AUTO;

-- Create user
CREATE USER COMPRESSION_MGR IDENTIFIED BY YourPassword123!
  DEFAULT TABLESPACE COMPRESSION_DATA
  TEMPORARY TABLESPACE TEMP
  QUOTA UNLIMITED ON COMPRESSION_DATA
  QUOTA UNLIMITED ON SCRATCH_TS;

-- Grant privileges
GRANT CONNECT, RESOURCE, DBA TO COMPRESSION_MGR;
GRANT CREATE SESSION TO COMPRESSION_MGR;
GRANT CREATE TABLE TO COMPRESSION_MGR;
GRANT CREATE VIEW TO COMPRESSION_MGR;
GRANT CREATE SEQUENCE TO COMPRESSION_MGR;
GRANT CREATE PROCEDURE TO COMPRESSION_MGR;
GRANT SELECT ANY TABLE TO COMPRESSION_MGR;
GRANT SELECT ANY DICTIONARY TO COMPRESSION_MGR;
GRANT ALTER ANY TABLE TO COMPRESSION_MGR;
GRANT EXECUTE ON DBMS_COMPRESSION TO COMPRESSION_MGR;
GRANT EXECUTE ON DBMS_STATS TO COMPRESSION_MGR;

-- Exit
EXIT;
```

### Step 2: Install Database Schema

```bash
# Navigate to SQL directory
cd /path/to/HCC-CompAdvisor/sql

# Connect as COMPRESSION_MGR
sqlplus COMPRESSION_MGR/YourPassword123!@<service_name>

# Run installation script
@install_full.sql

# Expected output:
# Installing HCC Compression Advisor v1.0
# =======================================
# [1/6] Creating schema objects... DONE
# [2/6] Loading compression strategies... DONE
# [3/6] Creating advisor package... DONE
# [4/6] Creating executor package... DONE
# [5/6] Creating views... DONE
# [6/6] Configuring ORDS (if available)... DONE
#
# Installation completed successfully!
# Objects created: 30+
# No errors detected.

# Verify installation
SELECT object_name, object_type, status
FROM user_objects
WHERE status != 'VALID'
ORDER BY object_type, object_name;

-- Should return no rows (all objects valid)
```

### Step 3: Install Python Dependencies

```bash
# Navigate to python directory
cd /path/to/HCC-CompAdvisor/python

# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# OR
venv\Scripts\activate  # Windows

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Verify installation
pip list

# Expected packages:
# streamlit>=1.28.0
# oracledb>=1.4.0
# pandas>=2.0.0
# plotly>=5.17.0
# requests>=2.31.0
# python-dotenv>=1.0.0
```

### Step 4: Configure Python Application

```bash
# Create configuration file
cd /path/to/HCC-CompAdvisor/python

# Create .env file
cat > .env << 'EOF'
# Oracle Database Connection
ORACLE_HOST=localhost
ORACLE_PORT=1521
ORACLE_SERVICE=FREEPDB1
ORACLE_USER=COMPRESSION_MGR
ORACLE_PASSWORD=YourPassword123!

# ORDS Configuration (Optional)
ORDS_BASE_URL=http://localhost:8080/ords
ORDS_SCHEMA=compression
ORDS_MODULE=compression
ORDS_VERSION=v1

# Streamlit Dashboard
STREAMLIT_PASSWORD=DashboardPass123!
STREAMLIT_SERVER_PORT=8501
STREAMLIT_SERVER_ADDRESS=0.0.0.0

# SSL Configuration (Optional)
SSL_ENABLED=true
SSL_CERT_PATH=ssl/cert.pem
SSL_KEY_PATH=ssl/key.pem

# Logging
LOG_LEVEL=INFO
LOG_FILE=logs/app.log
EOF

# Secure the file
chmod 600 .env
```

### Step 5: Generate SSL Certificates (Optional but Recommended)

```bash
# Navigate to SSL directory
cd /path/to/HCC-CompAdvisor/python/ssl

# Make generation script executable
chmod +x generate_cert.sh

# Generate self-signed certificate
./generate_cert.sh

# Expected output:
# Generating SSL certificate...
# Country Name: US
# State: Your State
# Organization: Your Organization
# Common Name: localhost
#
# Certificate generated:
# - Certificate: /path/to/ssl/cert.pem
# - Private Key: /path/to/ssl/key.pem
#
# Note: This is a self-signed certificate for development use only.
```

### Step 6: Start Streamlit Dashboard

```bash
# Navigate to python directory
cd /path/to/HCC-CompAdvisor/python

# Make start script executable
chmod +x start.sh

# Start dashboard
./start.sh

# Expected output:
# Starting HCC Compression Advisor Dashboard...
#
# You can now view your Streamlit app in your browser.
#
# URL: https://localhost:8501
# Network URL: https://192.168.1.100:8501
#
# Press CTRL+C to stop the server.
```

### Step 7: Verify Manual Installation

```bash
# Test database connection
cd /path/to/HCC-CompAdvisor/python
python3 test_connection.py

# Expected output:
# Testing Oracle Database Connection...
# ✅ Connection successful!
# Database version: Oracle Database 23c Free
# User: COMPRESSION_MGR
# Tablespace: COMPRESSION_DATA
# Objects: 30+ valid objects
#
# Testing packages...
# ✅ PKG_COMPRESSION_ADVISOR: VALID
# ✅ PKG_COMPRESSION_EXECUTOR: VALID
#
# All tests passed!
```

---

## Method 3: Cloud Deployment

Deploy to Oracle Cloud Infrastructure (OCI) or AWS.

### Oracle Cloud Infrastructure (OCI)

```bash
# Prerequisites
# - OCI account with appropriate permissions
# - OCI CLI installed and configured
# - Terraform installed (optional)

# Using OCI CLI
oci db autonomous-database create \
  --admin-password YourPassword123! \
  --compartment-id <compartment-ocid> \
  --db-name HCCADVISOR \
  --display-name "HCC Compression Advisor" \
  --db-workload OLTP \
  --cpu-core-count 1 \
  --data-storage-size-in-tbs 1 \
  --is-free-tier true

# Download wallet
oci db autonomous-database generate-wallet \
  --autonomous-database-id <adb-ocid> \
  --file wallet.zip \
  --password WalletPassword123!

# Extract wallet
unzip wallet.zip -d wallet/

# Update connection configuration
export TNS_ADMIN=/path/to/wallet
export ORACLE_SERVICE=hccadvisor_high

# Continue with Manual Installation steps (Step 2 onwards)
```

### AWS RDS for Oracle

```bash
# Prerequisites
# - AWS account with appropriate permissions
# - AWS CLI installed and configured

# Create RDS instance
aws rds create-db-instance \
  --db-instance-identifier hcc-advisor \
  --db-instance-class db.t3.medium \
  --engine oracle-ee \
  --engine-version 19.0.0.0 \
  --master-username admin \
  --master-user-password YourPassword123! \
  --allocated-storage 100 \
  --storage-type gp3 \
  --vpc-security-group-ids sg-xxxxxxxxx \
  --db-subnet-group-name my-db-subnet-group \
  --backup-retention-period 7 \
  --license-model bring-your-own-license

# Wait for instance to be available
aws rds wait db-instance-available \
  --db-instance-identifier hcc-advisor

# Get endpoint
aws rds describe-db-instances \
  --db-instance-identifier hcc-advisor \
  --query 'DBInstances[0].Endpoint.Address' \
  --output text

# Update connection configuration
export ORACLE_HOST=<rds-endpoint>
export ORACLE_PORT=1521
export ORACLE_SERVICE=ORCL

# Continue with Manual Installation steps (Step 2 onwards)
```

---

## Post-Installation Configuration

### 1. Configure Compression Strategies

```sql
-- Connect to database
sqlplus COMPRESSION_MGR/<password>@<service_name>

-- View default strategies
SELECT strategy_id, strategy_name, description, is_active
FROM COMPRESSION_STRATEGIES;

-- Modify strategy (example: adjust thresholds)
UPDATE COMPRESSION_STRATEGY_RULES
SET threshold_value = 500  -- 500MB instead of default
WHERE strategy_id = 2
  AND rule_type = 'SIZE_THRESHOLD';

COMMIT;

-- Create custom strategy (optional)
INSERT INTO COMPRESSION_STRATEGIES (
  strategy_id, strategy_name, description, is_active
) VALUES (
  4, 'CUSTOM_ARCHIVE', 'Custom archival strategy', 1
);

COMMIT;
```

### 2. Configure ORDS (Optional)

If you have Oracle REST Data Services installed:

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
  COMMIT;
END;
/

-- Install ORDS module
@06_ords.sql

-- Verify endpoints
SELECT name, uri_template, method
FROM user_ords_handlers
ORDER BY name;
```

### 3. Schedule Automated Analysis (Optional)

```sql
-- Create DBMS_SCHEDULER job for weekly analysis
BEGIN
  DBMS_SCHEDULER.CREATE_JOB(
    job_name => 'COMPRESSION_WEEKLY_ANALYSIS',
    job_type => 'PLSQL_BLOCK',
    job_action => 'BEGIN PKG_COMPRESSION_ADVISOR.run_analysis(p_strategy_id => 2); END;',
    start_date => SYSTIMESTAMP,
    repeat_interval => 'FREQ=WEEKLY;BYDAY=SUN;BYHOUR=2',
    enabled => TRUE,
    comments => 'Weekly compression analysis with BALANCED strategy'
  );
END;
/

-- Verify job
SELECT job_name, enabled, state, next_run_date
FROM user_scheduler_jobs
WHERE job_name = 'COMPRESSION_WEEKLY_ANALYSIS';
```

### 4. Configure Dashboard Settings

```bash
# Edit Streamlit configuration
cd /path/to/HCC-CompAdvisor/python

# Create/edit .streamlit/config.toml
mkdir -p .streamlit
cat > .streamlit/config.toml << 'EOF'
[server]
port = 8501
address = "0.0.0.0"
maxUploadSize = 200
enableCORS = false
enableXsrfProtection = true

[browser]
gatherUsageStats = false
serverAddress = "localhost"
serverPort = 8501

[theme]
primaryColor = "#F63366"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F0F2F6"
textColor = "#262730"
font = "sans serif"

[logger]
level = "info"
messageFormat = "%(asctime)s - %(levelname)s - %(message)s"
EOF
```

---

## Verification

### 1. Database Verification

```sql
-- Connect to database
sqlplus COMPRESSION_MGR/<password>@<service_name>

-- Check all objects are valid
SELECT object_type, COUNT(*) as count
FROM user_objects
WHERE status = 'VALID'
GROUP BY object_type
ORDER BY object_type;

-- Expected output:
-- OBJECT_TYPE          COUNT
-- -------------------- -----
-- INDEX                    8
-- PACKAGE                  2
-- PACKAGE BODY             2
-- SEQUENCE                 3
-- TABLE                   10
-- VIEW                    10

-- Test advisor package
SET SERVEROUTPUT ON
DECLARE
  v_status VARCHAR2(100);
BEGIN
  PKG_COMPRESSION_ADVISOR.run_analysis(
    p_owner => NULL,
    p_strategy_id => 2
  );
  DBMS_OUTPUT.PUT_LINE('Analysis completed successfully');
END;
/

-- Check recommendations
SELECT COUNT(*) as recommendation_count
FROM COMPRESSION_RECOMMENDATIONS
WHERE recommendation_date > SYSDATE - 1;
```

### 2. Dashboard Verification

```bash
# Open browser to dashboard
open https://localhost:8501

# Navigate through all pages:
# 1. Analysis page - trigger analysis
# 2. Recommendations page - view results
# 3. Execution page - test dry-run mode
# 4. History page - check execution log
# 5. Strategies page - compare strategies

# Check logs
tail -f /path/to/HCC-CompAdvisor/python/logs/app.log
```

### 3. API Verification (if ORDS configured)

```bash
# Test ORDS endpoints
curl -X GET http://localhost:8080/ords/compression/v1/summary

# Expected response:
# {
#   "total_objects": 1234,
#   "total_size_mb": 45678,
#   "potential_savings_mb": 12345,
#   "compression_ratio": 2.5
# }

# Test analysis endpoint
curl -X POST http://localhost:8080/ords/compression/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"strategy_id": 2}'
```

---

## Troubleshooting

### Common Installation Issues

#### Issue 1: Database Connection Failure

**Symptoms:**
```
ORA-12541: TNS:no listener
ORA-12545: Connect failed because target host or object does not exist
```

**Solution:**
```bash
# Check listener status
lsnrctl status

# Start listener if not running
lsnrctl start

# Verify tnsnames.ora
cat $ORACLE_HOME/network/admin/tnsnames.ora

# Test connection
tnsping <service_name>
sqlplus COMPRESSION_MGR/<password>@<service_name>
```

#### Issue 2: Insufficient Privileges

**Symptoms:**
```
ORA-01031: insufficient privileges
ORA-00990: missing or invalid privilege
```

**Solution:**
```sql
-- Connect as SYSDBA
sqlplus sys/<password>@<service_name> as sysdba

-- Re-grant all required privileges
@/path/to/docker/init-scripts/02-grant-privileges.sql

-- Verify grants
SELECT privilege
FROM dba_sys_privs
WHERE grantee = 'COMPRESSION_MGR'
ORDER BY privilege;
```

#### Issue 3: Tablespace Full

**Symptoms:**
```
ORA-01653: unable to extend table COMPRESSION_MGR.COMPRESSION_ANALYSIS
```

**Solution:**
```sql
-- Check tablespace usage
SELECT tablespace_name,
       ROUND(used_space * 8192 / 1024 / 1024, 2) as used_mb,
       ROUND(tablespace_size * 8192 / 1024 / 1024, 2) as total_mb,
       ROUND(used_percent, 2) as used_percent
FROM dba_tablespace_usage_metrics
WHERE tablespace_name IN ('COMPRESSION_DATA', 'SCRATCH_TS');

-- Add datafile or resize
ALTER TABLESPACE COMPRESSION_DATA
  ADD DATAFILE '/u01/app/oracle/oradata/FREEPDB1/compression_data02.dbf'
  SIZE 1G AUTOEXTEND ON NEXT 100M MAXSIZE 10G;

-- OR resize existing datafile
ALTER DATABASE DATAFILE '/u01/app/oracle/oradata/FREEPDB1/compression_data01.dbf'
  AUTOEXTEND ON NEXT 100M MAXSIZE 20G;
```

#### Issue 4: Docker Container Fails to Start

**Symptoms:**
```
Error response from daemon: driver failed programming external connectivity
Container oracle-23c-free is unhealthy
```

**Solution:**
```bash
# Check if port 1521 is already in use
sudo lsof -i :1521
sudo netstat -tuln | grep 1521

# Stop conflicting service or change port
docker-compose down
docker-compose up -d --force-recreate

# Check container logs
docker-compose logs -f oracle

# Increase memory if needed
# Edit docker-compose.yml:
# services:
#   oracle:
#     shm_size: 2g
#     environment:
#       - ORACLE_MEMORY=4G
```

#### Issue 5: Streamlit Dashboard Won't Start

**Symptoms:**
```
ModuleNotFoundError: No module named 'oracledb'
Port 8501 is already in use
```

**Solution:**
```bash
# Verify virtual environment
which python3
source venv/bin/activate

# Reinstall dependencies
pip install --force-reinstall -r requirements.txt

# Check for port conflicts
lsof -i :8501
sudo netstat -tuln | grep 8501

# Kill process or change port
kill -9 <pid>
# OR
export STREAMLIT_SERVER_PORT=8502
./start.sh
```

#### Issue 6: SSL Certificate Errors

**Symptoms:**
```
SSL: CERTIFICATE_VERIFY_FAILED
[SSL: WRONG_VERSION_NUMBER]
```

**Solution:**
```bash
# Regenerate certificates
cd /path/to/HCC-CompAdvisor/python/ssl
./generate_cert.sh

# OR disable SSL temporarily
# Edit .env:
SSL_ENABLED=false

# For production, use proper CA-signed certificates
# Install cert from Let's Encrypt or commercial CA
```

### Performance Issues

#### Issue: Slow Analysis on Large Databases

**Symptoms:**
- Analysis takes hours to complete
- High CPU/memory usage
- Database appears hung

**Solution:**
```sql
-- Analyze specific schemas instead of all
EXEC PKG_COMPRESSION_ADVISOR.run_analysis(
  p_owner => 'SPECIFIC_SCHEMA',
  p_strategy_id => 2
);

-- Exclude large objects initially
DELETE FROM COMPRESSION_ANALYSIS
WHERE size_mb > 10000;

-- Gather fresh statistics
EXEC DBMS_STATS.GATHER_SCHEMA_STATS('COMPRESSION_MGR');

-- Increase parallelism (if available)
ALTER SESSION ENABLE PARALLEL DML;
ALTER SESSION SET PARALLEL_DEGREE_POLICY = AUTO;
```

### Getting Help

If you encounter issues not covered here:

1. Check database alert log: `$ORACLE_BASE/diag/rdbms/<db_name>/<SID>/trace/alert_<SID>.log`
2. Check Streamlit logs: `/path/to/python/logs/app.log`
3. Check Docker logs: `docker-compose logs -f`
4. Review installation log: `sql/install_full.log`
5. Consult Oracle documentation: https://docs.oracle.com/en/database/

---

## Uninstallation

### Docker Method

```bash
# Stop and remove containers
cd /path/to/HCC-CompAdvisor/docker
docker-compose down -v

# Remove volumes (WARNING: This deletes all data)
docker volume rm hcc-advisor_oracle-data
docker volume rm hcc-advisor_streamlit-data

# Remove images (optional)
docker rmi oracle-23c-free:latest
docker rmi hcc-advisor-dashboard:latest
```

### Manual Method

```sql
-- Connect as COMPRESSION_MGR
sqlplus COMPRESSION_MGR/<password>@<service_name>

-- Run uninstall script
@/path/to/HCC-CompAdvisor/sql/uninstall.sql

-- Expected output:
-- Uninstalling HCC Compression Advisor
-- ====================================
-- Dropping ORDS module... DONE
-- Dropping views... DONE
-- Dropping packages... DONE
-- Dropping tables... DONE
-- Dropping sequences... DONE
--
-- Uninstallation completed successfully!

-- Connect as SYSDBA to drop user (optional)
sqlplus sys/<password>@<service_name> as sysdba

-- Drop user and tablespaces
DROP USER COMPRESSION_MGR CASCADE;
DROP TABLESPACE COMPRESSION_DATA INCLUDING CONTENTS AND DATAFILES;
DROP TABLESPACE SCRATCH_TS INCLUDING CONTENTS AND DATAFILES;
```

```bash
# Remove Python installation
cd /path/to/HCC-CompAdvisor/python
deactivate  # Exit virtual environment
cd ..
rm -rf python/venv
rm -rf python/logs
rm -rf python/.streamlit
```

---

## Next Steps

After successful installation:

1. Read the [User Guide](USER_GUIDE.md) to learn how to use the system
2. Review [Strategy Guide](STRATEGY_GUIDE.md) to understand compression strategies
3. Explore [API Reference](API_REFERENCE.md) for REST API integration
4. Configure automated analysis schedules
5. Customize compression strategies for your workload

For questions or issues, please refer to the troubleshooting section or consult the project documentation.
