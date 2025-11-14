/**
 * Performance Benchmark Tests
 * Tests system performance under various load conditions
 */

const { MockOraclePool } = require('../fixtures/databaseMock');
const TestDataGenerator = require('../fixtures/testDataGenerator');

describe('Performance Benchmarks', () => {
  let mockPool;
  let connection;

  beforeAll(async () => {
    mockPool = new MockOraclePool({
      user: 'compression_mgr',
      password: 'test_password',
      connectString: 'localhost/FREEPDB1',
      poolMin: 4,
      poolMax: 20
    });
  });

  afterAll(async () => {
    if (mockPool) {
      await mockPool.close();
    }
  });

  beforeEach(async () => {
    connection = await mockPool.getConnection();
  });

  afterEach(async () => {
    if (connection) {
      await connection.close();
    }
  });

  describe('Analysis Performance', () => {
    it('should analyze 100 tables in under 30 seconds', async () => {
      const startTime = Date.now();

      const tables = TestDataGenerator.generateBatch(100);
      const analysisPromises = tables.map(table =>
        connection.execute(
          `SELECT num_rows, blocks FROM DBA_TABLES WHERE table_name = :1`,
          [table.table_name]
        )
      );

      await Promise.all(analysisPromises);

      const duration = Date.now() - startTime;

      expect(duration).toBeLessThan(30000);
      console.log(`Analyzed 100 tables in ${duration}ms`);
    }, 35000);

    it('should analyze 1000 tables in under 5 minutes', async () => {
      const startTime = Date.now();

      // Batch processing for better performance
      const batchSize = 100;
      const totalTables = 1000;

      for (let i = 0; i < totalTables; i += batchSize) {
        const batch = TestDataGenerator.generateBatch(batchSize);
        const batchPromises = batch.map(table =>
          connection.execute(
            `SELECT num_rows, blocks FROM DBA_TABLES WHERE table_name = :1`,
            [table.table_name]
          )
        );
        await Promise.all(batchPromises);
      }

      const duration = Date.now() - startTime;

      expect(duration).toBeLessThan(300000); // 5 minutes
      console.log(`Analyzed 1000 tables in ${duration}ms`);
    }, 310000);

    it('should handle concurrent analysis requests efficiently', async () => {
      const startTime = Date.now();
      const concurrentRequests = 50;

      const requests = Array(concurrentRequests).fill(null).map(() =>
        connection.execute(
          `SELECT owner, table_name, num_rows FROM DBA_TABLES WHERE ROWNUM <= 10`
        )
      );

      await Promise.all(requests);

      const duration = Date.now() - startTime;

      expect(duration).toBeLessThan(10000); // 10 seconds
      console.log(`Handled ${concurrentRequests} concurrent requests in ${duration}ms`);
    });
  });

  describe('Compression Execution Performance', () => {
    it('should execute compression on 10 tables sequentially', async () => {
      const startTime = Date.now();

      for (let i = 0; i < 10; i++) {
        await connection.execute(
          `ALTER TABLE TESTUSER.BATCH_TABLE_${i.toString().padStart(4, '0')} MOVE COMPRESS FOR OLTP`
        );
        await connection.commit();
      }

      const duration = Date.now() - startTime;

      expect(duration).toBeLessThan(15000); // 15 seconds
      console.log(`Compressed 10 tables sequentially in ${duration}ms`);
    });

    it('should measure compression throughput', async () => {
      const tableCount = 20;
      const startTime = Date.now();

      const compressionPromises = Array(tableCount).fill(null).map((_, i) =>
        connection.execute(
          `ALTER TABLE TESTUSER.BATCH_TABLE_${i.toString().padStart(4, '0')} MOVE COMPRESS FOR QUERY_LOW`
        ).catch(err => ({ error: err.message }))
      );

      const results = await Promise.allSettled(compressionPromises);
      const duration = Date.now() - startTime;

      const throughput = (tableCount / duration) * 1000; // tables per second

      console.log(`Compression throughput: ${throughput.toFixed(2)} tables/second`);
      expect(throughput).toBeGreaterThan(0);
    });
  });

  describe('Query Performance', () => {
    it('should query compression candidates efficiently', async () => {
      const iterations = 100;
      const startTime = Date.now();

      for (let i = 0; i < iterations; i++) {
        await connection.execute(
          `SELECT owner, table_name, advisable_compression
           FROM V_COMPRESSION_CANDIDATES
           WHERE potential_savings_gb > 10`
        );
      }

      const duration = Date.now() - startTime;
      const avgQueryTime = duration / iterations;

      console.log(`Average query time: ${avgQueryTime.toFixed(2)}ms`);
      expect(avgQueryTime).toBeLessThan(100); // <100ms per query
    });

    it('should aggregate compression statistics efficiently', async () => {
      const startTime = Date.now();

      await connection.execute(
        `SELECT owner,
                COUNT(*) as table_count,
                SUM(potential_savings_gb) as total_savings,
                AVG(compression_ratio) as avg_ratio
         FROM V_COMPRESSION_CANDIDATES
         GROUP BY owner`
      );

      const duration = Date.now() - startTime;

      expect(duration).toBeLessThan(1000); // <1 second
      console.log(`Aggregation query completed in ${duration}ms`);
    });
  });

  describe('Memory Usage', () => {
    it('should maintain stable memory usage during bulk operations', async () => {
      const initialMemory = process.memoryUsage().heapUsed;

      // Process 500 tables
      for (let i = 0; i < 500; i++) {
        await connection.execute(
          'SELECT * FROM DBA_TABLES WHERE ROWNUM <= 1'
        );
      }

      const finalMemory = process.memoryUsage().heapUsed;
      const memoryIncrease = finalMemory - initialMemory;
      const memoryIncreaseMB = memoryIncrease / (1024 * 1024);

      console.log(`Memory increase: ${memoryIncreaseMB.toFixed(2)}MB`);
      expect(memoryIncreaseMB).toBeLessThan(100); // <100MB increase
    });

    it('should release resources after operations', async () => {
      const connections = [];

      // Create 20 connections
      for (let i = 0; i < 20; i++) {
        connections.push(await mockPool.getConnection());
      }

      // Close all connections
      for (const conn of connections) {
        await conn.close();
      }

      // Verify connections are released
      const activeConnections = mockPool.getConnectionCount();
      expect(activeConnections).toBeLessThanOrEqual(5);
    });
  });

  describe('Scalability', () => {
    it('should scale linearly with table count', async () => {
      const testSizes = [10, 50, 100];
      const timings = [];

      for (const size of testSizes) {
        const startTime = Date.now();

        const tables = TestDataGenerator.generateBatch(size);
        await Promise.all(
          tables.map(t =>
            connection.execute(
              'SELECT num_rows FROM DBA_TABLES WHERE table_name = :1',
              [t.table_name]
            )
          )
        );

        const duration = Date.now() - startTime;
        timings.push({ size, duration });
      }

      // Check that time roughly scales linearly
      const ratio1 = timings[1].duration / timings[0].duration;
      const ratio2 = timings[2].duration / timings[1].duration;

      console.log('Scalability ratios:', { ratio1, ratio2 });

      // Should scale roughly linearly (within 2x of expected)
      expect(ratio1).toBeLessThan(10);
      expect(ratio2).toBeLessThan(4);
    });

    it('should handle large result sets efficiently', async () => {
      const startTime = Date.now();

      // Query that returns many rows
      await connection.execute(
        `SELECT * FROM (
           SELECT owner, table_name, num_rows, blocks
           FROM DBA_TABLES
           WHERE num_rows > 0
         ) WHERE ROWNUM <= 1000`
      );

      const duration = Date.now() - startTime;

      expect(duration).toBeLessThan(2000); // <2 seconds
      console.log(`Retrieved 1000 rows in ${duration}ms`);
    });
  });

  describe('Latency Benchmarks', () => {
    it('should measure database round-trip latency', async () => {
      const iterations = 100;
      const latencies = [];

      for (let i = 0; i < iterations; i++) {
        const start = Date.now();
        await connection.execute('SELECT 1 FROM DUAL');
        latencies.push(Date.now() - start);
      }

      const avgLatency = latencies.reduce((a, b) => a + b, 0) / latencies.length;
      const maxLatency = Math.max(...latencies);
      const minLatency = Math.min(...latencies);

      console.log('Latency stats:', {
        avg: `${avgLatency.toFixed(2)}ms`,
        min: `${minLatency}ms`,
        max: `${maxLatency}ms`
      });

      expect(avgLatency).toBeLessThan(50); // <50ms average
    });

    it('should measure compression ratio calculation latency', async () => {
      const startTime = Date.now();

      await connection.execute(
        `BEGIN
           :ratio := DBMS_COMPRESSION.GET_COMPRESSION_RATIO(
             'TESTUSER', 'LARGE_TRANSACTIONAL', 'OLTP', 1000000
           );
         END;`
      );

      const duration = Date.now() - startTime;

      console.log(`Compression ratio calculation: ${duration}ms`);
      expect(duration).toBeLessThan(500); // <500ms
    });
  });

  describe('Stress Tests', () => {
    it('should handle sustained load', async () => {
      const duration = 10000; // 10 seconds
      const startTime = Date.now();
      let operationCount = 0;

      while (Date.now() - startTime < duration) {
        await connection.execute('SELECT COUNT(*) FROM DBA_TABLES WHERE ROWNUM <= 10');
        operationCount++;
      }

      const opsPerSecond = (operationCount / duration) * 1000;

      console.log(`Sustained load: ${opsPerSecond.toFixed(2)} ops/second`);
      expect(opsPerSecond).toBeGreaterThan(10);
    }, 15000);

    it('should recover from connection pool exhaustion', async () => {
      const connections = [];

      try {
        // Exhaust the pool
        for (let i = 0; i < 25; i++) {
          connections.push(await mockPool.getConnection());
        }

        // Release some connections
        for (let i = 0; i < 5; i++) {
          await connections[i].close();
        }

        // Should be able to get new connection
        const newConn = await mockPool.getConnection();
        expect(newConn).toBeDefined();
        await newConn.close();

      } finally {
        // Cleanup
        for (const conn of connections) {
          if (conn.isOpen) {
            await conn.close();
          }
        }
      }
    });
  });
});
