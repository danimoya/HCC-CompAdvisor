# HCC Compression Advisor

A centralized Oracle Database compression analysis and management system that manages multiple remote Oracle databases from a single server, adapted for Oracle 23c Free Edition.

## 🎯 Project Overview

This system provides a centralized architecture for managing compression analysis, intelligent recommendations, and execution capabilities across multiple remote Oracle databases. A central database stores all results, strategies, and target database configurations, while connecting to remote targets for analysis and execution. Originally designed for Exadata HCC (Hybrid Columnar Compression), it has been adapted to work with Oracle 23c Free Edition using standard compression techniques.

### Key Features

- **Multi-Database Management** (manage multiple remote Oracle databases from one server)
- **Centralized Results Store** (all analysis results, strategies, and history in a central database)
- **3 Configurable Compression Strategies** (table-driven, runtime modifiable)
- **Comprehensive Object Analysis** (tables, indexes, LOBs, IOTs, partitions)
- **Intelligent Recommendations** (hotness scoring, DML pattern analysis)
- **ORDS REST API** (optional RESTful interface with 10 endpoints)
- **Streamlit Dashboard** (modern web UI with SSL support)
- **Docker Environment** (Oracle 23c Free ready-to-run)
- **Complete Audit Trail** (execution history, rollback support)

## 📁 Project Structure

```
HCC-CompAdvisor/
├── sql/                        # Database implementation (target DB scripts)
│   ├── 01_schema.sql          # Tables, sequences, indexes (1004 lines)
│   ├── 02_strategies.sql      # 3 compression strategies with rules
│   ├── 03_advisor_pkg.sql     # PKG_COMPRESSION_ADVISOR (analysis engine)
│   ├── 04_executor_pkg.sql    # PKG_COMPRESSION_EXECUTOR (execution engine)
│   ├── 05_views.sql           # 10 reporting views
│   ├── 06_ords.sql            # REST API configuration (optional)
│   ├── install_full.sql       # Master installation script
│   ├── uninstall.sql          # Clean uninstallation
│   └── central/               # Central database schema
│       ├── 01_central_schema.sql   # Central tables and indexes
│       └── 02_seed_strategies.sql  # Default strategy data
│
├── python/                     # Streamlit Dashboard
│   ├── app.py                 # Main application
│   ├── auth.py                # Authentication
│   ├── config.py              # Configuration
│   ├── views/                 # 7 interactive pages
│   │   ├── page_01_analysis.py
│   │   ├── page_02_recommendations.py
│   │   ├── page_03_execution.py
│   │   ├── page_04_history.py
│   │   ├── page_05_strategies.py
│   │   ├── page_06_target_manager.py
│   │   └── page_07_sessions.py
│   ├── utils/                 # Database connectors & utilities
│   │   ├── central_connector.py    # Central DB connection
│   │   ├── target_connector.py     # Remote target DB connections
│   │   ├── central_queries.py      # Central DB queries
│   │   ├── target_queries.py       # Target DB queries
│   │   ├── migration.py            # Schema migration utilities
│   │   ├── api_client.py           # ORDS API client (optional)
│   │   └── logger.py               # Application logging
│   └── ssl/                   # SSL certificate generation
│
├── docker/                     # Docker Environment
│   ├── Dockerfile             # Oracle 23c Free image
│   ├── docker-compose.yml     # Centralized deployment (central-db + dashboard)
│   ├── docker-compose.dev.yml # Local development environment
│   ├── init-scripts-central/  # Central DB automated setup
│   └── README.md              # Docker documentation
│
└── docs/                       # Documentation
    ├── IMPLEMENTATION_ANALYSIS.md
    ├── INSTALLATION.md
    ├── USER_GUIDE.md
    └── API_REFERENCE.md
```

## 🚀 Quick Start

### Prerequisites

- Docker 20.10+ and Docker Compose 2.0+
- 8GB RAM minimum
- 50GB disk space

### Installation

```bash
# 1. Navigate to project
cd HCC-CompAdvisor/docker

# 2. Start the centralized deployment (central-db + streamlit-dashboard)
docker compose up -d

# 3. Wait for initialization (~10-15 minutes first time)

# 4. Access the dashboard
open http://localhost:8501
```

### Manual Installation (Without Docker)

```bash
# 1. Connect to Oracle Database
sqlplus COMPRESSION_MGR/password@database

# 2. Install the system
@sql/install_full.sql

# 3. Start Streamlit dashboard
cd python && ./start.sh
```

## 🎨 Compression Strategies

### 1. HIGH_PERFORMANCE (Strategy ID: 1)
- **Goal**: Minimal compression overhead
- **Use Case**: High-transaction OLTP systems
- **Approach**: OLTP compression for hot data, minimal compression for cold

### 2. BALANCED (Strategy ID: 2) - DEFAULT
- **Goal**: Optimal space/performance balance
- **Use Case**: General-purpose databases
- **Approach**: OLTP for hot, BASIC for warm/cold

### 3. MAXIMUM_COMPRESSION (Strategy ID: 3)
- **Goal**: Maximum space savings
- **Use Case**: Data warehouses, archives
- **Approach**: Aggressive compression across all objects

## 📊 Oracle 23c Free Compression Support

| Compression Type | Tables | Indexes | Available in 23c Free | Available on Exadata |
|------------------|--------|---------|----------------------|----------------------|
| BASIC | ✅ | ❌ | ✅ Yes | ✅ Yes |
| OLTP | ✅ | ❌ | ✅ Yes | ✅ Yes |
| ADVANCED LOW | ❌ | ✅ | ✅ Yes | ✅ Yes |
| ADVANCED HIGH | ❌ | ✅ | ✅ Yes | ✅ Yes |
| QUERY LOW (HCC) | ✅ | ❌ | ❌ No | ✅ Yes (Exadata only) |
| QUERY HIGH (HCC) | ✅ | ❌ | ❌ No | ✅ Yes (Exadata only) |
| ARCHIVE LOW (HCC) | ✅ | ❌ | ❌ No | ✅ Yes (Exadata only) |
| ARCHIVE HIGH (HCC) | ✅ | ❌ | ❌ No | ✅ Yes (Exadata only) |

**Note**: HCC (Hybrid Columnar Compression) consists of 4 types: QUERY LOW/HIGH and ARCHIVE LOW/HIGH, all of which are Exadata-only features. Oracle 23c Free uses standard Row Store Compression (BASIC, OLTP) and Advanced Compression (ADVANCED LOW/HIGH for indexes).

## 📖 Documentation

### Core Documentation
- **[Installation Guide](docs/guides/INSTALLATION.md)** - Setup instructions
- **[User Guide](docs/guides/USER_GUIDE.md)** - How to use the system
- **[API Reference](docs/reference/API_REFERENCE.md)** - REST API documentation
- **[Strategy Guide](docs/reference/STRATEGY_GUIDE.md)** - Compression strategy details

### Technical Documentation
- **[System Architecture](docs/architecture/system-architecture.md)** - Architecture overview
- **[Docker Setup Guide](docs/guides/docker-setup-guide.md)** - Docker environment
- **[Operations Runbook](docs/reference/operations-runbook.md)** - Operational procedures and troubleshooting

## 🔌 REST API Endpoints

> **Note**: ORDS is optional and not required for core functionality. The dashboard communicates directly with the central and target databases. ORDS endpoints are available when Oracle REST Data Services is configured on a target database.

Base URL: `https://server:8080/ords/compression/compression/v1/`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/analyze` | Trigger compression analysis |
| GET | `/recommendations` | Get compression candidates |
| POST | `/execute` | Execute compression operation |
| GET | `/history` | Retrieve execution history |
| GET | `/summary` | Dashboard metrics |
| GET | `/strategies` | List available strategies |
| POST | `/batch-execute` | Batch compression execution |

Full API documentation with examples: [API_REFERENCE.md](docs/API_REFERENCE.md)

## 🎯 Usage Examples

### Run Compression Analysis

```sql
-- Analyze all user objects with BALANCED strategy
EXEC PKG_COMPRESSION_ADVISOR.run_analysis(
  p_owner => NULL,
  p_strategy_id => 2
);

-- Analyze specific table
EXEC PKG_COMPRESSION_ADVISOR.analyze_table(
  p_owner => 'MYSCHEMA',
  p_table_name => 'SALES_DATA',
  p_strategy_id => 2
);
```

### View Recommendations

```sql
-- Top 10 compression candidates
SELECT owner, object_name, object_type,
       current_size_mb, potential_savings_mb,
       advisable_compression, rationale
FROM V_COMPRESSION_CANDIDATES
WHERE ROWNUM <= 10;
```

### Execute Compression

```sql
-- Compress a single table
EXEC PKG_COMPRESSION_EXECUTOR.compress_table(
  p_owner => 'MYSCHEMA',
  p_table_name => 'LARGE_TABLE',
  p_compression_type => 'OLTP',
  p_online => TRUE
);

-- Batch execute top recommendations
EXEC PKG_COMPRESSION_EXECUTOR.execute_recommendations(
  p_strategy_id => 2,
  p_max_tables => 10,
  p_max_size_gb => 100
);
```

## 📈 Dashboard Pages

1. **Analysis** - Trigger and monitor compression analysis
2. **Recommendations** - View and filter compression candidates
3. **Execution** - Execute compression operations with dry-run
4. **History** - Execution timeline and analytics
5. **Strategies** - Compare and manage compression strategies
6. **Target Database Manager** - Register, edit, and test remote Oracle database connections
7. **Session Browser** - Browse and inspect active database sessions

## 🔧 Configuration

### Environment Variables

```bash
# Central Database Connection
CENTRAL_DB_HOST=localhost
CENTRAL_DB_PORT=1521
CENTRAL_DB_SERVICE=FREEPDB1
CENTRAL_DB_USER=COMPRESSION_MGR
CENTRAL_DB_PASSWORD=your_password

# Dashboard
DASHBOARD_PASSWORD=YourDashboardPassword

# Encryption (for target DB passwords)
ENCRYPTION_KEY=your_fernet_key
```

## 🛠️ Development

### Running Tests

```bash
# SQL Tests
cd sql
sqlplus COMPRESSION_MGR/password@database @tests/test_analysis.sql

# Python Tests
cd python
python -m pytest tests/
```

### Building Docker Image

```bash
cd docker
docker compose up -d          # Centralized deployment
# OR for local development:
docker compose -f docker-compose.dev.yml up -d
```

## 📦 System Requirements

### Minimum Requirements
- Oracle Database 19c or higher (23c Free Edition supported)
- 4 CPU cores
- 8GB RAM
- 50GB disk space
- Python 3.8+ (for dashboard)

### Recommended Requirements
- Oracle Database 23c Free Edition
- 8 CPU cores
- 16GB RAM
- 100GB disk space
- Python 3.11+

## 🤝 Contributing

This is a unified implementation merging best practices from multiple sources:
- Original prompt specifications (prompt1-3.md)
- Example implementations (example2-4)
- Oracle best practices
- Production hardening

## 📝 License

Copyright © 2025 Daniel Moya. All rights reserved.
Author: Daniel Moya
GitHub: [github.com/danimoya](https://github.com/danimoya)
Website: [danimoya.com](https://danimoya.com)

## 🆘 Support

### Common Issues

1. **HCC Not Available**: Oracle 23c Free doesn't support HCC. Use BASIC/OLTP compression.
2. **Insufficient Privileges**: Ensure COMPRESSION_MGR has all required grants.
3. **SCRATCH Tablespace**: Create SCRATCH_TS before running analysis.
4. **ORDS Not Available**: ORDS endpoints are optional; system works without them.

### Troubleshooting

Check the following logs:
- Installation: `sql/install_full.log`
- Dashboard: `python/logs/streamlit.log`
- Docker: `docker-compose logs -f`

## 📊 Project Statistics

- **Total Files**: 80+
- **Lines of Code**: 15,000+
- **SQL Scripts**: 7 core scripts
- **Python Modules**: 20+ files
- **Documentation**: 10 comprehensive guides
- **Docker Configuration**: Complete environment
- **REST API Endpoints**: 10 endpoints (optional, via ORDS)
- **Dashboard Pages**: 7 interactive pages (including target DB management)
- **Compression Strategies**: 3 pre-configured
- **Database Objects**: 30+ (tables, views, packages)

## 🎓 Learning Resources

- [Oracle Database 23c Administration Guide](https://docs.oracle.com/en/database/oracle/oracle-database/23/admin/) - Database administration including compression
- [DBMS_COMPRESSION Package Reference](https://docs.oracle.com/en/database/oracle/oracle-database/23/arpls/DBMS_COMPRESSION.html) - PL/SQL package documentation
- [Oracle 23c Free Edition](https://www.oracle.com/database/free/) - Download and documentation for Oracle 23c Free
- [Streamlit Documentation](https://docs.streamlit.io/) - Python dashboard framework documentation

---

**Built with** 💙 **by merging best practices from multiple implementations**

For questions or issues, please review the documentation in the `docs/` directory.
