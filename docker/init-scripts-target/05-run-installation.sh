#!/bin/bash
# ============================================================================
# Script: 05-run-installation.sh
# Description: Run HCC Compression Advisor TARGET test database installation
# Database: Oracle 23c Free Edition (Target Test Database)
# ============================================================================

set -e
set -u

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

ORACLE_HOME=${ORACLE_HOME:-/opt/oracle/product/26ai/dbhomeFree}
ORACLE_SID=${ORACLE_SID:-FREE}
ORACLE_PWD=${ORACLE_PWD:-Welcome123}
COMPRESSION_USER=${COMPRESSION_USER:-COMPRESSION_MGR}
COMPRESSION_PWD=${COMPRESSION_PWD:-Compress123}
LOG_FILE="/opt/oracle/oradata/logs/target_installation_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$(dirname "$LOG_FILE")"

log_info "Starting HCC Target Test Database Installation"
log_info "Log file: $LOG_FILE"

wait_for_database() {
    log_info "Waiting for Oracle Database to be ready..."
    local max_attempts=60
    local attempt=1
    while [ $attempt -le $max_attempts ]; do
        if ${ORACLE_HOME}/bin/sqlplus -s sys/${ORACLE_PWD}@localhost:1521/FREE as sysdba <<< "SELECT 'DB_READY' FROM dual;" 2>&1 | grep -q "DB_READY"; then
            log_success "Database is ready"
            return 0
        fi
        log_info "Attempt $attempt/$max_attempts - waiting..."
        sleep 10
        ((attempt++))
    done
    log_error "Database did not become ready"
    return 1
}

open_pdb() {
    log_info "Ensuring FREEPDB1 is open..."
    ${ORACLE_HOME}/bin/sqlplus -s sys/${ORACLE_PWD}@localhost:1521/FREE as sysdba <<EOF | tee -a "$LOG_FILE"
ALTER PLUGGABLE DATABASE FREEPDB1 OPEN;
ALTER PLUGGABLE DATABASE FREEPDB1 SAVE STATE;
EXIT;
EOF
}

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
        log_success "$script_name completed"
        return 0
    else
        log_error "$script_name failed"
        return 1
    fi
}

run_sql_as_user() {
    local script_name=$1
    local script_path=$2
    log_info "Running $script_name as ${COMPRESSION_USER}..."
    if [ ! -f "$script_path" ]; then
        log_error "Script not found: $script_path"
        return 1
    fi
    ${ORACLE_HOME}/bin/sqlplus -s ${COMPRESSION_USER}/${COMPRESSION_PWD}@localhost:1521/FREEPDB1 <<EOF 2>&1 | tee -a "$LOG_FILE"
SET ECHO ON
SET SERVEROUTPUT ON SIZE UNLIMITED
@${script_path}
EXIT;
EOF
    if [ ${PIPESTATUS[0]} -eq 0 ]; then
        log_success "$script_name completed"
        return 0
    else
        log_warning "$script_name had warnings (may be OK)"
        return 0
    fi
}

main() {
    log_info "======================================================="
    log_info "HCC Target Test Database Installation"
    log_info "======================================================="

    if ! wait_for_database; then
        log_error "Database not ready. Aborting."
        exit 1
    fi

    open_pdb

    SCRIPT_DIR="/opt/oracle/scripts/setup"

    run_sql_script "Create User" "${SCRIPT_DIR}/01-create-user.sql" || exit 1
    run_sql_script "Grant Privileges" "${SCRIPT_DIR}/02-grant-privileges.sql" || exit 1
    run_sql_script "Create Tablespace" "${SCRIPT_DIR}/03-create-tablespace.sql" || exit 1

    log_info "Generating test data (~1GB, this will take several minutes)..."
    run_sql_as_user "Generate Test Data" "${SCRIPT_DIR}/04-generate-testdata.sql"

    log_success "======================================================="
    log_success "Target Test Database Installation Complete!"
    log_success "======================================================="
    log_info ""
    log_info "Connection: ${COMPRESSION_USER}/${COMPRESSION_PWD}@<host>:1522/FREEPDB1"
    log_info ""
    log_info "Test tables:"
    log_info "  SALES_TRANSACTIONS  (2M rows, ~400MB)"
    log_info "  SENSOR_READINGS     (3M rows, ~350MB)"
    log_info "  AUDIT_LOG           (2M rows, ~250MB)"
    log_info "  CUSTOMER_ACCOUNTS   (500K rows, ~80MB)"
    log_info ""
}

main "$@"
