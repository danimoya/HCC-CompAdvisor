#!/bin/bash
# ============================================================================
# Script: 04-run-installation.sh
# Description: Run complete HCC Compression Advisor CENTRAL database installation
# Author: Daniel Moya (copyright), GitHub: github.com/danimoya Website: danimoya.com
# Database: Oracle 23c Free Edition (Central Metadata Server)
#
# NOTE: This installs the CENTRAL database which stores metadata, analysis
# results, strategy definitions, and session data. This is NOT a target
# Oracle database where compression analysis is performed.
# ============================================================================

set -e  # Exit on error
set -u  # Exit on undefined variable

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Configuration
ORACLE_HOME=${ORACLE_HOME:-/opt/oracle/product/26ai/dbhomeFree}
ORACLE_SID=${ORACLE_SID:-FREE}
ORACLE_PWD=${ORACLE_PWD:-Welcome123}
COMPRESSION_USER=${COMPRESSION_USER:-COMPRESSION_MGR}
COMPRESSION_PWD=${COMPRESSION_PWD:-Compress123}
CENTRAL_SQL_DIR=${CENTRAL_SQL_DIR:-/opt/oracle/compression_advisor/sql/central}
LOG_FILE="/opt/oracle/oradata/logs/central_installation_$(date +%Y%m%d_%H%M%S).log"

# Create log directory if it doesn't exist
mkdir -p "$(dirname "$LOG_FILE")"

log_info "Starting HCC Compression Advisor CENTRAL Database Installation"
log_info "Log file: $LOG_FILE"

# Function to wait for database to be ready
wait_for_database() {
    log_info "Waiting for Oracle Database to be ready..."
    local max_attempts=60
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if ${ORACLE_HOME}/bin/sqlplus -s sys/${ORACLE_PWD}@localhost:1521/FREE as sysdba <<< "SELECT 'DB_READY' FROM dual;" 2>&1 | grep -q "DB_READY"; then
            log_success "Database is ready"
            return 0
        fi

        log_info "Attempt $attempt/$max_attempts - Database not ready yet, waiting..."
        sleep 10
        ((attempt++))
    done

    log_error "Database did not become ready in time"
    return 1
}

# Function to check if PDB is open
check_pdb_status() {
    log_info "Checking PDB status..."

    ${ORACLE_HOME}/bin/sqlplus -s sys/${ORACLE_PWD}@localhost:1521/FREE as sysdba <<EOF | tee -a "$LOG_FILE"
SET PAGESIZE 0 FEEDBACK OFF VERIFY OFF HEADING OFF
SELECT name, open_mode FROM v\$pdbs WHERE name = 'FREEPDB1';
EXIT;
EOF
}

# Function to open PDB if not already open
open_pdb() {
    log_info "Ensuring FREEPDB1 is open..."

    ${ORACLE_HOME}/bin/sqlplus -s sys/${ORACLE_PWD}@localhost:1521/FREE as sysdba <<EOF | tee -a "$LOG_FILE"
WHENEVER SQLERROR EXIT SQL.SQLCODE
ALTER PLUGGABLE DATABASE FREEPDB1 OPEN;
ALTER PLUGGABLE DATABASE FREEPDB1 SAVE STATE;
EXIT;
EOF

    if [ $? -eq 0 ]; then
        log_success "FREEPDB1 is now open"
    else
        log_warning "FREEPDB1 might already be open"
    fi
}

# Function to run SQL script as SYSDBA
run_sql_script() {
    local script_name=$1
    local script_path=$2

    log_info "Running $script_name..."

    if [ ! -f "$script_path" ]; then
        log_error "Script not found: $script_path"
        return 1
    fi

    ${ORACLE_HOME}/bin/sqlplus -s sys/${ORACLE_PWD}@localhost:1521/FREE as sysdba @"$script_path" 2>&1 | tee -a "$LOG_FILE"

    if [ ${PIPESTATUS[0]} -eq 0 ]; then
        log_success "$script_name completed successfully"
        return 0
    else
        log_error "$script_name failed"
        return 1
    fi
}

# Function to run SQL script as COMPRESSION_MGR user
run_sql_as_user() {
    local script_name=$1
    local script_path=$2

    log_info "Running $script_name as ${COMPRESSION_USER}..."

    if [ ! -f "$script_path" ]; then
        log_error "Script not found: $script_path"
        return 1
    fi

    ${ORACLE_HOME}/bin/sqlplus -s ${COMPRESSION_USER}/${COMPRESSION_PWD}@localhost:1521/FREEPDB1 <<EOF 2>&1 | tee -a "$LOG_FILE"
WHENEVER SQLERROR EXIT SQL.SQLCODE
SET ECHO ON
SET SERVEROUTPUT ON SIZE UNLIMITED
@${script_path}
EXIT;
EOF

    if [ ${PIPESTATUS[0]} -eq 0 ]; then
        log_success "$script_name completed successfully"
        return 0
    else
        log_error "$script_name failed"
        return 1
    fi
}

# Function to install central schema and seed data
install_central_schema() {
    log_info "Installing Central Database schema and seed data..."

    # Install central schema
    if [ -f "${CENTRAL_SQL_DIR}/01_central_schema.sql" ]; then
        run_sql_as_user "Central Schema" "${CENTRAL_SQL_DIR}/01_central_schema.sql" || return 1
    else
        log_warning "Central schema not found at ${CENTRAL_SQL_DIR}/01_central_schema.sql"
        log_warning "Skipping central schema installation"
    fi

    # Seed compression strategies
    if [ -f "${CENTRAL_SQL_DIR}/02_seed_strategies.sql" ]; then
        run_sql_as_user "Seed Strategies" "${CENTRAL_SQL_DIR}/02_seed_strategies.sql" || return 1
    else
        log_warning "Seed strategies not found at ${CENTRAL_SQL_DIR}/02_seed_strategies.sql"
        log_warning "Skipping strategy seed data"
    fi
}

# Function to verify installation
verify_installation() {
    log_info "Verifying Central Database installation..."

    ${ORACLE_HOME}/bin/sqlplus -s ${COMPRESSION_USER}/${COMPRESSION_PWD}@localhost:1521/FREEPDB1 <<EOF | tee -a "$LOG_FILE"
SET PAGESIZE 100 FEEDBACK ON VERIFY OFF HEADING ON
SET LINESIZE 200

PROMPT
PROMPT ========================================
PROMPT User Objects (Central DB)
PROMPT ========================================
SELECT object_type, COUNT(*) as count
FROM user_objects
WHERE status = 'VALID'
GROUP BY object_type
ORDER BY object_type;

PROMPT
PROMPT ========================================
PROMPT Invalid Objects
PROMPT ========================================
SELECT object_name, object_type, status
FROM user_objects
WHERE status != 'VALID'
ORDER BY object_type, object_name;

PROMPT
PROMPT ========================================
PROMPT Tablespace Quotas
PROMPT ========================================
SELECT tablespace_name, bytes/1024/1024 AS used_mb, max_bytes/1024/1024 AS quota_mb
FROM user_ts_quotas
ORDER BY tablespace_name;

EXIT;
EOF
}

# Function to display summary
display_summary() {
    cat <<EOF

${GREEN}========================================
Central Database Installation Summary
========================================${NC}

Server Role: CENTRAL METADATA SERVER
(This is NOT a target Oracle database for compression analysis)

Database Information:
- Oracle Version: Oracle Database 23c Free Edition
- Oracle SID: $ORACLE_SID
- PDB Name: FREEPDB1
- Database Port: 1521

Application User:
- Username: $COMPRESSION_USER
- Service Name: FREEPDB1
- Connection: $COMPRESSION_USER/$COMPRESSION_PWD@localhost:1521/FREEPDB1

Tablespaces:
- Default: USERS
- Scratch: SCRATCH_TS (5GB max, autoextend)
- Temporary: TEMP

Central DB Stores:
- Analysis metadata and results
- Compression strategy definitions
- Session and job tracking data
- Target database connection registry

Connection Examples:
1. SQL*Plus:
   sqlplus $COMPRESSION_USER/$COMPRESSION_PWD@localhost:1521/FREEPDB1

2. JDBC:
   jdbc:oracle:thin:@localhost:1521/FREEPDB1

3. SQL Developer / DBeaver:
   Host: localhost
   Port: 1521
   Service: FREEPDB1
   User: $COMPRESSION_USER

Log File: $LOG_FILE

${YELLOW}Important Notes:${NC}
- This is the CENTRAL server for metadata and results storage
- Compression analysis is performed on TARGET databases, not here
- Privileges are reduced: no DBA introspection or DBMS_COMPRESSION
- Password should be changed on first login for security

${GREEN}Central Database Installation Complete!${NC}

EOF
}

# Main installation workflow
main() {
    log_info "HCC Compression Advisor - Central Database Installation"
    log_info "======================================================="

    # Wait for database
    if ! wait_for_database; then
        log_error "Database is not ready. Aborting installation."
        exit 1
    fi

    # Check and open PDB
    check_pdb_status
    open_pdb

    # Run initialization scripts in order
    log_info "Running initialization scripts..."

    run_sql_script "Create User" "/opt/oracle/scripts/setup/01-create-user.sql" || exit 1
    run_sql_script "Grant Privileges" "/opt/oracle/scripts/setup/02-grant-privileges.sql" || exit 1
    run_sql_script "Create Tablespace" "/opt/oracle/scripts/setup/03-create-tablespace.sql" || exit 1

    # Install central schema and seed data
    install_central_schema

    # Verify installation
    verify_installation

    # Display summary
    display_summary

    log_success "HCC Compression Advisor Central Database installation completed successfully!"
}

# Execute main function
main "$@"
