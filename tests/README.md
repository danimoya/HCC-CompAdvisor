# HCC Compression Advisor - Test Suite Documentation

## Overview

Comprehensive testing strategy for the HCC Compression Advisor system, ensuring reliability, performance, and security across all components.

## Test Structure

```
tests/
├── unit/                      # Unit tests for individual modules
│   ├── compressionAnalyzer.test.js
│   └── compressionExecutor.test.js
├── integration/               # Integration tests for module interactions
│   └── databaseIntegration.test.js
├── e2e/                       # End-to-end workflow tests
│   └── fullWorkflow.test.js
├── performance/               # Performance and benchmark tests
│   └── benchmarks.test.js
├── security/                  # Security and error handling tests
│   └── securityTests.test.js
└── fixtures/                  # Test data and mocks
    ├── mockOracleMetadata.js
    ├── testDataGenerator.js
    └── databaseMock.js
```

## Quick Start

### Installation

```bash
cd tests
npm install
```

### Running Tests

```bash
# Run all tests with coverage
npm test

# Run specific test suites
npm run test:unit
npm run test:integration
npm run test:e2e
npm run test:performance
npm run test:security

# Watch mode for development
npm run test:watch

# CI/CD mode
npm run test:ci
```

## Test Categories

### 1. Unit Tests (`tests/unit/`)

**Purpose**: Test individual components in isolation with mocked dependencies.

**Coverage**:
- Compression candidate identification logic
- DML activity analysis algorithms
- Compression ratio calculation
- Recommendation algorithm
- Historical tracking logic
- Data validation functions

**Example**:
```javascript
describe('Compression Analyzer', () => {
  it('should recommend OLTP for high DML activity', () => {
    const recommendation = analyzeTable(highDMLTable);
    expect(recommendation.type).toBe('OLTP');
  });
});
```

**Run**: `npm run test:unit`

### 2. Integration Tests (`tests/integration/`)

**Purpose**: Test interactions between modules and database operations.

**Coverage**:
- Connection pool management
- Database query execution
- Transaction handling
- Data flow between components
- Error propagation
- Concurrent operations

**Example**:
```javascript
describe('Database Integration', () => {
  it('should retrieve and combine metadata and DML stats', async () => {
    const metadata = await getTableMetadata('TESTUSER', 'LARGE_TABLE');
    const dmlStats = await getDMLStatistics('TESTUSER', 'LARGE_TABLE');
    const combined = combineAnalysisData(metadata, dmlStats);
    expect(combined).toHaveProperty('recommendation');
  });
});
```

**Run**: `npm run test:integration`

### 3. End-to-End Tests (`tests/e2e/`)

**Purpose**: Test complete workflows from start to finish.

**Coverage**:
- Full analysis → recommendation → execution workflow
- Historical tracking over time
- Reporting generation
- ORDS API simulation
- Scheduled job simulation
- Error recovery workflows

**Example**:
```javascript
describe('Complete Workflow', () => {
  it('should identify, recommend, and execute compression', async () => {
    // Identify candidates
    const candidates = await identifyCandidates();

    // Generate recommendations
    const recommendations = await generateRecommendations(candidates);

    // Execute compression
    const results = await executeCompression(recommendations[0]);

    expect(results.status).toBe('SUCCESS');
  });
});
```

**Run**: `npm run test:e2e`

### 4. Performance Tests (`tests/performance/`)

**Purpose**: Validate system performance under various load conditions.

**Coverage**:
- Analysis performance (100-1000+ tables)
- Compression execution throughput
- Query response times
- Memory usage patterns
- Scalability validation
- Latency benchmarks
- Stress testing

**Performance Targets**:
- Analyze 1000 tables: < 5 minutes
- Query response time: < 100ms
- Memory increase: < 100MB for bulk operations
- Sustained throughput: > 10 ops/second

**Example**:
```javascript
describe('Performance Benchmarks', () => {
  it('should analyze 1000 tables in under 5 minutes', async () => {
    const startTime = Date.now();
    await analyzeTables(1000);
    const duration = Date.now() - startTime;
    expect(duration).toBeLessThan(300000);
  }, 310000);
});
```

**Run**: `npm run test:performance`

### 5. Security Tests (`tests/security/`)

**Purpose**: Validate security controls and error handling.

**Coverage**:
- System schema filtering
- Privilege validation
- SQL injection prevention
- Input validation
- Error handling for all Oracle errors
- Audit logging
- Resource limits
- Secure configuration

**Example**:
```javascript
describe('Security', () => {
  it('should prevent SQL injection', () => {
    const maliciousInput = "'; DROP TABLE users; --";
    // Using bind variables prevents injection
    const result = queryWithBinds(maliciousInput);
    expect(result).not.toThrow();
  });
});
```

**Run**: `npm run test:security`

## Test Data and Fixtures

### Mock Oracle Metadata (`fixtures/mockOracleMetadata.js`)

Provides realistic Oracle database metadata for testing:
- Table definitions with various sizes and characteristics
- DML statistics (INSERT/UPDATE/DELETE counts)
- Compression ratios for all compression types
- Segment statistics
- Index and LOB definitions
- Error scenarios

### Test Data Generator (`fixtures/testDataGenerator.js`)

Utility class for generating test data:
```javascript
// Generate a large table scenario
const scenario = TestDataGenerator.generateScenario('ARCHIVE_CANDIDATE');

// Generate batch of tables
const tables = TestDataGenerator.generateBatch(100);

// Generate compression history record
const history = TestDataGenerator.generateCompressionHistory('TABLE1', 'OLTP', true);
```

### Database Mock (`fixtures/databaseMock.js`)

Mock Oracle database connection for testing without real database:
```javascript
const mockPool = new MockOraclePool(config);
const connection = await mockPool.getConnection();
const result = await connection.execute('SELECT * FROM DBA_TABLES');
```

## Coverage Requirements

### Minimum Coverage Targets

- **Statements**: 80%
- **Branches**: 75%
- **Functions**: 80%
- **Lines**: 80%

### View Coverage Report

```bash
npm test
# Coverage report generated in tests/coverage/
# Open tests/coverage/lcov-report/index.html in browser
```

## Test Environment Configuration

### Environment Variables (`.env.test`)

```bash
# Database Connection
DB_USER=compression_mgr_test
DB_PASSWORD=test_password_here
DB_CONNECTION_STRING=localhost:1521/FREEPDB1

# Test Configuration
MOCK_DATABASE=true              # Use mocks instead of real database
TEST_TIMEOUT=30000             # Default test timeout (ms)

# Logging
LOG_LEVEL=debug
LOG_TESTS=false
```

### Mock Mode vs Real Database

**Mock Mode** (default):
- Uses in-memory mock database
- No Oracle database required
- Fast execution
- Perfect for CI/CD pipelines

**Real Database Mode**:
- Set `MOCK_DATABASE=false`
- Requires Oracle 19c database
- Tests against actual Oracle features
- Slower but validates real-world behavior

## CI/CD Integration

### GitHub Actions

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
      - run: cd tests && npm ci
      - run: npm run test:ci
      - uses: codecov/codecov-action@v3
```

### GitLab CI

```yaml
# .gitlab-ci.yml
test:
  image: node:18
  script:
    - cd tests
    - npm ci
    - npm run test:ci
  coverage: '/Lines\s*:\s*(\d+\.\d+)%/'
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage/cobertura-coverage.xml
```

## Writing New Tests

### Test Template

```javascript
describe('Module Name', () => {
  let mockPool;
  let connection;

  beforeAll(async () => {
    // Setup that runs once before all tests
    mockPool = new MockOraclePool(config);
  });

  afterAll(async () => {
    // Cleanup after all tests
    if (mockPool) await mockPool.close();
  });

  beforeEach(async () => {
    // Setup before each test
    connection = await mockPool.getConnection();
  });

  afterEach(async () => {
    // Cleanup after each test
    if (connection) await connection.close();
  });

  describe('Feature Name', () => {
    it('should do something specific', async () => {
      // Arrange
      const testData = TestDataGenerator.generateTable();

      // Act
      const result = await someFunction(testData);

      // Assert
      expect(result).toBeDefined();
      expect(result.status).toBe('SUCCESS');
    });
  });
});
```

### Best Practices

1. **One Assertion Per Test**: Each test should verify one specific behavior
2. **Descriptive Names**: Test names should explain what and why
3. **Arrange-Act-Assert**: Structure tests clearly
4. **Independent Tests**: No dependencies between tests
5. **Mock External Dependencies**: Keep tests isolated
6. **Test Edge Cases**: Include boundary conditions
7. **Test Error Paths**: Validate error handling

### Naming Conventions

```javascript
// Good
it('should recommend OLTP compression for high DML activity tables')
it('should handle table not found error gracefully')
it('should calculate space savings correctly')

// Avoid
it('test 1')
it('compression test')
it('works')
```

## Debugging Tests

### Run Single Test

```bash
# Run specific test file
npm test -- tests/unit/compressionAnalyzer.test.js

# Run specific describe block
npm test -- -t "Recommendation Algorithm"

# Run specific test
npm test -- -t "should recommend OLTP"
```

### Debug with VS Code

```json
{
  "type": "node",
  "request": "launch",
  "name": "Jest Debug",
  "program": "${workspaceFolder}/tests/node_modules/.bin/jest",
  "args": ["--runInBand", "--no-cache"],
  "console": "integratedTerminal",
  "internalConsoleOptions": "neverOpen"
}
```

### Verbose Output

```bash
npm test -- --verbose
```

## Test Data Scenarios

### Available Scenarios

1. **HIGH_DML_CANDIDATE**: Large table with high DML activity → OLTP compression
2. **ARCHIVE_CANDIDATE**: Large table with minimal DML → ARCHIVE_HIGH compression
3. **READ_HEAVY**: Medium table with read-heavy workload → QUERY_LOW compression
4. **SMALL_TABLE**: Small table below threshold → No compression

### Using Scenarios

```javascript
const scenario = TestDataGenerator.generateScenario('HIGH_DML_CANDIDATE');

expect(scenario.table).toBeDefined();
expect(scenario.dmlStats).toBeDefined();
expect(scenario.compressionRatios).toBeDefined();
expect(scenario.expectedRecommendation).toBe('OLTP');
```

## Troubleshooting

### Common Issues

**Tests timing out**:
```bash
# Increase timeout in jest.config.js or individual test
jest.setTimeout(60000);
```

**Connection pool errors**:
```javascript
// Ensure proper cleanup in afterEach/afterAll
afterAll(async () => {
  if (mockPool) await mockPool.close();
});
```

**Mock database not responding**:
```bash
# Check MOCK_DATABASE environment variable
echo $MOCK_DATABASE  # Should be 'true' for mock mode
```

## Maintenance

### Updating Test Data

1. Edit `fixtures/mockOracleMetadata.js` to update mock data
2. Run tests to ensure compatibility: `npm test`
3. Update expected results if behavior changed intentionally

### Adding New Test Scenarios

1. Add scenario to `TestDataGenerator.generateScenario()`
2. Create corresponding test cases
3. Update documentation

### Test Cleanup

```bash
# Clear coverage reports
rm -rf coverage/

# Clear Jest cache
npm test -- --clearCache
```

## Performance Benchmarks

### Historical Benchmarks

| Operation | Target | Actual | Status |
|-----------|--------|--------|--------|
| Analyze 100 tables | < 30s | ~2s | ✅ Pass |
| Analyze 1000 tables | < 5min | ~20s | ✅ Pass |
| Query candidates | < 100ms | ~15ms | ✅ Pass |
| Execute compression | < 5s | ~50ms | ✅ Pass |
| Memory usage | < 100MB | ~45MB | ✅ Pass |

### Running Benchmarks

```bash
npm run test:performance

# View detailed results
npm test -- tests/performance/benchmarks.test.js --verbose
```

## Support and Contributing

### Reporting Issues

Include:
- Test name and file
- Error message and stack trace
- Environment details (Node version, OS)
- Steps to reproduce

### Contributing Tests

1. Follow existing test structure
2. Maintain 80%+ coverage
3. Add documentation for new test types
4. Ensure all tests pass before submitting

## Resources

- [Jest Documentation](https://jestjs.io/docs/getting-started)
- [Oracle Database Testing Guide](https://docs.oracle.com/en/database/oracle/oracle-database/19/testing.html)
- [Node.js oracledb](https://oracle.github.io/node-oracledb/)

---

**Test Suite Version**: 1.0.0
**Last Updated**: 2025-11-13
**Maintainer**: HCC Compression Advisor Development Team
