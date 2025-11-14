/**
 * HCC Compression Advisor - Main Entry Point
 * Oracle Hybrid Columnar Compression (HCC) Management System
 *
 * @module hcc-compression-advisor
 */

const config = require('./config');
const CandidateIdentifier = require('./candidate-identifier');
const RecommendationEngine = require('./recommendation-engine');
const CompressionExecutor = require('./compression-executor');
const HistoryTracker = require('./history-tracker');
const { Logger } = require('./utils');

const logger = new Logger(config.get('logging'));

/**
 * HCC Compression Advisor main class
 */
class HCCCompressionAdvisor {
  constructor(configPath = null) {
    this.config = config;
    this.configPath = configPath;
    this.initialized = false;

    // Initialize components
    this.candidateIdentifier = new CandidateIdentifier();
    this.recommendationEngine = new RecommendationEngine();
    this.historyTracker = new HistoryTracker();
    this.compressionExecutor = new CompressionExecutor(this.historyTracker);
  }

  /**
   * Initialize the compression advisor
   * @returns {Promise<void>}
   */
  async initialize() {
    if (this.initialized) {
      return;
    }

    try {
      await logger.info('Initializing HCC Compression Advisor');

      // Load configuration if path provided
      if (this.configPath) {
        await this.config.loadFromFile(this.configPath);
      }

      // Validate configuration
      const validation = this.config.validate();
      if (!validation.isValid) {
        throw new Error(`Configuration validation failed: ${validation.errors.join(', ')}`);
      }

      // Initialize database connection pool
      await this.config.initializePool();

      // Initialize history tracking
      await this.historyTracker.initialize();

      this.initialized = true;
      await logger.info('HCC Compression Advisor initialized successfully');

    } catch (error) {
      await logger.error('Failed to initialize HCC Compression Advisor', {
        error: error.message
      });
      throw error;
    }
  }

  /**
   * Identify compression candidates
   * @param {Object} [options] - Filter options
   * @returns {Promise<Array>} Compression candidates
   */
  async identifyCandidates(options = {}) {
    this._ensureInitialized();
    return await this.candidateIdentifier.identifyCandidates(options);
  }

  /**
   * Analyze specific table
   * @param {string} schemaName - Schema name
   * @param {string} tableName - Table name
   * @returns {Promise<Object>} Table analysis
   */
  async analyzeTable(schemaName, tableName) {
    this._ensureInitialized();
    return await this.candidateIdentifier.analyzeTable(schemaName, tableName);
  }

  /**
   * Generate compression recommendation
   * @param {Object} tableAnalysis - Table analysis from analyzeTable
   * @returns {Promise<Object>} Compression recommendation
   */
  async generateRecommendation(tableAnalysis) {
    this._ensureInitialized();
    const recommendation = await this.recommendationEngine.generateRecommendation(tableAnalysis);

    // Record recommendation in history
    await this.historyTracker.recordRecommendation(recommendation);

    return recommendation;
  }

  /**
   * Generate batch recommendations
   * @param {Array} candidates - Compression candidates
   * @returns {Promise<Array>} Recommendations
   */
  async generateBatchRecommendations(candidates) {
    this._ensureInitialized();
    return await this.recommendationEngine.generateBatchRecommendations(candidates);
  }

  /**
   * Execute compression
   * @param {Object} recommendation - Compression recommendation
   * @param {Object} [options] - Execution options
   * @returns {Promise<Object>} Execution result
   */
  async executeCompression(recommendation, options = {}) {
    this._ensureInitialized();
    return await this.compressionExecutor.executeCompression(recommendation, options);
  }

  /**
   * Get table compression history
   * @param {string} schemaName - Schema name
   * @param {string} tableName - Table name
   * @param {Object} [options] - Query options
   * @returns {Promise<Array>} History records
   */
  async getTableHistory(schemaName, tableName, options = {}) {
    this._ensureInitialized();
    return await this.historyTracker.getTableHistory(schemaName, tableName, options);
  }

  /**
   * Get compression statistics summary
   * @param {Object} [options] - Query options
   * @returns {Promise<Object>} Statistics summary
   */
  async getStatistics(options = {}) {
    this._ensureInitialized();
    return await this.historyTracker.getStatisticsSummary(options);
  }

  /**
   * Get database pool statistics
   * @returns {Object|null} Pool statistics
   */
  getPoolStats() {
    return this.config.getPoolStats();
  }

  /**
   * Complete workflow: identify, recommend, and optionally execute
   * @param {Object} [options] - Workflow options
   * @param {boolean} [options.execute=false] - Execute compression
   * @param {boolean} [options.dryRun=true] - Generate DDL only
   * @returns {Promise<Object>} Workflow results
   */
  async runWorkflow(options = {}) {
    this._ensureInitialized();

    const workflowResults = {
      candidates: [],
      recommendations: [],
      executions: [],
      summary: {}
    };

    try {
      await logger.info('Starting compression workflow', { options });

      // Step 1: Identify candidates
      await logger.info('Identifying compression candidates');
      workflowResults.candidates = await this.identifyCandidates(options);

      if (workflowResults.candidates.length === 0) {
        await logger.info('No compression candidates found');
        return workflowResults;
      }

      // Step 2: Generate recommendations
      await logger.info(`Generating recommendations for ${workflowResults.candidates.length} candidates`);
      workflowResults.recommendations = await this.generateBatchRecommendations(
        workflowResults.candidates
      );

      // Step 3: Execute compression (if requested)
      if (options.execute || options.dryRun) {
        const executeOptions = {
          dryRun: options.dryRun !== false,
          online: options.online || false,
          parallel: options.parallel || 0
        };

        for (const recommendation of workflowResults.recommendations) {
          // Only execute high/medium priority by default
          if (recommendation.priority === 'LOW' && !options.includeLowPriority) {
            continue;
          }

          try {
            const result = await this.executeCompression(recommendation, executeOptions);
            workflowResults.executions.push(result);
          } catch (error) {
            await logger.error('Execution failed for table', {
              table: recommendation.table.name,
              error: error.message
            });
            workflowResults.executions.push({
              table: recommendation.table,
              status: 'FAILED',
              error: error.message
            });
          }
        }
      }

      // Generate summary
      workflowResults.summary = this._generateWorkflowSummary(workflowResults);

      await logger.info('Compression workflow completed', {
        summary: workflowResults.summary
      });

      return workflowResults;

    } catch (error) {
      await logger.error('Workflow failed', { error: error.message });
      throw error;
    }
  }

  /**
   * Shutdown the compression advisor
   * @returns {Promise<void>}
   */
  async shutdown() {
    try {
      await logger.info('Shutting down HCC Compression Advisor');
      await this.config.closePool();
      this.initialized = false;
      await logger.info('Shutdown complete');
    } catch (error) {
      await logger.error('Error during shutdown', { error: error.message });
      throw error;
    }
  }

  /**
   * Ensure advisor is initialized
   * @private
   * @throws {Error} If not initialized
   */
  _ensureInitialized() {
    if (!this.initialized) {
      throw new Error('HCC Compression Advisor not initialized. Call initialize() first.');
    }
  }

  /**
   * Generate workflow summary
   * @private
   * @param {Object} results - Workflow results
   * @returns {Object} Summary
   */
  _generateWorkflowSummary(results) {
    const summary = {
      candidatesFound: results.candidates.length,
      recommendationsGenerated: results.recommendations.length,
      executionsAttempted: results.executions.length,
      executionsSucceeded: results.executions.filter(e => e.status === 'COMPLETED').length,
      executionsFailed: results.executions.filter(e => e.status === 'FAILED').length,
      totalExpectedSavings: 0,
      totalActualSavings: 0
    };

    // Calculate expected savings
    for (const rec of results.recommendations) {
      if (rec.expectedSavings?.savedBytes) {
        summary.totalExpectedSavings += rec.expectedSavings.savedBytes;
      }
    }

    // Calculate actual savings
    for (const exec of results.executions) {
      if (exec.actualSavings?.savedBytes) {
        summary.totalActualSavings += exec.actualSavings.savedBytes;
      }
    }

    return summary;
  }
}

// Export main class and components
module.exports = HCCCompressionAdvisor;
module.exports.CandidateIdentifier = CandidateIdentifier;
module.exports.RecommendationEngine = RecommendationEngine;
module.exports.CompressionExecutor = CompressionExecutor;
module.exports.HistoryTracker = HistoryTracker;
module.exports.config = config;
