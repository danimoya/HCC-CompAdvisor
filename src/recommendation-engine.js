/**
 * Recommendation Engine Module
 * Analyzes table characteristics and recommends optimal HCC compression type
 *
 * @module recommendation-engine
 */

const config = require('./config');
const {
  Logger,
  ValidationError,
  formatBytes,
  calculateSavings
} = require('./utils');

const logger = new Logger(config.get('logging'));

/**
 * HCC Compression types and their characteristics
 */
const HCC_TYPES = {
  QUERY_LOW: {
    name: 'QUERY LOW',
    compressionRatio: { min: 6, max: 10, avg: 8 },
    queryPerformance: 'EXCELLENT',
    cpuOverhead: 'LOW',
    useCase: 'Frequently queried data with moderate compression needs',
    workloadType: 'READ_HEAVY'
  },
  QUERY_HIGH: {
    name: 'QUERY HIGH',
    compressionRatio: { min: 10, max: 15, avg: 12 },
    queryPerformance: 'GOOD',
    cpuOverhead: 'MEDIUM',
    useCase: 'Balanced query performance and compression',
    workloadType: 'READ_HEAVY'
  },
  ARCHIVE_LOW: {
    name: 'ARCHIVE LOW',
    compressionRatio: { min: 15, max: 20, avg: 17 },
    queryPerformance: 'MODERATE',
    cpuOverhead: 'HIGH',
    useCase: 'Infrequently accessed archival data',
    workloadType: 'ARCHIVE'
  },
  ARCHIVE_HIGH: {
    name: 'ARCHIVE HIGH',
    compressionRatio: { min: 20, max: 50, avg: 30 },
    queryPerformance: 'LOW',
    cpuOverhead: 'VERY_HIGH',
    useCase: 'Rarely accessed long-term archival data',
    workloadType: 'ARCHIVE'
  }
};

/**
 * Recommendation Engine class
 */
class RecommendationEngine {
  constructor() {
    this.config = config;
  }

  /**
   * Generate compression recommendations for a table
   * @param {Object} tableAnalysis - Table analysis from CandidateIdentifier
   * @returns {Promise<Object>} Compression recommendation
   */
  async generateRecommendation(tableAnalysis) {
    try {
      await logger.info('Generating compression recommendation', {
        schema: tableAnalysis.table?.schemaName,
        table: tableAnalysis.table?.tableName
      });

      // Analyze workload characteristics
      const workloadProfile = this._analyzeWorkload(tableAnalysis);

      // Select optimal compression type
      const compressionType = this._selectCompressionType(
        tableAnalysis,
        workloadProfile
      );

      // Calculate expected savings
      const savingsAnalysis = this._calculateExpectedSavings(
        tableAnalysis,
        compressionType
      );

      // Generate implementation strategy
      const implementationStrategy = this._generateImplementationStrategy(
        tableAnalysis,
        compressionType
      );

      // Assess risks and prerequisites
      const riskAssessment = this._assessRisks(tableAnalysis, compressionType);

      const recommendation = {
        table: {
          schema: tableAnalysis.table?.schemaName,
          name: tableAnalysis.table?.tableName,
          currentSize: formatBytes(tableAnalysis.table?.sizeBytes || 0),
          currentCompression: tableAnalysis.table?.compression || 'NONE'
        },
        workloadProfile,
        recommendedCompression: compressionType,
        expectedSavings: savingsAnalysis,
        implementationStrategy,
        riskAssessment,
        priority: this._calculatePriority(tableAnalysis, savingsAnalysis),
        estimatedDuration: this._estimateCompressionDuration(tableAnalysis),
        generatedAt: new Date().toISOString()
      };

      await logger.info('Recommendation generated', {
        type: compressionType.name,
        priority: recommendation.priority,
        savings: savingsAnalysis.savedFormatted
      });

      return recommendation;
    } catch (error) {
      await logger.error('Failed to generate recommendation', {
        error: error.message
      });
      throw error;
    }
  }

  /**
   * Generate batch recommendations for multiple tables
   * @param {Array} candidates - Array of table candidates
   * @returns {Promise<Array>} Array of recommendations
   */
  async generateBatchRecommendations(candidates) {
    await logger.info(`Generating recommendations for ${candidates.length} tables`);

    const recommendations = [];

    for (const candidate of candidates) {
      try {
        const recommendation = await this._generateQuickRecommendation(candidate);
        recommendations.push(recommendation);
      } catch (error) {
        await logger.warn('Failed to generate recommendation for table', {
          schema: candidate.schemaName,
          table: candidate.tableName,
          error: error.message
        });
      }
    }

    // Sort by priority
    recommendations.sort((a, b) => {
      const priorityOrder = { HIGH: 3, MEDIUM: 2, LOW: 1 };
      return priorityOrder[b.priority] - priorityOrder[a.priority];
    });

    return recommendations;
  }

  /**
   * Analyze workload characteristics
   * @private
   * @param {Object} tableAnalysis - Table analysis
   * @returns {Object} Workload profile
   */
  _analyzeWorkload(tableAnalysis) {
    const readCount = tableAnalysis.table?.readCount || 0;
    const writeCount = tableAnalysis.table?.writeCount || 0;
    const totalOps = readCount + writeCount;

    let workloadType = 'UNKNOWN';
    let accessFrequency = 'UNKNOWN';

    if (totalOps > 0) {
      const readRatio = readCount / totalOps;

      if (readRatio >= 0.9) {
        workloadType = 'READ_ONLY';
      } else if (readRatio >= 0.7) {
        workloadType = 'READ_HEAVY';
      } else if (readRatio >= 0.3) {
        workloadType = 'MIXED';
      } else {
        workloadType = 'WRITE_HEAVY';
      }

      // Classify access frequency
      if (totalOps > 10000) {
        accessFrequency = 'HIGH';
      } else if (totalOps > 1000) {
        accessFrequency = 'MEDIUM';
      } else if (totalOps > 100) {
        accessFrequency = 'LOW';
      } else {
        accessFrequency = 'VERY_LOW';
      }
    }

    return {
      workloadType,
      accessFrequency,
      readCount,
      writeCount,
      readRatio: totalOps > 0 ? (readCount / totalOps * 100).toFixed(2) : 0,
      writeRatio: totalOps > 0 ? (writeCount / totalOps * 100).toFixed(2) : 0,
      isArchivalCandidate: accessFrequency === 'VERY_LOW' || accessFrequency === 'LOW'
    };
  }

  /**
   * Select optimal compression type
   * @private
   * @param {Object} tableAnalysis - Table analysis
   * @param {Object} workloadProfile - Workload profile
   * @returns {Object} Selected HCC type
   */
  _selectCompressionType(tableAnalysis, workloadProfile) {
    // Default to configured type
    let selectedType = HCC_TYPES.QUERY_LOW;

    // Archive candidates
    if (workloadProfile.isArchivalCandidate) {
      if (workloadProfile.accessFrequency === 'VERY_LOW') {
        selectedType = HCC_TYPES.ARCHIVE_HIGH;
      } else {
        selectedType = HCC_TYPES.ARCHIVE_LOW;
      }
    }
    // Read-heavy workloads
    else if (workloadProfile.workloadType === 'READ_ONLY' ||
             workloadProfile.workloadType === 'READ_HEAVY') {
      const tableSize = tableAnalysis.table?.sizeMB || 0;

      // Larger tables benefit more from higher compression
      if (tableSize > 10000) { // > 10GB
        selectedType = HCC_TYPES.QUERY_HIGH;
      } else {
        selectedType = HCC_TYPES.QUERY_LOW;
      }
    }
    // Mixed workloads - use lower compression for better performance
    else if (workloadProfile.workloadType === 'MIXED') {
      selectedType = HCC_TYPES.QUERY_LOW;
    }
    // Write-heavy - HCC not recommended, but if forced, use lowest
    else if (workloadProfile.workloadType === 'WRITE_HEAVY') {
      selectedType = HCC_TYPES.QUERY_LOW;
      selectedType.warning = 'HCC not recommended for write-heavy workloads';
    }

    return { ...selectedType };
  }

  /**
   * Calculate expected savings
   * @private
   * @param {Object} tableAnalysis - Table analysis
   * @param {Object} compressionType - Selected compression type
   * @returns {Object} Savings analysis
   */
  _calculateExpectedSavings(tableAnalysis, compressionType) {
    const currentSize = tableAnalysis.table?.sizeBytes || 0;
    const avgRatio = compressionType.compressionRatio.avg;

    // Calculate expected compressed size
    const expectedCompressedSize = currentSize / avgRatio;

    // Calculate savings
    const savings = calculateSavings(currentSize, expectedCompressedSize);

    // Calculate range (min/max)
    const minCompressedSize = currentSize / compressionType.compressionRatio.max;
    const maxCompressedSize = currentSize / compressionType.compressionRatio.min;

    const minSavings = calculateSavings(currentSize, minCompressedSize);
    const maxSavings = calculateSavings(currentSize, maxCompressedSize);

    return {
      currentSize: formatBytes(currentSize),
      expectedCompressedSize: formatBytes(expectedCompressedSize),
      expectedRatio: avgRatio,
      savedBytes: savings.savedBytes,
      savedFormatted: savings.savedFormatted,
      percentageSaved: savings.percentage,
      range: {
        min: {
          compressedSize: formatBytes(maxCompressedSize),
          saved: maxSavings.savedFormatted,
          ratio: compressionType.compressionRatio.min
        },
        max: {
          compressedSize: formatBytes(minCompressedSize),
          saved: minSavings.savedFormatted,
          ratio: compressionType.compressionRatio.max
        }
      }
    };
  }

  /**
   * Generate implementation strategy
   * @private
   * @param {Object} tableAnalysis - Table analysis
   * @param {Object} compressionType - Selected compression type
   * @returns {Object} Implementation strategy
   */
  _generateImplementationStrategy(tableAnalysis, compressionType) {
    const isPartitioned = tableAnalysis.table?.partitioned || false;
    const partitionCount = tableAnalysis.partitions?.length || 0;
    const hasIndexes = tableAnalysis.indexes?.length > 0;

    const strategy = {
      approach: isPartitioned ? 'PARTITION_BY_PARTITION' : 'FULL_TABLE',
      steps: []
    };

    // Pre-compression steps
    strategy.steps.push({
      phase: 'PREPARATION',
      order: 1,
      action: 'Gather fresh table statistics',
      sql: `BEGIN DBMS_STATS.GATHER_TABLE_STATS('${tableAnalysis.table?.schemaName}', '${tableAnalysis.table?.tableName}'); END;`,
      critical: true
    });

    if (hasIndexes) {
      strategy.steps.push({
        phase: 'PREPARATION',
        order: 2,
        action: 'Consider rebuilding indexes after compression',
        note: `${tableAnalysis.indexes.length} index(es) detected`,
        critical: false
      });
    }

    // Compression step
    if (isPartitioned && partitionCount > 0) {
      strategy.steps.push({
        phase: 'COMPRESSION',
        order: 3,
        action: `Compress ${partitionCount} partition(s) incrementally`,
        approach: 'Online partition compression to minimize downtime',
        sql: `ALTER TABLE "${tableAnalysis.table?.schemaName}"."${tableAnalysis.table?.tableName}" MODIFY PARTITION <partition_name> COMPRESS FOR ${compressionType.name} ONLINE`,
        critical: true
      });
    } else {
      strategy.steps.push({
        phase: 'COMPRESSION',
        order: 3,
        action: 'Compress entire table',
        sql: `ALTER TABLE "${tableAnalysis.table?.schemaName}"."${tableAnalysis.table?.tableName}" MOVE COMPRESS FOR ${compressionType.name}`,
        critical: true,
        note: 'Table will be locked during operation'
      });
    }

    // Post-compression steps
    strategy.steps.push({
      phase: 'VALIDATION',
      order: 4,
      action: 'Re-gather statistics after compression',
      sql: `BEGIN DBMS_STATS.GATHER_TABLE_STATS('${tableAnalysis.table?.schemaName}', '${tableAnalysis.table?.tableName}'); END;`,
      critical: true
    });

    strategy.steps.push({
      phase: 'VALIDATION',
      order: 5,
      action: 'Verify compression and measure actual savings',
      sql: `SELECT compression, compress_for, blocks FROM dba_tables WHERE owner = '${tableAnalysis.table?.schemaName}' AND table_name = '${tableAnalysis.table?.tableName}'`,
      critical: true
    });

    return strategy;
  }

  /**
   * Assess risks and prerequisites
   * @private
   * @param {Object} tableAnalysis - Table analysis
   * @param {Object} compressionType - Selected compression type
   * @returns {Object} Risk assessment
   */
  _assessRisks(tableAnalysis, compressionType) {
    const risks = [];
    const prerequisites = [];
    let riskLevel = 'LOW';

    // Check Exadata requirement
    prerequisites.push({
      item: 'Exadata Storage',
      required: true,
      description: 'HCC compression requires Exadata or ZFS Storage Appliance',
      checkSQL: "SELECT DISTINCT cell_name FROM v$cell WHERE cell_name IS NOT NULL"
    });

    // Check license
    prerequisites.push({
      item: 'Advanced Compression Option',
      required: true,
      description: 'Oracle Advanced Compression license required for HCC'
    });

    // Table lock risk
    if (!tableAnalysis.table?.partitioned) {
      risks.push({
        risk: 'Table Lock During Compression',
        severity: 'HIGH',
        impact: 'Table will be locked and unavailable during ALTER TABLE MOVE operation',
        mitigation: 'Schedule during maintenance window or consider partitioning table'
      });
      riskLevel = 'HIGH';
    }

    // Index rebuild requirement
    if (tableAnalysis.indexes?.length > 0) {
      risks.push({
        risk: 'Index Rebuild Required',
        severity: 'MEDIUM',
        impact: `${tableAnalysis.indexes.length} index(es) will become unusable and require rebuild`,
        mitigation: 'Include index rebuild in maintenance window'
      });
      if (riskLevel === 'LOW') riskLevel = 'MEDIUM';
    }

    // Write-heavy workload warning
    if (compressionType.warning) {
      risks.push({
        risk: 'Workload Incompatibility',
        severity: 'HIGH',
        impact: compressionType.warning,
        mitigation: 'Consider alternative compression methods or table redesign'
      });
      riskLevel = 'HIGH';
    }

    // Large table duration
    const sizeMB = tableAnalysis.table?.sizeMB || 0;
    if (sizeMB > 50000) { // > 50GB
      risks.push({
        risk: 'Long Compression Duration',
        severity: 'MEDIUM',
        impact: 'Compression may take several hours for very large tables',
        mitigation: 'Use partition-by-partition approach or schedule during extended window'
      });
    }

    return {
      riskLevel,
      risks,
      prerequisites,
      recommendPilotTest: riskLevel === 'HIGH' || sizeMB > 10000
    };
  }

  /**
   * Calculate recommendation priority
   * @private
   * @param {Object} tableAnalysis - Table analysis
   * @param {Object} savingsAnalysis - Savings analysis
   * @returns {string} Priority level
   */
  _calculatePriority(tableAnalysis, savingsAnalysis) {
    const sizeMB = tableAnalysis.table?.sizeMB || 0;
    const savedPercentage = parseFloat(savingsAnalysis.percentageSaved);

    // High priority: Large tables with high savings
    if (sizeMB > 10000 && savedPercentage > 80) {
      return 'HIGH';
    }

    // High priority: Very large tables
    if (sizeMB > 50000) {
      return 'HIGH';
    }

    // Medium priority: Good savings
    if (savedPercentage > 70 && sizeMB > 1000) {
      return 'MEDIUM';
    }

    // Low priority: Small savings or small tables
    return 'LOW';
  }

  /**
   * Estimate compression duration
   * @private
   * @param {Object} tableAnalysis - Table analysis
   * @returns {Object} Duration estimate
   */
  _estimateCompressionDuration(tableAnalysis) {
    const sizeMB = tableAnalysis.table?.sizeMB || 0;

    // Rough estimate: 100MB/minute for compression
    const estimatedMinutes = Math.ceil(sizeMB / 100);

    let estimate = '';
    if (estimatedMinutes < 60) {
      estimate = `${estimatedMinutes} minutes`;
    } else if (estimatedMinutes < 1440) {
      estimate = `${Math.ceil(estimatedMinutes / 60)} hours`;
    } else {
      estimate = `${Math.ceil(estimatedMinutes / 1440)} days`;
    }

    return {
      estimatedMinutes,
      formattedEstimate: estimate,
      note: 'Actual duration varies based on hardware, workload, and data characteristics'
    };
  }

  /**
   * Generate quick recommendation for batch processing
   * @private
   * @param {Object} candidate - Table candidate
   * @returns {Object} Quick recommendation
   */
  async _generateQuickRecommendation(candidate) {
    const workloadProfile = {
      workloadType: 'READ_HEAVY',
      accessFrequency: 'MEDIUM',
      isArchivalCandidate: false
    };

    const tableAnalysis = {
      table: {
        schemaName: candidate.schemaName,
        tableName: candidate.tableName,
        sizeBytes: candidate.sizeBytes,
        sizeMB: candidate.sizeMB,
        compression: candidate.compression,
        partitioned: candidate.partitioned,
        readCount: candidate.readCount,
        writeCount: candidate.writeCount
      },
      indexes: [],
      partitions: []
    };

    const compressionType = this._selectCompressionType(tableAnalysis, workloadProfile);
    const savingsAnalysis = this._calculateExpectedSavings(tableAnalysis, compressionType);

    return {
      table: {
        schema: candidate.schemaName,
        name: candidate.tableName,
        currentSize: formatBytes(candidate.sizeBytes)
      },
      recommendedCompression: compressionType,
      expectedSavings: savingsAnalysis,
      priority: this._calculatePriority(tableAnalysis, savingsAnalysis),
      score: candidate.score
    };
  }
}

module.exports = RecommendationEngine;
