# HCC Compression Advisor - Testing Strategy

## Executive Summary

This document outlines the comprehensive testing strategy for the HCC Compression Advisor system, ensuring high quality, reliability, and performance across all components.

## Testing Philosophy

### Core Principles

1. **Test-Driven Development (TDD)**: Write tests before implementation
2. **Comprehensive Coverage**: Aim for >80% code coverage across all metrics
3. **Isolated Testing**: Tests should be independent and repeatable
4. **Performance Validation**: Continuous performance benchmarking
5. **Security First**: Validate security controls at every layer

### Test Pyramid

```
         /\
        /E2E\           5-10% - Complete workflows
       /------\
      /Integr.\        20-25% - Module interactions
     /----------\
    /   Unit     \     65-75% - Individual components
   /--------------\
```

## Test Coverage

### Unit Tests (65-75% of total tests)

**Scope**: Individual functions and modules in isolation

**Files**:
- `tests/unit/compressionAnalyzer.test.js`
- `tests/unit/compressionExecutor.test.js`

**Coverage Areas**:

1. **Candidate Identification**
   - Table size filtering (>10GB threshold)
   - System schema exclusion
   - Partitioned table handling
   - Data validation

2. **DML Activity Analysis**
   - DML operation counting
   - Activity classification (LOW/MEDIUM/HIGH)
   - Hotness scoring
   - Edge case handling (NULL values, missing stats)

3. **Compression Ratio Analysis**
   - Ratio calculation for all compression types
   - Compression type ordering (ARCHIVE_HIGH > QUERY_HIGH > etc.)
   - Poor ratio detection (<1.5x)
   - Large table bonus calculations

4. **Recommendation Algorithm**
   - OLTP recommendation for high DML (>100K ops)
   - ARCHIVE_HIGH for large inactive tables
   - QUERY compression for read-heavy workloads
   - NO COMPRESSION for small tables (<10GB)
   - Space savings calculations

5. **Compression Execution**
   - DDL generation and execution
   - Size capture before/after
   - Transaction management (COMMIT/ROLLBACK)
   - Parallel execution support

6. **Historical Tracking**
   - History record creation
   - Space savings calculation
   - Compression ratio tracking
   - Error recording

**Success Criteria**:
- 90%+ code coverage for business logic
- All edge cases tested
- Fast execution (<5 seconds total)

### Integration Tests (20-25% of total tests)

**Scope**: Interaction between modules and database

**Files**:
- `tests/integration/databaseIntegration.test.js`

**Coverage Areas**:

1. **Connection Pool Management**
   - Pool creation and configuration
   - Connection acquisition/release
   - Connection reuse
   - Pool exhaustion handling

2. **Database Query Execution**
   - Table metadata retrieval
   - DML statistics queries
   - Segment size queries
   - Compression ratio API calls

3. **Data Flow**
   - Analyzer → Database → Recommendation
   - Recommendation → Executor → Database
   - Executor → History → Database

4. **Transaction Handling**
   - Commit on success
   - Rollback on failure
   - Savepoint usage
   - Concurrent transactions

5. **Error Propagation**
   - ORA-00942: Table not found
   - ORA-01031: Insufficient privileges
   - ORA-01653: Tablespace full
   - ORA-00054: Resource busy
   - Connection timeouts

**Success Criteria**:
- All database operations tested
- Error scenarios validated
- Concurrent operations handled
- Resource cleanup verified

### End-to-End Tests (5-10% of total tests)

**Scope**: Complete workflows from start to finish

**Files**:
- `tests/e2e/fullWorkflow.test.js`

**Coverage Areas**:

1. **Complete Compression Workflow**
   - Identify candidates
   - Analyze compression ratios
   - Generate recommendations
   - Execute compression
   - Record history

2. **Historical Tracking**
   - Multiple compression operations over time
   - Cumulative space savings
   - Recompression scenarios

3. **Performance Validation**
   - Benchmark analysis of 100+ tables
   - Compression ratio accuracy validation
   - Time-to-completion tracking

4. **Reporting Workflows**
   - Candidate report generation
   - History report generation
   - Space savings summary

5. **Scheduled Operations**
   - Nightly analysis simulation
   - Automated compression execution
   - Job status tracking

6. **ORDS Integration**
   - REST API simulation
   - JSON payload handling
   - Response validation

**Success Criteria**:
- All workflows complete successfully
- Partial failures handled gracefully
- Reports generated correctly
- ORDS endpoints functional

### Performance Tests

**Scope**: System performance under load

**Files**:
- `tests/performance/benchmarks.test.js`

**Coverage Areas**:

1. **Analysis Performance**
   - 100 tables: <30 seconds
   - 1000 tables: <5 minutes
   - Concurrent requests: <10 seconds for 50 requests

2. **Execution Performance**
   - Sequential compression: <15 seconds for 10 tables
   - Throughput measurement: tables/second
   - Batch operations efficiency

3. **Query Performance**
   - Candidate queries: <100ms average
   - Aggregation queries: <1 second
   - Report generation: <2 seconds

4. **Resource Usage**
   - Memory usage: <100MB increase for bulk operations
   - Connection pool stability
   - Resource cleanup validation

5. **Scalability**
   - Linear scaling with table count
   - Large result set handling
   - Sustained load testing

6. **Latency**
   - Database round-trip: <50ms average
   - Compression ratio calculation: <500ms
   - End-to-end operation: <5 seconds

**Success Criteria**:
- All performance targets met
- No memory leaks
- Scalability validated
- Latency within SLA

### Security Tests

**Scope**: Security controls and error handling

**Files**:
- `tests/security/securityTests.test.js`

**Coverage Areas**:

1. **Schema Filtering**
   - System schema exclusion (SYS, SYSTEM, etc.)
   - User schema validation
   - Oracle-maintained schema filtering

2. **Privilege Validation**
   - Required privilege checks
   - Insufficient privilege handling
   - Role-based access control

3. **Input Validation**
   - SQL injection prevention
   - Table name validation
   - Compression type validation
   - Owner name validation

4. **Error Handling**
   - All Oracle error codes
   - Connection errors
   - Transaction deadlocks
   - Network failures

5. **Data Sanitization**
   - Error message sanitization
   - Path information removal
   - Credential masking

6. **Audit Logging**
   - Operation logging
   - Error logging with details
   - User activity tracking

7. **Resource Limits**
   - Maximum parallel degree
   - Batch size limits
   - Operation timeouts
   - Rate limiting

**Success Criteria**:
- No SQL injection vulnerabilities
- All errors handled gracefully
- Sensitive data protected
- Audit trail complete

## Coverage Metrics

### Minimum Thresholds

| Metric | Threshold | Current | Status |
|--------|-----------|---------|--------|
| Statements | 80% | TBD | ⏳ |
| Branches | 75% | TBD | ⏳ |
| Functions | 80% | TBD | ⏳ |
| Lines | 80% | TBD | ⏳ |

### Coverage Reports

**Generate Coverage**:
```bash
cd tests
npm test -- --coverage
```

**View HTML Report**:
```bash
open coverage/lcov-report/index.html
```

**CI/CD Integration**:
- Coverage uploaded to Codecov/Coveralls
- Failed builds if coverage drops below threshold
- Coverage trends tracked over time

## Test Data Strategy

### Mock Data

**Location**: `tests/fixtures/`

**Components**:
1. **mockOracleMetadata.js**: Realistic Oracle data dictionary data
2. **testDataGenerator.js**: Dynamic test data generation
3. **databaseMock.js**: In-memory database simulation

**Scenarios**:
- HIGH_DML_CANDIDATE: Large table, high DML → OLTP
- ARCHIVE_CANDIDATE: Large table, low DML → ARCHIVE_HIGH
- READ_HEAVY: Medium table, read-heavy → QUERY_LOW
- SMALL_TABLE: Small table → NO COMPRESSION

### Test Database

**Mock Mode** (Default):
- No Oracle database required
- Fast execution
- Perfect for CI/CD
- Full API compatibility

**Real Database Mode**:
- Set `MOCK_DATABASE=false`
- Requires Oracle 19c PDB
- Validates real Oracle behavior
- Slower but more accurate

## CI/CD Integration

### GitHub Actions

**File**: `tests/.github-workflows-test.yml`

**Pipeline**:
1. Install dependencies
2. Run linter
3. Run unit tests with coverage
4. Run integration tests
5. Run e2e tests
6. Run performance tests
7. Run security tests
8. Upload coverage to Codecov
9. Archive test results

**Triggers**:
- Push to main/develop
- Pull requests
- Daily scheduled runs

### GitLab CI

**File**: `tests/.gitlab-ci.yml`

**Stages**:
1. install: Dependencies
2. lint: Code quality
3. test: Unit/Integration/E2E/Security
4. performance: Benchmarks
5. report: Coverage aggregation

**Features**:
- Multi-version testing (Node 14/16/18/20)
- Coverage reporting
- Performance tracking
- Artifact retention

## Test Execution

### Local Development

```bash
# Run all tests
npm test

# Run specific suites
npm run test:unit
npm run test:integration
npm run test:e2e
npm run test:performance
npm run test:security

# Watch mode
npm run test:watch

# Debug mode
npm test -- --debug
```

### CI/CD Environment

```bash
# CI mode (no watch, single run)
npm run test:ci

# With coverage
npm test -- --coverage --ci

# Specific Node version
nvm use 18
npm test
```

## Quality Gates

### Pre-Commit

- Linter must pass
- Unit tests must pass
- No console.log statements

### Pre-Merge

- All tests must pass
- Coverage ≥ 80% (all metrics)
- No security vulnerabilities
- Performance benchmarks within SLA

### Pre-Release

- Full test suite passes
- Performance benchmarks validated
- Security audit completed
- Documentation updated

## Maintenance

### Weekly

- Review test coverage reports
- Update mock data if needed
- Check for flaky tests

### Monthly

- Update dependencies
- Review performance trends
- Update test scenarios

### Quarterly

- Full test suite review
- Coverage threshold adjustment
- Performance baseline update

## Troubleshooting

### Common Issues

1. **Tests timing out**
   - Increase timeout: `jest.setTimeout(60000)`
   - Check for unresolved promises
   - Verify connection cleanup

2. **Flaky tests**
   - Add proper wait conditions
   - Isolate test dependencies
   - Use deterministic test data

3. **Coverage gaps**
   - Identify uncovered branches
   - Add edge case tests
   - Test error paths

4. **Performance degradation**
   - Profile slow tests
   - Optimize database mocks
   - Parallelize test execution

## Metrics and Reporting

### Test Metrics

- **Total Tests**: ~200+
- **Total Test Suites**: 11
- **Average Execution Time**: <30 seconds
- **Code Coverage**: Target 80%+

### Performance Benchmarks

| Operation | Baseline | Target | Current |
|-----------|----------|--------|---------|
| 100 table analysis | 2s | <30s | TBD |
| 1000 table analysis | 20s | <5min | TBD |
| Query response | 15ms | <100ms | TBD |
| Memory usage | 45MB | <100MB | TBD |

### Success Metrics

- **Test Pass Rate**: >99%
- **Coverage Trend**: Increasing
- **Performance Trend**: Stable
- **Flaky Test Rate**: <1%

## References

- [Jest Documentation](https://jestjs.io/)
- [Oracle Testing Guide](https://docs.oracle.com/en/database/)
- [Node.js oracledb](https://oracle.github.io/node-oracledb/)
- [Test Coverage Best Practices](https://martinfowler.com/bliki/TestCoverage.html)

---

**Version**: 1.0.0
**Last Updated**: 2025-11-13
**Owner**: HCC Compression Advisor Test Team
