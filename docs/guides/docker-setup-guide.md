# Docker Environment Setup Guide

Complete guide for setting up Oracle 23c Free with HCC Compression Advisor using Docker.

## Overview

This Docker environment provides:
- **Oracle Database 23c Free Edition** pre-configured
- **Automatic initialization** with compression advisor setup
- **Streamlit dashboard** for visualization (optional)
- **One-command startup** for development and testing
- **Persistent data** with Docker volumes
- **Complete isolation** from host system

## Quick Start

### 1. Prerequisites Check

Before starting, ensure you have:

```bash
# Docker Desktop or Docker Engine (v20.10+)
docker --version

# Docker Compose (v2.0+)
docker-compose --version

# Minimum 8GB RAM allocated to Docker
# Minimum 50GB disk space
df -h

# Oracle Container Registry account (free)
# Sign up at: https://container-registry.oracle.com
```

### 2. Login to Oracle Container Registry

```bash
# Login with your Oracle account
docker login container-registry.oracle.com

# Accept Terms & Restrictions for Oracle Database images
# Visit: https://container-registry.oracle.com/ords/ocr/ba/database/free
```

### 3. Run Quick Start Script

```bash
cd docker

# Run automated setup
./quick-start.sh
```

The script will:
1. Check all prerequisites
2. Create `.env` file from template
3. Set up required directories
4. Pull Oracle Database image
5. Build custom image with compression advisor
6. Start all services
7. Wait for database initialization
8. Display connection information

### 4. Manual Setup (Alternative)

If you prefer manual control:

```bash
cd docker

# 1. Configure environment
cp .env.example .env
nano .env  # Edit passwords and settings

# 2. Create directories
mkdir -p data logs custom-scripts
chmod -R 777 data logs

# 3. Start services
docker-compose up -d --build

# 4. Monitor initialization
docker-compose logs -f oracle-db
```

## Architecture

### Container Services

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Host                          │
│                                                         │
│  ┌───────────────────────────────────────────────┐     │
│  │         Oracle 23c Free Container             │     │
│  │  ┌─────────────────────────────────────────┐  │     │
│  │  │  Oracle Database FREE                   │  │     │
│  │  │  - CDB: FREE                            │  │     │
│  │  │  - PDB: FREEPDB1                        │  │     │
│  │  │  - User: COMPRESSION_MGR                │  │     │
│  │  │  - Tablespace: SCRATCH_TS (10GB)        │  │     │
│  │  └─────────────────────────────────────────┘  │     │
│  │                                                │     │
│  │  Ports: 1521, 5500, 8080                      │     │
│  │  Volumes: oracle-data, logs                   │     │
│  └───────────────────────────────────────────────┘     │
│                                                         │
│  ┌───────────────────────────────────────────────┐     │
│  │      Streamlit Dashboard Container            │     │
│  │  ┌─────────────────────────────────────────┐  │     │
│  │  │  Python 3.11 + Streamlit                │  │     │
│  │  │  - Dashboard UI                         │  │     │
│  │  │  - Connected to Oracle DB               │  │     │
│  │  └─────────────────────────────────────────┘  │     │
│  │                                                │     │
│  │  Port: 8501                                    │     │
│  │  Depends on: oracle-db                        │     │
│  └───────────────────────────────────────────────┘     │
│                                                         │
│  Network: hcc-network (172.28.0.0/16)                  │
└─────────────────────────────────────────────────────────┘
```

### Directory Structure

```
docker/
├── Dockerfile                      # Oracle image with HCC advisor
├── docker-compose.yml              # Service orchestration
├── .env.example                   # Configuration template
├── .env                           # Active configuration (gitignored)
├── .gitignore                     # Git ignore rules
├── README.md                      # Complete documentation
├── quick-start.sh                 # Automated setup script
│
├── init-scripts/                  # Database initialization
│   ├── 01-create-user.sql        # Create COMPRESSION_MGR user
│   ├── 02-grant-privileges.sql   # Grant required privileges
│   ├── 03-create-tablespace.sql  # Create SCRATCH_TS tablespace
│   └── 04-run-installation.sh    # Main installation script
│
├── custom-scripts/                # User SQL scripts (optional)
│   └── *.sql                     # Custom initialization scripts
│
├── data/                          # Persistent database files
│   └── FREE/FREEPDB1/            # Oracle datafiles (auto-created)
│       ├── system01.dbf
│       ├── sysaux01.dbf
│       ├── users01.dbf
│       └── scratch01.dbf
│
└── logs/                          # Application logs
    └── hcc_installation_*.log    # Installation logs
```

## Initialization Process

### Startup Sequence

When you run `docker-compose up -d`, the following happens:

1. **Image Build** (first time only, ~5-10 minutes):
   ```
   - Pull Oracle 23c Free base image (~2GB)
   - Install system packages (vim, wget, etc.)
   - Copy initialization scripts
   - Configure permissions
   - Build custom image
   ```

2. **Container Creation**:
   ```
   - Create containers for Oracle and Streamlit
   - Set up networking (hcc-network)
   - Mount volumes (data, logs, scripts)
   - Apply resource limits
   ```

3. **Database Creation** (first time only, ~5-10 minutes):
   ```
   - Oracle starts automatic database creation
   - Creates CDB (FREE) and PDB (FREEPDB1)
   - Configures SGA/PGA from environment
   - Opens database for connections
   ```

4. **Initialization Scripts** (automatic):
   ```
   - Scripts in /opt/oracle/scripts/startup run automatically
   - 01-create-user.sql: Creates COMPRESSION_MGR user
   - 02-grant-privileges.sql: Grants required privileges
   - 03-create-tablespace.sql: Creates SCRATCH_TS tablespace
   - 04-run-installation.sh: Runs HCC advisor installation
   ```

5. **Service Ready**:
   ```
   - Database listener starts on port 1521
   - EM Express available on port 5500
   - ORDS available on port 8080
   - Streamlit dashboard on port 8501
   - Health check reports "healthy"
   ```

### Health Check Monitoring

```bash
# Check health status
docker inspect hcc-oracle-23c | grep -A 10 Health

# Watch health status change
watch -n 5 'docker inspect hcc-oracle-23c | grep -A 10 Health'

# View initialization progress
docker-compose logs -f oracle-db | grep -i "database is ready"
```

## Configuration Details

### Environment Variables (.env)

The `.env` file controls all configuration. Key variables:

#### Database Authentication
```bash
ORACLE_PWD=Welcome123          # SYS/SYSTEM password
COMPRESSION_PWD=Compress123    # Application user password
ORDS_PWD=Welcome123            # ORDS password
```

#### Performance Tuning
```bash
INIT_SGA_SIZE=2048            # System Global Area (MB)
INIT_PGA_SIZE=1024            # Program Global Area (MB)
SHARED_POOL_SIZE=512          # Shared pool (MB)
DB_CACHE_SIZE=1024            # Buffer cache (MB)
PROCESSES=300                 # Max connections
SESSIONS=400                  # Max sessions
```

#### Storage Configuration
```bash
COMPRESSION_TS=SCRATCH_TS     # Tablespace name
SCRATCH_TS_SIZE=10240         # Size in MB (10GB)
SCRATCH_TS_DATAFILE=/opt/oracle/oradata/FREE/scratch01.dbf
```

#### Feature Flags
```bash
ENABLE_ARCHIVELOG=false       # Archive log mode
ENABLE_FORCE_LOGGING=false    # Force logging
ENABLE_SAMPLE_SCHEMAS=false   # HR, OE, PM, IX, SH, BI
ENABLE_ORACLE_TEXT=true       # Full-text search
```

### Docker Compose Configuration

#### Resource Limits

```yaml
deploy:
  resources:
    limits:
      cpus: '4'           # Maximum CPU cores
      memory: 8G          # Maximum RAM
    reservations:
      cpus: '2'           # Reserved CPU cores
      memory: 4G          # Reserved RAM
```

#### Volume Mounts

```yaml
volumes:
  # Persistent database files
  - oracle-data:/opt/oracle/oradata

  # Auto-run initialization scripts
  - ./init-scripts:/opt/oracle/scripts/startup

  # Compression advisor installation
  - ../install:/opt/oracle/compression_advisor/install:ro

  # Diagnostic logs
  - ./logs:/opt/oracle/oradata/logs

  # Custom SQL scripts
  - ./custom-scripts:/opt/oracle/scripts/custom:ro
```

#### Port Mappings

```yaml
ports:
  - "1521:1521"   # Oracle TNS Listener
  - "5500:5500"   # Enterprise Manager Express
  - "8080:8080"   # ORDS (Oracle REST Data Services)
  - "8501:8501"   # Streamlit Dashboard
```

## Usage Examples

### Connecting to Database

#### SQL*Plus (from host)

```bash
# Install Oracle Instant Client first
# https://www.oracle.com/database/technologies/instant-client.html

sqlplus COMPRESSION_MGR/Compress123@localhost:1521/FREEPDB1
```

#### SQL*Plus (from container)

```bash
docker-compose exec oracle-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1

# Or as SYS
docker-compose exec oracle-db sqlplus sys/Welcome123@FREEPDB1 as sysdba
```

#### SQL Developer / DBeaver

```
Connection Type: Oracle
Host: localhost
Port: 1521
Service Name: FREEPDB1
Username: COMPRESSION_MGR
Password: Compress123
```

#### Python with cx_Oracle

```python
import cx_Oracle

# Create connection
connection = cx_Oracle.connect(
    user="COMPRESSION_MGR",
    password="Compress123",
    dsn="localhost:1521/FREEPDB1"
)

# Create cursor
cursor = connection.cursor()

# Execute query
cursor.execute("SELECT table_name FROM user_tables")
for row in cursor:
    print(row)

# Close
cursor.close()
connection.close()
```

#### JDBC Connection String

```java
String url = "jdbc:oracle:thin:@localhost:1521/FREEPDB1";
String user = "COMPRESSION_MGR";
String password = "Compress123";

Connection conn = DriverManager.getConnection(url, user, password);
```

### Running SQL Scripts

#### From Host

```bash
# Copy script to container
docker cp my-script.sql hcc-oracle-23c:/tmp/

# Execute script
docker-compose exec oracle-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1 @/tmp/my-script.sql
```

#### From Container

```bash
# Place script in custom-scripts directory
cp my-script.sql docker/custom-scripts/

# Execute from container
docker-compose exec oracle-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1 @/opt/oracle/scripts/custom/my-script.sql
```

### Database Operations

#### Start/Stop Services

```bash
# Stop all services (data persists)
docker-compose stop

# Start services
docker-compose start

# Restart specific service
docker-compose restart oracle-db

# Stop and remove containers (data persists in volumes)
docker-compose down

# Stop and remove everything including volumes (⚠️ DATA LOSS!)
docker-compose down -v
```

#### View Logs

```bash
# All services
docker-compose logs -f

# Oracle only
docker-compose logs -f oracle-db

# Streamlit only
docker-compose logs -f streamlit-dashboard

# Last 100 lines
docker-compose logs --tail=100 oracle-db

# Since specific time
docker-compose logs --since 2025-01-13T10:00:00 oracle-db
```

#### Database Maintenance

```bash
# Shell access
docker-compose exec oracle-db bash

# Gather statistics
docker-compose exec oracle-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1 <<EOF
exec DBMS_STATS.GATHER_SCHEMA_STATS('COMPRESSION_MGR');
exit;
EOF

# Check database status
docker-compose exec oracle-db /opt/oracle/checkDBStatus.sh

# Restart database
docker-compose exec oracle-db sqlplus sys/Welcome123@FREE as sysdba <<EOF
shutdown immediate;
startup;
exit;
EOF
```

### Backup and Restore

#### Volume Backup

```bash
# Stop database
docker-compose stop oracle-db

# Backup data directory
tar -czf oracle-backup-$(date +%Y%m%d).tar.gz data/

# Restart database
docker-compose start oracle-db
```

#### DataPump Export

```bash
# Export schema
docker-compose exec oracle-db expdp COMPRESSION_MGR/Compress123@FREEPDB1 \
  directory=COMPRESSION_DIR \
  dumpfile=schema_backup.dmp \
  logfile=schema_backup.log \
  schemas=COMPRESSION_MGR

# Copy export file from container
docker cp hcc-oracle-23c:/opt/oracle/compression_advisor/schema_backup.dmp .
```

#### DataPump Import

```bash
# Copy dump file to container
docker cp schema_backup.dmp hcc-oracle-23c:/opt/oracle/compression_advisor/

# Import schema
docker-compose exec oracle-db impdp COMPRESSION_MGR/Compress123@FREEPDB1 \
  directory=COMPRESSION_DIR \
  dumpfile=schema_backup.dmp \
  logfile=schema_import.log \
  schemas=COMPRESSION_MGR
```

## Troubleshooting

### Common Issues

#### 1. Container Won't Start

**Symptoms**:
- `docker-compose up` fails
- Container exits immediately
- Health check never becomes healthy

**Solutions**:

```bash
# Check Docker resources
docker info | grep -A 5 "Resources"

# Increase Docker memory (Docker Desktop)
# Settings -> Resources -> Memory -> 8GB+

# Check logs for errors
docker-compose logs oracle-db | grep -i error

# Remove and rebuild
docker-compose down -v
docker-compose up -d --build
```

#### 2. Database Not Responding

**Symptoms**:
- `ORA-12541: TNS:no listener`
- Connection timeouts
- Health check fails

**Solutions**:

```bash
# Check listener status
docker-compose exec oracle-db lsnrctl status

# Verify PDB is open
docker-compose exec oracle-db sqlplus sys/Welcome123@FREE as sysdba <<EOF
show pdbs;
alter pluggable database FREEPDB1 open;
exit;
EOF

# Restart listener
docker-compose exec oracle-db lsnrctl stop
docker-compose exec oracle-db lsnrctl start
```

#### 3. Installation Script Failed

**Symptoms**:
- `COMPRESSION_MGR` user doesn't exist
- `SCRATCH_TS` tablespace missing
- Missing privileges

**Solutions**:

```bash
# Check installation log
docker-compose exec oracle-db cat /opt/oracle/oradata/logs/hcc_installation_*.log

# Manually re-run scripts
docker-compose exec oracle-db bash
cd /opt/oracle/scripts/setup

sqlplus sys/Welcome123@FREE as sysdba @01-create-user.sql
sqlplus sys/Welcome123@FREE as sysdba @02-grant-privileges.sql
sqlplus sys/Welcome123@FREE as sysdba @03-create-tablespace.sql
./04-run-installation.sh
```

#### 4. Out of Disk Space

**Symptoms**:
- `ORA-01114: IO error writing block`
- `ENOSPC: no space left on device`
- Slow performance

**Solutions**:

```bash
# Check Docker disk usage
docker system df

# Check data volume size
du -sh docker/data/

# Clean up Docker
docker system prune -a --volumes

# Shrink tablespace
docker-compose exec oracle-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1 <<EOF
ALTER DATABASE DATAFILE '/opt/oracle/oradata/FREE/FREEPDB1/scratch02.dbf' RESIZE 512M;
exit;
EOF
```

#### 5. Performance Issues

**Symptoms**:
- Slow queries
- High CPU usage
- Database hangs

**Solutions**:

```bash
# Check container resources
docker stats hcc-oracle-23c

# Increase SGA/PGA (edit .env)
INIT_SGA_SIZE=4096
INIT_PGA_SIZE=2048

# Restart with new settings
docker-compose down
docker-compose up -d

# Gather statistics
docker-compose exec oracle-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1 <<EOF
exec DBMS_STATS.GATHER_SCHEMA_STATS('COMPRESSION_MGR', cascade=>TRUE);
exit;
EOF

# Check execution plans
docker-compose exec oracle-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1 <<EOF
SET AUTOTRACE ON EXPLAIN
SELECT * FROM my_table WHERE column = 'value';
exit;
EOF
```

## Important Limitations

### Oracle 23c Free Edition

**Resource Limits**:
- Maximum 2 CPUs
- Maximum 2GB RAM (database process)
- Maximum 12GB user data
- Single instance only (no RAC)

**Feature Restrictions**:
- ❌ **NO HCC (Hybrid Columnar Compression)** - Primary limitation
- ❌ No Database Vault
- ❌ No Label Security
- ❌ No Advanced Security Option
- ❌ No Active Data Guard
- ❌ No Multitenant (single PDB only)
- ✅ Standard compression (BASIC, OLTP) works
- ✅ Query compression available
- ✅ Archive compression available

**License**:
- Free for development, testing, prototyping
- Free for educational use
- **NOT licensed for production use**
- For production, use Oracle Enterprise Edition

### HCC Compression Advisor

**What Works**:
- ✅ Compression ratio estimation
- ✅ Standard compression testing (BASIC, OLTP)
- ✅ Query compression (LOW, HIGH)
- ✅ Archive compression simulation
- ✅ Space savings calculations
- ✅ Recommendations and reporting

**What Doesn't Work**:
- ❌ Actual HCC compression (requires Exadata)
- ❌ Real HCC performance benchmarks
- ❌ HCC storage efficiency testing

**For Actual HCC**:
- Requires Oracle Exadata Database Machine
- Requires ZFS Storage Appliance
- Requires Oracle Database Enterprise Edition
- Requires Advanced Compression license

## Advanced Topics

### Custom Tablespaces

```sql
-- Connect as SYS
sqlplus sys/Welcome123@FREEPDB1 as sysdba

-- Create custom tablespace
CREATE TABLESPACE my_data
  DATAFILE '/opt/oracle/oradata/FREE/FREEPDB1/my_data01.dbf'
  SIZE 1G
  AUTOEXTEND ON NEXT 256M MAXSIZE 5G
  EXTENT MANAGEMENT LOCAL
  SEGMENT SPACE MANAGEMENT AUTO;

-- Grant quota to user
ALTER USER COMPRESSION_MGR QUOTA UNLIMITED ON my_data;
```

### Archive Log Mode

```sql
-- Enable archive log mode
sqlplus sys/Welcome123@FREE as sysdba

SHUTDOWN IMMEDIATE;
STARTUP MOUNT;
ALTER DATABASE ARCHIVELOG;
ALTER DATABASE OPEN;

-- Verify
ARCHIVE LOG LIST;
```

### Performance Tuning

```sql
-- Increase SGA dynamically
ALTER SYSTEM SET sga_target=4G SCOPE=BOTH;

-- Increase PGA
ALTER SYSTEM SET pga_aggregate_target=2G SCOPE=BOTH;

-- Enable parallel execution
ALTER SYSTEM SET parallel_max_servers=8;

-- Optimize for OLTP
ALTER SYSTEM SET optimizer_mode=ALL_ROWS;
```

### ORDS Configuration

ORDS (Oracle REST Data Services) setup requires manual configuration:

```bash
# Access container
docker-compose exec oracle-db bash

# Install ORDS (if not already installed)
cd /opt/oracle

# Follow Oracle documentation
# https://docs.oracle.com/en/database/oracle/oracle-rest-data-services/
```

## Next Steps

After successful Docker setup:

1. **Test Connection**: Verify database connectivity
2. **Load Sample Data**: Test compression on sample tables
3. **Run Compression Analysis**: Use HCC advisor tools
4. **Explore Dashboard**: View Streamlit UI at http://localhost:8501
5. **Read Documentation**: Review `docs/`

## Additional Resources

### Documentation
- [Docker README](../docker/README.md)
- [Oracle 23c Documentation](https://docs.oracle.com/en/database/oracle/oracle-database/23/)
- [Docker Images Guide](https://github.com/oracle/docker-images/tree/main/OracleDatabase)
- [Compression Guide](https://docs.oracle.com/en/database/oracle/oracle-database/23/admin/managing-compression.html)

### Support
- **Oracle Community**: https://community.oracle.com/
- **Docker Issues**: https://github.com/oracle/docker-images/issues
- **Stack Overflow**: https://stackoverflow.com/questions/tagged/oracle

---

**Version**: 1.0.0
**Last Updated**: 2025-01-13
**Maintainer**: HCC Compression Advisor Team
