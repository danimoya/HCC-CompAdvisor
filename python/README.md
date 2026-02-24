# HCC Compression Advisor - Streamlit Dashboard

A Streamlit dashboard for centralized multi-database Oracle Hybrid Columnar Compression (HCC) management with SSL support and authentication.

## Features

- 🔐 **Secure Authentication** - Password-based login with session management
- 🔒 **SSL/HTTPS Support** - Self-signed certificates for encrypted connections
- 📊 **Interactive Dashboard** - Real-time metrics and visualizations
- 🔍 **Analysis Tools** - Trigger and monitor compression analysis
- 💡 **Smart Recommendations** - Filter and view compression candidates
- ▶️ **Execution Management** - Single and batch compression execution
- 🕐 **History Tracking** - Detailed execution history with analytics
- 📈 **Strategy Comparison** - Compare compression strategies
- 📥 **Export Capabilities** - CSV and Excel export

## Installation

### Prerequisites

- Python 3.8 or higher
- Oracle 23c Free or higher (central database)
- ORDS (Oracle REST Data Services) - optional, not required for core functionality
- OpenSSL (for SSL certificate generation)

### Setup

1. **Navigate to the project directory:**

```bash
cd HCC-CompAdvisor/python
```

2. **Create virtual environment:**

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies:**

```bash
pip install -r requirements.txt
```

4. **Configure environment:**

```bash
cp .env.example .env
# Edit .env with your configuration
nano .env
```

5. **Generate SSL certificates:**

```bash
cd ssl
chmod +x generate_cert.sh
./generate_cert.sh
cd ..
```

## Configuration

### Environment Variables

Edit `.env` file with your configuration:

```env
# Authentication
DASHBOARD_PASSWORD=YourSecurePassword123!

# Central Database Connection
CENTRAL_DB_HOST=localhost
CENTRAL_DB_PORT=1521
CENTRAL_DB_SERVICE=FREEPDB1
CENTRAL_DB_USER=COMPRESSION_MGR
CENTRAL_DB_PASSWORD=your_central_db_password

# Encryption key for target DB passwords
ENCRYPTION_KEY=

# SSL Configuration
SSL_ENABLED=true
SSL_CERT_FILE=ssl/cert.pem
SSL_KEY_FILE=ssl/key.pem
```

### Database Setup

Ensure the HCC Compression Advisor database schema is installed:

```sql
-- Run the installation scripts
@/path/to/sql/01_tables.sql
@/path/to/sql/02_packages.sql
@/path/to/sql/03_ords.sql
```

## Usage

### Starting the Application

#### Without SSL (Development):

```bash
streamlit run app.py
```

#### With SSL (Production):

```bash
streamlit run app.py \
  --server.sslCertFile=ssl/cert.pem \
  --server.sslKeyFile=ssl/key.pem \
  --server.port=8501
```

#### Custom Configuration:

```bash
streamlit run app.py \
  --server.sslCertFile=ssl/cert.pem \
  --server.sslKeyFile=ssl/key.pem \
  --server.port=8443 \
  --server.address=0.0.0.0 \
  --server.headless=true
```

### Accessing the Dashboard

- **HTTP:** http://localhost:8501
- **HTTPS:** https://localhost:8501

**Default Login:**
- Password: `admin123` (change in `.env`)

## Application Structure

```
python/
├── app.py                      # Main application
├── auth.py                     # Authentication module
├── config.py                   # Configuration management
├── requirements.txt            # Python dependencies
├── .env.example               # Environment template
├── views/                     # Application pages
│   ├── page_01_analysis.py        # Run compression analysis
│   ├── page_02_recommendations.py # View recommendations
│   ├── page_03_execution.py       # Execute compression
│   ├── page_04_history.py         # Execution history
│   ├── page_05_strategies.py      # Strategy management
│   ├── page_06_connections.py     # Target database manager
│   └── page_07_sessions.py        # Session browser
├── utils/                     # Utility modules
│   ├── central_connector.py       # Central DB connection pool
│   ├── target_connector.py        # Target DB connection pools
│   ├── central_queries.py         # Central DB queries
│   ├── target_queries.py          # Target DB queries
│   ├── migration.py              # Data migration utility
│   ├── api_client.py             # ORDS API client (optional)
│   └── logger.py                 # Application logging
└── ssl/                       # SSL certificates
```

## Pages Overview

### 1. Dashboard
- Overview metrics
- Recent activity
- Quick actions
- Connection status

### 2. Analysis
- Start new compression analysis
- Monitor analysis progress
- View analysis results
- Potential savings visualization

### 3. Recommendations
- View compression candidates
- Filter by strategy and size
- Detailed recommendations
- Export capabilities

### 4. Execution
- Execute single table compression
- Batch execution
- Monitor execution progress
- Dry-run mode

### 5. History
- Execution history timeline
- Success rate analytics
- Strategy performance
- Export history data

### 6. Strategies
- View compression strategies
- Compare strategy performance
- Table-specific comparison
- Strategy selection guide

### 7. Target Database Manager
- Register and manage remote Oracle databases
- Connection testing and validation
- Encrypted credential storage

### 8. Session Browser
- Monitor active database sessions
- View session details and statistics
- Real-time session tracking

## Security

### Authentication

- Password-based login
- Session timeout (configurable)
- Failed login tracking
- Maximum login attempts

### SSL/TLS

- Self-signed certificates for development
- HTTPS encryption
- Secure cookie handling
- Certificate validation

### Best Practices

1. **Change default password** immediately
2. **Use strong passwords** (minimum 12 characters)
3. **Enable SSL** in production
4. **Use trusted certificates** for production
5. **Rotate credentials** regularly
6. **Restrict network access** using firewall rules
7. **Monitor access logs** for suspicious activity

## Development

### Adding New Pages

1. Create new page file in `pages/`:
```python
# pages/page_06_mypage.py
import streamlit as st

def show_mypage():
    st.title("My Page")
    st.write("Page content")

if __name__ == "__main__":
    show_mypage()
```

2. Add to navigation in `app.py`:
```python
selected = option_menu(
    menu_title="Navigation",
    options=[..., "My Page"],
    icons=[..., "icon-name"]
)

if selected == "My Page":
    from pages.page_06_mypage import show_mypage
    show_mypage()
```

### Customizing Charts

Edit `config.py` to customize chart colors:

```python
CHART_COLORS: dict = {
    'primary': '#1f77b4',
    'success': '#2ca02c',
    'warning': '#ff7f0e',
    'danger': '#d62728',
    'info': '#17becf',
    'secondary': '#7f7f7f'
}
```

## Troubleshooting

### Connection Issues

**Database connection fails:**
- Verify database credentials in `.env`
- Check network connectivity
- Ensure Oracle Instant Client is installed

**ORDS API connection fails (optional -- not required for core functionality):**
- Verify ORDS is running
- Check ORDS URL and credentials
- Test endpoint manually with curl
- Note: The dashboard uses direct oracledb connections; ORDS is not required

### SSL Issues

**Certificate errors:**
```bash
# Regenerate certificates
cd ssl
./generate_cert.sh
```

**Browser warnings:**
- Self-signed certificates will trigger warnings
- Add exception in browser or use trusted CA

### Performance

**Slow loading:**
- Reduce query result limits
- Enable connection pooling
- Optimize database queries
- Use caching where appropriate

### Authentication

**Locked out:**
- Wait for session timeout
- Restart application
- Reset `st.session_state` manually

## API Endpoints

> **Note:** ORDS endpoints are optional and not required for core functionality. The dashboard uses direct oracledb connections to the central and target databases.

The following ORDS endpoints can optionally be used:

- `GET /analysis/latest` - Latest analysis results
- `POST /analysis/start` - Start new analysis
- `GET /recommendations` - Get recommendations
- `POST /compression/execute` - Execute compression
- `GET /compression/history` - Execution history
- `GET /statistics/*` - Various statistics
- `GET /strategies/*` - Strategy information

## Monitoring

### Logs

View Streamlit logs:
```bash
tail -f logs/app.log
```

### Metrics

Monitor application metrics:
- Connection pool status
- API response times
- Active sessions
- Error rates

## Production Deployment

### Docker Deployment

Create `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", \
     "--server.sslCertFile=ssl/cert.pem", \
     "--server.sslKeyFile=ssl/key.pem", \
     "--server.port=8501"]
```

Build and run:
```bash
docker build -t hcc-dashboard .
docker run -p 8501:8501 -v $(pwd)/.env:/app/.env hcc-dashboard
```

### Systemd Service

Create `/etc/systemd/system/hcc-dashboard.service`:
```ini
[Unit]
Description=HCC Compression Advisor Dashboard
After=network.target

[Service]
Type=simple
User=streamlit
WorkingDirectory=/opt/hcc-dashboard/python
ExecStart=/opt/hcc-dashboard/python/venv/bin/streamlit run app.py \
  --server.sslCertFile=ssl/cert.pem \
  --server.sslKeyFile=ssl/key.pem \
  --server.port=8501 \
  --server.headless=true
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable hcc-dashboard
sudo systemctl start hcc-dashboard
```

## License

See main project LICENSE file.

## Support

For issues and questions:
- Check documentation
- Review logs
- Contact support team
