# HCC Compression Advisor - Quick Start Guide

Get up and running with the HCC Compression Advisor Streamlit Dashboard in minutes.

## 🚀 Quick Start (5 Minutes)

### Step 1: Install Dependencies

```bash
cd HCC-CompAdvisor/python

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install required packages
pip install -r requirements.txt
```

### Step 2: Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit configuration (use your preferred editor)
nano .env
```

**Minimum required settings in `.env`:**

```env
# Authentication
DASHBOARD_PASSWORD=MySecurePassword123!

# Central Database
CENTRAL_DB_HOST=localhost
CENTRAL_DB_PORT=1521
CENTRAL_DB_SERVICE=FREEPDB1
CENTRAL_DB_USER=COMPRESSION_MGR
CENTRAL_DB_PASSWORD=your_central_db_password
```

### Step 3: Generate SSL Certificates (Optional but Recommended)

```bash
cd ssl
./generate_cert.sh
cd ..
```

### Step 4: Test Connections

```bash
# Test database and API connectivity
python test_connection.py
```

Expected output:
```
✓ SSL Configuration: PASS
✓ Central Database Connection: PASS
```

### Step 5: Start the Dashboard

```bash
# With HTTPS (recommended)
./start.sh

# Or without HTTPS (development only)
./start.sh http
```

### Step 6: Access the Dashboard

Open your browser:
- **HTTPS:** https://localhost:8501
- **HTTP:** http://localhost:8501

**Login with:**
- Password: The value you set in `.env` (default: `admin123`)

## 📋 Detailed Setup

### Prerequisites

Before you begin, ensure you have:

1. **Python 3.8+** installed
   ```bash
   python3 --version
   ```

2. **Oracle 23c Free or higher** (central database)
   - Stores metadata, recommendations, and target database registry

3. **HCC Advisor Schema** installed
   ```bash
   cd ../sql
   sqlplus sys/password@FREEPDB1 as sysdba @install_all.sql
   ```

4. **ORDS** (optional) - not required for core functionality
   ```bash
   # Verify ORDS is running (if using ORDS)
   curl -k https://localhost:8443/ords/hcc_advisor/health
   ```

### Database Setup

If you haven't installed the HCC Advisor schema yet:

```bash
cd ../sql

# Connect as SYSDBA
sqlplus sys/password@XEPDB1 as sysdba

-- Run installation scripts
@01_create_user.sql
@02_tables.sql
@03_packages.sql
@04_ords.sql
@05_sample_data.sql
```

### ORDS Configuration (Optional)

If using ORDS, ensure modules are enabled:

```sql
-- Connect as HCC_ADVISOR user
sqlplus hcc_advisor/password@XEPDB1

-- Verify ORDS modules
SELECT module_name, uri_prefix, status
FROM user_ords_modules;

-- Should show:
-- hcc.advisor  /hcc_advisor  PUBLISHED
```

## 🎯 First-Time Usage

### 1. Login

Navigate to the dashboard URL and enter your password.

### 2. Verify Connections

Check the sidebar for connection status:
- Central DB Connected (green) - Central database connection OK

If it shows disconnected (red), check your `CENTRAL_DB_*` configuration in `.env`.

### 3. Run Your First Analysis

1. Navigate to **Analysis** page
2. Set minimum table size (e.g., 100 MB)
3. Click **▶️ Start Analysis**
4. Wait for analysis to complete
5. Review results

### 4. View Recommendations

1. Navigate to **Recommendations** page
2. Filter by strategy or savings percentage
3. Review compression candidates
4. Export to CSV/Excel if needed

### 5. Execute Compression (Dry Run)

1. Navigate to **Execution** page
2. Select a table from recommendations
3. Enable **Dry Run** checkbox
4. Click **🚀 Execute Compression**
5. Review the execution plan

### 6. Monitor Progress

1. Navigate to **History** page
2. View execution timeline
3. Analyze success rates
4. Export history data

## 🔧 Configuration Options

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DASHBOARD_PASSWORD` | Login password | `admin123` | Yes |
| `CENTRAL_DB_HOST` | Central database host | `localhost` | Yes |
| `CENTRAL_DB_PORT` | Central database port | `1521` | Yes |
| `CENTRAL_DB_SERVICE` | Central database service | `FREEPDB1` | Yes |
| `CENTRAL_DB_USER` | Central database user | `COMPRESSION_MGR` | Yes |
| `CENTRAL_DB_PASSWORD` | Central database password | - | Yes |
| `ENCRYPTION_KEY` | Key for target DB password encryption | - | No |
| `SSL_ENABLED` | Enable SSL | `true` | No |
| `SESSION_TIMEOUT_MINUTES` | Session timeout | `30` | No |
| `MAX_LOGIN_ATTEMPTS` | Max login tries | `3` | No |

### Streamlit Configuration

Edit `.streamlit/config.toml` to customize:

```toml
[theme]
primaryColor = "#1f77b4"  # Change primary color
backgroundColor = "#ffffff"

[server]
port = 8501  # Change port
enableCORS = false
```

## 🔐 Security Best Practices

### 1. Change Default Password

```bash
# Edit .env
nano .env

# Set strong password
DASHBOARD_PASSWORD=MyV3ryStr0ngP@ssw0rd!
```

### 2. Use SSL in Production

```bash
# Generate proper certificates
cd ssl
./generate_cert.sh

# Or use CA-signed certificates
# Copy your certificates to ssl/cert.pem and ssl/key.pem
```

### 3. Restrict Network Access

```bash
# Start on localhost only (default)
./start.sh

# Or bind to specific IP
streamlit run app.py --server.address=192.168.1.100
```

### 4. Enable Firewall

```bash
# Allow only specific IPs
sudo ufw allow from 192.168.1.0/24 to any port 8501
```

## 📊 Common Tasks

### Export Recommendations

1. Go to **Recommendations** page
2. Apply filters as needed
3. Click **📄 Download CSV** or **📊 Download Excel**

### Compare Strategies

1. Go to **Strategies** page
2. Enter schema and table name
3. Click **🔍 Compare Strategies**
4. Review compression ratios

### View Execution History

1. Go to **History** page
2. Set date range
3. View charts and metrics
4. Export if needed

### Batch Compression

1. Go to **Execution** page
2. Select **Batch Execution** tab
3. Choose multiple tables
4. Set parameters
5. Click **🚀 Execute Batch**

## 🐛 Troubleshooting

### Connection Errors

**Central database connection fails:**
```bash
# Test central database connection
sqlplus COMPRESSION_MGR/password@localhost:1521/FREEPDB1

# Check listener
lsnrctl status
```

**ORDS API fails (optional -- not required for core functionality):**
```bash
# Test ORDS endpoint (if using ORDS)
curl -k https://localhost:8443/ords/hcc_advisor/health

# Check ORDS status
ps aux | grep ords
```

### SSL Certificate Issues

**Browser shows security warning:**
- Click "Advanced" → "Proceed to localhost (unsafe)"
- Or install certificate in browser trust store

**Certificate not found:**
```bash
cd ssl
./generate_cert.sh
```

### Login Issues

**Forgot password:**
```bash
# Edit .env and change DASHBOARD_PASSWORD
nano .env

# Restart application
./stop.sh
./start.sh
```

**Locked out:**
```bash
# Wait for session timeout (default 30 minutes)
# Or restart the application to reset sessions
./stop.sh
./start.sh
```

### Performance Issues

**Slow queries:**
```bash
# Reduce result limits in filters
# Enable database indexes
# Check database statistics
```

**High memory usage:**
```bash
# Reduce connection pool size in config.py
POOL_MIN = 1
POOL_MAX = 5
```

## 🔄 Updating

### Update Dependencies

```bash
# Activate virtual environment
source venv/bin/activate

# Update packages
pip install --upgrade -r requirements.txt
```

### Update Application

```bash
# Pull latest changes
git pull origin main

# Restart application
./stop.sh
./start.sh
```

## 📚 Additional Resources

- **Full Documentation:** [README.md](README.md)
- **API Documentation:** See ORDS endpoint documentation
- **Database Schema:** See `../sql/` directory
- **Support:** Contact your database administrator

## 🎓 Learning Path

1. **Day 1:** Install and configure
2. **Day 2:** Run first analysis, review recommendations
3. **Day 3:** Execute dry-run compressions
4. **Day 4:** Production compression execution
5. **Day 5:** Monitor and analyze results

## ⚡ Pro Tips

1. **Start with dry-run** mode to preview changes
2. **Use filters** to focus on high-value tables
3. **Export data** regularly for reporting
4. **Monitor history** to track savings over time
5. **Compare strategies** before committing
6. **Schedule analysis** during off-peak hours
7. **Back up tables** before compression

## 🆘 Getting Help

If you encounter issues:

1. Check the logs: `logs/app.log`
2. Run connection test: `python test_connection.py`
3. Review configuration: `.env`
4. Consult README.md
5. Check ORDS and database logs

## ✅ Checklist

Before going to production:

- [ ] Changed default password
- [ ] SSL certificates generated
- [ ] Central database connection tested
- [ ] ORDS API connection tested (if using ORDS)
- [ ] Firewall rules configured
- [ ] Backup procedures in place
- [ ] Monitoring configured
- [ ] User training completed

---

**Ready to start?** Run `./start.sh` and happy compressing! 🚀
