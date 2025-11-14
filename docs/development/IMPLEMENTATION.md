# HCC Compression Advisor - System Overview

## Overview

The HCC Compression Advisor is a comprehensive Oracle database management system for identifying, recommending, and executing Hybrid Columnar Compression (HCC) operations on Exadata platforms.

## Architecture

### Core Modules

#### 1. Configuration Management (`src/config.js`)
**Purpose**: Centralized configuration and database connection management

**Key Features**:
- Environment variable support
- Connection pooling with configurable parameters
- Configuration validation
- File-based configuration loading
- Deep merge of default and custom settings

**Design Decisions**:
- Singleton pattern for global configuration access
- Separate pool management for connection efficiency
- Validation layer to prevent runtime errors

**Key Methods**:
- `loadFromFile(configPath)` - Load configuration from JSON file
- `initializePool()` - Create Oracle connection pool
- `getConnection()` - Retrieve connection from pool
- `validate()` - Validate configuration completeness

---

#### 2. Utilities (`src/utils.js`)
**Purpose**: Shared utilities for logging, error handling, and formatting

**Key Features**:
- Structured JSON logging with file rotation
- Custom error classes (CompressionError, DatabaseError, ValidationError)
- Byte/number formatting utilities
- Retry logic with exponential backoff
- SQL identifier sanitization

**Design Decisions**:
- Log rotation to prevent disk space issues
- Comprehensive error types for precise error handling
- Functional utilities for common operations

**Key Classes/Functions**:
- `Logger` - Structured logging with levels and rotation
- `formatBytes()` - Human-readable size formatting
- `calculateSavings()` - Compression savings calculation
- `retry()` - Async retry with backoff
- `sanitizeSQLIdentifier()` - SQL injection prevention

---

#### 3. Candidate Identifier (`src/candidate-identifier.js`)
**Purpose**: Identify and score tables suitable for HCC compression

**Key Features**:
- Query Oracle metadata views (DBA_TABLES, DBA_SEGMENTS, V$SEGMENT_STATISTICS)
- Filter by size, compression status, and access patterns
- Score candidates using multi-factor algorithm
- Detailed table analysis with column/partition/index information

**Scoring Algorithm**:
1. **Size Factor**: Larger tables = higher priority (log scale)
2. **Compression Ratio**: Estimated compression potential
3. **I/O Ratio**: Read-heavy tables benefit more from HCC
4. **Penalties**: Already compressed (-50%), Partitioned (-10%)
5. **Bonuses**: Fresh statistics (+10%)

**Design Decisions**:
- Heuristic-based compression ratio estimation
- Configurable exclusion patterns
- Separation of quick scoring vs. detailed analysis

**Key Methods**:
- `identifyCandidates(options)` - Find and score compression candidates
- `analyzeTable(schema, table)` - Detailed single-table analysis
- `_scoreCandidates()` - Multi-factor scoring algorithm

---

#### 4. Recommendation Engine (`src/recommendation-engine.js`)
**Purpose**: Analyze workloads and recommend optimal HCC compression type

**HCC Compression Types**:
- **QUERY LOW**: 6-10x ratio, excellent query performance, read-heavy workloads
- **QUERY HIGH**: 10-15x ratio, good query performance, balanced usage
- **ARCHIVE LOW**: 15-20x ratio, moderate performance, infrequent access
- **ARCHIVE HIGH**: 20-50x ratio, low performance, archival data

**Selection Algorithm**:
1. Analyze workload (read/write ratio, access frequency)
2. Classify workload type (READ_ONLY, READ_HEAVY, MIXED, WRITE_HEAVY)
3. Select compression based on profile:
   - Archive candidates → ARCHIVE HIGH/LOW
   - Read-heavy + large tables → QUERY HIGH
   - Read-heavy + normal tables → QUERY LOW
   - Mixed workloads → QUERY LOW
   - Write-heavy → Warning (HCC not recommended)

**Design Decisions**:
- Workload-driven recommendations
- Risk assessment with prerequisites
- Implementation strategy generation (partitioned vs. full table)
- Duration estimation based on table size

**Key Methods**:
- `generateRecommendation(tableAnalysis)` - Full recommendation with strategy
- `generateBatchRecommendations(candidates)` - Batch processing
- `_selectCompressionType()` - Workload-based type selection
- `_assessRisks()` - Risk and prerequisite analysis

---

#### 5. Compression Executor (`src/compression-executor.js`)
**Purpose**: Safely execute HCC compression operations with rollback support

**Key Features**:
- DDL generation for pre/compression/post operations
- Step-by-step execution with error handling
- Before/after statistics capture
- Automatic rollback on failure
- Dry-run mode for DDL preview
- Parallel and online compression support

**Execution Flow**:
1. **Pre-compression**: Gather statistics
2. **Compression**: ALTER TABLE MOVE COMPRESS or partition compression
3. **Post-compression**: Rebuild indexes, re-gather statistics
4. **Validation**: Measure actual savings
5. **Rollback** (if failure): Restore to uncompressed state

**Design Decisions**:
- Transactional approach with rollback capability
- Execution tracking with unique IDs
- Integration with history tracker
- Support for both full table and partition-by-partition

**Key Methods**:
- `executeCompression(recommendation, options)` - Main execution
- `_generateCompressionDDL()` - DDL statement generation
- `_executeCompressionSteps()` - Step-by-step execution
- `_rollbackCompression()` - Failure recovery

---

#### 6. History Tracker (`src/history-tracker.js`)
**Purpose**: Maintain audit trail of recommendations and executions

**Key Features**:
- Persistent storage in Oracle table
- Track recommendations and executions separately
- Before/after metrics recording
- Statistics aggregation
- Configurable retention period

**Schema Design**:
- **COMPRESSION_HISTORY** table with record_type ('RECOMMENDATION' | 'EXECUTION')
- Stores JSON payloads for full context
- Indexes on schema/table, operation_time, status
- Retention-based cleanup

**Design Decisions**:
- Centralized audit trail
- JSON storage for flexibility
- Statistics for reporting and analysis
- Auto-cleanup to manage storage

**Key Methods**:
- `recordRecommendation(recommendation)` - Log recommendation
- `recordExecution(executionId, recommendation, result)` - Log execution
- `getTableHistory(schema, table)` - Retrieve table history
- `getStatisticsSummary()` - Aggregate statistics

---

#### 7. Main Entry Point (`src/index.js`)
**Purpose**: Unified API and complete workflow orchestration

**Key Features**:
- Single initialization for all components
- Complete workflow: identify → recommend → execute
- Component lifecycle management
- Batch processing support
- Summary generation

**Workflow Modes**:
1. **Identify Only**: Find compression candidates
2. **Recommend**: Generate recommendations without execution
3. **Dry Run**: Generate DDL without execution
4. **Execute**: Full compression with history tracking

**Design Decisions**:
- Facade pattern for simplified API
- Workflow automation for common use cases
- Graceful shutdown with connection cleanup
- Initialization validation

**Key Methods**:
- `initialize()` - Setup all components
- `runWorkflow(options)` - Complete automation
- `identifyCandidates()` - Find candidates
- `generateRecommendation()` - Create recommendation
- `executeCompression()` - Execute compression

---

## Design Patterns Used

1. **Singleton Pattern**: Configuration management
2. **Facade Pattern**: Main API (index.js)
3. **Strategy Pattern**: Compression type selection
4. **Template Method**: Execution workflow
5. **Factory Pattern**: Error object creation
6. **Repository Pattern**: History tracking

## Error Handling Strategy

1. **Custom Error Types**: Precise error classification
2. **Try-Catch-Finally**: Resource cleanup guaranteed
3. **Retry Logic**: Transient error recovery
4. **Rollback Support**: Automatic failure recovery
5. **Comprehensive Logging**: Debug and audit trail

## Performance Considerations

1. **Connection Pooling**: Reuse database connections
2. **Batch Processing**: Multiple tables in one session
3. **Parallel Execution**: Configurable parallel degree
4. **Statistics Caching**: Avoid redundant queries
5. **Streaming Logs**: File-based logging with rotation

## Security Measures

1. **SQL Injection Prevention**: Identifier sanitization
2. **No Hardcoded Credentials**: Environment variables
3. **Parameterized Queries**: Bind variables throughout
4. **Input Validation**: Schema/table name validation
5. **Least Privilege**: Recommendations for minimal permissions

## Testing Strategy

1. **Unit Tests**: Individual module functions
2. **Integration Tests**: Database operations
3. **Mock Objects**: Database connection mocking
4. **Error Scenarios**: Failure path testing
5. **Performance Tests**: Large dataset handling

## Future Enhancements

1. **Web UI**: Browser-based management interface
2. **Scheduling**: Automated compression jobs
3. **Monitoring**: Real-time compression progress
4. **Machine Learning**: Predictive compression recommendations
5. **Multi-Database**: Support for multiple database instances
6. **REST API**: HTTP-based integration
7. **Cloud Integration**: OCI integration for cloud databases

## Key Design Decisions

### Why Separate Modules?
- **Maintainability**: Each module under 500 lines
- **Testability**: Independent unit testing
- **Reusability**: Components can be used independently
- **Separation of Concerns**: Single Responsibility Principle

### Why Async/Await?
- **Modern JavaScript**: Clean error handling
- **Promise Chains**: Better than callbacks
- **Readability**: Synchronous-looking code
- **Error Propagation**: Natural try-catch support

### Why Connection Pooling?
- **Performance**: Avoid connection overhead
- **Resource Management**: Limited connections
- **Scalability**: Handle concurrent operations
- **Reliability**: Automatic connection recovery

### Why History Tracking?
- **Audit Trail**: Compliance requirements
- **Performance Analysis**: Track actual vs. expected
- **Trend Analysis**: Identify patterns over time
- **Rollback Reference**: Restore previous state

### Why Heuristic Scoring?
- **No Training Data**: Production systems vary
- **Fast Execution**: No ML inference overhead
- **Transparent**: Explainable recommendations
- **Tunable**: Easy to adjust weights

## Module Dependencies

```
index.js
  ├── config.js
  ├── utils.js
  ├── candidate-identifier.js
  │     └── config.js
  │     └── utils.js
  ├── recommendation-engine.js
  │     └── config.js
  │     └── utils.js
  ├── compression-executor.js
  │     └── config.js
  │     └── utils.js
  │     └── history-tracker.js
  └── history-tracker.js
        └── config.js
        └── utils.js
```

## Configuration Flow

1. Environment variables (highest priority)
2. Configuration file (if provided)
3. Default values (fallback)
4. Runtime overrides (optional)

## Execution Safety

1. **Validation**: Pre-execution checks
2. **Before Statistics**: Baseline capture
3. **Step-by-Step**: Granular execution
4. **Error Detection**: Per-step validation
5. **Rollback**: Automatic recovery
6. **After Statistics**: Result verification
7. **History**: Permanent record

## Summary

The HCC Compression Advisor provides a production-ready, enterprise-grade solution for managing Oracle HCC compression with:

- **Safety**: Rollback support and validation
- **Intelligence**: Workload-based recommendations
- **Auditability**: Complete history tracking
- **Flexibility**: Multiple execution modes
- **Performance**: Connection pooling and batch processing
- **Maintainability**: Modular architecture and comprehensive logging

All modules follow clean code principles with comprehensive error handling, logging, and documentation.
