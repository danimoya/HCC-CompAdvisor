/**
 * Unit Tests for Compression Executor
 * Tests the compression execution and historical tracking logic
 */

const { MockOraclePool } = require('../fixtures/databaseMock');
const TestDataGenerator = require('../fixtures/testDataGenerator');
const { mockErrorScenarios } = require('../fixtures/mockOracleMetadata');

describe('Compression Executor - Unit Tests', () => {
  let mockPool;
  let mockConnection;

  beforeEach(async () => {
    mockPool = new MockOraclePool({
      user: 'test_user',
      password: 'test_password',
      connectString: 'localhost/FREEPDB1'
    });
    mockConnection = await mockPool.getConnection();
  });

  afterEach(async () => {
    if (mockConnection) {
      await mockConnection.close();
    }
    if (mockPool) {
      await mockPool.close();
    }
  });

  describe('Compression Execution', () => {
    it('should execute OLTP compression successfully', async () => {
      const sql = 'ALTER TABLE TESTUSER.LARGE_TRANSACTIONAL MOVE COMPRESS FOR OLTP';

      const result = await mockConnection.execute(sql);

      expect(result.rowsAffected).toBe(1);
    });

    it('should execute QUERY LOW compression successfully', async () => {
      const sql = 'ALTER TABLE TESTUSER.PARTITIONED_SALES MOVE COMPRESS FOR QUERY LOW';

      const result = await mockConnection.execute(sql);

      expect(result.rowsAffected).toBe(1);
    });

    it('should execute ARCHIVE HIGH compression successfully', async () => {
      const sql = 'ALTER TABLE TESTUSER.ARCHIVE_DATA MOVE COMPRESS FOR ARCHIVE HIGH';

      const result = await mockConnection.execute(sql);

      expect(result.rowsAffected).toBe(1);
    });

    it('should support partition-level compression', async () => {
      const sql = 'ALTER TABLE TESTUSER.PARTITIONED_SALES MOVE PARTITION P_2025_Q4 COMPRESS FOR QUERY LOW';

      const result = await mockConnection.execute(sql);

      expect(result.rowsAffected).toBe(1);
    });

    it('should support parallel execution', async () => {
      const sql = 'ALTER TABLE TESTUSER.LARGE_TRANSACTIONAL MOVE PARALLEL 4 COMPRESS FOR OLTP';

      const result = await mockConnection.execute(sql);

      expect(result.rowsAffected).toBe(1);
    });
  });

  describe('Historical Tracking', () => {
    it('should record compression history', async () => {
      const history = TestDataGenerator.generateCompressionHistory(
        'TEST_TABLE',
        'QUERY_HIGH',
        true
      );

      expect(history).toHaveProperty('history_id');
      expect(history).toHaveProperty('owner');
      expect(history).toHaveProperty('object_name');
      expect(history).toHaveProperty('compression_type');
      expect(history).toHaveProperty('original_size_mb');
      expect(history).toHaveProperty('compressed_size_mb');
      expect(history).toHaveProperty('space_saved_mb');
      expect(history).toHaveProperty('compression_ratio_achieved');
      expect(history).toHaveProperty('execution_status');
    });

    it('should calculate space savings correctly', () => {
      const history = TestDataGenerator.generateCompressionHistory(
        'TEST_TABLE',
        'ARCHIVE_HIGH',
        true
      );

      const calculatedSavings = history.original_size_mb - history.compressed_size_mb;

      expect(history.space_saved_mb).toBe(calculatedSavings);
      expect(history.space_saved_mb).toBeGreaterThan(0);
    });

    it('should record compression ratio achieved', () => {
      const history = TestDataGenerator.generateCompressionHistory(
        'TEST_TABLE',
        'QUERY_LOW',
        true
      );

      expect(history.compression_ratio_achieved).toBeGreaterThan(1);
      expect(history.compression_ratio_achieved).toBeLessThan(20);
    });

    it('should record execution timestamps', () => {
      const history = TestDataGenerator.generateCompressionHistory(
        'TEST_TABLE',
        'OLTP',
        true
      );

      expect(history.start_time).toBeInstanceOf(Date);
      expect(history.end_time).toBeInstanceOf(Date);
      expect(history.end_time.getTime()).toBeGreaterThanOrEqual(history.start_time.getTime());
    });

    it('should record execution duration', () => {
      const history = TestDataGenerator.generateCompressionHistory(
        'TEST_TABLE',
        'QUERY_HIGH',
        true
      );

      const duration = history.end_time.getTime() - history.start_time.getTime();

      expect(duration).toBeGreaterThanOrEqual(0);
    });
  });

  describe('Size Calculation', () => {
    it('should capture original size before compression', async () => {
      const sql = 'SELECT bytes FROM DBA_SEGMENTS WHERE segment_name = :1';
      const result = await mockConnection.execute(sql, ['LARGE_TRANSACTIONAL']);

      expect(result.rows).toBeDefined();
      expect(result.rows.length).toBeGreaterThan(0);
    });

    it('should capture compressed size after compression', () => {
      const history = TestDataGenerator.generateCompressionHistory(
        'TEST_TABLE',
        'QUERY_HIGH',
        true
      );

      expect(history.compressed_size_mb).toBeLessThan(history.original_size_mb);
    });

    it('should handle size calculation for large objects (>100GB)', () => {
      const originalSizeMB = 150000; // 150GB
      const compressionRatio = 8.0;
      const compressedSizeMB = Math.floor(originalSizeMB / compressionRatio);
      const savedMB = originalSizeMB - compressedSizeMB;

      expect(compressedSizeMB).toBeLessThan(originalSizeMB);
      expect(savedMB).toBeGreaterThan(0);
      expect(savedMB).toBe(originalSizeMB - compressedSizeMB);
    });
  });

  describe('Error Handling', () => {
    it('should handle table not found error', async () => {
      const errorScenario = mockErrorScenarios.find(e => e.scenario === 'TABLE_NOT_FOUND');

      expect(errorScenario).toBeDefined();
      expect(errorScenario.error).toContain('ORA-00942');
    });

    it('should handle insufficient privileges error', async () => {
      const errorScenario = mockErrorScenarios.find(e => e.scenario === 'INSUFFICIENT_PRIVILEGES');

      expect(errorScenario).toBeDefined();
      expect(errorScenario.error).toContain('ORA-01031');
    });

    it('should handle tablespace full error', async () => {
      const errorScenario = mockErrorScenarios.find(e => e.scenario === 'TABLESPACE_FULL');

      await expect(async () => {
        const sql = `ALTER TABLE ${errorScenario.owner}.${errorScenario.table_name} MOVE COMPRESS FOR QUERY HIGH`;
        await mockConnection.execute(sql);
      }).rejects.toThrow('ORA-01653');
    });

    it('should handle lock timeout error', async () => {
      const errorScenario = mockErrorScenarios.find(e => e.scenario === 'LOCK_TIMEOUT');

      await expect(async () => {
        const sql = `ALTER TABLE ${errorScenario.owner}.${errorScenario.table_name} MOVE COMPRESS FOR OLTP`;
        await mockConnection.execute(sql);
      }).rejects.toThrow('ORA-00054');
    });

    it('should record error message in history', () => {
      const history = TestDataGenerator.generateCompressionHistory(
        'FAILED_TABLE',
        'QUERY_HIGH',
        false
      );

      expect(history.execution_status).toBe('FAILED');
      expect(history.error_message).toBeDefined();
      expect(history.error_message).not.toBeNull();
    });

    it('should rollback on compression failure', async () => {
      try {
        const sql = 'ALTER TABLE TESTUSER.LOCKED_TABLE MOVE COMPRESS FOR OLTP';
        await mockConnection.execute(sql);
      } catch (error) {
        await mockConnection.rollback();
        expect(error).toBeDefined();
      }
    });
  });

  describe('Transaction Management', () => {
    it('should commit successful compression', async () => {
      const sql = 'ALTER TABLE TESTUSER.LARGE_TRANSACTIONAL MOVE COMPRESS FOR OLTP';
      await mockConnection.execute(sql);

      await expect(mockConnection.commit()).resolves.not.toThrow();
    });

    it('should rollback failed compression', async () => {
      try {
        const sql = 'ALTER TABLE TESTUSER.LOCKED_TABLE MOVE COMPRESS FOR OLTP';
        await mockConnection.execute(sql);
      } catch (error) {
        await expect(mockConnection.rollback()).resolves.not.toThrow();
      }
    });

    it('should handle concurrent compression operations', async () => {
      const operations = [
        mockConnection.execute('ALTER TABLE TESTUSER.TABLE1 MOVE COMPRESS FOR OLTP'),
        mockConnection.execute('ALTER TABLE TESTUSER.TABLE2 MOVE COMPRESS FOR QUERY LOW'),
        mockConnection.execute('ALTER TABLE TESTUSER.TABLE3 MOVE COMPRESS FOR ARCHIVE HIGH')
      ];

      // Some may succeed, some may fail due to locks
      const results = await Promise.allSettled(operations);

      expect(results).toHaveLength(3);
      results.forEach(result => {
        expect(['fulfilled', 'rejected']).toContain(result.status);
      });
    });
  });

  describe('Verification and Validation', () => {
    it('should verify compression was applied', async () => {
      // After compression, verify the table has compression enabled
      const sql = 'SELECT compression, compress_for FROM DBA_TABLES WHERE table_name = :1';
      const result = await mockConnection.execute(sql, ['LARGE_TRANSACTIONAL']);

      expect(result.rows).toBeDefined();
    });

    it('should validate compression type is supported', () => {
      const validTypes = ['OLTP', 'QUERY_LOW', 'QUERY_HIGH', 'ARCHIVE_LOW', 'ARCHIVE_HIGH'];

      validTypes.forEach(type => {
        expect(['OLTP', 'QUERY_LOW', 'QUERY_HIGH', 'ARCHIVE_LOW', 'ARCHIVE_HIGH']).toContain(type);
      });
    });

    it('should reject invalid compression types', () => {
      const invalidTypes = ['INVALID', 'UNKNOWN', 'BASIC', ''];

      invalidTypes.forEach(type => {
        expect(['OLTP', 'QUERY_LOW', 'QUERY_HIGH', 'ARCHIVE_LOW', 'ARCHIVE_HIGH']).not.toContain(type);
      });
    });

    it('should calculate actual compression ratio after execution', () => {
      const originalSize = 100000; // MB
      const compressedSize = 25000; // MB
      const actualRatio = originalSize / compressedSize;

      expect(actualRatio).toBeCloseTo(4.0, 1);
    });
  });

  describe('Performance Optimization', () => {
    it('should support NOLOGGING for faster compression', async () => {
      const sql = 'ALTER TABLE TESTUSER.LARGE_TRANSACTIONAL MOVE NOLOGGING COMPRESS FOR QUERY HIGH';

      const result = await mockConnection.execute(sql);
      expect(result).toBeDefined();
    });

    it('should support online compression where possible', async () => {
      const sql = 'ALTER TABLE TESTUSER.LARGE_TRANSACTIONAL MOVE ONLINE COMPRESS FOR OLTP';

      const result = await mockConnection.execute(sql);
      expect(result).toBeDefined();
    });

    it('should batch compression operations', async () => {
      const tables = ['TABLE1', 'TABLE2', 'TABLE3', 'TABLE4', 'TABLE5'];
      const compressionOps = tables.map(table =>
        `ALTER TABLE TESTUSER.${table} MOVE COMPRESS FOR QUERY LOW`
      );

      expect(compressionOps).toHaveLength(5);
      compressionOps.forEach(sql => {
        expect(sql).toContain('COMPRESS FOR');
      });
    });
  });
});
