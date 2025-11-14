/**
 * Configuration Management Module
 * Handles database connections, logging, and application settings
 *
 * @module config
 */

const oracledb = require('oracledb');
const fs = require('fs').promises;
const path = require('path');

/**
 * Default configuration values
 */
const DEFAULT_CONFIG = {
  database: {
    user: process.env.DB_USER || '',
    password: process.env.DB_PASSWORD || '',
    connectString: process.env.DB_CONNECT_STRING || '',
    poolMin: parseInt(process.env.DB_POOL_MIN) || 2,
    poolMax: parseInt(process.env.DB_POOL_MAX) || 10,
    poolIncrement: parseInt(process.env.DB_POOL_INCREMENT) || 1,
    poolTimeout: parseInt(process.env.DB_POOL_TIMEOUT) || 60,
    enableStatistics: true
  },
  compression: {
    minTableSizeMB: parseInt(process.env.MIN_TABLE_SIZE_MB) || 100,
    minCompressionRatio: parseFloat(process.env.MIN_COMPRESSION_RATIO) || 2.0,
    maxConcurrentOps: parseInt(process.env.MAX_CONCURRENT_OPS) || 3,
    defaultCompressionType: process.env.DEFAULT_COMPRESSION_TYPE || 'QUERY LOW',
    excludedSchemas: (process.env.EXCLUDED_SCHEMAS || 'SYS,SYSTEM,OUTLN,XDB').split(','),
    excludedTablePatterns: (process.env.EXCLUDED_TABLE_PATTERNS || 'TMP_,TEMP_').split(',')
  },
  logging: {
    level: process.env.LOG_LEVEL || 'info',
    file: process.env.LOG_FILE || 'logs/compression-advisor.log',
    maxFileSize: parseInt(process.env.LOG_MAX_SIZE) || 10485760, // 10MB
    maxFiles: parseInt(process.env.LOG_MAX_FILES) || 5,
    enableConsole: process.env.LOG_CONSOLE !== 'false'
  },
  history: {
    retentionDays: parseInt(process.env.HISTORY_RETENTION_DAYS) || 90,
    tableName: process.env.HISTORY_TABLE || 'COMPRESSION_HISTORY',
    schemaName: process.env.HISTORY_SCHEMA || 'ADMIN'
  }
};

/**
 * Configuration class for managing application settings
 */
class Config {
  constructor() {
    this.config = { ...DEFAULT_CONFIG };
    this.pool = null;
    this.loaded = false;
  }

  /**
   * Load configuration from file
   * @param {string} configPath - Path to configuration file
   * @returns {Promise<Object>} Loaded configuration
   */
  async loadFromFile(configPath) {
    try {
      const configFile = path.resolve(configPath);
      const content = await fs.readFile(configFile, 'utf8');
      const fileConfig = JSON.parse(content);

      // Deep merge with defaults
      this.config = this._deepMerge(DEFAULT_CONFIG, fileConfig);
      this.loaded = true;

      return this.config;
    } catch (error) {
      if (error.code === 'ENOENT') {
        console.warn(`Config file not found: ${configPath}, using defaults`);
      } else {
        throw new Error(`Failed to load config: ${error.message}`);
      }
      return this.config;
    }
  }

  /**
   * Initialize database connection pool
   * @returns {Promise<oracledb.Pool>} Database connection pool
   */
  async initializePool() {
    if (this.pool) {
      return this.pool;
    }

    try {
      const dbConfig = this.config.database;

      // Validate required credentials
      if (!dbConfig.user || !dbConfig.password || !dbConfig.connectString) {
        throw new Error('Database credentials not configured. Set DB_USER, DB_PASSWORD, and DB_CONNECT_STRING environment variables.');
      }

      this.pool = await oracledb.createPool({
        user: dbConfig.user,
        password: dbConfig.password,
        connectString: dbConfig.connectString,
        poolMin: dbConfig.poolMin,
        poolMax: dbConfig.poolMax,
        poolIncrement: dbConfig.poolIncrement,
        poolTimeout: dbConfig.poolTimeout,
        enableStatistics: dbConfig.enableStatistics
      });

      console.log('Database connection pool initialized');
      return this.pool;
    } catch (error) {
      throw new Error(`Failed to initialize database pool: ${error.message}`);
    }
  }

  /**
   * Get a connection from the pool
   * @returns {Promise<oracledb.Connection>} Database connection
   */
  async getConnection() {
    if (!this.pool) {
      await this.initializePool();
    }
    return await this.pool.getConnection();
  }

  /**
   * Close the connection pool
   * @returns {Promise<void>}
   */
  async closePool() {
    if (this.pool) {
      await this.pool.close(10); // 10 second drain time
      this.pool = null;
      console.log('Database connection pool closed');
    }
  }

  /**
   * Get pool statistics
   * @returns {Object|null} Pool statistics or null if pool not initialized
   */
  getPoolStats() {
    if (!this.pool) {
      return null;
    }

    return {
      connectionsInUse: this.pool.connectionsInUse,
      connectionsOpen: this.pool.connectionsOpen,
      poolMin: this.pool.poolMin,
      poolMax: this.pool.poolMax,
      poolIncrement: this.pool.poolIncrement
    };
  }

  /**
   * Get configuration value
   * @param {string} path - Dot-notation path to config value (e.g., 'database.poolMax')
   * @returns {*} Configuration value
   */
  get(path) {
    return path.split('.').reduce((obj, key) => obj?.[key], this.config);
  }

  /**
   * Set configuration value
   * @param {string} path - Dot-notation path to config value
   * @param {*} value - Value to set
   */
  set(path, value) {
    const keys = path.split('.');
    const lastKey = keys.pop();
    const target = keys.reduce((obj, key) => {
      if (!(key in obj)) obj[key] = {};
      return obj[key];
    }, this.config);
    target[lastKey] = value;
  }

  /**
   * Get all configuration
   * @returns {Object} Complete configuration object
   */
  getAll() {
    return { ...this.config };
  }

  /**
   * Validate configuration
   * @returns {Object} Validation result with isValid flag and errors array
   */
  validate() {
    const errors = [];

    // Database validation
    if (!this.config.database.user) {
      errors.push('Database user not configured');
    }
    if (!this.config.database.connectString) {
      errors.push('Database connect string not configured');
    }
    if (this.config.database.poolMax < this.config.database.poolMin) {
      errors.push('Database poolMax must be >= poolMin');
    }

    // Compression validation
    if (this.config.compression.minTableSizeMB < 0) {
      errors.push('Minimum table size must be >= 0');
    }
    if (this.config.compression.minCompressionRatio < 1.0) {
      errors.push('Minimum compression ratio must be >= 1.0');
    }
    if (this.config.compression.maxConcurrentOps < 1) {
      errors.push('Maximum concurrent operations must be >= 1');
    }

    // History validation
    if (this.config.history.retentionDays < 1) {
      errors.push('History retention days must be >= 1');
    }

    return {
      isValid: errors.length === 0,
      errors
    };
  }

  /**
   * Deep merge two objects
   * @private
   * @param {Object} target - Target object
   * @param {Object} source - Source object
   * @returns {Object} Merged object
   */
  _deepMerge(target, source) {
    const output = { ...target };

    if (this._isObject(target) && this._isObject(source)) {
      Object.keys(source).forEach(key => {
        if (this._isObject(source[key])) {
          if (!(key in target)) {
            output[key] = source[key];
          } else {
            output[key] = this._deepMerge(target[key], source[key]);
          }
        } else {
          output[key] = source[key];
        }
      });
    }

    return output;
  }

  /**
   * Check if value is an object
   * @private
   * @param {*} item - Value to check
   * @returns {boolean} True if object
   */
  _isObject(item) {
    return item && typeof item === 'object' && !Array.isArray(item);
  }
}

// Singleton instance
const config = new Config();

module.exports = config;
