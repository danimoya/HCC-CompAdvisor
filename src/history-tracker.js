/**
 * Historical Tracker Module
 * Tracks compression operations, recommendations, and results
 *
 * @module history-tracker
 */

const config = require('./config');
const {
  Logger,
  DatabaseError,
  ValidationError,
  sanitizeSQLIdentifier
} = require('./utils');

const logger = new Logger(config.get('logging'));

/**
 * Historical Tracker class
 */
class HistoryTracker {
  constructor() {
    this.config = config;
    this.initialized = false;
  }

  /**
   * Initialize history tracking tables
   * @returns {Promise<void>}
   */
  async initialize() {
    if (this.initialized) {
      return;
    }

    const conn = await this.config.getConnection();

    try {
      await logger.info('Initializing history tracking tables');

      // Create history table if not exists
      await this._createHistoryTable(conn);

      // Create indexes
      await this._createIndexes(conn);

      this.initialized = true;
      await logger.info('History tracking initialized');

    } catch (error) {
      await logger.error('Failed to initialize history tracking', {
        error: error.message
      });
      throw new DatabaseError('Failed to initialize history tracking', error);
    } finally {
      await conn.close();
    }
  }

  /**
   * Record a compression recommendation
   * @param {Object} recommendation - Compression recommendation
   * @returns {Promise<string>} Record ID
   */
  async recordRecommendation(recommendation) {
    const conn = await this.config.getConnection();

    try {
      const recordId = this._generateRecordId('REC');

      const insertSQL = `
        INSERT INTO compression_history (
          record_id,
          record_type,
          schema_name,
          table_name,
          operation_time,
          status,
          recommended_compression,
          expected_ratio,
          expected_savings_mb,
          current_size_mb,
          current_compression,
          workload_type,
          priority,
          recommendation_data
        ) VALUES (
          :recordId,
          'RECOMMENDATION',
          :schema,
          :table,
          SYSTIMESTAMP,
          'GENERATED',
          :recommendedCompression,
          :expectedRatio,
          :expectedSavings,
          :currentSize,
          :currentCompression,
          :workloadType,
          :priority,
          :recommendationData
        )
      `;

      await conn.execute(insertSQL, {
        recordId,
        schema: recommendation.table.schema,
        table: recommendation.table.name,
        recommendedCompression: recommendation.recommendedCompression.name,
        expectedRatio: recommendation.expectedSavings.expectedRatio,
        expectedSavings: parseFloat(recommendation.expectedSavings.expectedCompressedSize),
        currentSize: parseFloat(recommendation.table.currentSize),
        currentCompression: recommendation.table.currentCompression,
        workloadType: recommendation.workloadProfile?.workloadType || 'UNKNOWN',
        priority: recommendation.priority,
        recommendationData: JSON.stringify(recommendation)
      }, { autoCommit: true });

      await logger.info('Recommendation recorded', {
        recordId,
        schema: recommendation.table.schema,
        table: recommendation.table.name
      });

      return recordId;

    } catch (error) {
      await logger.error('Failed to record recommendation', {
        error: error.message
      });
      throw new DatabaseError('Failed to record recommendation', error);
    } finally {
      await conn.close();
    }
  }

  /**
   * Record a compression execution
   * @param {string} executionId - Execution ID
   * @param {Object} recommendation - Original recommendation
   * @param {Object} result - Execution result
   * @returns {Promise<string>} Record ID
   */
  async recordExecution(executionId, recommendation, result) {
    const conn = await this.config.getConnection();

    try {
      const recordId = this._generateRecordId('EXEC');

      const insertSQL = `
        INSERT INTO compression_history (
          record_id,
          record_type,
          execution_id,
          schema_name,
          table_name,
          operation_time,
          status,
          recommended_compression,
          applied_compression,
          expected_ratio,
          actual_ratio,
          expected_savings_mb,
          actual_savings_mb,
          before_size_mb,
          after_size_mb,
          execution_duration_ms,
          execution_data
        ) VALUES (
          :recordId,
          'EXECUTION',
          :executionId,
          :schema,
          :table,
          SYSTIMESTAMP,
          :status,
          :recommendedCompression,
          :appliedCompression,
          :expectedRatio,
          :actualRatio,
          :expectedSavings,
          :actualSavings,
          :beforeSize,
          :afterSize,
          :duration,
          :executionData
        )
      `;

      const actualSavings = result.actualSavings || {};
      const beforeStats = result.beforeStats || {};
      const afterStats = result.afterStats || {};

      await conn.execute(insertSQL, {
        recordId,
        executionId,
        schema: recommendation.table.schema,
        table: recommendation.table.name,
        status: result.status,
        recommendedCompression: recommendation.recommendedCompression.name,
        appliedCompression: afterStats.compressFor || null,
        expectedRatio: recommendation.expectedSavings.expectedRatio,
        actualRatio: parseFloat(actualSavings.compressionRatio) || null,
        expectedSavings: parseFloat(recommendation.expectedSavings.savedBytes) / (1024 * 1024),
        actualSavings: (actualSavings.savedBytes || 0) / (1024 * 1024),
        beforeSize: (beforeStats.sizeBytes || 0) / (1024 * 1024),
        afterSize: (afterStats.sizeBytes || 0) / (1024 * 1024),
        duration: Date.now() - recommendation.generatedAt || 0,
        executionData: JSON.stringify({
          recommendation,
          result,
          steps: result.steps
        })
      }, { autoCommit: true });

      await logger.info('Execution recorded', {
        recordId,
        executionId,
        status: result.status
      });

      return recordId;

    } catch (error) {
      await logger.error('Failed to record execution', {
        executionId,
        error: error.message
      });
      throw new DatabaseError('Failed to record execution', error);
    } finally {
      await conn.close();
    }
  }

  /**
   * Get history for a specific table
   * @param {string} schemaName - Schema name
   * @param {string} tableName - Table name
   * @param {Object} [options={}] - Query options
   * @returns {Promise<Array>} History records
   */
  async getTableHistory(schemaName, tableName, options = {}) {
    const conn = await this.config.getConnection();

    try {
      const limit = options.limit || 100;
      const recordType = options.recordType || null;

      let whereClause = 'WHERE schema_name = :schema AND table_name = :table';
      const binds = {
        schema: sanitizeSQLIdentifier(schemaName),
        table: sanitizeSQLIdentifier(tableName)
      };

      if (recordType) {
        whereClause += ' AND record_type = :recordType';
        binds.recordType = recordType;
      }

      const query = `
        SELECT
          record_id,
          record_type,
          execution_id,
          operation_time,
          status,
          recommended_compression,
          applied_compression,
          expected_ratio,
          actual_ratio,
          expected_savings_mb,
          actual_savings_mb,
          before_size_mb,
          after_size_mb,
          execution_duration_ms
        FROM compression_history
        ${whereClause}
        ORDER BY operation_time DESC
        FETCH FIRST :limit ROWS ONLY
      `;

      binds.limit = limit;

      const result = await conn.execute(query, binds);

      return result.rows.map(row => ({
        recordId: row[0],
        recordType: row[1],
        executionId: row[2],
        operationTime: row[3],
        status: row[4],
        recommendedCompression: row[5],
        appliedCompression: row[6],
        expectedRatio: row[7],
        actualRatio: row[8],
        expectedSavingsMB: row[9],
        actualSavingsMB: row[10],
        beforeSizeMB: row[11],
        afterSizeMB: row[12],
        executionDurationMs: row[13]
      }));

    } catch (error) {
      await logger.error('Failed to retrieve table history', {
        schemaName,
        tableName,
        error: error.message
      });
      throw new DatabaseError('Failed to retrieve table history', error);
    } finally {
      await conn.close();
    }
  }

  /**
   * Get compression statistics summary
   * @param {Object} [options={}] - Query options
   * @returns {Promise<Object>} Statistics summary
   */
  async getStatisticsSummary(options = {}) {
    const conn = await this.config.getConnection();

    try {
      const days = options.days || 30;

      const query = `
        SELECT
          COUNT(*) AS total_operations,
          COUNT(CASE WHEN record_type = 'RECOMMENDATION' THEN 1 END) AS total_recommendations,
          COUNT(CASE WHEN record_type = 'EXECUTION' THEN 1 END) AS total_executions,
          COUNT(CASE WHEN status = 'COMPLETED' THEN 1 END) AS successful_executions,
          COUNT(CASE WHEN status = 'FAILED' THEN 1 END) AS failed_executions,
          SUM(actual_savings_mb) AS total_space_saved_mb,
          AVG(actual_ratio) AS avg_compression_ratio,
          MAX(actual_ratio) AS max_compression_ratio,
          MIN(actual_ratio) AS min_compression_ratio
        FROM compression_history
        WHERE operation_time >= SYSTIMESTAMP - INTERVAL ':days' DAY
      `;

      const result = await conn.execute(query, { days });

      if (result.rows.length === 0) {
        return null;
      }

      const row = result.rows[0];
      return {
        totalOperations: row[0],
        totalRecommendations: row[1],
        totalExecutions: row[2],
        successfulExecutions: row[3],
        failedExecutions: row[4],
        totalSpaceSavedMB: row[5] || 0,
        avgCompressionRatio: row[6] || 0,
        maxCompressionRatio: row[7] || 0,
        minCompressionRatio: row[8] || 0,
        successRate: row[2] > 0 ? ((row[3] / row[2]) * 100).toFixed(2) : 0,
        periodDays: days
      };

    } catch (error) {
      await logger.error('Failed to retrieve statistics summary', {
        error: error.message
      });
      throw new DatabaseError('Failed to retrieve statistics summary', error);
    } finally {
      await conn.close();
    }
  }

  /**
   * Clean up old history records
   * @param {number} [retentionDays] - Number of days to retain
   * @returns {Promise<number>} Number of records deleted
   */
  async cleanupHistory(retentionDays = null) {
    const conn = await this.config.getConnection();

    try {
      const days = retentionDays || this.config.get('history.retentionDays');

      const deleteSQL = `
        DELETE FROM compression_history
        WHERE operation_time < SYSTIMESTAMP - INTERVAL ':days' DAY
      `;

      const result = await conn.execute(deleteSQL, { days }, { autoCommit: true });

      await logger.info(`Cleaned up ${result.rowsAffected} old history records`, {
        retentionDays: days
      });

      return result.rowsAffected;

    } catch (error) {
      await logger.error('Failed to cleanup history', {
        error: error.message
      });
      throw new DatabaseError('Failed to cleanup history', error);
    } finally {
      await conn.close();
    }
  }

  /**
   * Create history tracking table
   * @private
   */
  async _createHistoryTable(conn) {
    const schemaName = this.config.get('history.schemaName');
    const tableName = this.config.get('history.tableName');

    const createTableSQL = `
      CREATE TABLE ${schemaName}.${tableName} (
        record_id VARCHAR2(50) PRIMARY KEY,
        record_type VARCHAR2(20) NOT NULL,
        execution_id VARCHAR2(50),
        schema_name VARCHAR2(128) NOT NULL,
        table_name VARCHAR2(128) NOT NULL,
        operation_time TIMESTAMP DEFAULT SYSTIMESTAMP,
        status VARCHAR2(20),
        recommended_compression VARCHAR2(30),
        applied_compression VARCHAR2(30),
        expected_ratio NUMBER(10,2),
        actual_ratio NUMBER(10,2),
        expected_savings_mb NUMBER(15,2),
        actual_savings_mb NUMBER(15,2),
        before_size_mb NUMBER(15,2),
        after_size_mb NUMBER(15,2),
        current_size_mb NUMBER(15,2),
        current_compression VARCHAR2(30),
        workload_type VARCHAR2(20),
        priority VARCHAR2(10),
        execution_duration_ms NUMBER(15),
        recommendation_data CLOB,
        execution_data CLOB,
        created_at TIMESTAMP DEFAULT SYSTIMESTAMP,
        CONSTRAINT chk_record_type CHECK (record_type IN ('RECOMMENDATION', 'EXECUTION')),
        CONSTRAINT chk_status CHECK (status IN ('GENERATED', 'PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'ROLLED_BACK'))
      )
    `;

    try {
      await conn.execute(createTableSQL);
      await logger.info('History table created');
    } catch (error) {
      // Table might already exist
      if (error.message.includes('ORA-00955')) {
        await logger.debug('History table already exists');
      } else {
        throw error;
      }
    }
  }

  /**
   * Create indexes on history table
   * @private
   */
  async _createIndexes(conn) {
    const schemaName = this.config.get('history.schemaName');
    const tableName = this.config.get('history.tableName');

    const indexes = [
      `CREATE INDEX idx_ch_table ON ${schemaName}.${tableName}(schema_name, table_name)`,
      `CREATE INDEX idx_ch_operation_time ON ${schemaName}.${tableName}(operation_time)`,
      `CREATE INDEX idx_ch_status ON ${schemaName}.${tableName}(status)`,
      `CREATE INDEX idx_ch_record_type ON ${schemaName}.${tableName}(record_type)`
    ];

    for (const indexSQL of indexes) {
      try {
        await conn.execute(indexSQL);
      } catch (error) {
        // Index might already exist
        if (!error.message.includes('ORA-00955')) {
          await logger.warn('Failed to create index', { error: error.message });
        }
      }
    }
  }

  /**
   * Generate unique record ID
   * @private
   */
  _generateRecordId(prefix) {
    return `${prefix}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }
}

module.exports = HistoryTracker;
