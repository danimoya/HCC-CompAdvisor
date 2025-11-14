/**
 * Mock Oracle Database Metadata for Testing
 * Simulates data from Oracle data dictionary views
 */

const mockTables = [
  {
    owner: 'TESTUSER',
    table_name: 'LARGE_TRANSACTIONAL',
    tablespace_name: 'USERS',
    num_rows: 5000000,
    blocks: 65536,
    avg_row_len: 250,
    compression: 'DISABLED',
    compress_for: null,
    segment_created: 'YES',
    iot_type: null,
    last_analyzed: new Date('2025-11-01'),
    size_bytes: 16777216000, // ~16GB
    size_gb: 15.625,
    partitioned: 'NO'
  },
  {
    owner: 'TESTUSER',
    table_name: 'ARCHIVE_DATA',
    tablespace_name: 'USERS',
    num_rows: 10000000,
    blocks: 131072,
    avg_row_len: 300,
    compression: 'DISABLED',
    compress_for: null,
    segment_created: 'YES',
    iot_type: null,
    last_analyzed: new Date('2025-01-01'),
    size_bytes: 41943040000, // ~39GB
    size_gb: 39.0625,
    partitioned: 'NO'
  },
  {
    owner: 'TESTUSER',
    table_name: 'SMALL_TABLE',
    tablespace_name: 'USERS',
    num_rows: 1000,
    blocks: 128,
    avg_row_len: 100,
    compression: 'DISABLED',
    compress_for: null,
    segment_created: 'YES',
    iot_type: null,
    last_analyzed: new Date('2025-11-10'),
    size_bytes: 1048576, // 1MB
    size_gb: 0.0009765625,
    partitioned: 'NO'
  },
  {
    owner: 'TESTUSER',
    table_name: 'PARTITIONED_SALES',
    tablespace_name: 'USERS',
    num_rows: 8000000,
    blocks: 98304,
    avg_row_len: 200,
    compression: 'ENABLED',
    compress_for: 'OLTP',
    segment_created: 'YES',
    iot_type: null,
    last_analyzed: new Date('2025-11-12'),
    size_bytes: 25769803776, // ~24GB
    size_gb: 24.0,
    partitioned: 'YES'
  }
];

const mockTabModifications = [
  {
    table_owner: 'TESTUSER',
    table_name: 'LARGE_TRANSACTIONAL',
    partition_name: null,
    inserts: 150000,
    updates: 75000,
    deletes: 25000,
    timestamp: new Date('2025-11-13'),
    truncated: 'NO',
    drop_segments: 0
  },
  {
    table_owner: 'TESTUSER',
    table_name: 'ARCHIVE_DATA',
    partition_name: null,
    inserts: 0,
    updates: 5,
    deletes: 0,
    timestamp: new Date('2025-11-13'),
    truncated: 'NO',
    drop_segments: 0
  },
  {
    table_owner: 'TESTUSER',
    table_name: 'SMALL_TABLE',
    partition_name: null,
    inserts: 10,
    updates: 5,
    deletes: 2,
    timestamp: new Date('2025-11-13'),
    truncated: 'NO',
    drop_segments: 0
  },
  {
    table_owner: 'TESTUSER',
    table_name: 'PARTITIONED_SALES',
    partition_name: 'P_2025_Q4',
    inserts: 50000,
    updates: 10000,
    deletes: 5000,
    timestamp: new Date('2025-11-13'),
    truncated: 'NO',
    drop_segments: 0
  }
];

const mockCompressionRatios = {
  'LARGE_TRANSACTIONAL': {
    OLTP: 2.8,
    QUERY_LOW: 3.5,
    QUERY_HIGH: 4.2,
    ARCHIVE_LOW: 5.1,
    ARCHIVE_HIGH: 6.8
  },
  'ARCHIVE_DATA': {
    OLTP: 2.1,
    QUERY_LOW: 4.8,
    QUERY_HIGH: 7.2,
    ARCHIVE_LOW: 9.5,
    ARCHIVE_HIGH: 12.3
  },
  'SMALL_TABLE': {
    OLTP: 1.2,
    QUERY_LOW: 1.4,
    QUERY_HIGH: 1.6,
    ARCHIVE_LOW: 1.8,
    ARCHIVE_HIGH: 2.0
  },
  'PARTITIONED_SALES': {
    OLTP: 3.1,
    QUERY_LOW: 4.0,
    QUERY_HIGH: 5.5,
    ARCHIVE_LOW: 6.8,
    ARCHIVE_HIGH: 8.9
  }
};

const mockSegmentStatistics = [
  {
    owner: 'TESTUSER',
    object_name: 'LARGE_TRANSACTIONAL',
    object_type: 'TABLE',
    statistic_name: 'physical reads',
    value: 1500000
  },
  {
    owner: 'TESTUSER',
    object_name: 'LARGE_TRANSACTIONAL',
    object_type: 'TABLE',
    statistic_name: 'db block changes',
    value: 250000
  },
  {
    owner: 'TESTUSER',
    object_name: 'ARCHIVE_DATA',
    object_type: 'TABLE',
    statistic_name: 'physical reads',
    value: 5000
  },
  {
    owner: 'TESTUSER',
    object_name: 'ARCHIVE_DATA',
    object_type: 'TABLE',
    statistic_name: 'db block changes',
    value: 10
  }
];

const mockIndexes = [
  {
    owner: 'TESTUSER',
    index_name: 'IDX_TRANS_DATE',
    table_owner: 'TESTUSER',
    table_name: 'LARGE_TRANSACTIONAL',
    index_type: 'NORMAL',
    uniqueness: 'NONUNIQUE',
    compression: 'DISABLED',
    prefix_length: 0,
    blevel: 3,
    leaf_blocks: 12800,
    distinct_keys: 5000000,
    clustering_factor: 4500000,
    num_rows: 5000000,
    sample_size: 5000000,
    last_analyzed: new Date('2025-11-01')
  }
];

const mockLobs = [
  {
    owner: 'TESTUSER',
    table_name: 'DOCUMENT_STORE',
    column_name: 'DOCUMENT_CONTENT',
    segment_name: 'SYS_LOB0000012345C00001$$',
    lob_name: 'DOCUMENT_CONTENT_LOB',
    chunk: 8192,
    in_row: 'NO',
    format: 'ENDIAN NEUTRAL',
    compression: 'NO',
    deduplication: 'NO',
    securefile: 'YES'
  }
];

const mockExpectedRecommendations = {
  'LARGE_TRANSACTIONAL': {
    recommendation: 'OLTP',
    reason: 'High DML activity (250000 operations)',
    compression_ratio: 2.8,
    space_savings_pct: 64.3
  },
  'ARCHIVE_DATA': {
    recommendation: 'ARCHIVE_HIGH',
    reason: 'Large size (39GB), minimal DML activity',
    compression_ratio: 12.3,
    space_savings_pct: 91.9
  },
  'SMALL_TABLE': {
    recommendation: 'NONE',
    reason: 'Table too small (< 10GB threshold)',
    compression_ratio: 1.0,
    space_savings_pct: 0
  },
  'PARTITIONED_SALES': {
    recommendation: 'QUERY_LOW',
    reason: 'Moderate DML, read-heavy workload',
    compression_ratio: 4.0,
    space_savings_pct: 75.0
  }
};

const mockErrorScenarios = [
  {
    scenario: 'TABLE_NOT_FOUND',
    owner: 'TESTUSER',
    table_name: 'NONEXISTENT_TABLE',
    error: 'ORA-00942: table or view does not exist'
  },
  {
    scenario: 'INSUFFICIENT_PRIVILEGES',
    owner: 'RESTRICTED_SCHEMA',
    table_name: 'SECRET_TABLE',
    error: 'ORA-01031: insufficient privileges'
  },
  {
    scenario: 'TABLESPACE_FULL',
    owner: 'TESTUSER',
    table_name: 'LARGE_TRANSACTIONAL',
    error: 'ORA-01653: unable to extend table'
  },
  {
    scenario: 'LOCK_TIMEOUT',
    owner: 'TESTUSER',
    table_name: 'LOCKED_TABLE',
    error: 'ORA-00054: resource busy and acquire with NOWAIT specified'
  }
];

module.exports = {
  mockTables,
  mockTabModifications,
  mockCompressionRatios,
  mockSegmentStatistics,
  mockIndexes,
  mockLobs,
  mockExpectedRecommendations,
  mockErrorScenarios
};
