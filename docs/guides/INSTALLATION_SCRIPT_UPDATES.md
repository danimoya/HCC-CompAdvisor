# Installation Script Updates

## Summary of Changes to install_full.sql

The master installation script has been enhanced to include all new components with improved error handling, progress reporting, and validation.

### Components Added

1. **01a_schema_fixes.sql** - Schema enhancements and fixes
   - Position: After 01_schema.sql
   - Adds missing constraints, indexes, and table modifications

2. **02a_logging_pkg.sql** - Logging foundation package
   - Position: Before all other packages (first in package section)
   - Provides centralized logging for all other packages

3. **02b_exadata_detection.sql** - Exadata platform detection
   - Position: Before HCC_ADVISOR_PKG
   - Detects Exadata platform and HCC capabilities

4. **validate_installation.sql** - Installation validation
   - Position: End of post-installation tasks
   - Comprehensive validation of all installed components

### Enhanced Features

#### 1. Progress Reporting
```
Progress: [####################] 10% Complete  - Pre-installation validation
Progress: [########------------] 30% Complete  - Core schema objects
Progress: [##########----------] 40% Complete  - Reference data
Progress: [##############------] 60% Complete  - PL/SQL packages
Progress: [################----] 70% Complete  - Views
Progress: [###################-] 90% Complete  - Post-installation
Progress: [####################] 100% Complete - Installation complete
```

#### 2. Component Overview
Installation header now shows all components being installed:
- Core Schema Objects (tables, sequences, indexes)
- Schema Fixes and Enhancements
- Compression Strategies Reference Data
- Logging Package (foundation)
- Exadata Detection Package
- HCC Advisor Package (main logic)
- Compression Executor Package
- Reporting Views
- REST API Modules (if ORDS available)
- Installation Validation

#### 3. Enhanced Package Verification
Updated to verify all 4 packages (8 objects including bodies):
- HCC_LOGGING_PKG (foundation)
- HCC_EXADATA_PKG (detection)
- HCC_ADVISOR_PKG (main logic)
- HCC_EXECUTOR_PKG (execution)

#### 4. Rollback Instructions
Added comprehensive rollback section for failed installations.

### Installation Order

1. **Pre-Installation Validation** (10%)
   - Database version check
   - HCC support verification
   - Privilege verification
   - Tablespace quota check

2. **Core Schema** (30%)
   - 01_schema.sql - Base tables, sequences, indexes
   - 01a_schema_fixes.sql - Enhancements and fixes

3. **Reference Data** (40%)
   - 02_strategies.sql - Compression strategies

4. **PL/SQL Packages** (60%)
   - 02a_logging_pkg.sql - Logging foundation
   - 02b_exadata_detection.sql - Platform detection
   - 03_advisor_pkg.sql - Main advisor logic
   - 04_executor_pkg.sql - Compression execution

5. **Views** (70%)
   - 05_views.sql - Reporting views

6. **REST API** (Optional)
   - 06_ords.sql - REST API modules

7. **Post-Installation** (90%)
   - Schema recompilation
   - Statistics gathering
   - validate_installation.sql - Comprehensive validation

8. **Summary** (100%)
   - Object inventory
   - Invalid object report
   - Next steps guidance

### Error Handling

- WHENEVER SQLERROR EXIT FAILURE during critical sections
- Validation checks after each major section
- Detailed error reporting in install_full.log
- Automatic rollback guidance on failure

### Usage

Standard installation:
```bash
sqlplus user/password@database @install_full.sql
```

Review results:
```bash
cat install_full.log
```

### Prerequisites

- Oracle Database 19c or later
- SYSDBA or schema owner privileges
- ORDS installed (for REST API installation)
- Minimum 100MB tablespace quota

### Post-Installation

1. Review install_full.log for any warnings or errors
2. Run validation queries
3. Test basic functionality
4. Configure advisor settings if needed
5. Set up ORDS REST API if required

### Troubleshooting

If installation fails:
1. Check install_full.log for specific errors
2. Verify all prerequisites are met
3. Run rollback instructions
4. Fix any issues
5. Re-run installation

For common issues, see docs/TROUBLESHOOTING.md
