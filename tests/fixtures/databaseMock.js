/**
 * Database Connection Mock
 * Simulates Oracle Database connections for testing without real database
 */

const {
  mockTables,
  mockTabModifications,
  mockCompressionRatios,
  mockSegmentStatistics,
  mockErrorScenarios
} = require('./mockOracleMetadata');

class MockOracleConnection {
  constructor() {
    this.isOpen = true;
    this.queryHistory = [];
  }

  /**
   * Mock execute method
   */
  async execute(sql, binds = [], options = {}) {
    this.queryHistory.push({ sql, binds, options, timestamp: new Date() });

    // Simulate query delay
    await this._simulateDelay(10, 100);

    // Parse SQL and return appropriate mock data
    const sqlUpper = sql.toUpperCase();

    // DBA_TABLES queries
    if (sqlUpper.includes('DBA_TABLES') || sqlUpper.includes('ALL_TABLES')) {
      return this._mockTablesQuery(sql, binds);
    }

    // ALL_TAB_MODIFICATIONS queries
    if (sqlUpper.includes('ALL_TAB_MODIFICATIONS')) {
      return this._mockTabModificationsQuery(sql, binds);
    }

    // DBA_SEGMENTS queries
    if (sqlUpper.includes('DBA_SEGMENTS')) {
      return this._mockSegmentsQuery(sql, binds);
    }

    // V$SEGMENT_STATISTICS queries
    if (sqlUpper.includes('V$SEGMENT_STATISTICS')) {
      return this._mockSegmentStatsQuery(sql, binds);
    }

    // DBMS_COMPRESSION calls (mocked as queries for testing)
    if (sqlUpper.includes('DBMS_COMPRESSION') || sqlUpper.includes('GET_COMPRESSION_RATIO')) {
      return this._mockCompressionRatioQuery(sql, binds);
    }

    // DDL operations (ALTER TABLE)
    if (sqlUpper.includes('ALTER TABLE') && sqlUpper.includes('COMPRESS')) {
      return this._mockCompressionExecution(sql, binds);
    }

    // INSERT operations
    if (sqlUpper.includes('INSERT INTO')) {
      return this._mockInsert(sql, binds);
    }

    // Default empty result
    return { rows: [], rowsAffected: 0 };
  }

  /**
   * Mock tables query
   */
  _mockTablesQuery(sql, binds) {
    let filteredTables = [...mockTables];

    // Apply filters based on binds
    if (binds && binds.length > 0) {
      if (binds[0]) {
        filteredTables = filteredTables.filter(t => t.owner === binds[0]);
      }
      if (binds[1]) {
        filteredTables = filteredTables.filter(t => t.table_name === binds[1]);
      }
    }

    return {
      rows: filteredTables.map(t => Object.values(t)),
      metaData: Object.keys(mockTables[0] || {}).map(name => ({ name: name.toUpperCase() })),
      rowsAffected: filteredTables.length
    };
  }

  /**
   * Mock tab modifications query
   */
  _mockTabModificationsQuery(sql, binds) {
    let filteredMods = [...mockTabModifications];

    if (binds && binds.length > 0) {
      if (binds[0]) {
        filteredMods = filteredMods.filter(m => m.table_owner === binds[0]);
      }
      if (binds[1]) {
        filteredMods = filteredMods.filter(m => m.table_name === binds[1]);
      }
    }

    return {
      rows: filteredMods.map(m => Object.values(m)),
      metaData: Object.keys(mockTabModifications[0] || {}).map(name => ({ name: name.toUpperCase() })),
      rowsAffected: filteredMods.length
    };
  }

  /**
   * Mock segments query
   */
  _mockSegmentsQuery(sql, binds) {
    const segments = mockTables.map(t => ({
      owner: t.owner,
      segment_name: t.table_name,
      segment_type: 'TABLE',
      tablespace_name: t.tablespace_name,
      bytes: t.size_bytes,
      blocks: t.blocks
    }));

    return {
      rows: segments.map(s => Object.values(s)),
      metaData: Object.keys(segments[0] || {}).map(name => ({ name: name.toUpperCase() })),
      rowsAffected: segments.length
    };
  }

  /**
   * Mock segment statistics query
   */
  _mockSegmentStatsQuery(sql, binds) {
    return {
      rows: mockSegmentStatistics.map(s => Object.values(s)),
      metaData: Object.keys(mockSegmentStatistics[0] || {}).map(name => ({ name: name.toUpperCase() })),
      rowsAffected: mockSegmentStatistics.length
    };
  }

  /**
   * Mock compression ratio query
   */
  _mockCompressionRatioQuery(sql, binds) {
    const tableName = binds && binds.length > 1 ? binds[1] : 'LARGE_TRANSACTIONAL';
    const compressionType = binds && binds.length > 2 ? binds[2] : 'OLTP';

    const ratios = mockCompressionRatios[tableName] || mockCompressionRatios['LARGE_TRANSACTIONAL'];
    const ratio = ratios[compressionType] || 2.5;

    return {
      rows: [[ratio]],
      metaData: [{ name: 'COMPRESSION_RATIO' }],
      rowsAffected: 1
    };
  }

  /**
   * Mock compression execution
   */
  _mockCompressionExecution(sql, binds) {
    // Check for error scenarios
    const errorScenario = mockErrorScenarios.find(e =>
      sql.includes(e.table_name) && e.scenario !== 'TABLE_NOT_FOUND'
    );

    if (errorScenario) {
      throw new Error(errorScenario.error);
    }

    return {
      rows: [],
      rowsAffected: 1
    };
  }

  /**
   * Mock INSERT operation
   */
  _mockInsert(sql, binds) {
    return {
      rows: [],
      rowsAffected: 1,
      lastRowid: 'AAASjKAAEAAAADmAAA'
    };
  }

  /**
   * Simulate network delay
   */
  async _simulateDelay(min, max) {
    const delay = Math.floor(Math.random() * (max - min + 1)) + min;
    return new Promise(resolve => setTimeout(resolve, delay));
  }

  /**
   * Mock commit
   */
  async commit() {
    await this._simulateDelay(5, 20);
  }

  /**
   * Mock rollback
   */
  async rollback() {
    await this._simulateDelay(5, 20);
  }

  /**
   * Mock close
   */
  async close() {
    this.isOpen = false;
  }

  /**
   * Get query history for testing
   */
  getQueryHistory() {
    return this.queryHistory;
  }

  /**
   * Clear query history
   */
  clearQueryHistory() {
    this.queryHistory = [];
  }
}

class MockOraclePool {
  constructor(config) {
    this.config = config;
    this.connections = [];
    this.isOpen = true;
  }

  async getConnection() {
    const connection = new MockOracleConnection();
    this.connections.push(connection);
    return connection;
  }

  async close() {
    for (const conn of this.connections) {
      if (conn.isOpen) {
        await conn.close();
      }
    }
    this.isOpen = false;
  }

  getConnectionCount() {
    return this.connections.filter(c => c.isOpen).length;
  }
}

module.exports = {
  MockOracleConnection,
  MockOraclePool,
  createMockPool: (config) => new MockOraclePool(config)
};
