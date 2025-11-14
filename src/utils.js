/**
 * Utility Functions Module
 * Provides logging, error handling, and common utility functions
 *
 * @module utils
 */

const fs = require('fs').promises;
const path = require('path');

/**
 * Log levels
 */
const LOG_LEVELS = {
  error: 0,
  warn: 1,
  info: 2,
  debug: 3
};

/**
 * Logger class for structured logging
 */
class Logger {
  constructor(config = {}) {
    this.level = LOG_LEVELS[config.level] || LOG_LEVELS.info;
    this.logFile = config.file || 'logs/compression-advisor.log';
    this.enableConsole = config.enableConsole !== false;
    this.maxFileSize = config.maxFileSize || 10485760; // 10MB
    this.maxFiles = config.maxFiles || 5;
  }

  /**
   * Log error message
   * @param {string} message - Log message
   * @param {Object} [meta] - Additional metadata
   */
  async error(message, meta = {}) {
    await this._log('error', message, meta);
  }

  /**
   * Log warning message
   * @param {string} message - Log message
   * @param {Object} [meta] - Additional metadata
   */
  async warn(message, meta = {}) {
    await this._log('warn', message, meta);
  }

  /**
   * Log info message
   * @param {string} message - Log message
   * @param {Object} [meta] - Additional metadata
   */
  async info(message, meta = {}) {
    await this._log('info', message, meta);
  }

  /**
   * Log debug message
   * @param {string} message - Log message
   * @param {Object} [meta] - Additional metadata
   */
  async debug(message, meta = {}) {
    await this._log('debug', message, meta);
  }

  /**
   * Internal logging method
   * @private
   * @param {string} level - Log level
   * @param {string} message - Log message
   * @param {Object} meta - Metadata
   */
  async _log(level, message, meta) {
    if (LOG_LEVELS[level] > this.level) {
      return;
    }

    const timestamp = new Date().toISOString();
    const logEntry = {
      timestamp,
      level: level.toUpperCase(),
      message,
      ...meta
    };

    const logLine = JSON.stringify(logEntry) + '\n';

    // Console output
    if (this.enableConsole) {
      const consoleMsg = `[${timestamp}] ${level.toUpperCase()}: ${message}`;
      console.log(consoleMsg);
      if (Object.keys(meta).length > 0) {
        console.log(JSON.stringify(meta, null, 2));
      }
    }

    // File output
    try {
      await this._writeToFile(logLine);
    } catch (error) {
      console.error('Failed to write to log file:', error.message);
    }
  }

  /**
   * Write log entry to file with rotation
   * @private
   * @param {string} logLine - Log line to write
   */
  async _writeToFile(logLine) {
    try {
      const logDir = path.dirname(this.logFile);
      await fs.mkdir(logDir, { recursive: true });

      // Check file size and rotate if needed
      try {
        const stats = await fs.stat(this.logFile);
        if (stats.size >= this.maxFileSize) {
          await this._rotateLogFile();
        }
      } catch (error) {
        // File doesn't exist, will be created
      }

      await fs.appendFile(this.logFile, logLine, 'utf8');
    } catch (error) {
      throw new Error(`Failed to write log: ${error.message}`);
    }
  }

  /**
   * Rotate log files
   * @private
   */
  async _rotateLogFile() {
    const ext = path.extname(this.logFile);
    const base = this.logFile.slice(0, -ext.length);

    // Delete oldest file
    const oldestFile = `${base}.${this.maxFiles}${ext}`;
    try {
      await fs.unlink(oldestFile);
    } catch (error) {
      // File doesn't exist, ignore
    }

    // Rotate existing files
    for (let i = this.maxFiles - 1; i >= 1; i--) {
      const oldFile = i === 1 ? this.logFile : `${base}.${i}${ext}`;
      const newFile = `${base}.${i + 1}${ext}`;
      try {
        await fs.rename(oldFile, newFile);
      } catch (error) {
        // File doesn't exist, ignore
      }
    }
  }
}

/**
 * Custom error classes
 */
class CompressionError extends Error {
  constructor(message, code, details = {}) {
    super(message);
    this.name = 'CompressionError';
    this.code = code;
    this.details = details;
  }
}

class DatabaseError extends Error {
  constructor(message, originalError = null) {
    super(message);
    this.name = 'DatabaseError';
    this.originalError = originalError;
  }
}

class ValidationError extends Error {
  constructor(message, field = null) {
    super(message);
    this.name = 'ValidationError';
    this.field = field;
  }
}

/**
 * Format bytes to human-readable string
 * @param {number} bytes - Bytes to format
 * @param {number} [decimals=2] - Number of decimal places
 * @returns {string} Formatted string
 */
function formatBytes(bytes, decimals = 2) {
  if (bytes === 0) return '0 Bytes';

  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB'];

  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

/**
 * Format number with thousands separator
 * @param {number} num - Number to format
 * @returns {string} Formatted string
 */
function formatNumber(num) {
  return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/**
 * Calculate compression ratio
 * @param {number} originalSize - Original size in bytes
 * @param {number} compressedSize - Compressed size in bytes
 * @returns {number} Compression ratio
 */
function calculateCompressionRatio(originalSize, compressedSize) {
  if (compressedSize === 0) return 0;
  return originalSize / compressedSize;
}

/**
 * Calculate space savings
 * @param {number} originalSize - Original size in bytes
 * @param {number} compressedSize - Compressed size in bytes
 * @returns {Object} Savings information
 */
function calculateSavings(originalSize, compressedSize) {
  const saved = originalSize - compressedSize;
  const percentage = (saved / originalSize) * 100;
  const ratio = calculateCompressionRatio(originalSize, compressedSize);

  return {
    savedBytes: saved,
    savedFormatted: formatBytes(saved),
    percentage: percentage.toFixed(2),
    ratio: ratio.toFixed(2)
  };
}

/**
 * Retry async function with exponential backoff
 * @param {Function} fn - Async function to retry
 * @param {number} [maxRetries=3] - Maximum number of retries
 * @param {number} [delayMs=1000] - Initial delay in milliseconds
 * @returns {Promise<*>} Function result
 */
async function retry(fn, maxRetries = 3, delayMs = 1000) {
  let lastError;

  for (let i = 0; i <= maxRetries; i++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;

      if (i < maxRetries) {
        const delay = delayMs * Math.pow(2, i);
        await sleep(delay);
      }
    }
  }

  throw lastError;
}

/**
 * Sleep for specified milliseconds
 * @param {number} ms - Milliseconds to sleep
 * @returns {Promise<void>}
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Validate table name format
 * @param {string} tableName - Table name to validate
 * @returns {boolean} True if valid
 */
function isValidTableName(tableName) {
  // Oracle table name rules: 1-30 chars, alphanumeric + _ $ #
  const pattern = /^[A-Za-z][A-Za-z0-9_$#]{0,29}$/;
  return pattern.test(tableName);
}

/**
 * Validate schema name format
 * @param {string} schemaName - Schema name to validate
 * @returns {boolean} True if valid
 */
function isValidSchemaName(schemaName) {
  return isValidTableName(schemaName);
}

/**
 * Parse Oracle error code from error message
 * @param {Error} error - Oracle error
 * @returns {string|null} Error code or null
 */
function parseOracleErrorCode(error) {
  if (!error || !error.message) return null;

  const match = error.message.match(/ORA-(\d{5})/);
  return match ? `ORA-${match[1]}` : null;
}

/**
 * Chunk array into smaller arrays
 * @param {Array} array - Array to chunk
 * @param {number} size - Chunk size
 * @returns {Array<Array>} Array of chunks
 */
function chunkArray(array, size) {
  const chunks = [];
  for (let i = 0; i < array.length; i += size) {
    chunks.push(array.slice(i, i + size));
  }
  return chunks;
}

/**
 * Sanitize SQL identifier (table/schema name)
 * @param {string} identifier - Identifier to sanitize
 * @returns {string} Sanitized identifier
 */
function sanitizeSQLIdentifier(identifier) {
  // Remove quotes and whitespace, uppercase
  return identifier.replace(/["'\s]/g, '').toUpperCase();
}

/**
 * Build fully qualified table name
 * @param {string} schemaName - Schema name
 * @param {string} tableName - Table name
 * @returns {string} Fully qualified table name
 */
function buildQualifiedTableName(schemaName, tableName) {
  return `"${sanitizeSQLIdentifier(schemaName)}"."${sanitizeSQLIdentifier(tableName)}"`;
}

/**
 * Measure execution time of async function
 * @param {Function} fn - Async function to measure
 * @returns {Promise<Object>} Result with execution time
 */
async function measureTime(fn) {
  const startTime = Date.now();
  const result = await fn();
  const executionTime = Date.now() - startTime;

  return {
    result,
    executionTime,
    executionTimeFormatted: formatDuration(executionTime)
  };
}

/**
 * Format duration in milliseconds to human-readable string
 * @param {number} ms - Duration in milliseconds
 * @returns {string} Formatted duration
 */
function formatDuration(ms) {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(2)}s`;
  if (ms < 3600000) return `${(ms / 60000).toFixed(2)}m`;
  return `${(ms / 3600000).toFixed(2)}h`;
}

/**
 * Deep clone object
 * @param {Object} obj - Object to clone
 * @returns {Object} Cloned object
 */
function deepClone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

/**
 * Merge objects deeply
 * @param {...Object} objects - Objects to merge
 * @returns {Object} Merged object
 */
function deepMerge(...objects) {
  return objects.reduce((acc, obj) => {
    Object.keys(obj).forEach(key => {
      const accVal = acc[key];
      const objVal = obj[key];

      if (Array.isArray(accVal) && Array.isArray(objVal)) {
        acc[key] = accVal.concat(objVal);
      } else if (isObject(accVal) && isObject(objVal)) {
        acc[key] = deepMerge(accVal, objVal);
      } else {
        acc[key] = objVal;
      }
    });
    return acc;
  }, {});
}

/**
 * Check if value is object
 * @param {*} obj - Value to check
 * @returns {boolean} True if object
 */
function isObject(obj) {
  return obj !== null && typeof obj === 'object' && !Array.isArray(obj);
}

module.exports = {
  Logger,
  CompressionError,
  DatabaseError,
  ValidationError,
  formatBytes,
  formatNumber,
  calculateCompressionRatio,
  calculateSavings,
  retry,
  sleep,
  isValidTableName,
  isValidSchemaName,
  parseOracleErrorCode,
  chunkArray,
  sanitizeSQLIdentifier,
  buildQualifiedTableName,
  measureTime,
  formatDuration,
  deepClone,
  deepMerge,
  isObject
};
