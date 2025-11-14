/**
 * Compression Executor Module
 * Executes HCC compression operations safely with rollback support
 *
 * @module compression-executor
 */

const config = require('./config');
const {
  Logger,
  CompressionError,
  DatabaseError,
  ValidationError,
  retry,
  sleep,
  formatDuration,
  sanitizeSQLIdentifier,
  buildQualifiedTableName,
  measureTime
} = require('./utils');

const logger = new Logger(config.get('logging'));

/**
 * Execution status constants
 */
const EXECUTION_STATUS = {
  PENDING: 'PENDING',
  IN_PROGRESS: 'IN_PROGRESS',
  COMPLETED: 'COMPLETED',
  FAILED: 'FAILED',
  ROLLED_BACK: 'ROLLED_BACK'
};

/**
 * Compression Executor class
 */
class CompressionExecutor {
  constructor(historyTracker = null) {
    this.config = config;
    this.historyTracker = historyTracker;
    this.activeExecutions = new Map();
  }

  /**
   * Execute compression for a table
   * @param {Object} recommendation - Compression recommendation
   * @param {Object} [options={}] - Execution options
   * @param {boolean} [options.dryRun=false] - Generate DDL without executing
   * @param {boolean} [options.online=false] - Use online compression (partitions only)
   * @param {boolean} [options.parallel=0] - Parallel degree (0 = no parallel)
   * @returns {Promise<Object>} Execution result
   */
  async executeCompression(recommendation, options = {}) {
    const executionId = this._generateExecutionId();
    const startTime = Date.now();

    try {
      await logger.info('Starting compression execution', {
        executionId,
        schema: recommendation.table.schema,
        table: recommendation.table.name,
        compressionType: recommendation.recommendedCompression.name,
        dryRun: options.dryRun || false
      });

      // Validate recommendation
      this._validateRecommendation(recommendation);

      // Initialize execution tracking
      this.activeExecutions.set(executionId, {
        status: EXECUTION_STATUS.PENDING,
        recommendation,
        startTime,
        options
      });

      // Generate DDL statements
      const ddl = this._generateCompressionDDL(recommendation, options);

      // Dry run - return DDL without executing
      if (options.dryRun) {
        await logger.info('Dry run completed', { executionId });
        return {
          executionId,
          status: 'DRY_RUN',
          ddl,
          message: 'DDL generated successfully (not executed)'
        };
      }

      // Execute compression
      const result = await this._executeCompressionSteps(
        executionId,
        recommendation,
        ddl,
        options
      );

      // Record in history
      if (this.historyTracker) {
        await this.historyTracker.recordExecution(executionId, recommendation, result);
      }

      const executionTime = Date.now() - startTime;

      await logger.info('Compression execution completed', {
        executionId,
        duration: formatDuration(executionTime),
        status: result.status
      });

      return {
        executionId,
        ...result,
        executionTime: formatDuration(executionTime)
      };

    } catch (error) {
      await logger.error('Compression execution failed', {
        executionId,
        error: error.message,
        stack: error.stack
      });

      // Update execution status
      const execution = this.activeExecutions.get(executionId);
      if (execution) {
        execution.status = EXECUTION_STATUS.FAILED;
        execution.error = error;
      }

      throw new CompressionError(
        `Compression execution failed: ${error.message}`,
        'EXECUTION_FAILED',
        { executionId, originalError: error }
      );
    } finally {
      // Clean up old executions
      setTimeout(() => {
        this.activeExecutions.delete(executionId);
      }, 3600000); // Keep for 1 hour
    }
  }

  /**
   * Generate compression DDL statements
   * @private
   * @param {Object} recommendation - Compression recommendation
   * @param {Object} options - Execution options
   * @returns {Object} DDL statements
   */
  _generateCompressionDDL(recommendation, options) {
    const schema = recommendation.table.schema;
    const table = recommendation.table.name;
    const compressionType = recommendation.recommendedCompression.name;
    const qualifiedName = buildQualifiedTableName(schema, table);

    const ddl = {
      preCompression: [],
      compression: [],
      postCompression: [],
      rollback: []
    };

    // Pre-compression: Gather statistics
    ddl.preCompression.push({
      step: 'gather_stats_pre',
      description: 'Gather table statistics before compression',
      sql: `BEGIN DBMS_STATS.GATHER_TABLE_STATS('${schema}', '${table}', CASCADE => TRUE); END;`
    });

    // Compression DDL
    const parallelClause = options.parallel > 0 ? ` PARALLEL ${options.parallel}` : '';

    if (recommendation.implementationStrategy.approach === 'PARTITION_BY_PARTITION') {
      // Partition-by-partition compression
      const onlineClause = options.online ? ' ONLINE' : '';

      ddl.compression.push({
        step: 'compress_partitions',
        description: 'Compress table partitions',
        sql: `-- Note: Execute for each partition\nALTER TABLE ${qualifiedName} MODIFY PARTITION <partition_name> COMPRESS FOR ${compressionType}${onlineClause}${parallelClause}`,
        note: 'Replace <partition_name> with actual partition names'
      });
    } else {
      // Full table compression
      ddl.compression.push({
        step: 'compress_table',
        description: 'Compress entire table',
        sql: `ALTER TABLE ${qualifiedName} MOVE COMPRESS FOR ${compressionType}${parallelClause}`,
        warning: 'Table will be locked during this operation'
      });
    }

    // Post-compression: Rebuild indexes
    ddl.postCompression.push({
      step: 'rebuild_indexes',
      description: 'Rebuild unusable indexes',
      sql: `BEGIN
  FOR idx IN (
    SELECT index_name
    FROM dba_indexes
    WHERE owner = '${schema}'
      AND table_name = '${table}'
      AND status = 'UNUSABLE'
  ) LOOP
    EXECUTE IMMEDIATE 'ALTER INDEX "${schema}"."' || idx.index_name || '" REBUILD${parallelClause}';
  END LOOP;
END;`
    });

    // Post-compression: Gather statistics again
    ddl.postCompression.push({
      step: 'gather_stats_post',
      description: 'Gather table statistics after compression',
      sql: `BEGIN DBMS_STATS.GATHER_TABLE_STATS('${schema}', '${table}', CASCADE => TRUE); END;`
    });

    // Rollback: Move table back to uncompressed
    ddl.rollback.push({
      step: 'rollback_compression',
      description: 'Rollback compression (if needed)',
      sql: `ALTER TABLE ${qualifiedName} MOVE NOCOMPRESS${parallelClause}`,
      warning: 'Use only if compression causes issues'
    });

    return ddl;
  }

  /**
   * Execute compression steps
   * @private
   * @param {string} executionId - Execution ID
   * @param {Object} recommendation - Compression recommendation
   * @param {Object} ddl - Generated DDL
   * @param {Object} options - Execution options
   * @returns {Promise<Object>} Execution result
   */
  async _executeCompressionSteps(executionId, recommendation, ddl, options) {
    const conn = await this.config.getConnection();
    const results = {
      status: EXECUTION_STATUS.IN_PROGRESS,
      steps: [],
      beforeStats: null,
      afterStats: null,
      actualSavings: null
    };

    try {
      // Update execution status
      this.activeExecutions.get(executionId).status = EXECUTION_STATUS.IN_PROGRESS;

      // Capture before stats
      results.beforeStats = await this._captureTableStats(
        conn,
        recommendation.table.schema,
        recommendation.table.name
      );

      // Execute pre-compression steps
      for (const step of ddl.preCompression) {
        const stepResult = await this._executeStep(conn, step, executionId);
        results.steps.push(stepResult);

        if (!stepResult.success && step.critical !== false) {
          throw new CompressionError(
            `Pre-compression step failed: ${step.step}`,
            'STEP_FAILED',
            stepResult
          );
        }
      }

      // Execute compression
      for (const step of ddl.compression) {
        const stepResult = await this._executeStep(conn, step, executionId);
        results.steps.push(stepResult);

        if (!stepResult.success) {
          throw new CompressionError(
            `Compression step failed: ${step.step}`,
            'COMPRESSION_FAILED',
            stepResult
          );
        }
      }

      // Execute post-compression steps
      for (const step of ddl.postCompression) {
        const stepResult = await this._executeStep(conn, step, executionId);
        results.steps.push(stepResult);

        if (!stepResult.success && step.critical !== false) {
          await logger.warn('Post-compression step failed', {
            executionId,
            step: step.step,
            error: stepResult.error
          });
        }
      }

      // Capture after stats
      results.afterStats = await this._captureTableStats(
        conn,
        recommendation.table.schema,
        recommendation.table.name
      );

      // Calculate actual savings
      results.actualSavings = this._calculateActualSavings(
        results.beforeStats,
        results.afterStats
      );

      results.status = EXECUTION_STATUS.COMPLETED;
      this.activeExecutions.get(executionId).status = EXECUTION_STATUS.COMPLETED;

      return results;

    } catch (error) {
      await logger.error('Compression execution failed, attempting rollback', {
        executionId,
        error: error.message
      });

      // Attempt rollback
      try {
        await this._rollbackCompression(conn, ddl, executionId);
        results.status = EXECUTION_STATUS.ROLLED_BACK;
      } catch (rollbackError) {
        await logger.error('Rollback failed', {
          executionId,
          error: rollbackError.message
        });
        results.status = EXECUTION_STATUS.FAILED;
        results.rollbackError = rollbackError.message;
      }

      throw error;

    } finally {
      await conn.close();
    }
  }

  /**
   * Execute a single DDL step
   * @private
   * @param {Object} conn - Database connection
   * @param {Object} step - DDL step
   * @param {string} executionId - Execution ID
   * @returns {Promise<Object>} Step result
   */
  async _executeStep(conn, step, executionId) {
    await logger.info(`Executing step: ${step.step}`, { executionId });

    const stepResult = {
      step: step.step,
      description: step.description,
      success: false,
      startTime: Date.now(),
      executionTime: null,
      error: null
    };

    try {
      const result = await measureTime(async () => {
        return await conn.execute(step.sql, [], { autoCommit: true });
      });

      stepResult.success = true;
      stepResult.executionTime = result.executionTimeFormatted;
      stepResult.rowsAffected = result.result.rowsAffected;

      await logger.info(`Step completed: ${step.step}`, {
        executionId,
        duration: result.executionTimeFormatted
      });

    } catch (error) {
      stepResult.error = error.message;
      await logger.error(`Step failed: ${step.step}`, {
        executionId,
        error: error.message
      });
    }

    return stepResult;
  }

  /**
   * Capture table statistics
   * @private
   * @param {Object} conn - Database connection
   * @param {string} schema - Schema name
   * @param {string} table - Table name
   * @returns {Promise<Object>} Table statistics
   */
  async _captureTableStats(conn, schema, table) {
    const query = `
      SELECT
        t.num_rows,
        t.blocks,
        t.avg_row_len,
        t.compression,
        t.compress_for,
        s.bytes,
        s.bytes / 1024 / 1024 AS size_mb
      FROM dba_tables t
      JOIN dba_segments s ON t.owner = s.owner AND t.table_name = s.segment_name
      WHERE t.owner = :schema AND t.table_name = :table
    `;

    const result = await conn.execute(query, {
      schema: sanitizeSQLIdentifier(schema),
      table: sanitizeSQLIdentifier(table)
    });

    if (result.rows.length === 0) {
      throw new ValidationError(`Table ${schema}.${table} not found`);
    }

    const row = result.rows[0];
    return {
      numRows: row[0],
      blocks: row[1],
      avgRowLen: row[2],
      compression: row[3],
      compressFor: row[4],
      sizeBytes: row[5],
      sizeMB: row[6],
      capturedAt: new Date().toISOString()
    };
  }

  /**
   * Calculate actual savings achieved
   * @private
   * @param {Object} beforeStats - Stats before compression
   * @param {Object} afterStats - Stats after compression
   * @returns {Object} Savings information
   */
  _calculateActualSavings(beforeStats, afterStats) {
    const savedBytes = beforeStats.sizeBytes - afterStats.sizeBytes;
    const compressionRatio = beforeStats.sizeBytes / afterStats.sizeBytes;
    const percentageSaved = (savedBytes / beforeStats.sizeBytes) * 100;

    return {
      beforeSize: beforeStats.sizeBytes,
      afterSize: afterStats.sizeBytes,
      savedBytes,
      compressionRatio: compressionRatio.toFixed(2),
      percentageSaved: percentageSaved.toFixed(2),
      beforeCompression: beforeStats.compression,
      afterCompression: afterStats.compression,
      compressionType: afterStats.compressFor
    };
  }

  /**
   * Rollback compression
   * @private
   * @param {Object} conn - Database connection
   * @param {Object} ddl - Generated DDL
   * @param {string} executionId - Execution ID
   * @returns {Promise<void>}
   */
  async _rollbackCompression(conn, ddl, executionId) {
    await logger.info('Executing rollback', { executionId });

    for (const step of ddl.rollback) {
      try {
        await conn.execute(step.sql, [], { autoCommit: true });
        await logger.info(`Rollback step completed: ${step.step}`, { executionId });
      } catch (error) {
        await logger.error(`Rollback step failed: ${step.step}`, {
          executionId,
          error: error.message
        });
        throw error;
      }
    }

    this.activeExecutions.get(executionId).status = EXECUTION_STATUS.ROLLED_BACK;
  }

  /**
   * Validate recommendation before execution
   * @private
   * @param {Object} recommendation - Compression recommendation
   * @throws {ValidationError} If recommendation is invalid
   */
  _validateRecommendation(recommendation) {
    if (!recommendation.table?.schema || !recommendation.table?.name) {
      throw new ValidationError('Invalid recommendation: missing table information');
    }

    if (!recommendation.recommendedCompression?.name) {
      throw new ValidationError('Invalid recommendation: missing compression type');
    }

    if (recommendation.riskAssessment?.riskLevel === 'HIGH') {
      throw new ValidationError(
        'High-risk compression requires manual review and approval'
      );
    }
  }

  /**
   * Generate unique execution ID
   * @private
   * @returns {string} Execution ID
   */
  _generateExecutionId() {
    return `exec_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  /**
   * Get execution status
   * @param {string} executionId - Execution ID
   * @returns {Object|null} Execution status or null if not found
   */
  getExecutionStatus(executionId) {
    return this.activeExecutions.get(executionId) || null;
  }

  /**
   * List all active executions
   * @returns {Array} Active executions
   */
  listActiveExecutions() {
    return Array.from(this.activeExecutions.entries()).map(([id, exec]) => ({
      executionId: id,
      status: exec.status,
      table: `${exec.recommendation.table.schema}.${exec.recommendation.table.name}`,
      startTime: exec.startTime,
      elapsedTime: formatDuration(Date.now() - exec.startTime)
    }));
  }
}

module.exports = CompressionExecutor;
module.exports.EXECUTION_STATUS = EXECUTION_STATUS;
