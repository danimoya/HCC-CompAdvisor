# HCC Compression Advisor - Developer Guide

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Development Setup](#development-setup)
3. [Code Structure](#code-structure)
4. [Testing Procedures](#testing-procedures)
5. [Contributing Guidelines](#contributing-guidelines)
6. [Code Standards](#code-standards)
7. [Extension Points](#extension-points)

## Architecture Overview

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Streamlit Dashboard                       │
│         (Python/Streamlit with oracledb client)             │
└────────────────┬────────────────────────────────────────────┘
                 │ HTTPS (REST API)
                 ▼
┌─────────────────────────────────────────────────────────────┐
│                    ORDS REST Layer                          │
│           (/compression/v1/* endpoints)                      │
└────────────────┬────────────────────────────────────────────┘
                 │ SQL/JSON
                 ▼
┌─────────────────────────────────────────────────────────────┐
│             PL/SQL Business Logic Layer                      │
│  ┌──────────────────────────┬──────────────────────────┐   │
│  │ PKG_COMPRESSION_ANALYZER │ PKG_COMPRESSION_EXECUTOR │   │
│  │ - Analyze tables         │ - Compress tables        │   │
│  │ - Calculate ratios       │ - Execute batch ops      │   │
│  │ - Generate recommendations│ - Track history          │   │
│  └──────────────────────────┴──────────────────────────┘   │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│                    Data Layer                                │
│  ┌──────────────────┬──────────────────┬────────────────┐  │
│  │ COMPRESSION_     │ COMPRESSION_     │ Configuration  │  │
│  │ ANALYSIS         │ HISTORY          │ Tables         │  │
│  └──────────────────┴──────────────────┴────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │            Materialized Views                          │  │
│  │  - V_COMPRESSION_CANDIDATES                            │  │
│  │  - V_COMPRESSION_SUMMARY                               │  │
│  │  - V_SPACE_SAVINGS                                     │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│              Oracle Database 19c (PDB)                      │
│         with Advanced Compression & HCC                     │
└─────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

#### 1. Analysis Layer (PKG_COMPRESSION_ANALYZER)
- **Purpose**: Evaluate compression opportunities
- **Key Functions**:
  - Sample data using DBMS_COMPRESSION.GET_COMPRESSION_RATIO
  - Calculate activity metrics (hot score, DML ratios)
  - Generate compression recommendations
  - Store results in COMPRESSION_ANALYSIS table

#### 2. Execution Layer (PKG_COMPRESSION_EXECUTOR)
- **Purpose**: Apply compression operations
- **Key Functions**:
  - Execute ALTER TABLE ... COMPRESS operations
  - Handle online/offline compression modes
  - Rebuild indexes automatically
  - Track operation history and metrics

#### 3. REST API Layer (ORDS)
- **Purpose**: Expose functionality via HTTP
- **Endpoints**:
  - `/advisor/tables` - Run analysis
  - `/analysis/:owner/:table` - Get results
  - `/execute` - Execute compression
  - `/recommendations` - Get recommendations
  - `/history/:id` - Get operation history

#### 4. Dashboard Layer (Streamlit)
- **Purpose**: User interface for management
- **Features**:
  - Connection management
  - Table listing and filtering
  - Compression scenario simulation
  - History and monitoring views

### Data Flow

```
1. User initiates analysis (via Dashboard or SQL)
2. PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES() called
3. For each table:
   a. Sample data using DBMS_COMPRESSION
   b. Test 5 compression types (OLTP, Query Low/High, Archive Low/High)
   c. Query DML statistics from ALL_TAB_MODIFICATIONS
   d. Calculate hot score from V$SEGMENT_STATISTICS
   e. Determine optimal compression type
   f. Store results in COMPRESSION_ANALYSIS
4. User reviews recommendations (V_COMPRESSION_CANDIDATES)
5. User executes compression (PKG_COMPRESSION_EXECUTOR.COMPRESS_TABLE)
6. System applies compression:
   a. Record start time and original size
   b. Execute ALTER TABLE ... MOVE COMPRESS
   c. Rebuild indexes if needed
   d. Record end time and new size
   e. Store metrics in COMPRESSION_HISTORY
7. User monitors results (V_COMPRESSION_HISTORY, V_SPACE_SAVINGS)
```

## Development Setup

### Prerequisites

- Oracle Database 19c or higher (with Advanced Compression)
- Oracle SQL Developer or equivalent IDE
- Python 3.8+ (for dashboard development)
- Git for version control

### Local Development Environment

#### 1. Database Setup

```sql
-- Create development PDB
CREATE PLUGGABLE DATABASE pdb_dev
  ADMIN USER pdb_admin IDENTIFIED BY <password>
  FILE_NAME_CONVERT=('/pdbseed/', '/pdb_dev/');

ALTER PLUGGABLE DATABASE pdb_dev OPEN;
ALTER PLUGGABLE DATABASE pdb_dev SAVE STATE;

-- Connect to development PDB
CONN sys/<password>@localhost:1521/pdb_dev AS SYSDBA

-- Create development schema
@install_compression_system.sql
```

#### 2. Python Development Environment

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# requirements.txt contents:
# oracledb==1.4.0
# streamlit==1.28.0
# pandas==2.1.0
# plotly==5.17.0
# python-dotenv==1.0.0
```

#### 3. Configuration

Create `.env` file:
```bash
# Database connection
DB_USER=compression_mgr
DB_PASSWORD=<password>
DB_HOST=localhost
DB_PORT=1521
DB_SERVICE=pdb_dev

# ORDS configuration
ORDS_BASE_URL=https://localhost:8443/ords/compression/v1
ORDS_API_KEY=<api_key>

# Application settings
APP_PORT=8501
DEBUG_MODE=True
```

### Project Structure

```
HCC-CompAdvisor/
├── README.md
├── CLAUDE.md
├── .gitignore
├── docs/
│   ├── user-guide.md
│   ├── api-reference.md
│   ├── admin-guide.md
│   ├── developer-guide.md
│   └── operations-runbook.md
├── database/
│   ├── schema/
│   │   ├── 01_tables.sql
│   │   ├── 02_sequences.sql
│   │   ├── 03_indexes.sql
│   │   └── 04_views.sql
│   ├── packages/
│   │   ├── pkg_compression_analyzer_spec.sql
│   │   ├── pkg_compression_analyzer_body.sql
│   │   ├── pkg_compression_executor_spec.sql
│   │   └── pkg_compression_executor_body.sql
│   ├── ords/
│   │   └── compression_module.sql
│   ├── install/
│   │   ├── install_compression_system.sql
│   │   └── uninstall_compression_system.sql
│   └── tests/
│       ├── test_analyzer.sql
│       └── test_executor.sql
├── dashboard/
│   ├── app.py
│   ├── pages/
│   │   ├── 1_Analysis.py
│   │   ├── 2_Recommendations.py
│   │   └── 3_History.py
│   ├── components/
│   │   ├── db_connection.py
│   │   ├── charts.py
│   │   └── utils.py
│   └── requirements.txt
├── tests/
│   ├── unit/
│   │   ├── test_analyzer.py
│   │   └── test_executor.py
│   └── integration/
│       └── test_end_to_end.py
└── scripts/
    ├── deploy.sh
    ├── backup.sh
    └── health_check.sh
```

## Code Structure

### PL/SQL Package Structure

#### PKG_COMPRESSION_ANALYZER Structure

```sql
CREATE OR REPLACE PACKAGE PKG_COMPRESSION_ANALYZER AS
    -- Package metadata
    VERSION CONSTANT VARCHAR2(20) := '1.0.0';

    -- Public types
    TYPE t_compression_recommendation IS RECORD (
        owner                VARCHAR2(128),
        table_name          VARCHAR2(128),
        advisable_compression VARCHAR2(30),
        estimated_savings_mb NUMBER,
        hot_score           NUMBER
    );
    TYPE t_recommendation_list IS TABLE OF t_compression_recommendation;

    -- Public procedures/functions
    PROCEDURE ANALYZE_ALL_TABLES(...);
    PROCEDURE ANALYZE_SPECIFIC_TABLE(...);
    FUNCTION GET_RECOMMENDATIONS(...) RETURN t_recommendation_list PIPELINED;

    -- Private procedures (in body only)
    -- FUNCTION calculate_compression_ratio(...)
    -- PROCEDURE gather_dml_statistics(...)
END PKG_COMPRESSION_ANALYZER;
```

**Coding Patterns**:

1. **Separation of Concerns**
   - Public API in specification
   - Implementation details in body
   - Helper functions as private procedures

2. **Error Handling**
   ```sql
   EXCEPTION
       WHEN NO_DATA_FOUND THEN
           -- Log error
           LOG_ERROR('No data found for table: ' || p_table_name);
           RETURN NULL;
       WHEN OTHERS THEN
           -- Log unexpected errors
           LOG_ERROR('Unexpected error: ' || SQLERRM);
           RAISE;
   ```

3. **Resource Management**
   ```sql
   -- Always clean up cursors
   IF cursor%ISOPEN THEN
       CLOSE cursor;
   END IF;

   -- Always commit/rollback
   COMMIT;  -- or ROLLBACK in exception handler
   ```

### Python Dashboard Structure

#### Main Application (`app.py`)

```python
import streamlit as st
import oracledb
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Database connection pool
@st.cache_resource
def get_connection_pool():
    return oracledb.create_pool(
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        dsn=f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_SERVICE')}",
        min=2,
        max=10,
        increment=1
    )

# Main dashboard
def main():
    st.set_page_config(
        page_title="HCC Compression Advisor",
        page_icon="🗜️",
        layout="wide"
    )

    st.title("HCC Compression Advisor Dashboard")

    # Sidebar navigation
    with st.sidebar:
        st.header("Navigation")
        page = st.radio("Go to", ["Overview", "Analysis", "Recommendations", "History"])

    # Load selected page
    if page == "Overview":
        show_overview()
    elif page == "Analysis":
        show_analysis()
    # ... etc

if __name__ == "__main__":
    main()
```

#### Database Component (`components/db_connection.py`)

```python
import oracledb
from typing import List, Dict, Any

class CompressionDB:
    """Database interface for compression advisor"""

    def __init__(self, connection_pool):
        self.pool = connection_pool

    def get_recommendations(self, min_ratio: float = 1.5, min_size_mb: float = 100) -> List[Dict[str, Any]]:
        """Fetch compression recommendations"""
        with self.pool.acquire() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT owner, table_name, advisable_compression,
                           estimated_savings_mb, hot_score
                    FROM TABLE(PKG_COMPRESSION_ANALYZER.GET_RECOMMENDATIONS(:1, :2))
                    ORDER BY estimated_savings_mb DESC
                """, [min_ratio, min_size_mb])

                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def execute_compression(self, owner: str, table_name: str, compression_type: str = None) -> Dict[str, Any]:
        """Execute compression on a table"""
        with self.pool.acquire() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.callproc('PKG_COMPRESSION_EXECUTOR.COMPRESS_TABLE', [
                        owner,
                        table_name,
                        compression_type,  # NULL uses recommendation
                        True,  # online
                        True   # log_operation
                    ])
                    conn.commit()
                    return {"status": "SUCCESS", "message": "Compression initiated"}
                except Exception as e:
                    conn.rollback()
                    return {"status": "ERROR", "message": str(e)}

    # Additional methods for other operations...
```

## Testing Procedures

### Unit Testing (PL/SQL)

```sql
-- Test suite for PKG_COMPRESSION_ANALYZER
CREATE OR REPLACE PACKAGE test_compression_analyzer AS
    PROCEDURE run_all_tests;
    PROCEDURE test_hot_score_calculation;
    PROCEDURE test_recommendation_logic;
END;
/

CREATE OR REPLACE PACKAGE BODY test_compression_analyzer AS

    -- Test framework using simple assertions
    PROCEDURE assert_equals(p_expected IN NUMBER, p_actual IN NUMBER, p_message IN VARCHAR2) IS
    BEGIN
        IF p_expected != p_actual THEN
            RAISE_APPLICATION_ERROR(-20001, p_message ||
                ' - Expected: ' || p_expected || ', Actual: ' || p_actual);
        ELSE
            DBMS_OUTPUT.PUT_LINE('✓ ' || p_message);
        END IF;
    END;

    PROCEDURE test_hot_score_calculation IS
        v_score NUMBER;
    BEGIN
        -- Test case 1: High activity
        v_score := PKG_COMPRESSION_ANALYZER.CALCULATE_HOT_SCORE(
            p_inserts => 100000,
            p_updates => 50000,
            p_deletes => 25000,
            p_segment_size_mb => 1024
        );
        assert_equals(85, ROUND(v_score), 'High activity should yield high score');

        -- Test case 2: Low activity
        v_score := PKG_COMPRESSION_ANALYZER.CALCULATE_HOT_SCORE(
            p_inserts => 100,
            p_updates => 50,
            p_deletes => 25,
            p_segment_size_mb => 10240
        );
        assert_equals(5, ROUND(v_score), 'Low activity should yield low score');

        DBMS_OUTPUT.PUT_LINE('All hot score tests passed!');
    END;

    PROCEDURE run_all_tests IS
    BEGIN
        DBMS_OUTPUT.PUT_LINE('Running compression analyzer test suite...');
        test_hot_score_calculation;
        test_recommendation_logic;
        DBMS_OUTPUT.PUT_LINE('All tests completed successfully!');
    END;

END test_compression_analyzer;
/

-- Run tests
SET SERVEROUTPUT ON
EXEC test_compression_analyzer.run_all_tests;
```

### Integration Testing (Python)

```python
# tests/integration/test_end_to_end.py
import pytest
import oracledb
from components.db_connection import CompressionDB

@pytest.fixture
def db_connection():
    """Create test database connection"""
    pool = oracledb.create_pool(
        user="compression_mgr_test",
        password="test_password",
        dsn="localhost:1521/pdb_test",
        min=1, max=2
    )
    yield CompressionDB(pool)
    pool.close()

def test_full_analysis_workflow(db_connection):
    """Test complete analysis and compression workflow"""

    # Step 1: Create test table
    with db_connection.pool.acquire() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE test_compress_table AS
            SELECT * FROM all_objects WHERE rownum <= 10000
        """)
        conn.commit()

    # Step 2: Run analysis
    db_connection.execute_sql(
        "BEGIN PKG_COMPRESSION_ANALYZER.ANALYZE_SPECIFIC_TABLE(:1, :2); END;",
        ["COMPRESSION_MGR_TEST", "TEST_COMPRESS_TABLE"]
    )

    # Step 3: Get recommendations
    recommendations = db_connection.get_recommendations()
    assert len(recommendations) > 0, "Should have at least one recommendation"

    # Step 4: Execute compression
    result = db_connection.execute_compression(
        owner="COMPRESSION_MGR_TEST",
        table_name="TEST_COMPRESS_TABLE"
    )
    assert result["status"] == "SUCCESS", "Compression should succeed"

    # Step 5: Verify results
    history = db_connection.get_compression_history(limit=1)
    assert history[0]["execution_status"] == "SUCCESS"
    assert history[0]["space_saved_mb"] > 0, "Should have saved space"

    # Cleanup
    with db_connection.pool.acquire() as conn:
        cursor = conn.cursor()
        cursor.execute("DROP TABLE test_compress_table PURGE")
        conn.commit()

def test_error_handling(db_connection):
    """Test error handling for invalid operations"""

    # Test compressing non-existent table
    result = db_connection.execute_compression(
        owner="COMPRESSION_MGR_TEST",
        table_name="NONEXISTENT_TABLE"
    )
    assert result["status"] == "ERROR", "Should fail for non-existent table"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

### Load Testing

```python
# tests/load/test_concurrent_compression.py
import concurrent.futures
import time
from components.db_connection import CompressionDB

def test_concurrent_compressions():
    """Test system under concurrent compression load"""

    db = CompressionDB(get_connection_pool())

    # Create 10 test tables
    tables = [f"LOAD_TEST_TABLE_{i}" for i in range(10)]

    def compress_table(table_name):
        start = time.time()
        result = db.execute_compression(
            owner="COMPRESSION_MGR_TEST",
            table_name=table_name
        )
        duration = time.time() - start
        return {"table": table_name, "duration": duration, "result": result}

    # Execute compressions concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(compress_table, tables))

    # Analyze results
    successful = sum(1 for r in results if r["result"]["status"] == "SUCCESS")
    avg_duration = sum(r["duration"] for r in results) / len(results)

    print(f"Successful compressions: {successful}/{len(tables)}")
    print(f"Average duration: {avg_duration:.2f} seconds")

    assert successful == len(tables), "All compressions should succeed"
    assert avg_duration < 60, "Average compression should complete under 60 seconds"
```

## Contributing Guidelines

### Git Workflow

1. **Branch Naming**
   - Feature: `feature/description`
   - Bug fix: `bugfix/issue-number-description`
   - Hotfix: `hotfix/critical-issue`

2. **Commit Messages**
   ```
   [TYPE] Short description (50 chars max)

   Detailed explanation of changes (optional)
   - Bullet points for multiple changes
   - Reference issue numbers: Fixes #123

   [TYPE] can be:
   - feat: New feature
   - fix: Bug fix
   - docs: Documentation
   - refactor: Code refactoring
   - test: Adding tests
   - perf: Performance improvement
   ```

3. **Pull Request Process**
   - Create feature branch from `develop`
   - Implement changes with tests
   - Run full test suite
   - Update documentation
   - Submit PR with description
   - Address code review feedback
   - Squash and merge when approved

### Code Review Checklist

**PL/SQL Code**:
- [ ] Exception handling in place
- [ ] Resource cleanup (cursors, temp tables)
- [ ] Appropriate commit/rollback
- [ ] Logging for debugging
- [ ] Performance considerations (bulk operations, indexes)
- [ ] Documentation comments
- [ ] Unit tests included

**Python Code**:
- [ ] Type hints used
- [ ] Docstrings present
- [ ] Error handling
- [ ] Connection pool management
- [ ] SQL injection prevention
- [ ] Unit tests included
- [ ] PEP 8 compliance

## Code Standards

### PL/SQL Coding Standards

```sql
-- Use consistent naming conventions
PKG_<domain>_<purpose>  -- Packages
t_<name>                -- Types
v_<name>                -- Local variables
p_<name>                -- Parameters
c_<name>                -- Constants
g_<name>                -- Global variables

-- Always include header comments
/*
 * Package: PKG_COMPRESSION_ANALYZER
 * Purpose: Analyze database objects for compression opportunities
 * Author: Development Team
 * Created: 2025-01-13
 * Version: 1.0.0
 */

-- Use meaningful variable names
v_compression_ratio NUMBER;  -- Good
v_cr NUMBER;                  -- Bad

-- Format SQL for readability
SELECT
    owner,
    table_name,
    ROUND(bytes / 1024 / 1024, 2) AS size_mb
FROM dba_segments
WHERE owner = p_owner
  AND segment_type = 'TABLE'
ORDER BY size_mb DESC;

-- Use bulk operations for performance
FORALL i IN 1..l_table_names.COUNT
    INSERT INTO compression_analysis VALUES l_analysis_records(i);

-- Always handle exceptions
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        -- Specific handling
    WHEN OTHERS THEN
        -- Log and re-raise
        log_error(SQLERRM);
        RAISE;
```

### Python Coding Standards

```python
# Use type hints
def get_recommendations(
    self,
    min_ratio: float = 1.5,
    min_size_mb: float = 100
) -> List[Dict[str, Any]]:
    """
    Fetch compression recommendations from database.

    Args:
        min_ratio: Minimum compression ratio threshold
        min_size_mb: Minimum table size in megabytes

    Returns:
        List of dictionaries containing recommendation data

    Raises:
        DatabaseError: If database query fails
    """
    pass

# Use context managers for resources
with self.pool.acquire() as conn:
    with conn.cursor() as cursor:
        # Use cursor
        pass
    # Auto-closed

# Use meaningful variable names
compression_candidates = db.get_candidates()  # Good
cc = db.get_candidates()                       # Bad

# Format imports
import os
import sys
from typing import List, Dict, Any

import oracledb
import streamlit as st

from components.db_connection import CompressionDB
```

## Extension Points

### Adding New Compression Types

```sql
-- 1. Add new compression type constant
c_compression_type_custom CONSTANT VARCHAR2(30) := 'CUSTOM_COMPRESSION';

-- 2. Extend recommendation logic
FUNCTION determine_compression_type(...) RETURN VARCHAR2 IS
BEGIN
    -- Add custom logic
    IF <custom_condition> THEN
        RETURN 'CUSTOM_COMPRESSION';
    END IF;
    -- ... existing logic
END;

-- 3. Update executor to handle new type
PROCEDURE compress_table(...) IS
BEGIN
    v_compression_clause := CASE p_compression_type
        WHEN 'CUSTOM_COMPRESSION' THEN 'COMPRESS FOR CUSTOM'
        -- ... existing cases
    END CASE;
END;
```

### Custom Analysis Metrics

```sql
-- Add custom metric calculation
FUNCTION calculate_custom_metric(
    p_owner IN VARCHAR2,
    p_table_name IN VARCHAR2
) RETURN NUMBER IS
    v_metric NUMBER;
BEGIN
    -- Custom metric calculation logic
    SELECT <custom_calculation>
    INTO v_metric
    FROM <custom_source>;

    RETURN v_metric;
END;

-- Integrate into analysis
UPDATE compression_analysis
SET custom_metric = calculate_custom_metric(owner, table_name)
WHERE owner = p_owner AND table_name = p_table_name;
```

### Dashboard Extensions

```python
# Add custom visualization
def show_custom_analysis():
    """Custom analysis visualization"""
    st.header("Custom Analysis")

    # Fetch custom data
    data = db.execute_sql("SELECT * FROM v_custom_analysis")

    # Create custom chart
    fig = create_custom_chart(data)
    st.plotly_chart(fig)

# Register in main app
# In app.py navigation:
elif page == "Custom Analysis":
    show_custom_analysis()
```

---

**Document Version**: 1.0
**Last Updated**: 2025-01-13
**Author**: Daniel Moya (copyright)
**GitHub**: [github.com/danimoya](https://github.com/danimoya)
**Website**: [danielmoya.cv](https://danielmoya.cv)
