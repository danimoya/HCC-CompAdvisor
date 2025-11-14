# HCC Compression Advisor - Docker Environment

Complete Docker environment for Oracle 23c Free with HCC Compression Advisor pre-configured for development and testing.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Port Mappings](#port-mappings)
- [Default Credentials](#default-credentials)
- [Directory Structure](#directory-structure)
- [Usage Examples](#usage-examples)
- [Troubleshooting](#troubleshooting)
- [Known Limitations](#known-limitations)
- [Advanced Configuration](#advanced-configuration)
- [Cleanup](#cleanup)

## Prerequisites

### Required Software

1. **Docker Desktop** or **Docker Engine** (v20.10+)
   - Download: https://www.docker.com/products/docker-desktop
   - Minimum 8GB RAM allocated to Docker
   - Minimum 50GB disk space

2. **Docker Compose** (v2.0+)
   - Usually included with Docker Desktop
   - Verify: `docker-compose --version`

3. **Oracle Container Registry Account**
   - Sign up: https://container-registry.oracle.com
   - Accept Oracle Standard Terms and Restrictions for Database Images

### System Requirements

- **CPU**: 4+ cores recommended
- **RAM**: 8GB minimum, 16GB recommended
- **Disk**: 50GB free space minimum
- **OS**: Linux, macOS, or Windows 10/11 with WSL2

### Optional Tools

- **SQL Developer**: https://www.oracle.com/database/sqldeveloper/
- **DBeaver**: https://dbeaver.io/
- **Oracle Instant Client**: https://www.oracle.com/database/technologies/instant-client.html

## Quick Start

### 1. Clone Repository

```bash
cd /home/claude/Oracle-Database-Related/HCC-CompAdvisor
```

### 2. Login to Oracle Container Registry

```bash
docker login container-registry.oracle.com
# Username: Your Oracle account email
# Password: Your Oracle account password
```

### 3. Configure Environment

```bash
cd docker
cp .env.example .env

# Edit .env with your preferred passwords and settings
nano .env  # or vim, code, etc.
```

### 4. Create Data Directory

```bash
mkdir -p data logs custom-scripts
chmod -R 777 data logs  # Ensure Oracle user can write
```

### 5. Start Services

```bash
# Build and start all services
docker-compose up -d

# View logs
docker-compose logs -f oracle-db
```

### 6. Wait for Database Initialization

First startup takes 5-10 minutes for database creation and initialization.

```bash
# Check database status
docker-compose exec oracle-db /opt/oracle/checkDBStatus.sh

# Watch initialization logs
docker-compose logs -f oracle-db | grep -i "database is ready"
```

### 7. Connect to Database

```bash
# Using Docker exec
docker-compose exec oracle-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1

# Using SQL*Plus from host (if installed)
sqlplus COMPRESSION_MGR/Compress123@localhost:1521/FREEPDB1
```

### 8. Access Streamlit Dashboard (Optional)

```bash
# Open browser to http://localhost:8501
# Default password: Dashboard123 (configured in .env)
```

## Configuration

### Environment Variables (.env)

Key configuration options:

```bash
# Database Passwords
ORACLE_PWD=Welcome123              # SYS/SYSTEM password
COMPRESSION_PWD=Compress123        # Application user password

# Performance Tuning
INIT_SGA_SIZE=2048                 # SGA size in MB
INIT_PGA_SIZE=1024                 # PGA size in MB

# Tablespace Configuration
SCRATCH_TS_SIZE=10240              # Scratch tablespace size in MB

# Dashboard
STREAMLIT_PASSWORD=Dashboard123    # Dashboard access password
```

### Custom SQL Scripts

Place custom initialization scripts in `custom-scripts/`:

```bash
docker/
└── custom-scripts/
    ├── 10-custom-tables.sql
    ├── 20-sample-data.sql
    └── 30-custom-procedures.sql
```

Scripts are executed alphabetically after main installation.

## Port Mappings

| Service | Internal Port | External Port | Description |
|---------|--------------|---------------|-------------|
| Oracle Database | 1521 | 1521 | TNS Listener |
| Enterprise Manager | 5500 | 5500 | EM Express Web UI |
| ORDS | 8080 | 8080 | REST Data Services |
| Streamlit | 8501 | 8501 | Dashboard UI |

### Accessing Services

1. **Database Connection**:
   ```bash
   # Host: localhost
   # Port: 1521
   # Service: FREEPDB1
   # User: COMPRESSION_MGR
   # Password: Compress123
   ```

2. **Enterprise Manager Express**:
   ```
   https://localhost:5500/em
   User: SYS as SYSDBA
   Password: Welcome123
   ```

3. **Streamlit Dashboard**:
   ```
   http://localhost:8501
   Password: Dashboard123
   ```

## Default Credentials

### Database Accounts

| Account | Password | Description |
|---------|----------|-------------|
| SYS | Welcome123 | Database administrator |
| SYSTEM | Welcome123 | System administrator |
| COMPRESSION_MGR | Compress123 | Application user |

### Service Accounts

| Service | Username | Password |
|---------|----------|----------|
| ORDS | ORDS_PUBLIC_USER | Welcome123 |
| Streamlit | N/A | Dashboard123 |

**⚠️ Security Warning**: Change all default passwords in production environments!

## Directory Structure

```
docker/
├── Dockerfile                 # Oracle Database image definition
├── docker-compose.yml         # Service orchestration
├── .env                       # Environment configuration (gitignored)
├── .env.example              # Environment template
├── README.md                 # This file
│
├── init-scripts/             # Database initialization
│   ├── 01-create-user.sql
│   ├── 02-grant-privileges.sql
│   ├── 03-create-tablespace.sql
│   └── 04-run-installation.sh
│
├── custom-scripts/           # User-defined SQL scripts
│   └── (your custom .sql files)
│
├── data/                     # Persistent database files
│   └── FREE/
│       └── FREEPDB1/
│
└── logs/                     # Application and database logs
    └── hcc_installation_*.log
```

## Usage Examples

### Connect with SQL*Plus

```bash
# From within container
docker-compose exec oracle-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1

# From host (if SQL*Plus installed)
sqlplus COMPRESSION_MGR/Compress123@localhost:1521/FREEPDB1
```

### Execute SQL Script

```bash
# Copy script into container
docker cp my-script.sql hcc-oracle-23c:/tmp/

# Execute script
docker-compose exec oracle-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1 @/tmp/my-script.sql
```

### View Logs

```bash
# All services
docker-compose logs -f

# Oracle Database only
docker-compose logs -f oracle-db

# Last 100 lines
docker-compose logs --tail=100 oracle-db

# Installation log
docker-compose exec oracle-db cat /opt/oracle/oradata/logs/hcc_installation_*.log
```

### Database Operations

```bash
# Stop database (data persists)
docker-compose stop

# Start database
docker-compose start

# Restart database
docker-compose restart oracle-db

# Rebuild and restart
docker-compose up -d --build

# Remove everything (including data)
docker-compose down -v
```

### Backup Database

```bash
# Export data directory
docker-compose stop oracle-db
tar -czf oracle-backup-$(date +%Y%m%d).tar.gz data/
docker-compose start oracle-db

# Export using DataPump
docker-compose exec oracle-db expdp COMPRESSION_MGR/Compress123@FREEPDB1 \
  directory=COMPRESSION_DIR \
  dumpfile=backup.dmp \
  logfile=backup.log \
  full=y
```

### Restore Database

```bash
# Restore data directory
docker-compose down
tar -xzf oracle-backup-20250113.tar.gz
docker-compose up -d

# Import using DataPump
docker-compose exec oracle-db impdp COMPRESSION_MGR/Compress123@FREEPDB1 \
  directory=COMPRESSION_DIR \
  dumpfile=backup.dmp \
  logfile=restore.log \
  full=y
```

## Troubleshooting

### Database Not Starting

**Symptom**: Container starts but database doesn't respond

**Solutions**:
```bash
# 1. Check logs
docker-compose logs oracle-db | grep -i error

# 2. Verify health status
docker inspect hcc-oracle-23c | grep -A 10 Health

# 3. Increase Docker resources
# Docker Desktop -> Settings -> Resources -> Increase RAM to 8GB

# 4. Check disk space
df -h
docker system df

# 5. Clean up Docker
docker system prune -a --volumes
```

### Connection Refused

**Symptom**: `ORA-12541: TNS:no listener`

**Solutions**:
```bash
# 1. Verify listener is running
docker-compose exec oracle-db lsnrctl status

# 2. Check if PDB is open
docker-compose exec oracle-db sqlplus sys/Welcome123@FREE as sysdba
SQL> show pdbs;
SQL> alter pluggable database FREEPDB1 open;

# 3. Restart listener
docker-compose exec oracle-db lsnrctl stop
docker-compose exec oracle-db lsnrctl start
```

### Out of Memory

**Symptom**: `ORA-04031: unable to allocate shared memory`

**Solutions**:
```bash
# 1. Reduce SGA/PGA in .env
INIT_SGA_SIZE=1024
INIT_PGA_SIZE=512

# 2. Increase Docker memory limit
# Edit docker-compose.yml -> deploy.resources.limits.memory

# 3. Restart services
docker-compose down
docker-compose up -d
```

### Slow Performance

**Symptom**: Queries taking too long

**Solutions**:
```bash
# 1. Enable statistics gathering
docker-compose exec oracle-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1
SQL> exec DBMS_STATS.GATHER_SCHEMA_STATS('COMPRESSION_MGR');

# 2. Check system resources
docker stats hcc-oracle-23c

# 3. Increase shared pool
# Edit .env: SHARED_POOL_SIZE=1024

# 4. Optimize queries
SQL> SET AUTOTRACE ON EXPLAIN
SQL> [your query]
```

### Installation Failed

**Symptom**: Installation script errors

**Solutions**:
```bash
# 1. Check installation log
docker-compose exec oracle-db cat /opt/oracle/oradata/logs/hcc_installation_*.log

# 2. Manually run scripts
docker-compose exec oracle-db bash
cd /opt/oracle/scripts/setup
sqlplus sys/Welcome123@FREE as sysdba @01-create-user.sql

# 3. Re-run installation
docker-compose exec oracle-db bash /opt/oracle/scripts/setup/04-run-installation.sh

# 4. Complete rebuild
docker-compose down -v
docker-compose up -d
```

### Permission Denied

**Symptom**: Cannot write to volumes

**Solutions**:
```bash
# Fix volume permissions
sudo chown -R 54321:54321 data logs  # Oracle UID:GID
chmod -R 755 data logs

# Or run with proper user
docker-compose run --user 54321:54321 oracle-db
```

## Known Limitations

### Oracle 23c Free Edition Restrictions

1. **No HCC Support**:
   - Oracle 23c Free does NOT include Hybrid Columnar Compression
   - HCC requires Oracle Exadata or ZFS Storage Appliance
   - This environment provides **simulation and demonstration** only
   - For production HCC, use Oracle Enterprise Edition with Exadata

2. **Resource Limits**:
   - Maximum 2 CPUs
   - Maximum 2GB RAM
   - Maximum 12GB user data
   - Single instance only (no RAC)

3. **Feature Restrictions**:
   - No Database Vault
   - No Label Security
   - No Advanced Compression (HCC)
   - No Multitenant (single PDB only)
   - No Advanced Security Option
   - No Active Data Guard

4. **License**:
   - Free for development, testing, and prototyping
   - NOT licensed for production use
   - See Oracle Technology Network License Agreement

### Docker-Specific Limitations

1. **Performance**:
   - Docker adds ~5-10% overhead
   - Use native installation for production
   - Consider Oracle Cloud for cloud deployments

2. **Networking**:
   - Port conflicts with existing Oracle installations
   - Docker networking may impact performance
   - Use host networking for better performance (Linux only)

3. **Persistence**:
   - Data persists in volumes
   - Volumes tied to Docker installation
   - Regular backups recommended

### Compression Advisor Limitations

1. **Simulation Mode**:
   - HCC compression ratios are **estimated**
   - Actual HCC requires Oracle Exadata
   - Use for planning and education only

2. **Testing**:
   - Standard compression methods work (BASIC, OLTP)
   - Query Low/High compression available
   - Archive Low/High compression simulated

3. **Recommendations**:
   - Use for compression strategy planning
   - Test Standard compression methods
   - For actual HCC testing, use Oracle Cloud with Exadata

## Advanced Configuration

### Enable Archive Log Mode

```bash
# Edit .env
ENABLE_ARCHIVELOG=true

# Restart database
docker-compose restart oracle-db
```

### Configure Custom Tablespace

```sql
-- Connect as SYS
sqlplus sys/Welcome123@FREEPDB1 as sysdba

-- Create tablespace
CREATE TABLESPACE my_data
  DATAFILE '/opt/oracle/oradata/FREE/FREEPDB1/my_data01.dbf'
  SIZE 1G AUTOEXTEND ON NEXT 256M MAXSIZE 10G;

-- Grant quota
ALTER USER COMPRESSION_MGR QUOTA UNLIMITED ON my_data;
```

### Enable Sample Schemas

```bash
# Edit .env
ENABLE_SAMPLE_SCHEMAS=true

# Rebuild
docker-compose down
docker-compose up -d --build
```

### Configure ORDS

```bash
# Install ORDS in container
docker-compose exec oracle-db bash

# Follow Oracle documentation for ORDS configuration
# https://docs.oracle.com/en/database/oracle/oracle-rest-data-services/
```

### Performance Tuning

```sql
-- Connect as SYS
sqlplus sys/Welcome123@FREEPDB1 as sysdba

-- Increase SGA
ALTER SYSTEM SET sga_target=4G SCOPE=SPFILE;

-- Increase PGA
ALTER SYSTEM SET pga_aggregate_target=2G SCOPE=SPFILE;

-- Enable parallel execution
ALTER SYSTEM SET parallel_max_servers=8;

-- Restart database
SHUTDOWN IMMEDIATE;
STARTUP;
```

## Cleanup

### Remove Containers Only (Keep Data)

```bash
docker-compose down
```

### Remove Everything (Including Data)

```bash
# ⚠️ WARNING: This deletes all database data!
docker-compose down -v
rm -rf data logs

# Remove images
docker rmi hcc-oracle-23c
docker rmi container-registry.oracle.com/database/free:latest
```

### Clean Up Docker System

```bash
# Remove unused images, containers, networks
docker system prune -a

# Remove unused volumes
docker volume prune

# Check disk usage
docker system df
```

## Support and Documentation

### Official Documentation

- **Oracle 23c Free**: https://docs.oracle.com/en/database/oracle/oracle-database/23/
- **Docker Guide**: https://github.com/oracle/docker-images/tree/main/OracleDatabase
- **ORDS**: https://docs.oracle.com/en/database/oracle/oracle-rest-data-services/

### HCC Compression Resources

- **Compression Advisor Guide**: https://docs.oracle.com/en/database/oracle/oracle-database/23/admin/managing-compression.html
- **HCC Overview**: https://www.oracle.com/database/advanced-compression/
- **Exadata Documentation**: https://docs.oracle.com/en/engineered-systems/exadata/

### Community Support

- **Oracle Community**: https://community.oracle.com/
- **Stack Overflow**: https://stackoverflow.com/questions/tagged/oracle
- **GitHub Issues**: https://github.com/oracle/docker-images/issues

---

**Last Updated**: 2025-01-13
**Version**: 1.0.0
**Maintainer**: HCC Compression Advisor Team
