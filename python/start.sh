#!/bin/bash
#
# HCC Compression Advisor Dashboard Startup Script
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "================================================"
echo "HCC Compression Advisor Dashboard"
echo "================================================"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Virtual environment not found. Creating...${NC}"
    python3 -m venv venv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Check if dependencies are installed
if ! python -c "import streamlit" 2>/dev/null; then
    echo -e "${YELLOW}Installing dependencies...${NC}"
    pip install -r requirements.txt
    echo -e "${GREEN}✓ Dependencies installed${NC}"
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo -e "${RED}Error: .env file not found${NC}"
    echo "Creating .env from template..."
    cp .env.example .env
    echo -e "${YELLOW}⚠ Please edit .env with your configuration${NC}"
    echo ""
    nano .env
fi

# Check if SSL certificates exist
if [ ! -f "ssl/cert.pem" ] || [ ! -f "ssl/key.pem" ]; then
    echo -e "${YELLOW}SSL certificates not found. Generating...${NC}"
    cd ssl
    ./generate_cert.sh
    cd ..
    echo -e "${GREEN}✓ SSL certificates generated${NC}"
fi

echo ""
echo "================================================"
echo "Configuration Summary"
echo "================================================"

# Read configuration from .env
if [ -f ".env" ]; then
    source .env
    echo "Database: $DB_HOST:$DB_PORT/$DB_SERVICE"
    echo "ORDS API: $ORDS_BASE_URL"
    echo "SSL Enabled: $SSL_ENABLED"
fi

echo ""
echo "================================================"
echo "Starting Dashboard..."
echo "================================================"
echo ""

# Check for command line arguments
SSL_MODE=${1:-https}

if [ "$SSL_MODE" == "http" ]; then
    echo -e "${YELLOW}Starting in HTTP mode (not secure)${NC}"
    streamlit run app.py \
        --server.port=8501 \
        --server.address=0.0.0.0
else
    echo -e "${GREEN}Starting in HTTPS mode${NC}"
    streamlit run app.py \
        --server.sslCertFile=ssl/cert.pem \
        --server.sslKeyFile=ssl/key.pem \
        --server.port=8501 \
        --server.address=0.0.0.0
fi
