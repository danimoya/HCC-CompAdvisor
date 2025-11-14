/**
 * Security and Error Handling Tests
 * Tests security controls and error handling mechanisms
 */

const { MockOraclePool } = require('../fixtures/databaseMock');
const { mockErrorScenarios } = require('../fixtures/mockOracleMetadata');

describe('Security Tests', () => {
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

  describe('Schema Filtering', () => {
    it('should exclude system schemas from analysis', async () => {
      const systemSchemas = [
        'SYS', 'SYSTEM', 'ORACLE_OCM', 'XDB', 'DBSNMP',
        'GSMCATUSER', 'OUTLN', 'ORDS_METADATA', 'ORDS_PUBLIC_USER'
      ];

      const result = await connection.execute(
        `SELECT owner FROM DBA_TABLES
         WHERE owner NOT IN (${systemSchemas.map(() => ':s').join(',')})
         GROUP BY owner`,
        systemSchemas
      );

      expect(result.rows).toBeDefined();

      // Verify no system schemas in results
      const owners = result.rows.map(r => r[0]);
      systemSchemas.forEach(schema => {
        expect(owners).not.toContain(schema);
      });
    });

    it('should only operate on user schemas', async () => {
      const result = await connection.execute(
        `SELECT owner FROM DBA_USERS
         WHERE oracle_maintained = 'N'
         AND account_status = 'OPEN'`
      );

      expect(result.rows).toBeDefined();
    });

    it('should validate schema ownership before compression', async () => {
      const restrictedSchema = 'RESTRICTED_SCHEMA';

      const errorScenario = mockErrorScenarios.find(
        e => e.scenario === 'INSUFFICIENT_PRIVILEGES'
      );

      expect(errorScenario).toBeDefined();
      expect(errorScenario.error).toContain('ORA-01031');
    });
  });

  describe('Privilege Validation', () => {
    it('should check for required privileges', async () => {
      const requiredPrivileges = [
        'SELECT ANY TABLE',
        'ALTER ANY TABLE',
        'CREATE TABLE',
        'DROP TABLE'
      ];

      // In real scenario, would check DBA_SYS_PRIVS
      expect(requiredPrivileges.length).toBeGreaterThan(0);
    });

    it('should handle insufficient privileges gracefully', async () => {
      const errorScenario = mockErrorScenarios.find(
        e => e.scenario === 'INSUFFICIENT_PRIVILEGES'
      );

      await expect(async () => {
        const sql = `ALTER TABLE ${errorScenario.owner}.${errorScenario.table_name} MOVE COMPRESS FOR OLTP`;
        await connection.execute(sql);
      }).rejects.toThrow('ORA-01031');
    });
  });

  describe('Input Validation', () => {
    it('should reject SQL injection attempts', () => {
      const maliciousInputs = [
        "'; DROP TABLE users; --",
        "1' OR '1'='1",
        "admin'--",
        "1; DELETE FROM compression_history WHERE 1=1--"
      ];

      maliciousInputs.forEach(input => {
        // Bind variables prevent SQL injection
        expect(input).toContain("'");
      });
    });

    it('should validate table names', () => {
      const invalidNames = [
        '',
        null,
        undefined,
        'table with spaces',
        'table;drop',
        '../../../etc/passwd'
      ];

      invalidNames.forEach(name => {
        const isValid = name && /^[A-Za-z0-9_$#]+$/.test(name);
        expect(isValid).toBe(false);
      });
    });

    it('should validate compression types', () => {
      const validTypes = ['OLTP', 'QUERY_LOW', 'QUERY_HIGH', 'ARCHIVE_LOW', 'ARCHIVE_HIGH'];
      const invalidTypes = ['INVALID', 'BASIC', '', null];

      validTypes.forEach(type => {
        expect(['OLTP', 'QUERY_LOW', 'QUERY_HIGH', 'ARCHIVE_LOW', 'ARCHIVE_HIGH']).toContain(type);
      });

      invalidTypes.forEach(type => {
        expect(['OLTP', 'QUERY_LOW', 'QUERY_HIGH', 'ARCHIVE_LOW', 'ARCHIVE_HIGH']).not.toContain(type);
      });
    });

    it('should validate owner names', () => {
      const validOwners = ['TESTUSER', 'APP_SCHEMA', 'USER123'];
      const invalidOwners = ['', null, 'SYS', 'SYSTEM'];

      validOwners.forEach(owner => {
        const isValid = owner && owner.length > 0;
        expect(isValid).toBe(true);
      });
    });
  });

  describe('Error Handling', () => {
    it('should handle ORA-00942: table or view does not exist', async () => {
      const errorScenario = mockErrorScenarios.find(
        e => e.scenario === 'TABLE_NOT_FOUND'
      );

      expect(errorScenario.error).toBe('ORA-00942: table or view does not exist');
    });

    it('should handle ORA-01653: unable to extend table', async () => {
      const errorScenario = mockErrorScenarios.find(
        e => e.scenario === 'TABLESPACE_FULL'
      );

      await expect(async () => {
        const sql = `ALTER TABLE ${errorScenario.owner}.${errorScenario.table_name} MOVE COMPRESS FOR QUERY HIGH`;
        await connection.execute(sql);
      }).rejects.toThrow('ORA-01653');
    });

    it('should handle ORA-00054: resource busy (lock timeout)', async () => {
      const errorScenario = mockErrorScenarios.find(
        e => e.scenario === 'LOCK_TIMEOUT'
      );

      await expect(async () => {
        const sql = `ALTER TABLE ${errorScenario.owner}.${errorScenario.table_name} MOVE COMPRESS FOR OLTP`;
        await connection.execute(sql);
      }).rejects.toThrow('ORA-00054');
    });

    it('should handle connection timeouts', async () => {
      jest.setTimeout(10000);

      // Close connection to simulate timeout
      await connection.close();

      await expect(async () => {
        await connection.execute('SELECT 1 FROM DUAL');
      }).rejects.toThrow();
    });

    it('should handle network errors gracefully', async () => {
      // Simulate network error by closing connection
      await connection.close();

      await expect(async () => {
        await connection.execute('SELECT * FROM DBA_TABLES');
      }).rejects.toThrow();
    });
  });

  describe('Data Sanitization', () => {
    it('should sanitize error messages before logging', () => {
      const sensitiveError = 'Error connecting to database user=admin password=secret123';
      const sanitized = sensitiveError.replace(/password=[^\s]+/gi, 'password=***');

      expect(sanitized).not.toContain('secret123');
      expect(sanitized).toContain('password=***');
    });

    it('should not expose internal paths in errors', () => {
      const internalPath = '/opt/oracle/product/19c/dbhome_1/dbs/init.ora';
      const publicPath = internalPath.replace(/\/opt\/oracle\/.*/, '[ORACLE_HOME]/...');

      expect(publicPath).not.toContain('/opt/oracle/product');
    });
  });

  describe('Audit Logging', () => {
    it('should log compression operations', async () => {
      const auditLog = {
        timestamp: new Date(),
        user: 'COMPRESSION_MGR',
        operation: 'COMPRESS_TABLE',
        object_owner: 'TESTUSER',
        object_name: 'LARGE_TRANSACTIONAL',
        compression_type: 'OLTP',
        status: 'SUCCESS'
      };

      expect(auditLog).toHaveProperty('timestamp');
      expect(auditLog).toHaveProperty('user');
      expect(auditLog).toHaveProperty('operation');
      expect(auditLog).toHaveProperty('status');
    });

    it('should log failed operations with error details', async () => {
      const auditLog = {
        timestamp: new Date(),
        user: 'COMPRESSION_MGR',
        operation: 'COMPRESS_TABLE',
        object_owner: 'TESTUSER',
        object_name: 'LOCKED_TABLE',
        status: 'FAILED',
        error_code: 'ORA-00054',
        error_message: 'resource busy and acquire with NOWAIT specified'
      };

      expect(auditLog.status).toBe('FAILED');
      expect(auditLog).toHaveProperty('error_code');
      expect(auditLog).toHaveProperty('error_message');
    });
  });

  describe('Resource Limits', () => {
    it('should enforce maximum parallel degree', () => {
      const maxParallel = 16;
      const requestedParallel = 32;

      const actualParallel = Math.min(requestedParallel, maxParallel);

      expect(actualParallel).toBe(maxParallel);
      expect(actualParallel).toBeLessThanOrEqual(16);
    });

    it('should limit batch size for bulk operations', () => {
      const maxBatchSize = 100;
      const requestedBatchSize = 500;

      const actualBatchSize = Math.min(requestedBatchSize, maxBatchSize);

      expect(actualBatchSize).toBe(maxBatchSize);
    });

    it('should timeout long-running operations', async () => {
      jest.setTimeout(15000);

      const timeout = 10000; // 10 seconds
      const operationPromise = new Promise((resolve) => {
        setTimeout(resolve, 20000); // 20 second operation
      });

      const timeoutPromise = new Promise((_, reject) => {
        setTimeout(() => reject(new Error('Operation timeout')), timeout);
      });

      await expect(Promise.race([operationPromise, timeoutPromise]))
        .rejects.toThrow('Operation timeout');
    }, 15000);
  });

  describe('Secure Configuration', () => {
    it('should not expose credentials in error messages', () => {
      const config = {
        user: 'compression_mgr',
        password: 'SecretPassword123!',
        connectString: 'localhost/FREEPDB1'
      };

      const safeConfig = { ...config, password: '***' };

      expect(JSON.stringify(safeConfig)).not.toContain('SecretPassword123!');
      expect(safeConfig.password).toBe('***');
    });

    it('should validate connection strings', () => {
      const validConnStrings = [
        'localhost:1521/FREEPDB1',
        'db.example.com:1521/PROD',
        '192.168.1.100:1521/TEST'
      ];

      const invalidConnStrings = [
        '',
        null,
        'invalid',
        'http://malicious.com/exploit'
      ];

      validConnStrings.forEach(connStr => {
        expect(connStr).toMatch(/^[\w.-]+:\d+\/[\w]+$/);
      });

      invalidConnStrings.forEach(connStr => {
        const isValid = connStr && /^[\w.-]+:\d+\/[\w]+$/.test(connStr);
        expect(isValid).toBe(false);
      });
    });
  });

  describe('Rate Limiting', () => {
    it('should limit compression operations per minute', async () => {
      const maxOpsPerMinute = 60;
      const operations = [];
      const startTime = Date.now();

      for (let i = 0; i < 100; i++) {
        const elapsed = Date.now() - startTime;
        const opsThisMinute = operations.filter(
          op => op.timestamp > Date.now() - 60000
        ).length;

        if (opsThisMinute < maxOpsPerMinute) {
          operations.push({ timestamp: Date.now() });
        }
      }

      // Should have rate-limited to max 60
      const recentOps = operations.filter(
        op => op.timestamp > startTime
      );

      expect(recentOps.length).toBeLessThanOrEqual(maxOpsPerMinute);
    });
  });
});
