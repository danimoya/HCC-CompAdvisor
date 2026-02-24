# HCC Compression Advisor - Docker Environment

Complete Docker environment for centralized multi-database management. A central Oracle 23c Free instance stores analysis results, metadata, and compression recommendations gathered from all registered target databases.

## Table of Contents

- [Architecture](#architecture)
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

## Architecture

```
+------------------------------------------------------+
|                    Docker Stack                       |
|                                                       |
|  +------------------+      +---------------------+   |
|  | Central Oracle   |      | Streamlit Dashboard |   |
|  | 23c Free DB      |<---->| (hcc-streamlit)     |   |
|  | (hcc-central-db) |      |                     |   |
|  |                  |      |  Connects to central |   |
|  | Stores:          |      |  DB + remote targets |   |
|  | - Analysis runs  |      +--------|------------+   |
|  | - Recommendations|               |                |
|  | - Target DB info |               |                |
|  +------------------+               |                |
+--------------------------------------|---------------+
                                       |
                      +----------------+----------------+
                      |                |                |
               +------+------+  +------+------+  +-----+-------+
               | Remote      |  | Remote      |  | Remote      |
               | Target DB 1 |  | Target DB 2 |  | Target DB N |
               | (registered |  | (registered |  | (registered |
               |  via UI)    |  |  via UI)    |  |  via UI)    |
               +-------------+  +-------------+  +-------------+
```

The **Central Oracle 23c DB** runs locally in Docker and persists all analysis metadata.
**Remote Target Databases** are production or test Oracle instances registered through
the Streamlit dashboard. They are not part of the Docker stack.

## Prerequisites

### Required Software

1. **Docker Desktop** or **Docker Engine** (v20.10+)
   - Download: https://www.docker.com/products/docker-desktop
   - Minimum 8GB RAM allocated to Docker
   - Minimum 50GB disk space

2. **Docker Compose** (v2.0+)
   - Usually included with Docker Desktop
   - Verify: `docker compose version`

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

### 1. Navigate to Project

```bash
cd HCC-CompAdvisor
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
docker compose up -d

# View logs
docker compose logs -f central-db
```

### 6. Wait for Database Initialization

First startup takes 5-10 minutes for database creation and initialization.

```bash
# Check database status
docker compose exec central-db /opt/oracle/checkDBStatus.sh

# Watch initialization logs
docker compose logs -f central-db | grep -i "database is ready"
```

### 7. Connect to Database

```bash
# Using Docker exec
docker compose exec central-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1

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
# Central Database Passwords
CENTRAL_DB_PWD=Welcome123          # SYS/SYSTEM password for central DB
CENTRAL_DB_USER=COMPRESSION_MGR    # Application user
CENTRAL_DB_USER_PWD=Compress123    # Application user password

# Performance Tuning
INIT_SGA_SIZE=2048                 # SGA size in MB
INIT_PGA_SIZE=1024                 # PGA size in MB

# Tablespace Configuration
SCRATCH_TS_SIZE=10240              # Scratch tablespace size in MB

# Dashboard
STREAMLIT_PASSWORD=Dashboard123    # Dashboard access password

# Security
ENCRYPTION_KEY=<generate-a-key>   # Key for encrypting stored target DB credentials
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
| Central Oracle Database | 1521 | 1521 | TNS Listener |
| Enterprise Manager | 5500 | 5500 | EM Express Web UI |
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
| Streamlit | N/A | Dashboard123 |

**⚠️ Security Warning**: Change all default passwords in production environments!

## Directory Structure

```
docker/
├── Dockerfile                 # Central Oracle Database image definition
├── docker-compose.yml         # Centralized production orchestration
├── docker-compose.dev.yml     # Local development overrides
├── .env                       # Environment configuration (gitignored)
├── .env.example              # Environment template
├── README.md                 # This file
│
├── init-scripts-central/     # Central database initialization
│   ├── 01-create-user.sql
│   ├── 02-grant-privileges.sql
│   ├── 03-create-tablespace.sql
│   └── 04-run-installation.sh
│
├── ../sql/central/           # Central schema definitions (mounted)
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
docker compose exec central-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1

# From host (if SQL*Plus installed)
sqlplus COMPRESSION_MGR/Compress123@localhost:1521/FREEPDB1
```

### Execute SQL Script

```bash
# Copy script into container
docker cp my-script.sql hcc-central-db:/tmp/

# Execute script
docker compose exec central-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1 @/tmp/my-script.sql
```

### View Logs

```bash
# All services
docker compose logs -f

# Central Database only
docker compose logs -f central-db

# Last 100 lines
docker compose logs --tail=100 central-db

# Installation log
docker compose exec central-db cat /opt/oracle/oradata/logs/hcc_installation_*.log
```

### Database Operations

```bash
# Stop database (data persists)
docker compose stop

# Start database
docker compose start

# Restart database
docker compose restart central-db

# Rebuild and restart
docker compose up -d --build

# Remove everything (including data)
docker compose down -v
```

### Backup Database

```bash
# Export data directory
docker compose stop central-db
tar -czf oracle-backup-$(date +%Y%m%d).tar.gz data/
docker compose start central-db

# Export using DataPump
docker compose exec central-db expdp COMPRESSION_MGR/Compress123@FREEPDB1 \
  directory=COMPRESSION_DIR \
  dumpfile=backup.dmp \
  logfile=backup.log \
  full=y
```

### Restore Database

```bash
# Restore data directory
docker compose down
tar -xzf oracle-backup-20250113.tar.gz
docker compose up -d

# Import using DataPump
docker compose exec central-db impdp COMPRESSION_MGR/Compress123@FREEPDB1 \
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
docker compose logs central-db | grep -i error

# 2. Verify health status
docker inspect hcc-central-db | grep -A 10 Health

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
docker compose exec central-db lsnrctl status

# 2. Check if PDB is open
docker compose exec central-db sqlplus sys/Welcome123@FREE as sysdba
SQL> show pdbs;
SQL> alter pluggable database FREEPDB1 open;

# 3. Restart listener
docker compose exec central-db lsnrctl stop
docker compose exec central-db lsnrctl start
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
docker compose down
docker compose up -d
```

### Slow Performance

**Symptom**: Queries taking too long

**Solutions**:
```bash
# 1. Enable statistics gathering
docker compose exec central-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1
SQL> exec DBMS_STATS.GATHER_SCHEMA_STATS('COMPRESSION_MGR');

# 2. Check system resources
docker stats hcc-central-db

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
docker compose exec central-db cat /opt/oracle/oradata/logs/hcc_installation_*.log

# 2. Manually run scripts
docker compose exec central-db bash
cd /opt/oracle/scripts/setup
sqlplus sys/Welcome123@FREE as sysdba @01-create-user.sql

# 3. Re-run installation
docker compose exec central-db bash /opt/oracle/scripts/setup/04-run-installation.sh

# 4. Complete rebuild
docker compose down -v
docker compose up -d
```

### Permission Denied

**Symptom**: Cannot write to volumes

**Solutions**:
```bash
# Fix volume permissions
sudo chown -R 54321:54321 data logs  # Oracle UID:GID
chmod -R 755 data logs

# Or run with proper user
docker compose run --user 54321:54321 central-db
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

### Target Database Connectivity

1. **Remote Targets Only**:
   - Target Oracle databases are remote and are NOT included in this Docker stack
   - They are registered through the Streamlit dashboard UI
   - Network connectivity from the Docker host to each target database is required
   - Firewall rules must allow outbound connections on the target listener port (typically 1521)

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
docker compose restart central-db
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
docker compose down
docker compose up -d --build
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
docker compose down
```

### Remove Everything (Including Data)

```bash
# WARNING: This deletes all database data!
docker compose down -v
rm -rf data logs

# Remove images
docker rmi hcc-central-db
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

### HCC Compression Resources

- **Compression Advisor Guide**: https://docs.oracle.com/en/database/oracle/oracle-database/23/admin/managing-compression.html
- **HCC Overview**: https://www.oracle.com/database/advanced-compression/
- **Exadata Documentation**: https://docs.oracle.com/en/engineered-systems/exadata/

### Community Support

- **Oracle Community**: https://community.oracle.com/
- **Stack Overflow**: https://stackoverflow.com/questions/tagged/oracle
- **GitHub Issues**: https://github.com/oracle/docker-images/issues

---

**Last Updated**: 2026-02-24
**Version**: 2.0.0
**Maintainer**: HCC Compression Advisor Team
