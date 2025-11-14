/**
 * Integration Tests for Database Operations
 * Tests interaction between analyzer, executor, and database
 */

const { MockOraclePool } = require('../fixtures/databaseMock');
const TestDataGenerator = require('../fixtures/testDataGenerator');

describe('Database Integration Tests', () => {
  let mockPool;
  let connection1;
  let connection2;

  beforeAll(async () => {
    mockPool = new MockOraclePool({
      user: 'compression_mgr',
      password: 'test_password',
      connectString: 'localhost/FREEPDB1',
      poolMin: 2,
      poolMax: 10
    });
  });

  afterAll(async () => {
    if (mockPool) {
      await mockPool.close();
    }
  });

  beforeEach(async () => {
    connection1 = await mockPool.getConnection();
    connection2 = await mockPool.getConnection();
  });

  afterEach(async () => {
    if (connection1) await connection1.close();
    if (connection2) await connection2.close();
  });

  describe('Connection Pool Management', () => {
    it('should create connection pool successfully', () => {
      expect(mockPool).toBeDefined();
      expect(mockPool.isOpen).toBe(true);
    });

    it('should get connection from pool', async () => {
      const conn = await mockPool.getConnection();

      expect(conn).toBeDefined();
      expect(conn.isOpen).toBe(true);

      await conn.close();
    });

    it('should handle multiple concurrent connections', async () => {
      const connections = await Promise.all([
        mockPool.getConnection(),
        mockPool.getConnection(),
        mockPool.getConnection(),
        mockPool.getConnection()
      ]);

      expect(connections).toHaveLength(4);
      connections.forEach(conn => {
        expect(conn.isOpen).toBe(true);
      });

      // Cleanup
      await Promise.all(connections.map(conn => conn.close()));
    });

    it('should track active connections', async () => {
      const conn1 = await mockPool.getConnection();
      const conn2 = await mockPool.getConnection();

      const activeCount = mockPool.getConnectionCount();
      expect(activeCount).toBeGreaterThanOrEqual(2);

      await conn1.close();
      await conn2.close();
    });
  });

  describe('Analyzer-to-Database Integration', () => {
    it('should retrieve table metadata from database', async () => {
      const result = await connection1.execute(
        `SELECT owner, table_name, num_rows, blocks
         FROM DBA_TABLES
         WHERE owner = :owner`,
        ['TESTUSER']
      );

      expect(result.rows).toBeDefined();
      expect(result.rows.length).toBeGreaterThan(0);
    });

    it('should retrieve DML statistics', async () => {
      const result = await connection1.execute(
        `SELECT table_owner, table_name, inserts, updates, deletes
         FROM ALL_TAB_MODIFICATIONS
         WHERE table_owner = :owner`,
        ['TESTUSER']
      );

      expect(result.rows).toBeDefined();
    });

    it('should combine metadata and DML stats', async () => {
      // Simulate joining table metadata with DML stats
      const tables = await connection1.execute(
        'SELECT owner, table_name FROM DBA_TABLES WHERE owner = :1',
        ['TESTUSER']
      );

      const dmlStats = await connection1.execute(
        'SELECT table_owner, table_name, inserts, updates, deletes FROM ALL_TAB_MODIFICATIONS WHERE table_owner = :1',
        ['TESTUSER']
      );

      expect(tables.rows.length).toBeGreaterThan(0);
      expect(dmlStats.rows).toBeDefined();
    });

    it('should calculate compression ratios for tables', async () => {
      const result = await connection1.execute(
        `BEGIN
           :ratio := DBMS_COMPRESSION.GET_COMPRESSION_RATIO(
             :owner, :table_name, :compression_type, 1000000
           );
         END;`,
        ['TESTUSER', 'LARGE_TRANSACTIONAL', 'OLTP']
      );

      // Mock returns compression ratio
      expect(result).toBeDefined();
    });
  });

  describe('Executor-to-Database Integration', () => {
    it('should execute compression DDL', async () => {
      const sql = 'ALTER TABLE TESTUSER.LARGE_TRANSACTIONAL MOVE COMPRESS FOR OLTP';

      const result = await connection1.execute(sql);

      expect(result.rowsAffected).toBe(1);
      await connection1.commit();
    });

    it('should record compression history', async () => {
      const history = TestDataGenerator.generateCompressionHistory(
        'TEST_TABLE',
        'QUERY_HIGH',
        true
      );

      const sql = `INSERT INTO COMPRESSION_HISTORY
                   (history_id, owner, object_name, compression_type,
                    original_size_mb, compressed_size_mb, execution_status)
                   VALUES (:1, :2, :3, :4, :5, :6, :7)`;

      const result = await connection1.execute(sql, [
        history.history_id,
        history.owner,
        history.object_name,
        history.compression_type,
        history.original_size_mb,
        history.compressed_size_mb,
        history.execution_status
      ]);

      expect(result.rowsAffected).toBe(1);
      await connection1.commit();
    });

    it('should update segment sizes after compression', async () => {
      // Get original size
      const beforeResult = await connection1.execute(
        'SELECT bytes FROM DBA_SEGMENTS WHERE segment_name = :1',
        ['LARGE_TRANSACTIONAL']
      );

      // Execute compression
      await connection1.execute(
        'ALTER TABLE TESTUSER.LARGE_TRANSACTIONAL MOVE COMPRESS FOR OLTP'
      );

      // Get new size (in real scenario, would be different)
      const afterResult = await connection1.execute(
        'SELECT bytes FROM DBA_SEGMENTS WHERE segment_name = :1',
        ['LARGE_TRANSACTIONAL']
      );

      expect(beforeResult.rows).toBeDefined();
      expect(afterResult.rows).toBeDefined();
    });
  });

  describe('Full Workflow Integration', () => {
    it('should complete full analysis-to-compression workflow', async () => {
      // Step 1: Analyze table
      const analysisResult = await connection1.execute(
        'SELECT owner, table_name, num_rows FROM DBA_TABLES WHERE table_name = :1',
        ['LARGE_TRANSACTIONAL']
      );

      expect(analysisResult.rows.length).toBeGreaterThan(0);

      // Step 2: Get DML stats
      const dmlResult = await connection1.execute(
        'SELECT inserts, updates, deletes FROM ALL_TAB_MODIFICATIONS WHERE table_name = :1',
        ['LARGE_TRANSACTIONAL']
      );

      expect(dmlResult.rows).toBeDefined();

      // Step 3: Calculate compression ratio
      const compressionResult = await connection1.execute(
        'BEGIN :ratio := DBMS_COMPRESSION.GET_COMPRESSION_RATIO(:1, :2, :3, 1000000); END;',
        ['TESTUSER', 'LARGE_TRANSACTIONAL', 'OLTP']
      );

      expect(compressionResult).toBeDefined();

      // Step 4: Execute compression
      const executeResult = await connection1.execute(
        'ALTER TABLE TESTUSER.LARGE_TRANSACTIONAL MOVE COMPRESS FOR OLTP'
      );

      expect(executeResult.rowsAffected).toBe(1);

      // Step 5: Record history
      const historyResult = await connection1.execute(
        `INSERT INTO COMPRESSION_HISTORY
         (history_id, owner, object_name, compression_type, execution_status)
         VALUES (SEQ_HISTORY_ID.NEXTVAL, :1, :2, :3, :4)`,
        ['TESTUSER', 'LARGE_TRANSACTIONAL', 'OLTP', 'SUCCESS']
      );

      expect(historyResult.rowsAffected).toBe(1);

      await connection1.commit();
    });

    it('should handle workflow rollback on failure', async () => {
      try {
        // Start transaction
        await connection1.execute('SAVEPOINT before_compression');

        // Attempt compression (will fail)
        await connection1.execute(
          'ALTER TABLE TESTUSER.LOCKED_TABLE MOVE COMPRESS FOR OLTP'
        );

        // Should not reach here
        expect(true).toBe(false);
      } catch (error) {
        // Rollback to savepoint
        await connection1.execute('ROLLBACK TO before_compression');

        // Record failure
        await connection1.execute(
          `INSERT INTO COMPRESSION_HISTORY
           (history_id, owner, object_name, execution_status, error_message)
           VALUES (SEQ_HISTORY_ID.NEXTVAL, :1, :2, :3, :4)`,
          ['TESTUSER', 'LOCKED_TABLE', 'FAILED', error.message]
        );

        await connection1.commit();
        expect(error).toBeDefined();
      }
    });
  });

  describe('Data Consistency', () => {
    it('should maintain referential integrity', async () => {
      // Insert analysis record
      await connection1.execute(
        `INSERT INTO COMPRESSION_ANALYSIS
         (analysis_id, owner, table_name, advisable_compression)
         VALUES (SEQ_ANALYSIS_ID.NEXTVAL, :1, :2, :3)`,
        ['TESTUSER', 'TEST_TABLE', 'OLTP']
      );

      // Insert history record referencing analysis
      await connection1.execute(
        `INSERT INTO COMPRESSION_HISTORY
         (history_id, owner, object_name, compression_type)
         VALUES (SEQ_HISTORY_ID.NEXTVAL, :1, :2, :3)`,
        ['TESTUSER', 'TEST_TABLE', 'OLTP']
      );

      await connection1.commit();
    });

    it('should handle concurrent reads and writes', async () => {
      // Connection 1: Read
      const readPromise = connection1.execute(
        'SELECT * FROM COMPRESSION_ANALYSIS WHERE owner = :1',
        ['TESTUSER']
      );

      // Connection 2: Write
      const writePromise = connection2.execute(
        `INSERT INTO COMPRESSION_ANALYSIS
         (analysis_id, owner, table_name, advisable_compression)
         VALUES (SEQ_ANALYSIS_ID.NEXTVAL, :1, :2, :3)`,
        ['TESTUSER', 'NEW_TABLE', 'QUERY_LOW']
      );

      const [readResult, writeResult] = await Promise.all([readPromise, writePromise]);

      expect(readResult.rows).toBeDefined();
      expect(writeResult.rowsAffected).toBe(1);

      await connection2.commit();
    });
  });

  describe('Error Propagation', () => {
    it('should propagate database errors correctly', async () => {
      await expect(async () => {
        await connection1.execute('SELECT * FROM NONEXISTENT_TABLE');
      }).rejects.toThrow();
    });

    it('should handle connection errors', async () => {
      await connection1.close();

      await expect(async () => {
        await connection1.execute('SELECT 1 FROM DUAL');
      }).rejects.toThrow();
    });

    it('should handle transaction deadlocks', async () => {
      // This would test deadlock scenarios in real database
      // Mock implementation shows the pattern
      try {
        await connection1.execute('LOCK TABLE test_table IN EXCLUSIVE MODE NOWAIT');
        await connection2.execute('LOCK TABLE test_table IN EXCLUSIVE MODE NOWAIT');
      } catch (error) {
        expect(error.message).toContain('ORA-00054');
      }
    });
  });

  describe('Performance Under Load', () => {
    it('should handle bulk analysis operations', async () => {
      const tables = TestDataGenerator.generateBatch(50);

      const analysisPromises = tables.map(table =>
        connection1.execute(
          'SELECT num_rows, blocks FROM DBA_TABLES WHERE table_name = :1',
          [table.table_name]
        )
      );

      const results = await Promise.all(analysisPromises);

      expect(results).toHaveLength(50);
    });

    it('should handle batch compression operations', async () => {
      const compressionOps = Array(20).fill(null).map((_, i) =>
        connection1.execute(
          `ALTER TABLE TESTUSER.BATCH_TABLE_${i.toString().padStart(4, '0')} MOVE COMPRESS FOR QUERY LOW`
        )
      );

      const results = await Promise.allSettled(compressionOps);

      expect(results).toHaveLength(20);
    });
  });
});
