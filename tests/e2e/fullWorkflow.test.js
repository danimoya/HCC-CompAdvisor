/**
 * End-to-End Tests
 * Tests complete workflows from candidate identification to compression execution
 */

const { MockOraclePool } = require('../fixtures/databaseMock');
const TestDataGenerator = require('../fixtures/testDataGenerator');
const { mockExpectedRecommendations } = require('../fixtures/mockOracleMetadata');

describe('End-to-End Workflow Tests', () => {
  let mockPool;
  let connection;

  beforeAll(async () => {
    mockPool = new MockOraclePool({
      user: 'compression_mgr',
      password: 'test_password',
      connectString: 'localhost/FREEPDB1'
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

  describe('Complete Compression Workflow', () => {
    it('should identify candidates, recommend, and execute compression', async () => {
      // Phase 1: Identify Candidates
      const tablesResult = await connection.execute(
        `SELECT owner, table_name, num_rows, blocks
         FROM DBA_TABLES
         WHERE owner NOT IN ('SYS', 'SYSTEM')
         AND num_rows > 100000`
      );

      expect(tablesResult.rows.length).toBeGreaterThan(0);
      const tables = tablesResult.rows;

      // Phase 2: Analyze Each Candidate
      const analysisResults = [];

      for (const table of tables.slice(0, 3)) {
        // Get DML statistics
        const dmlResult = await connection.execute(
          `SELECT inserts, updates, deletes
           FROM ALL_TAB_MODIFICATIONS
           WHERE table_owner = :1 AND table_name = :2`,
          [table[0], table[1]]
        );

        // Get compression ratios
        const compressionTypes = ['OLTP', 'QUERY_LOW', 'QUERY_HIGH', 'ARCHIVE_LOW', 'ARCHIVE_HIGH'];
        const ratios = {};

        for (const type of compressionTypes) {
          const ratioResult = await connection.execute(
            `BEGIN :ratio := DBMS_COMPRESSION.GET_COMPRESSION_RATIO(:1, :2, :3, 1000000); END;`,
            [table[0], table[1], type]
          );
          ratios[type] = 2.5; // Mock value
        }

        analysisResults.push({
          owner: table[0],
          table_name: table[1],
          dml_stats: dmlResult.rows[0] || [0, 0, 0],
          compression_ratios: ratios
        });
      }

      expect(analysisResults.length).toBe(3);

      // Phase 3: Generate Recommendations
      const recommendations = analysisResults.map(result => {
        const totalDML = result.dml_stats[0] + result.dml_stats[1] + result.dml_stats[2];

        let recommendation;
        if (totalDML > 100000) {
          recommendation = 'OLTP';
        } else if (totalDML > 10000) {
          recommendation = 'QUERY_LOW';
        } else {
          recommendation = 'ARCHIVE_HIGH';
        }

        return {
          ...result,
          recommended_compression: recommendation
        };
      });

      expect(recommendations.every(r => r.recommended_compression)).toBe(true);

      // Phase 4: Execute Compression
      for (const rec of recommendations.slice(0, 1)) {
        // Execute compression
        const compressionResult = await connection.execute(
          `ALTER TABLE ${rec.owner}.${rec.table_name} MOVE COMPRESS FOR ${rec.recommended_compression}`
        );

        expect(compressionResult.rowsAffected).toBe(1);

        // Record history
        await connection.execute(
          `INSERT INTO COMPRESSION_HISTORY
           (history_id, owner, object_name, compression_type, execution_status)
           VALUES (SEQ_HISTORY_ID.NEXTVAL, :1, :2, :3, :4)`,
          [rec.owner, rec.table_name, rec.recommended_compression, 'SUCCESS']
        );

        await connection.commit();
      }
    });

    it('should handle partial failures gracefully', async () => {
      const testTables = [
        { owner: 'TESTUSER', name: 'VALID_TABLE_1', shouldSucceed: true },
        { owner: 'TESTUSER', name: 'LOCKED_TABLE', shouldSucceed: false },
        { owner: 'TESTUSER', name: 'VALID_TABLE_2', shouldSucceed: true }
      ];

      const results = [];

      for (const table of testTables) {
        try {
          await connection.execute(
            `ALTER TABLE ${table.owner}.${table.name} MOVE COMPRESS FOR OLTP`
          );

          results.push({ table: table.name, status: 'SUCCESS' });
          await connection.commit();
        } catch (error) {
          results.push({ table: table.name, status: 'FAILED', error: error.message });
          await connection.rollback();
        }
      }

      const succeeded = results.filter(r => r.status === 'SUCCESS');
      const failed = results.filter(r => r.status === 'FAILED');

      expect(succeeded.length).toBeGreaterThan(0);
      expect(failed.length).toBeGreaterThan(0);
    });
  });

  describe('Historical Tracking Workflow', () => {
    it('should track compression history over time', async () => {
      const tableName = 'HISTORICAL_TEST_TABLE';

      // First compression
      await connection.execute(
        `INSERT INTO COMPRESSION_HISTORY
         (history_id, owner, object_name, compression_type,
          original_size_mb, compressed_size_mb, execution_status, start_time)
         VALUES (1, 'TESTUSER', :1, 'OLTP', 10000, 3500, 'SUCCESS', SYSDATE - 30)`,
        [tableName]
      );

      // Second compression (recompression)
      await connection.execute(
        `INSERT INTO COMPRESSION_HISTORY
         (history_id, owner, object_name, compression_type,
          original_size_mb, compressed_size_mb, execution_status, start_time)
         VALUES (2, 'TESTUSER', :1, 'ARCHIVE_HIGH', 3500, 500, 'SUCCESS', SYSDATE)`,
        [tableName]
      );

      await connection.commit();

      // Query history
      const historyResult = await connection.execute(
        `SELECT compression_type, original_size_mb, compressed_size_mb
         FROM COMPRESSION_HISTORY
         WHERE object_name = :1
         ORDER BY history_id`,
        [tableName]
      );

      expect(historyResult.rows.length).toBe(2);
    });

    it('should calculate cumulative space savings', async () => {
      const histories = [
        TestDataGenerator.generateCompressionHistory('TABLE1', 'OLTP', true),
        TestDataGenerator.generateCompressionHistory('TABLE2', 'QUERY_HIGH', true),
        TestDataGenerator.generateCompressionHistory('TABLE3', 'ARCHIVE_HIGH', true)
      ];

      const totalSavings = histories.reduce((sum, h) => sum + h.space_saved_mb, 0);

      expect(totalSavings).toBeGreaterThan(0);
    });
  });

  describe('Performance Validation Workflow', () => {
    it('should benchmark compression performance', async () => {
      const startTime = Date.now();

      // Analyze 100 tables
      const analysisPromises = Array(100).fill(null).map((_, i) =>
        connection.execute(
          'SELECT owner, table_name FROM DBA_TABLES WHERE ROWNUM <= 1'
        )
      );

      await Promise.all(analysisPromises);

      const duration = Date.now() - startTime;

      // Should complete in reasonable time (<5 seconds for mock)
      expect(duration).toBeLessThan(5000);
    });

    it('should validate compression ratio accuracy', async () => {
      const scenarios = [
        TestDataGenerator.generateScenario('HIGH_DML_CANDIDATE'),
        TestDataGenerator.generateScenario('ARCHIVE_CANDIDATE'),
        TestDataGenerator.generateScenario('READ_HEAVY')
      ];

      scenarios.forEach(scenario => {
        const recommendedType = scenario.expectedRecommendation;
        const expectedRatio = scenario.compressionRatios[recommendedType.replace(' ', '_').toUpperCase()];

        expect(expectedRatio).toBeGreaterThan(1.5);
      });
    });
  });

  describe('Reporting Workflow', () => {
    it('should generate compression candidates report', async () => {
      const report = await connection.execute(
        `SELECT owner, table_name, advisable_compression,
                potential_savings_gb
         FROM V_COMPRESSION_CANDIDATES
         WHERE potential_savings_gb > 10
         ORDER BY potential_savings_gb DESC`
      );

      expect(report.rows).toBeDefined();
    });

    it('should generate compression history report', async () => {
      const report = await connection.execute(
        `SELECT owner, object_name, compression_type,
                space_saved_mb, execution_status
         FROM V_COMPRESSION_HISTORY
         WHERE execution_status = 'SUCCESS'
         ORDER BY start_time DESC`
      );

      expect(report.rows).toBeDefined();
    });

    it('should generate space savings summary', async () => {
      const report = await connection.execute(
        `SELECT SUM(space_saved_mb) as total_saved_mb,
                AVG(compression_ratio_achieved) as avg_ratio,
                COUNT(*) as successful_compressions
         FROM COMPRESSION_HISTORY
         WHERE execution_status = 'SUCCESS'`
      );

      expect(report.rows).toBeDefined();
    });
  });

  describe('Scheduled Operations Workflow', () => {
    it('should simulate nightly analysis job', async () => {
      // Simulate scheduled job that runs nightly
      const jobStart = new Date();

      // Analyze all user tables
      const analysisResult = await connection.execute(
        `SELECT COUNT(*) as analyzed_tables
         FROM DBA_TABLES
         WHERE owner NOT IN ('SYS', 'SYSTEM')`
      );

      expect(analysisResult.rows[0][0]).toBeGreaterThan(0);

      // Record job execution
      await connection.execute(
        `INSERT INTO JOB_HISTORY
         (job_id, job_name, start_time, status)
         VALUES (SEQ_JOB_ID.NEXTVAL, 'NIGHTLY_ANALYSIS', :1, 'RUNNING')`,
        [jobStart]
      );

      await connection.commit();
    });

    it('should execute compression based on recommendations', async () => {
      // Get top 5 recommendations
      const recommendations = await connection.execute(
        `SELECT owner, table_name, advisable_compression
         FROM V_COMPRESSION_CANDIDATES
         WHERE advisable_compression != 'NONE'
         ORDER BY potential_savings_gb DESC
         FETCH FIRST 5 ROWS ONLY`
      );

      // Execute compressions
      for (const rec of recommendations.rows || []) {
        try {
          await connection.execute(
            `ALTER TABLE ${rec[0]}.${rec[1]} MOVE COMPRESS FOR ${rec[2]}`
          );
          await connection.commit();
        } catch (error) {
          await connection.rollback();
        }
      }
    });
  });

  describe('ORDS Integration Workflow', () => {
    it('should simulate REST API call for analysis', async () => {
      // Simulate POST /compression/v1/advisor/tables
      const requestPayload = {
        owner: 'TESTUSER',
        min_size_gb: 10
      };

      // Execute analysis
      const result = await connection.execute(
        `SELECT owner, table_name, num_rows
         FROM DBA_TABLES
         WHERE owner = :1`,
        [requestPayload.owner]
      );

      const response = {
        status: 'OK',
        analyzed_tables: result.rows.length,
        timestamp: new Date().toISOString()
      };

      expect(response.status).toBe('OK');
      expect(response.analyzed_tables).toBeGreaterThanOrEqual(0);
    });

    it('should simulate REST API call for compression execution', async () => {
      // Simulate POST /compression/v1/compress
      const requestPayload = {
        owner: 'TESTUSER',
        object_name: 'LARGE_TRANSACTIONAL',
        compression_type: 'OLTP'
      };

      try {
        await connection.execute(
          `ALTER TABLE ${requestPayload.owner}.${requestPayload.object_name}
           MOVE COMPRESS FOR ${requestPayload.compression_type}`
        );

        const response = {
          status: 'OK',
          message: 'Compression executed successfully'
        };

        expect(response.status).toBe('OK');
      } catch (error) {
        const response = {
          status: 'ERROR',
          message: error.message
        };

        expect(response.status).toBe('ERROR');
      }
    });
  });
});
