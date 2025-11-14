# HCC Compression Advisor - Installation Guide

Complete step-by-step installation guide for the Streamlit Dashboard.

## 📋 Prerequisites Check

Before starting, verify you have:

```bash
# Python 3.8 or higher
python3 --version
# Should output: Python 3.8.x or higher

# pip package manager
pip3 --version

# Git (optional, for cloning)
git --version

# OpenSSL (for SSL certificates)
openssl version

# Oracle Database access
# sqlplus should be available or Oracle client installed
```

## 🚀 Installation Methods

### Method 1: Automated Installation (Recommended)

```bash
# Navigate to project directory
cd /home/claude/Oracle-Database-Related/HCC-CompAdvisor/python

# Run start script (handles everything)
./start.sh
```

The start script will:
1. Create virtual environment
2. Install dependencies
3. Generate SSL certificates
4. Create .env from template
5. Start the application

### Method 2: Manual Installation

#### Step 1: Create Virtual Environment

```bash
cd /home/claude/Oracle-Database-Related/HCC-CompAdvisor/python

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# Linux/Mac:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# Verify activation (should show venv path)
which python
```

#### Step 2: Install Dependencies

```bash
# Upgrade pip
pip install --upgrade pip

# Install required packages
pip install -r requirements.txt

# Verify installation
pip list
```

**Expected packages:**
- streamlit
- oracledb
- pandas
- plotly
- requests
- python-dotenv
- And 9 more dependencies

#### Step 3: Configure Environment

```bash
# Copy template
cp .env.example .env

# Edit configuration
nano .env
```

**Required configuration:**

```env
# Authentication - CHANGE THIS!
DASHBOARD_PASSWORD=YourSecurePassword123!

# Database Connection
DB_HOST=localhost
DB_PORT=1521
DB_SERVICE=XEPDB1
DB_USER=hcc_advisor
DB_PASSWORD=your_actual_db_password

# ORDS REST API
ORDS_BASE_URL=https://localhost:8443/ords/hcc_advisor
ORDS_USERNAME=hcc_advisor
ORDS_PASSWORD=your_actual_ords_password

# SSL Configuration
SSL_ENABLED=true
SSL_CERT_FILE=ssl/cert.pem
SSL_KEY_FILE=ssl/key.pem
```

#### Step 4: Generate SSL Certificates

```bash
cd ssl
chmod +x generate_cert.sh
./generate_cert.sh
cd ..

# Verify certificates created
ls -l ssl/
# Should show: cert.pem and key.pem
```

#### Step 5: Test Connections

```bash
# Make test script executable
chmod +x test_connection.py

# Run connection test
python test_connection.py
```

**Expected output:**
```
============================================================
HCC Compression Advisor - Connection Test
============================================================

============================================================
Testing SSL Configuration
============================================================
SSL Enabled: True
Certificate: /path/to/ssl/cert.pem
Private Key: /path/to/ssl/key.pem

✓ SSL certificate found
✓ SSL private key found

============================================================
Testing Database Connection
============================================================
Host: localhost
Port: 1521
Service: XEPDB1
User: hcc_advisor

✓ Connection pool initialized
✓ Database connection successful
✓ Oracle Version: Oracle Database 23ai ...

============================================================
Testing ORDS API Connection
============================================================
Base URL: https://localhost:8443/ords/hcc_advisor
Username: hcc_advisor

✓ ORDS API connection successful
✓ Strategies endpoint working (4 strategies)
✓ Statistics endpoint working

============================================================
Test Summary
============================================================
SSL Configuration: ✓ PASS
Database Connection: ✓ PASS
ORDS API Connection: ✓ PASS

✓ All tests passed! Ready to start the dashboard.

Run: ./start.sh
```

#### Step 6: Start Application

```bash
# With HTTPS (recommended)
./start.sh

# Or manually with HTTPS
streamlit run app.py \
  --server.sslCertFile=ssl/cert.pem \
  --server.sslKeyFile=ssl/key.pem \
  --server.port=8501

# Or with HTTP (development only)
./start.sh http

# Or manually with HTTP
streamlit run app.py --server.port=8501
```

#### Step 7: Access Dashboard

Open your web browser:

**HTTPS (recommended):**
```
https://localhost:8501
```

**HTTP (development):**
```
http://localhost:8501
```

**First-time browser warning (HTTPS with self-signed cert):**
1. Click "Advanced"
2. Click "Proceed to localhost (unsafe)"
3. Accept the security exception

**Login:**
- Enter the password you set in `.env` file
- Default: `admin123` (CHANGE THIS!)

## 🔧 Configuration Details

### Database Configuration

Ensure the HCC Advisor schema is installed:

```bash
# Navigate to SQL directory
cd /home/claude/Oracle-Database-Related/HCC-CompAdvisor/sql

# Connect to database
sqlplus sys/password@XEPDB1 as sysdba

# Run installation
@install_all.sql
```

**Verify installation:**

```sql
-- Connect as hcc_advisor
CONNECT hcc_advisor/password@XEPDB1

-- Check tables
SELECT table_name FROM user_tables;

-- Should show:
-- HCC_ANALYSIS_RUNS
-- HCC_COMPRESSION_CANDIDATES
-- HCC_EXECUTION_LOG
-- HCC_STRATEGIES
```

### ORDS Configuration

Verify ORDS is configured:

```bash
# Test ORDS health endpoint
curl -k -u hcc_advisor:password \
  https://localhost:8443/ords/hcc_advisor/health

# Expected response:
# {"status":"healthy","version":"1.0"}
```

**Check ORDS modules:**

```sql
-- Connect as hcc_advisor
CONNECT hcc_advisor/password@XEPDB1

-- List modules
SELECT module_name, uri_prefix, status
FROM user_ords_modules;

-- Expected:
-- hcc.advisor  /hcc_advisor  PUBLISHED
```

**Verify endpoints:**

```bash
# Test strategies endpoint
curl -k -u hcc_advisor:password \
  https://localhost:8443/ords/hcc_advisor/strategies

# Test statistics endpoint
curl -k -u hcc_advisor:password \
  https://localhost:8443/ords/hcc_advisor/statistics/compression
```

### Network Configuration

**Firewall rules (if needed):**

```bash
# Allow Streamlit port
sudo ufw allow 8501/tcp

# Or restrict to specific network
sudo ufw allow from 192.168.1.0/24 to any port 8501
```

**For remote access:**

```bash
# Start with specific address binding
streamlit run app.py \
  --server.address=0.0.0.0 \
  --server.port=8501 \
  --server.sslCertFile=ssl/cert.pem \
  --server.sslKeyFile=ssl/key.pem
```

## 🐳 Docker Installation (Alternative)

### Create Dockerfile

```dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Generate SSL certificates
RUN cd ssl && chmod +x generate_cert.sh && ./generate_cert.sh

# Expose port
EXPOSE 8501

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -k -f https://localhost:8501/_stcore/health || exit 1

# Start application
CMD ["streamlit", "run", "app.py", \
     "--server.sslCertFile=ssl/cert.pem", \
     "--server.sslKeyFile=ssl/key.pem", \
     "--server.port=8501", \
     "--server.address=0.0.0.0"]
```

### Build and Run

```bash
# Build image
docker build -t hcc-dashboard .

# Run container
docker run -d \
  --name hcc-dashboard \
  -p 8501:8501 \
  -v $(pwd)/.env:/app/.env:ro \
  hcc-dashboard

# View logs
docker logs -f hcc-dashboard

# Stop container
docker stop hcc-dashboard
```

## 🔐 Production Deployment

### 1. Use Production-Grade SSL Certificates

```bash
# Copy your CA-signed certificates
cp /path/to/your/certificate.crt ssl/cert.pem
cp /path/to/your/private.key ssl/key.pem

# Set secure permissions
chmod 600 ssl/key.pem
chmod 644 ssl/cert.pem
```

### 2. Systemd Service

Create `/etc/systemd/system/hcc-dashboard.service`:

```ini
[Unit]
Description=HCC Compression Advisor Dashboard
After=network.target oracle.service

[Service]
Type=simple
User=streamlit
Group=streamlit
WorkingDirectory=/opt/hcc-dashboard/python
Environment="PATH=/opt/hcc-dashboard/python/venv/bin"
ExecStart=/opt/hcc-dashboard/python/venv/bin/streamlit run app.py \
  --server.sslCertFile=ssl/cert.pem \
  --server.sslKeyFile=ssl/key.pem \
  --server.port=8501 \
  --server.address=0.0.0.0 \
  --server.headless=true

# Restart configuration
Restart=always
RestartSec=10

# Security
NoNewPrivileges=true
PrivateTmp=true

# Logging
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Enable and start:**

```bash
# Create service user
sudo useradd -r -s /bin/false streamlit

# Set permissions
sudo chown -R streamlit:streamlit /opt/hcc-dashboard

# Enable service
sudo systemctl daemon-reload
sudo systemctl enable hcc-dashboard

# Start service
sudo systemctl start hcc-dashboard

# Check status
sudo systemctl status hcc-dashboard

# View logs
sudo journalctl -u hcc-dashboard -f
```

### 3. Nginx Reverse Proxy (Optional)

```nginx
server {
    listen 443 ssl http2;
    server_name hcc-dashboard.example.com;

    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;

    location / {
        proxy_pass https://localhost:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_read_timeout 86400;
    }
}
```

## 🔍 Verification

After installation, verify:

1. **Application starts:** No errors in console
2. **URL accessible:** Can open in browser
3. **Login works:** Can authenticate
4. **Database connected:** Green checkmark in sidebar
5. **API connected:** Green checkmark in sidebar
6. **Pages load:** All 6 pages accessible
7. **Charts render:** Visualizations display
8. **Export works:** Can download CSV/Excel

## 🐛 Troubleshooting Installation

### Python Version Issues

```bash
# Check Python version
python3 --version

# If too old, install newer version
sudo apt-get update
sudo apt-get install python3.11
python3.11 -m venv venv
```

### Dependency Installation Fails

```bash
# Upgrade pip
pip install --upgrade pip setuptools wheel

# Install with verbose output
pip install -v -r requirements.txt

# If specific package fails
pip install package_name --no-cache-dir
```

### Oracle Client Issues

```bash
# Install Oracle Instant Client (Linux)
wget https://download.oracle.com/otn_software/linux/instantclient/instantclient-basic-linux.x64-21.9.0.0.0dbru.zip
unzip instantclient-basic-linux.x64-21.9.0.0.0dbru.zip
sudo mv instantclient_21_9 /opt/oracle
export LD_LIBRARY_PATH=/opt/oracle/instantclient_21_9:$LD_LIBRARY_PATH

# Add to .bashrc
echo 'export LD_LIBRARY_PATH=/opt/oracle/instantclient_21_9:$LD_LIBRARY_PATH' >> ~/.bashrc
```

### Connection Test Fails

```bash
# Test database directly
sqlplus hcc_advisor/password@localhost:1521/XEPDB1

# Test ORDS directly
curl -k -u hcc_advisor:password \
  https://localhost:8443/ords/hcc_advisor/health

# Check listener
lsnrctl status

# Check ORDS
ps aux | grep ords
```

### SSL Certificate Issues

```bash
# Regenerate certificates
cd ssl
./generate_cert.sh

# Or use HTTP mode for testing
./start.sh http
```

### Permission Issues

```bash
# Make scripts executable
chmod +x start.sh stop.sh test_connection.py
chmod +x ssl/generate_cert.sh

# Fix SSL permissions
chmod 600 ssl/key.pem
chmod 644 ssl/cert.pem
```

## 📚 Post-Installation

After successful installation:

1. **Change default password** in `.env`
2. **Review security settings**
3. **Configure firewall rules**
4. **Set up backups** for configuration
5. **Configure monitoring**
6. **Train users**
7. **Document your setup**

## 🎓 Next Steps

1. Read [QUICKSTART.md](QUICKSTART.md) for usage guide
2. Review [FEATURES.md](FEATURES.md) for feature details
3. Check [README.md](README.md) for comprehensive docs
4. Run your first analysis
5. Explore all dashboard pages

## 📞 Getting Help

If you encounter issues during installation:

1. Check error messages carefully
2. Review logs: `logs/app.log`
3. Run connection test: `python test_connection.py`
4. Verify prerequisites are met
5. Check firewall and network settings
6. Consult documentation
7. Contact support team

---

**Installation Complete!** 🎉

Access your dashboard at: https://localhost:8501

**Default login:** Password from `.env` file (change immediately!)
