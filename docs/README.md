# HCC Compression Advisor - Documentation Index

## Overview

The HCC (Hybrid Columnar Compression) Compression Advisor is a comprehensive solution for Oracle Database compression management. This documentation suite provides complete guidance for users, administrators, developers, and operations teams.

## Documentation Structure

### 📘 [User Guide](user-guide.md)
**Audience**: Database users, application teams, analysts

**Topics Covered**:
- Getting started with the compression advisor
- Configuration of compression strategies (Conservative, Balanced, Aggressive)
- Using the analysis and execution features
- Understanding compression types and recommendations
- Troubleshooting common issues
- Frequently asked questions

**Key Sections**:
- ✓ Introduction and system requirements
- ✓ Quick start examples
- ✓ Strategy configuration
- ✓ Analyzing and compressing objects
- ✓ Monitoring operations
- ✓ Troubleshooting guide (12 common issues)
- ✓ FAQ (15+ questions)

---

### 📗 [API Reference](api-reference.md)
**Audience**: Developers, integration engineers

**Topics Covered**:
- Complete PL/SQL package APIs
- REST API endpoint specifications
- Database views and data structures
- Error codes and exception handling
- Usage examples and code samples

**Key Sections**:
- ✓ PKG_COMPRESSION_ANALYZER (7 procedures/functions)
- ✓ PKG_COMPRESSION_EXECUTOR (6 procedures/functions)
- ✓ REST API Endpoints (6 endpoints)
- ✓ Database Views (8 views)
- ✓ Data Structures (2 custom types)
- ✓ Error Codes (6 custom exceptions)

---

### 📕 [Administrator Guide](admin-guide.md)
**Audience**: Database administrators, system administrators

**Topics Covered**:
- Installation and deployment procedures
- Database and ExaCC configuration
- System maintenance tasks
- Monitoring and alerting setup
- Security and access control
- Performance tuning
- Backup and recovery

**Key Sections**:
- ✓ Installation (5-step deployment)
- ✓ Database setup (Oracle 19c, ExaCC)
- ✓ Configuration (3 compression strategies)
- ✓ Maintenance tasks (Daily, Weekly, Monthly, Quarterly)
- ✓ Monitoring setup (Views, alerts, AWR integration)
- ✓ Security (RBAC, auditing, encryption)
- ✓ Performance tuning
- ✓ Backup and recovery procedures

---

### 📙 [Developer Guide](developer-guide.md)
**Audience**: Developers, contributors, technical leads

**Topics Covered**:
- Architecture and design patterns
- Development environment setup
- Code structure and organization
- Testing procedures (unit, integration, load)
- Contributing guidelines
- Code standards and best practices
- Extension points

**Key Sections**:
- ✓ System architecture (4 layers)
- ✓ Development setup (Database, Python, configuration)
- ✓ Project structure
- ✓ Code structure (PL/SQL and Python)
- ✓ Testing procedures (3 test types)
- ✓ Contributing guidelines (Git workflow, code review)
- ✓ Code standards (PL/SQL and Python)
- ✓ Extension points (Adding features)

---

### 📓 [Operations Runbook](operations-runbook.md)
**Audience**: Operations teams, on-call engineers, DevOps

**Topics Covered**:
- Deployment and upgrade procedures
- Health checks and monitoring
- Common issue resolution
- Performance tuning
- Emergency procedures
- Backup and recovery
- Monitoring and alerting

**Key Sections**:
- ✓ Deployment procedures (5-step process)
- ✓ Upgrade procedures (3-step process)
- ✓ Health checks (Daily, component-based)
- ✓ Common issues resolution (5 major issues)
- ✓ Performance tuning (Database and application)
- ✓ Backup and recovery procedures
- ✓ Emergency procedures (Rollback, restoration)
- ✓ Monitoring and alerting (Prometheus, Grafana)

---

### [AI Advisor Setup Guide](guides/ai-advisor-setup.md)
**Audience**: Administrators, power users

**Topics Covered**:
- Installing Ollama (Linux, macOS, Windows, Docker)
- Downloading and selecting models (phi3, mistral, llama3)
- Configuring HCC Advisor to connect to Ollama
- Using the AI Advisor page for compression analysis
- Network and security considerations
- Troubleshooting common issues

---

## v3.0 Dashboard Pages

| Page | Purpose |
|------|---------|
| **Overview** | Compression progress donut, savings timeline, forecast, growth alerts |
| **Quick Action** | Fast hotness-only scan with DBMS_SCHEDULER job queue (Tables/Partitions/Subpartitions/Schemas) |
| **Run Analysis** | Full DBMS_COMPRESSION ratio analysis with background execution |
| **View Recommendations** | Filtered candidate list with execution status (Pending/Compressed) |
| **Compress Tables** | Single table or batch compression execution |
| **Tablespaces** | Analyze and shrink tablespace datafiles after compression |
| **Index Manager** | Detect and rebuild unusable/invalid indexes via scheduler jobs |
| **Execution History** | Compression history with error details and rollback capability |
| **Session Browser** | Active compression sessions on target with v$session_longops progress |
| **Scheduler** | Cross-database job queue monitor with auto-refresh and persistent queue |
| **AI Advisor** | Local SLM analysis via Ollama for intelligent recommendations |
| **Wizard** | 6-step guided compression lifecycle (Scan-Review-Submit-Monitor-Shrink) |
| **Compression Rules** | Strategy and rule management with comparison tool |
| **DB Connections** | Target database registration with NORMAL/SYSDBA mode support |
| **Admin** | SQL patches, Ollama config, webhooks, AWR license, system info |

---

## Documentation Coverage Summary

| Category | Coverage | Details |
|----------|----------|---------|
| **User Documentation** | 100% | Complete user guide with examples, troubleshooting, and FAQ |
| **API Documentation** | 100% | All packages, functions, endpoints, and views documented |
| **Administration** | 100% | Installation, configuration, maintenance, and security covered |
| **Development** | 100% | Architecture, setup, testing, and contribution guidelines |
| **Operations** | 100% | Deployment, health checks, issue resolution, and monitoring |
| **AI Advisor** | 100% | Ollama setup, model selection, configuration, troubleshooting |

**Total Documentation Pages**: 6 comprehensive guides
**Total Topics Covered**: 60+ major topics
**Code Examples**: 100+ SQL, PL/SQL, Python, and Shell examples
**Troubleshooting Items**: 20+ common issues with solutions

## Quick Navigation

### For New Users
1. Start with [User Guide - Getting Started](user-guide.md#getting-started)
2. Review [User Guide - Quick Start Example](user-guide.md#quick-start-example)
3. Explore [User Guide - Compression Strategies](user-guide.md#understanding-compression-strategies)
4. Check [User Guide - FAQ](user-guide.md#faq)

### For Administrators
1. Begin with [Admin Guide - Installation](admin-guide.md#installation)
2. Configure [Admin Guide - Database Setup](admin-guide.md#database-setup)
3. Set up [Admin Guide - Monitoring](admin-guide.md#monitoring-setup)
4. Review [Admin Guide - Maintenance Tasks](admin-guide.md#maintenance-tasks)

### For Developers
1. Review [Developer Guide - Architecture](developer-guide.md#architecture-overview)
2. Set up [Developer Guide - Development Environment](developer-guide.md#development-setup)
3. Understand [Developer Guide - Code Structure](developer-guide.md#code-structure)
4. Follow [Developer Guide - Testing](developer-guide.md#testing-procedures)

### For Operations Teams
1. Follow [Operations Runbook - Deployment](operations-runbook.md#deployment-procedures)
2. Set up [Operations Runbook - Health Checks](operations-runbook.md#health-checks)
3. Review [Operations Runbook - Common Issues](operations-runbook.md#common-issues-resolution)
4. Prepare [Operations Runbook - Emergency Procedures](operations-runbook.md#emergency-procedures)

### For API Integration
1. Review [API Reference - REST Endpoints](api-reference.md#rest-api-endpoints)
2. Explore [API Reference - PL/SQL Packages](api-reference.md#plsql-package-apis)
3. Check [API Reference - Database Views](api-reference.md#database-views)
4. Handle [API Reference - Error Codes](api-reference.md#error-codes)

## System Requirements

### Database Requirements
- Oracle Database 19c or higher (Enterprise Edition)
- Exadata Cloud at Customer (ExaCC) or Exadata hardware for HCC features
- Advanced Compression option licensed and enabled
- Minimum 4 CPU cores, 8 GB RAM
- Dedicated scratch tablespace (500 MB - 2 GB)

### Application Requirements
- Python 3.8+ (for Streamlit dashboard)
- Oracle REST Data Services (ORDS) 20.4+
- Network connectivity for REST API access

## Key Features

### Analysis Capabilities
- ✓ Automatic compression ratio calculation for 5 compression types
- ✓ Hot score calculation based on DML activity and access patterns
- ✓ Intelligent recommendations using workload analysis
- ✓ Support for tables, partitions, indexes, and LOBs
- ✓ Parallel processing for large-scale analysis

### Execution Capabilities
- ✓ Online and offline compression modes
- ✓ Automatic index rebuilding
- ✓ Batch compression operations
- ✓ Rollback and recovery support
- ✓ Complete audit trail with before/after metrics

### Monitoring Capabilities
- ✓ Real-time compression operation tracking
- ✓ Space savings reports and summaries
- ✓ Effectiveness assessment (optimal/suboptimal)
- ✓ Historical trend analysis
- ✓ Integration with AWR and Prometheus

### Compression Strategies
- ✓ **Conservative**: OLTP-focused, minimal risk (20-40% savings)
- ✓ **Balanced**: Mixed workloads, moderate savings (40-60% savings)
- ✓ **Aggressive**: Data warehouse, maximum savings (60-90% savings)

## Support and Contribution

### Getting Help
- **Documentation Issues**: Create an issue in the repository
- **Feature Requests**: Submit via GitHub issues
- **Bug Reports**: Use the bug report template

### Contributing
See [Developer Guide - Contributing Guidelines](developer-guide.md#contributing-guidelines) for:
- Git workflow and branching strategy
- Code review process
- Testing requirements
- Code standards

## Version Information

- **Documentation Version**: 1.0.0
- **Last Updated**: 2025-01-13
- **Compatibility**: Oracle Database 19c and higher
- **Target Platform**: Exadata Cloud at Customer (ExaCC)

## Document Maintenance

### Update Schedule
- **Minor updates**: As needed for clarifications
- **Major updates**: Quarterly or with new feature releases
- **Review cycle**: Annual comprehensive review

### Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-01-13 | Initial comprehensive documentation suite |

## Related Resources

### Oracle Documentation
- [Oracle Advanced Compression Guide](https://docs.oracle.com/en/database/oracle/oracle-database/19/adlob/)
- [Oracle DBMS_COMPRESSION Package](https://docs.oracle.com/en/database/oracle/oracle-database/19/arpls/DBMS_COMPRESSION.html)
- [Oracle REST Data Services (ORDS)](https://docs.oracle.com/en/database/oracle/oracle-rest-data-services/)
- [Exadata Cloud at Customer Documentation](https://docs.oracle.com/en/engineered-systems/exadata-cloud-at-customer/)

### Community Resources
- GitHub Repository: [HCC-CompAdvisor](https://github.com/example/hcc-compadvisor)
- Discussion Forum: [Oracle Community](https://community.oracle.com/)

---

## Quick Reference Card

### Most Common Commands

```sql
-- Analyze all tables
EXEC PKG_COMPRESSION_ANALYZER.ANALYZE_ALL_TABLES;

-- Get top recommendations
SELECT * FROM V_COMPRESSION_CANDIDATES
ORDER BY estimated_savings_mb DESC
FETCH FIRST 20 ROWS ONLY;

-- Compress a table (auto-selects compression type)
EXEC PKG_COMPRESSION_EXECUTOR.COMPRESS_TABLE(
    p_owner => 'SCHEMA',
    p_table_name => 'TABLE_NAME'
);

-- View compression history
SELECT * FROM V_COMPRESSION_HISTORY
ORDER BY start_time DESC
FETCH FIRST 20 ROWS ONLY;

-- Check space savings
SELECT * FROM V_SPACE_SAVINGS
ORDER BY total_saved_mb DESC;
```

### Most Common REST API Calls

```bash
# Run analysis
curl -X POST https://host/ords/compression/v1/advisor/tables

# Get recommendations
curl https://host/ords/compression/v1/recommendations?threshold=1.5

# Execute compression
curl -X POST https://host/ords/compression/v1/execute \
  -H "Content-Type: application/json" \
  -d '{"owner":"SCHEMA","table_name":"TABLE","compression_type":"QUERY LOW"}'

# Get operation history
curl https://host/ords/compression/v1/history/12345
```

---

**For questions or feedback about this documentation, please contact the documentation team.**
