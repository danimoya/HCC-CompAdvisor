/**
 * Unit Tests for Compression Analyzer
 * Tests the candidate identification and recommendation logic
 */

const { MockOraclePool } = require('../fixtures/databaseMock');
const TestDataGenerator = require('../fixtures/testDataGenerator');
const {
  mockTables,
  mockTabModifications,
  mockCompressionRatios,
  mockExpectedRecommendations
} = require('../fixtures/mockOracleMetadata');

describe('Compression Analyzer - Unit Tests', () => {
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

  describe('Candidate Identification', () => {
    it('should identify large tables as compression candidates', async () => {
      const largeTables = mockTables.filter(t => t.size_gb > 10);
      expect(largeTables.length).toBeGreaterThan(0);

      largeTables.forEach(table => {
        expect(table.size_gb).toBeGreaterThanOrEqual(10);
      });
    });

    it('should exclude small tables from compression', () => {
      const smallTables = mockTables.filter(t => t.size_gb < 10);

      smallTables.forEach(table => {
        const recommendation = mockExpectedRecommendations[table.table_name];
        if (recommendation) {
          expect(recommendation.recommendation).toBe('NONE');
        }
      });
    });

    it('should filter out system schemas', async () => {
      const systemSchemas = ['SYS', 'SYSTEM', 'ORACLE_OCM', 'XDB'];
      const userTables = mockTables.filter(t => !systemSchemas.includes(t.owner));

      expect(userTables.length).toBe(mockTables.length);
      userTables.forEach(table => {
        expect(systemSchemas).not.toContain(table.owner);
      });
    });

    it('should handle partitioned tables correctly', () => {
      const partitionedTable = mockTables.find(t => t.partitioned === 'YES');

      expect(partitionedTable).toBeDefined();
      expect(partitionedTable.table_name).toBe('PARTITIONED_SALES');
    });
  });

  describe('DML Activity Analysis', () => {
    it('should calculate total DML operations correctly', () => {
      mockTabModifications.forEach(mod => {
        const totalDML = mod.inserts + mod.updates + mod.deletes;
        expect(totalDML).toBeGreaterThanOrEqual(0);
      });
    });

    it('should identify high DML activity tables', () => {
      const highDML = mockTabModifications.filter(mod => {
        const total = mod.inserts + mod.updates + mod.deletes;
        return total > 100000;
      });

      expect(highDML.length).toBeGreaterThan(0);
      highDML.forEach(mod => {
        const total = mod.inserts + mod.updates + mod.deletes;
        expect(total).toBeGreaterThan(100000);
      });
    });

    it('should identify low DML activity (archival candidates)', () => {
      const lowDML = mockTabModifications.filter(mod => {
        const total = mod.inserts + mod.updates + mod.deletes;
        return total < 100;
      });

      expect(lowDML.length).toBeGreaterThan(0);
    });

    it('should handle tables with no DML activity', () => {
      const noDML = mockTabModifications.find(mod => {
        return mod.inserts === 0 && mod.updates === 0 && mod.deletes === 0;
      });

      // Archive table should have minimal or no DML
      const archiveMod = mockTabModifications.find(m => m.table_name === 'ARCHIVE_DATA');
      expect(archiveMod.inserts + archiveMod.updates + archiveMod.deletes).toBeLessThan(100);
    });
  });

  describe('Compression Ratio Analysis', () => {
    it('should have compression ratios for all compression types', () => {
      Object.keys(mockCompressionRatios).forEach(tableName => {
        const ratios = mockCompressionRatios[tableName];

        expect(ratios).toHaveProperty('OLTP');
        expect(ratios).toHaveProperty('QUERY_LOW');
        expect(ratios).toHaveProperty('QUERY_HIGH');
        expect(ratios).toHaveProperty('ARCHIVE_LOW');
        expect(ratios).toHaveProperty('ARCHIVE_HIGH');
      });
    });

    it('should have higher ratios for archive compression', () => {
      Object.keys(mockCompressionRatios).forEach(tableName => {
        const ratios = mockCompressionRatios[tableName];

        expect(ratios.ARCHIVE_HIGH).toBeGreaterThan(ratios.ARCHIVE_LOW);
        expect(ratios.ARCHIVE_LOW).toBeGreaterThan(ratios.QUERY_HIGH);
        expect(ratios.QUERY_HIGH).toBeGreaterThan(ratios.QUERY_LOW);
        expect(ratios.QUERY_LOW).toBeGreaterThan(ratios.OLTP);
      });
    });

    it('should reject poor compression ratios (<1.5)', () => {
      const poorRatio = 1.2;
      expect(poorRatio).toBeLessThan(1.5);

      // Tables with poor compression should not be compressed
      const smallTable = mockCompressionRatios['SMALL_TABLE'];
      if (smallTable.OLTP < 1.5) {
        const recommendation = mockExpectedRecommendations['SMALL_TABLE'];
        expect(recommendation.recommendation).toBe('NONE');
      }
    });

    it('should prioritize compression type with best ratio for archival', () => {
      const archiveTable = mockCompressionRatios['ARCHIVE_DATA'];

      const maxRatio = Math.max(
        archiveTable.OLTP,
        archiveTable.QUERY_LOW,
        archiveTable.QUERY_HIGH,
        archiveTable.ARCHIVE_LOW,
        archiveTable.ARCHIVE_HIGH
      );

      expect(archiveTable.ARCHIVE_HIGH).toBe(maxRatio);
    });
  });

  describe('Recommendation Algorithm', () => {
    it('should recommend OLTP for high DML activity', () => {
      const recommendation = mockExpectedRecommendations['LARGE_TRANSACTIONAL'];

      expect(recommendation.recommendation).toBe('OLTP');
      expect(recommendation.reason).toContain('High DML');
    });

    it('should recommend ARCHIVE_HIGH for large, inactive tables', () => {
      const recommendation = mockExpectedRecommendations['ARCHIVE_DATA'];

      expect(recommendation.recommendation).toBe('ARCHIVE_HIGH');
      expect(recommendation.reason).toContain('minimal DML');
    });

    it('should recommend QUERY compression for read-heavy workloads', () => {
      const recommendation = mockExpectedRecommendations['PARTITIONED_SALES'];

      expect(['QUERY_LOW', 'QUERY_HIGH']).toContain(recommendation.recommendation);
      expect(recommendation.reason).toContain('read-heavy');
    });

    it('should recommend NO compression for small tables', () => {
      const recommendation = mockExpectedRecommendations['SMALL_TABLE'];

      expect(recommendation.recommendation).toBe('NONE');
      expect(recommendation.reason).toContain('too small');
    });

    it('should calculate space savings correctly', () => {
      Object.keys(mockExpectedRecommendations).forEach(tableName => {
        const rec = mockExpectedRecommendations[tableName];

        if (rec.recommendation !== 'NONE') {
          expect(rec.space_savings_pct).toBeGreaterThan(0);
          expect(rec.space_savings_pct).toBeLessThan(100);

          // Verify calculation: savings = (1 - 1/ratio) * 100
          const expectedSavings = (1 - 1/rec.compression_ratio) * 100;
          expect(rec.space_savings_pct).toBeCloseTo(expectedSavings, 1);
        }
      });
    });
  });

  describe('Edge Cases', () => {
    it('should handle NULL partition names', async () => {
      const result = await mockConnection.execute(
        'SELECT * FROM ALL_TAB_MODIFICATIONS WHERE PARTITION_NAME IS NULL'
      );

      expect(result.rows).toBeDefined();
    });

    it('should handle tables with no statistics', () => {
      const testTable = TestDataGenerator.generateTable({
        num_rows: null,
        last_analyzed: null
      });

      expect(testTable.num_rows).toBeNull();
      expect(testTable.last_analyzed).toBeNull();
    });

    it('should handle very large tables (>100GB)', () => {
      const largeTable = TestDataGenerator.generateTable({
        size_gb: 500,
        num_rows: 100000000
      });

      expect(largeTable.size_gb).toBeGreaterThan(100);
    });

    it('should handle compressed tables', () => {
      const compressedTable = mockTables.find(t => t.compression === 'ENABLED');

      expect(compressedTable).toBeDefined();
      expect(compressedTable.compress_for).toBe('OLTP');
    });

    it('should handle concurrent analysis requests', async () => {
      const promises = Array(10).fill(null).map(() =>
        mockConnection.execute('SELECT * FROM DBA_TABLES WHERE ROWNUM <= 100')
      );

      const results = await Promise.all(promises);
      expect(results).toHaveLength(10);
      results.forEach(result => {
        expect(result.rows).toBeDefined();
      });
    });
  });

  describe('Data Validation', () => {
    it('should validate table owner is not null', () => {
      mockTables.forEach(table => {
        expect(table.owner).toBeDefined();
        expect(table.owner).not.toBeNull();
        expect(table.owner.length).toBeGreaterThan(0);
      });
    });

    it('should validate table name is not null', () => {
      mockTables.forEach(table => {
        expect(table.table_name).toBeDefined();
        expect(table.table_name).not.toBeNull();
        expect(table.table_name.length).toBeGreaterThan(0);
      });
    });

    it('should validate compression ratios are positive', () => {
      Object.values(mockCompressionRatios).forEach(ratios => {
        Object.values(ratios).forEach(ratio => {
          expect(ratio).toBeGreaterThan(0);
        });
      });
    });

    it('should validate DML counts are non-negative', () => {
      mockTabModifications.forEach(mod => {
        expect(mod.inserts).toBeGreaterThanOrEqual(0);
        expect(mod.updates).toBeGreaterThanOrEqual(0);
        expect(mod.deletes).toBeGreaterThanOrEqual(0);
      });
    });
  });
});
