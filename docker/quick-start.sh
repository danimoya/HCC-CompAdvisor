#!/bin/bash
# ============================================================================
# Script: quick-start.sh
# Description: Quick start script for HCC Compression Advisor Docker environment
# Author: HCC Compression Advisor Team
# ============================================================================

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Helper functions
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Banner
cat <<'EOF'
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║        HCC Compression Advisor - Docker Quick Start          ║
║                  Oracle 23c Free Edition                      ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝

EOF

# Check prerequisites
log_info "Checking prerequisites..."

# Check Docker
if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed. Please install Docker Desktop or Docker Engine."
    exit 1
fi
log_success "Docker found: $(docker --version)"

# Check Docker Compose
if ! command -v docker-compose &> /dev/null; then
    log_error "Docker Compose is not installed."
    exit 1
fi
log_success "Docker Compose found: $(docker-compose --version)"

# Check Docker daemon
if ! docker info &> /dev/null; then
    log_error "Docker daemon is not running. Please start Docker."
    exit 1
fi
log_success "Docker daemon is running"

# Check for .env file
if [ ! -f .env ]; then
    log_warning ".env file not found, creating from template..."
    cp .env.example .env
    log_success ".env file created"
    log_warning "Please review and update .env file with your preferred passwords"

    read -p "Do you want to edit .env now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ${EDITOR:-nano} .env
    fi
fi

# Create required directories
log_info "Creating required directories..."
mkdir -p data logs custom-scripts
chmod -R 777 data logs
log_success "Directories created"

# Check Oracle Container Registry login
log_info "Checking Oracle Container Registry access..."
if ! docker pull container-registry.oracle.com/database/free:latest &> /dev/null; then
    log_warning "Not logged into Oracle Container Registry"
    log_info "You need to login with your Oracle account"
    log_info "Visit: https://container-registry.oracle.com and accept Terms & Restrictions"

    read -p "Press Enter to login to Oracle Container Registry..."
    docker login container-registry.oracle.com
fi

# Confirm startup
cat <<EOF

${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}
${YELLOW}Ready to start HCC Compression Advisor Docker environment${NC}
${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}

This will:
  1. Build Oracle 23c Free Docker image (~5-10 minutes)
  2. Start database and initialize (~5-10 minutes)
  3. Create COMPRESSION_MGR user and SCRATCH_TS tablespace
  4. Install HCC Compression Advisor components
  5. Start Streamlit dashboard (optional)

System Requirements:
  - CPU: 4+ cores
  - RAM: 8GB minimum (16GB recommended)
  - Disk: 50GB free space
  - First startup takes 10-20 minutes

EOF

read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_warning "Startup cancelled by user"
    exit 0
fi

# Start services
log_info "Starting Docker Compose services..."
docker-compose up -d --build

log_info "Waiting for database to initialize (this may take 10-15 minutes)..."
log_info "You can monitor progress with: docker-compose logs -f oracle-db"

# Wait for health check
log_info "Monitoring database health status..."
attempt=1
max_attempts=60

while [ $attempt -le $max_attempts ]; do
    if docker inspect hcc-oracle-23c 2>/dev/null | grep -q '"Status": "healthy"'; then
        log_success "Database is healthy and ready!"
        break
    fi

    echo -ne "\r  Waiting... ($attempt/$max_attempts) "
    sleep 10
    ((attempt++))
done

if [ $attempt -gt $max_attempts ]; then
    log_error "Database did not become healthy in time"
    log_info "Check logs with: docker-compose logs oracle-db"
    exit 1
fi

# Display connection information
cat <<EOF

${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}
${GREEN}        HCC Compression Advisor is ready!                  ${NC}
${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}

Database Connection:
  Host:     localhost
  Port:     1521
  Service:  FREEPDB1
  User:     COMPRESSION_MGR
  Password: Compress123

Connection String:
  sqlplus COMPRESSION_MGR/Compress123@localhost:1521/FREEPDB1

Enterprise Manager Express:
  URL:      https://localhost:5500/em
  User:     SYS as SYSDBA
  Password: Welcome123

Streamlit Dashboard:
  URL:      http://localhost:8501
  Password: Dashboard123

Useful Commands:
  View logs:        docker-compose logs -f
  Stop services:    docker-compose stop
  Start services:   docker-compose start
  Restart:          docker-compose restart
  Shell access:     docker-compose exec oracle-db bash
  SQL*Plus:         docker-compose exec oracle-db sqlplus COMPRESSION_MGR/Compress123@FREEPDB1

${YELLOW}Important Notes:${NC}
  - Oracle 23c Free does NOT support actual HCC compression
  - This environment provides simulation and demonstration capabilities
  - For production HCC, use Oracle Exadata or ZFS Storage Appliance
  - Change default passwords for production use

Documentation: docker/README.md

${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}

Happy Compressing! 🗜️

EOF

log_success "Quick start complete!"
