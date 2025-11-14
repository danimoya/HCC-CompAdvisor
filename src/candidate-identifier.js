/**
 * Candidate Identification Module
 * Identifies and scores tables for HCC compression
 *
 * @module candidate-identifier
 */

const config = require('./config');
const {
  Logger,
  DatabaseError,
  ValidationError,
  formatBytes,
  calculateCompressionRatio,
  isValidSchemaName,
  isValidTableName,
  sanitizeSQLIdentifier
} = require('./utils');

const logger = new Logger(config.get('logging'));

/**
 * Candidate Identifier class
 */
class CandidateIdentifier {
  constructor() {
    this.config = config;
  }

  /**
   * Identify compression candidates
   * @param {Object} [options={}] - Filtering options
   * @param {string[]} [options.schemas] - Specific schemas to analyze
   * @param {number} [options.minSizeMB] - Minimum table size in MB
   * @param {number} [options.minCompressionRatio] - Minimum expected compression ratio
   * @param {number} [options.limit] - Maximum number of candidates to return
   * @returns {Promise<Array>} Array of compression candidates
   */
  async identifyCandidates(options = {}) {
    const conn = await this.config.getConnection();

    try {
      await logger.info('Starting candidate identification', { options });

      // Build and execute query
      const candidates = await this._queryCandidates(conn, options);

      // Apply filtering
      const filtered = this._applyFilters(candidates, options);

      // Calculate scores
      const scored = this._scoreCandidates(filtered);

      // Sort by score descending
      const sorted = scored.sort((a, b) => b.score - a.score);

      // Apply limit
      const limited = options.limit ? sorted.slice(0, options.limit) : sorted;

      await logger.info(`Identified ${limited.length} compression candidates`, {
        totalAnalyzed: candidates.length,
        afterFiltering: filtered.length,
        returned: limited.length
      });

      return limited;
    } catch (error) {
      await logger.error('Failed to identify candidates', { error: error.message });
      throw new DatabaseError('Failed to identify compression candidates', error);
    } finally {
      await conn.close();
    }
  }

  /**
   * Query candidate tables from database
   * @private
   * @param {Object} conn - Database connection
   * @param {Object} options - Query options
   * @returns {Promise<Array>} Query results
   */
  async _queryCandidates(conn, options) {
    const minSizeMB = options.minSizeMB || this.config.get('compression.minTableSizeMB');
    const minSizeBytes = minSizeMB * 1024 * 1024;

    const excludedSchemas = this.config.get('compression.excludedSchemas');
    const excludedPatterns = this.config.get('compression.excludedTablePatterns');

    // Build schema filter
    let schemaFilter = '';
    if (options.schemas && options.schemas.length > 0) {
      const schemaList = options.schemas
        .map(s => `'${sanitizeSQLIdentifier(s)}'`)
        .join(',');
      schemaFilter = `AND t.owner IN (${schemaList})`;
    } else {
      const excludedList = excludedSchemas
        .map(s => `'${s}'`)
        .join(',');
      schemaFilter = `AND t.owner NOT IN (${excludedList})`;
    }

    // Build table name exclusion filter
    const patternFilters = excludedPatterns
      .map(p => `t.table_name NOT LIKE '${p}%'`)
      .join(' AND ');

    const query = `
      SELECT
        t.owner AS schema_name,
        t.table_name,
        t.num_rows,
        t.blocks,
        t.avg_row_len,
        t.compression,
        t.compress_for,
        s.bytes AS size_bytes,
        s.bytes / 1024 / 1024 AS size_mb,
        t.last_analyzed,
        t.partitioned,
        NVL(io.read_count, 0) AS read_count,
        NVL(io.write_count, 0) AS write_count,
        CASE
          WHEN t.compression = 'ENABLED' THEN 'YES'
          ELSE 'NO'
        END AS is_compressed,
        CASE
          WHEN t.num_rows > 0 THEN
            ROUND((s.bytes / t.num_rows), 2)
          ELSE 0
        END AS bytes_per_row
      FROM
        dba_tables t
        JOIN (
          SELECT
            owner,
            segment_name,
            SUM(bytes) AS bytes
          FROM dba_segments
          WHERE segment_type IN ('TABLE', 'TABLE PARTITION')
          GROUP BY owner, segment_name
        ) s ON t.owner = s.owner AND t.table_name = s.segment_name
        LEFT JOIN (
          SELECT
            owner,
            object_name,
            SUM(physical_reads) AS read_count,
            SUM(physical_writes) AS write_count
          FROM v$segment_statistics
          WHERE statistic_name IN ('physical reads', 'physical writes')
          GROUP BY owner, object_name
        ) io ON t.owner = io.owner AND t.table_name = io.object_name
      WHERE
        s.bytes >= :minSize
        ${schemaFilter}
        AND ${patternFilters}
        AND t.temporary = 'N'
        AND t.nested = 'NO'
        AND t.status = 'VALID'
      ORDER BY
        s.bytes DESC
    `;

    const result = await conn.execute(query, { minSize: minSizeBytes });

    return result.rows.map(row => ({
      schemaName: row[0],
      tableName: row[1],
      numRows: row[2] || 0,
      blocks: row[3] || 0,
      avgRowLen: row[4] || 0,
      compression: row[5] || 'DISABLED',
      compressFor: row[6],
      sizeBytes: row[7] || 0,
      sizeMB: row[8] || 0,
      lastAnalyzed: row[9],
      partitioned: row[10] === 'YES',
      readCount: row[11] || 0,
      writeCount: row[12] || 0,
      isCompressed: row[13] === 'YES',
      bytesPerRow: row[14] || 0
    }));
  }

  /**
   * Apply additional filters to candidates
   * @private
   * @param {Array} candidates - Initial candidates
   * @param {Object} options - Filter options
   * @returns {Array} Filtered candidates
   */
  _applyFilters(candidates, options) {
    let filtered = [...candidates];

    // Filter out already HCC compressed tables
    filtered = filtered.filter(c => {
      if (!c.compressFor) return true;
      return !c.compressFor.includes('QUERY') && !c.compressFor.includes('ARCHIVE');
    });

    // Filter by minimum compression ratio potential
    const minRatio = options.minCompressionRatio ||
                     this.config.get('compression.minCompressionRatio');

    filtered = filtered.filter(c => {
      const estimatedRatio = this._estimateCompressionRatio(c);
      return estimatedRatio >= minRatio;
    });

    // Filter by access patterns (prefer read-heavy tables)
    if (options.readHeavy) {
      filtered = filtered.filter(c => {
        const totalOps = c.readCount + c.writeCount;
        if (totalOps === 0) return true;
        const readRatio = c.readCount / totalOps;
        return readRatio >= 0.7; // 70% reads
      });
    }

    // Filter tables not analyzed recently
    if (options.requireRecentStats) {
      const thirtyDaysAgo = new Date();
      thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

      filtered = filtered.filter(c => {
        if (!c.lastAnalyzed) return false;
        return new Date(c.lastAnalyzed) >= thirtyDaysAgo;
      });
    }

    return filtered;
  }

  /**
   * Score candidates based on compression potential
   * @private
   * @param {Array} candidates - Candidates to score
   * @returns {Array} Candidates with scores
   */
  _scoreCandidates(candidates) {
    return candidates.map(candidate => {
      let score = 0;

      // Size factor (larger tables = higher priority)
      // 100MB = 10 points, 1GB = 100 points, 10GB = 1000 points
      const sizeScore = Math.log10(candidate.sizeMB) * 50;
      score += sizeScore;

      // Compression ratio potential
      const estimatedRatio = this._estimateCompressionRatio(candidate);
      const ratioScore = estimatedRatio * 20;
      score += ratioScore;

      // Read/write ratio (read-heavy tables benefit more from HCC)
      const totalOps = candidate.readCount + candidate.writeCount;
      if (totalOps > 0) {
        const readRatio = candidate.readCount / totalOps;
        const ioScore = readRatio * 30;
        score += ioScore;
      }

      // Penalty for already compressed tables
      if (candidate.isCompressed && candidate.compression !== 'DISABLED') {
        score *= 0.5; // 50% penalty
      }

      // Penalty for partitioned tables (more complex to compress)
      if (candidate.partitioned) {
        score *= 0.9; // 10% penalty
      }

      // Statistics freshness bonus
      if (candidate.lastAnalyzed) {
        const daysSinceAnalysis = Math.floor(
          (Date.now() - new Date(candidate.lastAnalyzed)) / (1000 * 60 * 60 * 24)
        );
        if (daysSinceAnalysis <= 7) {
          score *= 1.1; // 10% bonus for recent stats
        }
      }

      return {
        ...candidate,
        estimatedCompressionRatio: parseFloat(estimatedRatio.toFixed(2)),
        score: Math.round(score),
        scoreBreakdown: {
          size: Math.round(sizeScore),
          compressionPotential: Math.round(ratioScore),
          readHeavy: Math.round((totalOps > 0 ? (candidate.readCount / totalOps) * 30 : 0)),
          total: Math.round(score)
        }
      };
    });
  }

  /**
   * Estimate compression ratio for a table
   * @private
   * @param {Object} candidate - Candidate table
   * @returns {number} Estimated compression ratio
   */
  _estimateCompressionRatio(candidate) {
    // Heuristic based on table characteristics
    let estimatedRatio = 2.0; // Conservative baseline

    // Tables with larger average row length compress better
    if (candidate.avgRowLen > 200) {
      estimatedRatio += 1.0;
    } else if (candidate.avgRowLen > 100) {
      estimatedRatio += 0.5;
    }

    // Tables with many rows compress better (more patterns)
    if (candidate.numRows > 10000000) {
      estimatedRatio += 1.0;
    } else if (candidate.numRows > 1000000) {
      estimatedRatio += 0.5;
    }

    // If already compressed, estimate additional benefit
    if (candidate.isCompressed && candidate.compression === 'ENABLED') {
      // Basic compression already applied, HCC might add 20-30% more
      estimatedRatio = 1.3;
    }

    return estimatedRatio;
  }

  /**
   * Get detailed analysis for a specific table
   * @param {string} schemaName - Schema name
   * @param {string} tableName - Table name
   * @returns {Promise<Object>} Detailed table analysis
   */
  async analyzeTable(schemaName, tableName) {
    // Validate inputs
    if (!isValidSchemaName(schemaName)) {
      throw new ValidationError('Invalid schema name', 'schemaName');
    }
    if (!isValidTableName(tableName)) {
      throw new ValidationError('Invalid table name', 'tableName');
    }

    const conn = await this.config.getConnection();

    try {
      await logger.info('Analyzing table', { schemaName, tableName });

      // Get basic table info
      const tableInfo = await this._getTableInfo(conn, schemaName, tableName);

      // Get column information
      const columns = await this._getColumnInfo(conn, schemaName, tableName);

      // Get partition information if partitioned
      const partitions = tableInfo.partitioned
        ? await this._getPartitionInfo(conn, schemaName, tableName)
        : [];

      // Get index information
      const indexes = await this._getIndexInfo(conn, schemaName, tableName);

      // Calculate compression potential
      const compressionAnalysis = this._analyzeCompressionPotential(
        tableInfo,
        columns,
        partitions
      );

      return {
        table: tableInfo,
        columns,
        partitions,
        indexes,
        compressionAnalysis,
        recommendation: this._generateRecommendation(compressionAnalysis)
      };
    } catch (error) {
      await logger.error('Failed to analyze table', {
        schemaName,
        tableName,
        error: error.message
      });
      throw new DatabaseError(`Failed to analyze table ${schemaName}.${tableName}`, error);
    } finally {
      await conn.close();
    }
  }

  /**
   * Get table information
   * @private
   */
  async _getTableInfo(conn, schemaName, tableName) {
    const query = `
      SELECT
        t.num_rows,
        t.blocks,
        t.avg_row_len,
        t.compression,
        t.compress_for,
        s.bytes,
        t.partitioned,
        t.last_analyzed
      FROM dba_tables t
      JOIN dba_segments s ON t.owner = s.owner AND t.table_name = s.segment_name
      WHERE t.owner = :schema AND t.table_name = :table
    `;

    const result = await conn.execute(query, {
      schema: sanitizeSQLIdentifier(schemaName),
      table: sanitizeSQLIdentifier(tableName)
    });

    if (result.rows.length === 0) {
      throw new ValidationError(`Table ${schemaName}.${tableName} not found`);
    }

    const row = result.rows[0];
    return {
      numRows: row[0],
      blocks: row[1],
      avgRowLen: row[2],
      compression: row[3],
      compressFor: row[4],
      sizeBytes: row[5],
      sizeMB: row[5] / 1024 / 1024,
      partitioned: row[6] === 'YES',
      lastAnalyzed: row[7]
    };
  }

  /**
   * Get column information
   * @private
   */
  async _getColumnInfo(conn, schemaName, tableName) {
    const query = `
      SELECT
        column_name,
        data_type,
        data_length,
        nullable,
        num_distinct,
        density
      FROM dba_tab_columns
      WHERE owner = :schema AND table_name = :table
      ORDER BY column_id
    `;

    const result = await conn.execute(query, {
      schema: sanitizeSQLIdentifier(schemaName),
      table: sanitizeSQLIdentifier(tableName)
    });

    return result.rows.map(row => ({
      name: row[0],
      dataType: row[1],
      length: row[2],
      nullable: row[3] === 'Y',
      distinctValues: row[4],
      density: row[5]
    }));
  }

  /**
   * Get partition information
   * @private
   */
  async _getPartitionInfo(conn, schemaName, tableName) {
    const query = `
      SELECT
        partition_name,
        num_rows,
        compression,
        compress_for
      FROM dba_tab_partitions
      WHERE table_owner = :schema AND table_name = :table
      ORDER BY partition_position
    `;

    const result = await conn.execute(query, {
      schema: sanitizeSQLIdentifier(schemaName),
      table: sanitizeSQLIdentifier(tableName)
    });

    return result.rows.map(row => ({
      name: row[0],
      numRows: row[1],
      compression: row[2],
      compressFor: row[3]
    }));
  }

  /**
   * Get index information
   * @private
   */
  async _getIndexInfo(conn, schemaName, tableName) {
    const query = `
      SELECT
        index_name,
        uniqueness,
        compression,
        leaf_blocks
      FROM dba_indexes
      WHERE owner = :schema AND table_name = :table
    `;

    const result = await conn.execute(query, {
      schema: sanitizeSQLIdentifier(schemaName),
      table: sanitizeSQLIdentifier(tableName)
    });

    return result.rows.map(row => ({
      name: row[0],
      unique: row[1] === 'UNIQUE',
      compression: row[2],
      leafBlocks: row[3]
    }));
  }

  /**
   * Analyze compression potential
   * @private
   */
  _analyzeCompressionPotential(tableInfo, columns, partitions) {
    const estimatedRatio = this._estimateCompressionRatio(tableInfo);
    const estimatedSavingsBytes = tableInfo.sizeBytes - (tableInfo.sizeBytes / estimatedRatio);

    return {
      currentCompression: tableInfo.compression,
      currentCompressFor: tableInfo.compressFor,
      estimatedRatio,
      estimatedSavingsBytes,
      estimatedSavingsMB: estimatedSavingsBytes / 1024 / 1024,
      factors: {
        avgRowLength: tableInfo.avgRowLen,
        totalRows: tableInfo.numRows,
        currentSize: formatBytes(tableInfo.sizeBytes),
        partitionCount: partitions.length
      }
    };
  }

  /**
   * Generate recommendation
   * @private
   */
  _generateRecommendation(analysis) {
    if (analysis.estimatedRatio < 2.0) {
      return {
        recommended: false,
        reason: 'Low compression potential (ratio < 2.0)',
        action: 'Skip compression'
      };
    }

    return {
      recommended: true,
      reason: `High compression potential (estimated ratio: ${analysis.estimatedRatio.toFixed(2)}x)`,
      action: 'Proceed with compression',
      expectedSavings: formatBytes(analysis.estimatedSavingsBytes)
    };
  }
}

module.exports = CandidateIdentifier;
