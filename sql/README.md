# SQL Scripts Directory

This directory contains the database schema and SQL scripts for the HCC Compression Advisor system, adapted for Oracle 23c Free.

## Files

### Core Schema
- **01_schema.sql** (1004 lines, 35KB)
  - Complete database schema creation
  - Strategy configuration tables
  - Analysis result tables
  - Execution history tracking
  - Advisor run management
  - Includes verification queries

### Documentation
- **SCHEMA_SUMMARY.md** (9.2KB)
  - Comprehensive schema documentation
  - Table descriptions and design decisions
  - Comparison with original examples
  - Migration notes from HCC to Oracle 23c Free

- **QUICK_REFERENCE.md** (9.8KB)
  - Quick reference guide
  - Common queries and patterns
  - Maintenance procedures
  - Testing queries
  - Performance tuning tips

## Installation Order

### 1. Create Schema Owner (as SYSDBA)
```sql
-- Connect as SYSDBA
sqlplus sys/password@FREEPDB1 as sysdba

-- Create user/schema
CREATE USER compression_mgr IDENTIFIED BY secure_password
  DEFAULT TABLESPACE users
  TEMPORARY TABLESPACE temp
  QUOTA UNLIMITED ON users;

-- Grant privileges
GRANT CREATE SESSION TO compression_mgr;
GRANT CREATE TABLE TO compression_mgr;
GRANT CREATE SEQUENCE TO compression_mgr;
GRANT CREATE VIEW TO compression_mgr;
GRANT CREATE PROCEDURE TO compression_mgr;
GRANT SELECT ANY DICTIONARY TO compression_mgr;
GRANT EXECUTE ON DBMS_COMPRESSION TO compression_mgr;
GRANT EXECUTE ON DBMS_STATS TO compression_mgr;
GRANT EXECUTE ON DBMS_LOCK TO compression_mgr;
```

### 2. Install Schema
```sql
-- Connect as schema owner
sqlplus compression_mgr/secure_password@FREEPDB1

-- Execute schema creation
@01_schema.sql
```

### 3. Verify Installation
```sql
-- Check objects created
SELECT object_type, COUNT(*)
FROM user_objects
WHERE object_name LIKE 'T_%COMPRESS%'
GROUP BY object_type;

-- Verify default strategies
SELECT strategy_name, category, is_default
FROM t_compression_strategies;
```

## Database Requirements

### Version
- Oracle Database 23c Free or higher
- Oracle Database 19c+ (with minor adaptations)

### Privileges Required
- CREATE TABLE
- CREATE SEQUENCE
- CREATE INDEX
- SELECT ANY DICTIONARY (for analysis queries)
- EXECUTE on DBMS_COMPRESSION
- EXECUTE on DBMS_STATS

### Tablespace
- Minimum 100MB for initial setup
- Growth depends on number of objects analyzed

## Schema Overview

### Tables Created (7)
1. **T_COMPRESSION_STRATEGIES** - Strategy configurations
2. **T_STRATEGY_RULES** - Detailed strategy rules
3. **T_COMPRESSION_ANALYSIS** - Table/IOT analysis results
4. **T_INDEX_COMPRESSION_ANALYSIS** - Index analysis
5. **T_LOB_COMPRESSION_ANALYSIS** - LOB analysis
6. **T_COMPRESSION_HISTORY** - Execution history
7. **T_ADVISOR_RUN** - Analysis session tracking

### Sequences Created (1)
1. **SEQ_EXECUTION_ID** - Execution batch identifier

### Indexes Created (17)
- B-tree indexes for performance
- Bitmap indexes for analytics
- Unique indexes for constraints

### Default Data
- 3 compression strategies:
  - BALANCED_PRODUCTION (default)
  - HIGH_PERFORMANCE
  - MAXIMUM_COMPRESSION

## Supported Compression Types

### Oracle 23c Free (No HCC)
✅ **BASIC** - ROW STORE COMPRESS BASIC
✅ **OLTP** - ROW STORE COMPRESS ADVANCED
✅ **ADV_LOW** - COLUMN STORE COMPRESS FOR QUERY LOW*
✅ **ADV_HIGH** - COLUMN STORE COMPRESS FOR QUERY HIGH*

*Requires Advanced Compression Option license

### Not Supported (HCC)
❌ QUERY LOW - HCC (Exadata/ZFS only)
❌ QUERY HIGH - HCC (Exadata/ZFS only)
❌ ARCHIVE LOW - HCC (Exadata/ZFS only)
❌ ARCHIVE HIGH - HCC (Exadata/ZFS only)

## Key Features

### 1. Strategy Configuration
- Flexible threshold configuration
- Multiple strategies support
- Hot/Warm/Cool/Cold categorization
- Custom rule definitions

### 2. Comprehensive Analysis
- Table compression analysis
- Index compression analysis
- LOB compression analysis
- Hotness scoring (0-100)
- Space savings projections

### 3. Complete Audit Trail
- Before/after metrics
- Space savings tracking
- Performance metrics
- Error tracking
- Rollback support

### 4. Modern Oracle Features
- Identity columns
- Virtual columns
- Bitmap indexes
- Check constraints
- Foreign key cascades

## Next Steps

After installing the schema:

1. **Install PL/SQL Packages** (future)
   - Compression analysis package
   - Compression execution package
   - Reporting package

2. **Create Views** (future)
   - Compression candidates view
   - Space savings summary view
   - Execution status view

3. **Test Suite** (future)
   - Unit tests
   - Integration tests
   - Performance tests

## Maintenance

### Regular Tasks
- Gather statistics weekly
- Cleanup old analysis data (>90 days)
- Archive execution history (>180 days)
- Monitor index fragmentation

### Statistics Collection
```sql
BEGIN
    DBMS_STATS.GATHER_SCHEMA_STATS(
        ownname => 'COMPRESSION_MGR',
        cascade => TRUE
    );
END;
/
```

### Data Cleanup
```sql
-- Delete old analysis results
DELETE FROM t_compression_analysis
WHERE analysis_date < SYSDATE - 90;

-- Archive old history
CREATE TABLE t_compression_history_archive AS
SELECT * FROM t_compression_history
WHERE start_time < SYSTIMESTAMP - INTERVAL '180' DAY;

DELETE FROM t_compression_history
WHERE start_time < SYSTIMESTAMP - INTERVAL '180' DAY;

COMMIT;
```

## Troubleshooting

### Common Issues

**Issue**: ORA-00955: name is already used by an existing object
**Solution**: Drop existing objects or use a different schema

**Issue**: ORA-01950: no privileges on tablespace
**Solution**: Grant quota on tablespace to schema owner

**Issue**: ORA-01031: insufficient privileges
**Solution**: Grant required system privileges (see Installation Order)

**Issue**: Invalid objects after installation
**Solution**: Check error messages, compile manually

### Verification Queries

```sql
-- Check for invalid objects
SELECT object_name, object_type, status
FROM user_objects
WHERE status != 'VALID'
  AND object_name LIKE 'T_%COMPRESS%';

-- Verify foreign keys
SELECT constraint_name, table_name, r_constraint_name
FROM user_constraints
WHERE constraint_type = 'R'
  AND table_name LIKE 'T_%COMPRESS%';

-- Check indexes
SELECT index_name, table_name, uniqueness, status
FROM user_indexes
WHERE table_name LIKE 'T_%COMPRESS%';
```

## Performance Expectations

### Schema Creation
- **Duration**: < 30 seconds
- **Objects**: 25+ objects created
- **Size**: ~1-5 MB initial footprint

### Analysis Performance
- **Small DB** (<10GB): < 5 minutes
- **Medium DB** (10-100GB): 10-30 minutes
- **Large DB** (>100GB): 30-60+ minutes

### Query Performance
- **Object lookup**: < 1 second
- **Summary reports**: < 5 seconds
- **Complex analytics**: 5-30 seconds

## Support

For issues or questions:
1. Review SCHEMA_SUMMARY.md for design details
2. Check QUICK_REFERENCE.md for common queries
3. Verify installation with verification queries
4. Check Oracle error codes and messages

## Version History

### 1.0.0 (2025-11-13)
- Initial schema creation
- Oracle 23c Free adaptation
- Strategy configuration framework
- Comprehensive analysis tables
- Complete audit trail
- 3 default strategies

## License

Part of the HCC Compression Advisor project.
See main project README for license information.

## Files Summary

| File | Size | Lines | Purpose |
|------|------|-------|---------|
| 01_schema.sql | 35KB | 1004 | Schema creation script |
| SCHEMA_SUMMARY.md | 9.2KB | - | Comprehensive documentation |
| QUICK_REFERENCE.md | 9.8KB | - | Quick reference guide |
| README.md | This file | - | Directory overview |

## Contact

For questions or contributions, please refer to the main project documentation.
