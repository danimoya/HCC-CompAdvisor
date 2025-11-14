# HCC Compression Advisor - System Architecture

## Overview

Analysis of 3 prompts and 3 examples to create a unified implementation for Oracle 23c Free (Docker).

## Key Sources Analyzed

### Prompts
1. **prompt1.md** - Core requirements (2 packages, ORDS, comprehensive analysis)
2. **prompt2.md** - Extended objects (IOTs, LOBs, indexes), ORDS endpoints
3. **prompt3.md** - Production spec (turnkey, COMPRESSION_MGR schema, cURL examples)

### Examples
1. **example2.md** - Full PL/SQL implementation (PKG_COMPRESSION_ANALYZER, PKG_COMPRESSION_EXECUTOR)
2. **example3.md** - Enhanced with parallel processing, comprehensive views
3. **example4.sql** - Production-grade (PKG_COMPRESS_ADVISOR, PKG_COMPRESS_APPLY, complete ORDS)

## Feature Matrix

| Feature | Example2 | Example3 | Example4 | Unified |
|---------|----------|----------|----------|---------|
| **Tables Analysis** | ✅ | ✅ | ✅ | ✅ |
| **Indexes Analysis** | ❌ | ✅ | ✅ | ✅ |
| **LOBs Analysis** | ❌ | ✅ | ✅ | ✅ |
| **IOTs Support** | ❌ | ✅ | ✅ | ✅ |
| **Partitioning** | ✅ | ✅ | ✅ | ✅ |
| **Parallel Processing** | ❌ | ✅ | ❌ | ✅ |
| **Hotness Scoring** | ✅ | ✅ | ✅ | ✅ |
| **DML Tracking** | ✅ | ✅ | ✅ | ✅ |
| **History Tracking** | ✅ | ✅ | ✅ | ✅ |
| **Rollback Support** | ✅ | ✅ | ❌ | ✅ |
| **ORDS Endpoints** | ✅ | ✅ | ✅ | ✅ |
| **Strategy Tables** | ❌ | ❌ | ❌ | ✅ |
| **Oracle 23c Free** | ❌ | ❌ | ❌ | ✅ |

## Compression Types by Edition

### HCC (Exadata/ExaCC Only)
- QUERY LOW/HIGH
- ARCHIVE LOW/HIGH
- **NOT available in Oracle Free Edition**

### Available in Oracle 23c Free
- **BASIC** (Row Store Compress Basic)
- **OLTP** (Row Store Compress Advanced)
- **Advanced Index Compression**
- **SecureFile LOB Compression**

## Unified Implementation Strategy

### 1. Configurable Compression Strategies (Table-Driven)

**Three strategies stored in `T_COMPRESSION_STRATEGIES` table:**

```sql
STRATEGY_ID | STRATEGY_NAME        | DESCRIPTION
----------- | -------------------- | -----------
1           | HIGH_PERFORMANCE     | Minimal compression overhead
2           | BALANCED             | Balance space/performance
3           | MAXIMUM_COMPRESSION  | Maximum space savings

Strategy Rules stored in `T_STRATEGY_RULES` table:
- Hotness thresholds
- DML ratio thresholds
- Compression type mappings
- Size thresholds
```

### 2. Adapted for Oracle 23c Free

**Compression Mapping:**
```
HCC QUERY LOW    → OLTP (Row Store Compress Advanced)
HCC QUERY HIGH   → OLTP (Row Store Compress Advanced)
HCC ARCHIVE LOW  → BASIC (Row Store Compress Basic)
HCC ARCHIVE HIGH → BASIC (Row Store Compress Basic)
OLTP            → OLTP (unchanged)
```

### 3. Architecture

```
┌─────────────────────────────────────────────────┐
│  Streamlit Dashboard (Python + SSL)             │
│  - Password Auth                                │
│  - Scenario Reports                             │
│  - Execution History                            │
│  - Schedule Management                          │
└─────────────────┬───────────────────────────────┘
                  │ HTTPS (oracledb client)
                  ↓
┌─────────────────────────────────────────────────┐
│  ORDS REST API Layer                            │
│  /compression/v1/analyze                        │
│  /compression/v1/recommendations                │
│  /compression/v1/execute                        │
│  /compression/v1/history                        │
│  /compression/v1/strategies                     │
└─────────────────┬───────────────────────────────┘
                  │
                  ↓
┌─────────────────────────────────────────────────┐
│  PL/SQL Packages                                │
│  - PKG_COMPRESSION_ADVISOR (Analysis)           │
│  - PKG_COMPRESSION_EXECUTOR (Execution)         │
│  - PKG_COMPRESSION_STRATEGY (Config)            │
└─────────────────┬───────────────────────────────┘
                  │
                  ↓
┌─────────────────────────────────────────────────┐
│  Repository Tables                              │
│  - T_COMPRESSION_STRATEGIES                     │
│  - T_STRATEGY_RULES                             │
│  - T_COMPRESSION_ANALYSIS                       │
│  - T_INDEX_ANALYSIS                             │
│  - T_LOB_ANALYSIS                               │
│  - T_COMPRESSION_HISTORY                        │
└─────────────────────────────────────────────────┘
```

### 4. Key Improvements

1. **Table-Driven Configuration**: Strategies loaded as global variables from tables
2. **Oracle 23c Free Compatible**: No HCC dependencies, fallback to BASIC/OLTP
3. **Comprehensive Testing**: Docker-based test environment included
4. **Production-Ready**: Complete error handling, logging, audit trail
5. **ORDS Integration**: Full REST API with cURL examples
6. **Streamlit Dashboard**: Modern web UI with SSL support
7. **Extended Object Support**: Tables, Indexes, LOBs, IOTs
8. **Parallel Processing**: Optional parallel analysis execution
9. **Flexible Scheduling**: DBMS_SCHEDULER integration
10. **Strategy Management**: Runtime-configurable without code changes

### 5. Deliverables

```
/HCC-CompAdvisor/
├── docker/
│   ├── Dockerfile                  # Oracle 23c Free setup
│   ├── docker-compose.yml          # Complete stack
│   └── init-scripts/
│       ├── 01-create-tablespace.sql
│       ├── 02-create-schema.sql
│       ├── 03-install-packages.sql
│       ├── 04-load-strategies.sql
│       └── 05-configure-ords.sql
├── sql/
│   ├── install_full.sql            # Master installation
│   ├── uninstall.sql               # Clean removal
│   ├── 01_schema.sql               # Tables & sequences
│   ├── 02_strategies.sql           # Strategy tables & data
│   ├── 03_advisor_pkg.sql          # Analysis package
│   ├── 04_executor_pkg.sql         # Execution package
│   ├── 05_strategy_pkg.sql         # Strategy management
│   ├── 06_views.sql                # Reporting views
│   └── 07_ords.sql                 # REST endpoints
├── python/
│   ├── dashboard/
│   │   ├── app.py                  # Main Streamlit app
│   │   ├── config.py               # Configuration
│   │   ├── auth.py                 # Authentication
│   │   ├── pages/
│   │   │   ├── 01_analysis.py
│   │   │   ├── 02_recommendations.py
│   │   │   ├── 03_execution.py
│   │   │   ├── 04_history.py
│   │   │   └── 05_strategies.py
│   │   ├── utils/
│   │   │   ├── db_connector.py     # oracledb client
│   │   │   └── api_client.py       # ORDS REST client
│   │   └── ssl/
│   │       ├── generate_cert.sh
│   │       ├── cert.pem
│   │       └── key.pem
│   └── requirements.txt
├── tests/
│   ├── test_analysis.sql
│   ├── test_execution.sql
│   ├── test_strategies.sql
│   └── test_ords.sh                # cURL tests
└── docs/
    ├── INSTALLATION.md
    ├── USER_GUIDE.md
    ├── API_REFERENCE.md
    └── STRATEGY_GUIDE.md
```

## Components

### Core PL/SQL
- ✅ Schema objects (tables, sequences)
- ✅ Strategy tables and default data
- ✅ PKG_COMPRESSION_ADVISOR (analysis engine)
- ✅ PKG_COMPRESSION_EXECUTOR (execution engine)
- ✅ PKG_COMPRESSION_STRATEGY (config management)

### ORDS & Testing
- ✅ REST endpoint configuration
- ✅ Docker container setup (Oracle 23c Free)
- ✅ Compilation and unit tests
- ✅ Integration testing

### Streamlit Dashboard
- ✅ Dashboard application
- ✅ SSL certificate generation
- ✅ Authentication layer
- ✅ ORDS REST client
- ✅ UI pages (Analysis, Recommendations, Execution, History, Strategies)

### Documentation & Deployment
- ✅ Installation guide
- ✅ User guide
- ✅ API reference with examples
- ✅ Strategy configuration guide

## Available Features

1. ✅ Unified SQL installation scripts
2. ✅ 3 table-driven compression strategies
3. ✅ Oracle 23c Free compatibility (no HCC)
4. ✅ ORDS endpoints
5. ✅ Streamlit dashboard with SSL
6. ✅ Docker environment
7. ✅ Comprehensive documentation
8. ✅ Complete stack testing
