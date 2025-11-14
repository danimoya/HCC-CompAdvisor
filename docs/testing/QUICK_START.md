# Quick Start Guide - HCC Compression Advisor Tests

## 5-Minute Setup

### 1. Install Dependencies (1 minute)

```bash
cd tests
npm install
```

### 2. Run All Tests (2 minutes)

```bash
npm test
```

Expected output:
```
Test Suites: 6 passed, 6 total
Tests:       224 passed, 224 total
Time:        ~30 seconds
```

### 3. View Coverage Report (1 minute)

```bash
npm test -- --coverage
open coverage/lcov-report/index.html
```

### 4. Run Specific Test Suite (1 minute)

```bash
# Unit tests only (~10 seconds)
npm run test:unit

# Integration tests (~8 seconds)
npm run test:integration

# End-to-end tests (~6 seconds)
npm run test:e2e

# Performance benchmarks (~15 seconds)
npm run test:performance

# Security tests (~5 seconds)
npm run test:security
```

## Common Commands

```bash
# Development mode (auto-rerun on changes)
npm run test:watch

# CI/CD mode (single run, no cache)
npm run test:ci

# Lint code
npm run lint

# Fix lint issues
npm run lint:fix

# Debug specific test
npm test -- --debug tests/unit/compressionAnalyzer.test.js

# Run single test
npm test -- -t "should recommend OLTP"

# Verbose output
npm test -- --verbose
```

## Test Files Overview

```
tests/
├── unit/                      # Fast, isolated tests
│   ├── compressionAnalyzer.test.js   (64 tests)
│   └── compressionExecutor.test.js   (48 tests)
├── integration/               # Module interaction tests
│   └── databaseIntegration.test.js   (32 tests)
├── e2e/                       # Complete workflow tests
│   └── fullWorkflow.test.js          (24 tests)
├── performance/               # Performance benchmarks
│   └── benchmarks.test.js            (16 tests)
└── security/                  # Security validation
    └── securityTests.test.js         (40 tests)

Total: 224 tests
```

## Environment Configuration

Edit `/tests/.env.test`:

```bash
# Use mock database (fast, no Oracle required)
MOCK_DATABASE=true

# Or use real Oracle 19c database
MOCK_DATABASE=false
DB_USER=compression_mgr
DB_PASSWORD=your_password
DB_CONNECTION_STRING=localhost:1521/FREEPDB1
```

## Troubleshooting

**Tests fail with "Cannot find module"**:
```bash
npm install
```

**Tests timeout**:
```bash
# Increase timeout in jest.config.js
testTimeout: 60000
```

**Coverage below threshold**:
```bash
# Run coverage report to see gaps
npm test -- --coverage --verbose
```

**Mock database not working**:
```bash
# Verify environment variable
echo $MOCK_DATABASE  # Should be 'true'
```

## Next Steps

1. ✅ Tests running successfully
2. 📖 Read full documentation: `/tests/README.md`
3. 🔧 Integrate with CI/CD: `.github/workflows/` or `.gitlab-ci.yml`
4. 📊 Monitor coverage trends
5. 🚀 Add tests for new features

## Getting Help

- Full documentation: `/tests/README.md`
- Testing strategy: `/docs/testing/TEST_STRATEGY.md`
- Coverage plan: `/docs/testing/COVERAGE_PLAN.md`
- Jest docs: https://jestjs.io/

---

**Quick Start Version**: 1.0.0
**Last Updated**: 2025-11-13
