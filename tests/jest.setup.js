/**
 * Jest Global Setup
 * Runs before all tests
 */

// Load environment variables
require('dotenv').config({ path: '.env.test' });

// Set up global test timeout
jest.setTimeout(30000);

// Mock console methods for cleaner test output (optional)
global.console = {
  ...console,
  // Uncomment to suppress console during tests
  // log: jest.fn(),
  // debug: jest.fn(),
  // info: jest.fn(),
  // warn: jest.fn(),
  error: console.error // Keep errors visible
};

// Global test utilities
global.testUtils = {
  // Helper to wait for async operations
  wait: (ms) => new Promise(resolve => setTimeout(resolve, ms)),

  // Helper to generate random test data
  randomString: (length = 10) => {
    return Math.random().toString(36).substring(2, length + 2);
  },

  // Helper to format test timestamps
  testTimestamp: () => {
    return new Date().toISOString().replace(/[:.]/g, '-');
  }
};

// Database connection pool for tests
let dbPool = null;

global.getDbPool = () => {
  if (!dbPool) {
    // Initialize Oracle DB pool for testing
    // This will be properly configured when oracledb is available
    dbPool = {
      getConnection: jest.fn(),
      close: jest.fn()
    };
  }
  return dbPool;
};

// Clean up after all tests
afterAll(async () => {
  if (dbPool && dbPool.close) {
    await dbPool.close();
  }
});
