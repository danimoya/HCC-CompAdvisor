/**
 * Test Data Generator
 * Creates realistic test data for various testing scenarios
 */

class TestDataGenerator {
  /**
   * Generate a random table definition
   */
  static generateTable(overrides = {}) {
    const defaultTable = {
      owner: 'TESTUSER',
      table_name: `TEST_TABLE_${Math.random().toString(36).substring(7).toUpperCase()}`,
      tablespace_name: 'USERS',
      num_rows: Math.floor(Math.random() * 10000000),
      blocks: Math.floor(Math.random() * 100000),
      avg_row_len: Math.floor(Math.random() * 500) + 50,
      compression: 'DISABLED',
      compress_for: null,
      segment_created: 'YES',
      iot_type: null,
      last_analyzed: new Date(),
      partitioned: 'NO'
    };

    const table = { ...defaultTable, ...overrides };

    // Calculate size
    table.size_bytes = table.blocks * 8192; // 8KB block size
    table.size_gb = table.size_bytes / (1024 * 1024 * 1024);

    return table;
  }

  /**
   * Generate DML statistics for a table
   */
  static generateDMLStats(tableName, activity = 'MEDIUM') {
    const activityLevels = {
      LOW: { inserts: 10, updates: 5, deletes: 2 },
      MEDIUM: { inserts: 10000, updates: 5000, deletes: 1000 },
      HIGH: { inserts: 150000, updates: 75000, deletes: 25000 },
      VERY_HIGH: { inserts: 500000, updates: 250000, deletes: 100000 }
    };

    const stats = activityLevels[activity] || activityLevels.MEDIUM;

    return {
      table_owner: 'TESTUSER',
      table_name: tableName,
      partition_name: null,
      inserts: stats.inserts,
      updates: stats.updates,
      deletes: stats.deletes,
      timestamp: new Date(),
      truncated: 'NO',
      drop_segments: 0
    };
  }

  /**
   * Generate compression ratios for different compression types
   */
  static generateCompressionRatios(tableSize, dataType = 'MIXED') {
    const baseRatios = {
      TRANSACTIONAL: { OLTP: 2.5, QUERY_LOW: 3.2, QUERY_HIGH: 4.0, ARCHIVE_LOW: 5.0, ARCHIVE_HIGH: 6.5 },
      ARCHIVAL: { OLTP: 2.0, QUERY_LOW: 4.5, QUERY_HIGH: 7.0, ARCHIVE_LOW: 9.0, ARCHIVE_HIGH: 12.0 },
      MIXED: { OLTP: 2.8, QUERY_LOW: 3.8, QUERY_HIGH: 5.5, ARCHIVE_LOW: 7.0, ARCHIVE_HIGH: 9.0 },
      LOW_COMPRESSION: { OLTP: 1.2, QUERY_LOW: 1.5, QUERY_HIGH: 1.8, ARCHIVE_LOW: 2.0, ARCHIVE_HIGH: 2.5 }
    };

    // Larger tables generally compress better
    const sizeMultiplier = tableSize > 50 ? 1.2 : tableSize > 10 ? 1.1 : 1.0;

    const ratios = baseRatios[dataType] || baseRatios.MIXED;

    return {
      OLTP: parseFloat((ratios.OLTP * sizeMultiplier).toFixed(2)),
      QUERY_LOW: parseFloat((ratios.QUERY_LOW * sizeMultiplier).toFixed(2)),
      QUERY_HIGH: parseFloat((ratios.QUERY_HIGH * sizeMultiplier).toFixed(2)),
      ARCHIVE_LOW: parseFloat((ratios.ARCHIVE_LOW * sizeMultiplier).toFixed(2)),
      ARCHIVE_HIGH: parseFloat((ratios.ARCHIVE_HIGH * sizeMultiplier).toFixed(2))
    };
  }

  /**
   * Generate a complete test scenario
   */
  static generateScenario(scenarioType) {
    const scenarios = {
      HIGH_DML_CANDIDATE: {
        table: this.generateTable({
          table_name: 'HIGH_DML_TABLE',
          num_rows: 5000000,
          blocks: 65536,
          size_gb: 15.0
        }),
        dmlStats: this.generateDMLStats('HIGH_DML_TABLE', 'HIGH'),
        compressionRatios: this.generateCompressionRatios(15, 'TRANSACTIONAL'),
        expectedRecommendation: 'OLTP'
      },
      ARCHIVE_CANDIDATE: {
        table: this.generateTable({
          table_name: 'ARCHIVE_TABLE',
          num_rows: 10000000,
          blocks: 131072,
          size_gb: 50.0
        }),
        dmlStats: this.generateDMLStats('ARCHIVE_TABLE', 'LOW'),
        compressionRatios: this.generateCompressionRatios(50, 'ARCHIVAL'),
        expectedRecommendation: 'ARCHIVE_HIGH'
      },
      SMALL_TABLE: {
        table: this.generateTable({
          table_name: 'SMALL_TABLE',
          num_rows: 1000,
          blocks: 128,
          size_gb: 0.001
        }),
        dmlStats: this.generateDMLStats('SMALL_TABLE', 'LOW'),
        compressionRatios: this.generateCompressionRatios(0.001, 'LOW_COMPRESSION'),
        expectedRecommendation: 'NONE'
      },
      READ_HEAVY: {
        table: this.generateTable({
          table_name: 'READ_HEAVY_TABLE',
          num_rows: 8000000,
          blocks: 98304,
          size_gb: 30.0
        }),
        dmlStats: this.generateDMLStats('READ_HEAVY_TABLE', 'MEDIUM'),
        compressionRatios: this.generateCompressionRatios(30, 'MIXED'),
        expectedRecommendation: 'QUERY_LOW'
      }
    };

    return scenarios[scenarioType] || scenarios.HIGH_DML_CANDIDATE;
  }

  /**
   * Generate batch of test tables
   */
  static generateBatch(count = 10, options = {}) {
    const tables = [];
    for (let i = 0; i < count; i++) {
      tables.push(this.generateTable({
        table_name: `BATCH_TABLE_${i.toString().padStart(4, '0')}`,
        ...options
      }));
    }
    return tables;
  }

  /**
   * Generate historical compression execution record
   */
  static generateCompressionHistory(tableName, compressionType, success = true) {
    const originalSize = Math.floor(Math.random() * 100000000000); // Up to 100GB
    const compressionRatio = success ? (2.5 + Math.random() * 8) : 1.0;
    const compressedSize = Math.floor(originalSize / compressionRatio);

    return {
      history_id: Math.floor(Math.random() * 1000000),
      owner: 'TESTUSER',
      object_name: tableName,
      object_type: 'TABLE',
      partition_name: null,
      compression_type: compressionType,
      original_size_mb: Math.floor(originalSize / (1024 * 1024)),
      compressed_size_mb: Math.floor(compressedSize / (1024 * 1024)),
      space_saved_mb: Math.floor((originalSize - compressedSize) / (1024 * 1024)),
      compression_ratio_achieved: parseFloat(compressionRatio.toFixed(2)),
      start_time: new Date(Date.now() - 3600000), // 1 hour ago
      end_time: new Date(),
      execution_status: success ? 'SUCCESS' : 'FAILED',
      error_message: success ? null : 'ORA-01653: unable to extend table'
    };
  }
}

module.exports = TestDataGenerator;
