--------------------------------------------------------------------------------
-- Test Script: Tablespace Preservation During Compression
-- Purpose: Verify that all compression operations preserve original tablespace
-- Author: Daniel Moya (copyright), GitHub: github.com/danimoya Website: danielmoya.cv
-- Date: 2025-11-13
--------------------------------------------------------------------------------

SET SERVEROUTPUT ON SIZE UNLIMITED
SET LINESIZE 200
SET PAGESIZE 1000

PROMPT ================================================================================
PROMPT TEST: Tablespace Preservation During Compression Operations
PROMPT ================================================================================
PROMPT

-- Create test tablespaces
PROMPT Creating test tablespaces...
CREATE TABLESPACE TS_TEST_DATA
  DATAFILE 'ts_test_data.dbf' SIZE 100M AUTOEXTEND ON NEXT 10M;

CREATE TABLESPACE TS_TEST_INDEX
  DATAFILE 'ts_test_index.dbf' SIZE 50M AUTOEXTEND ON NEXT 10M;

CREATE TABLESPACE TS_TEST_LOB
  DATAFILE 'ts_test_lob.dbf' SIZE 50M AUTOEXTEND ON NEXT 10M;

CREATE TABLESPACE TS_TEST_PART1
  DATAFILE 'ts_test_part1.dbf' SIZE 50M AUTOEXTEND ON NEXT 10M;

CREATE TABLESPACE TS_TEST_PART2
  DATAFILE 'ts_test_part2.dbf' SIZE 50M AUTOEXTEND ON NEXT 10M;

PROMPT Test tablespaces created successfully
PROMPT

--------------------------------------------------------------------------------
-- TEST 1: Regular Table Tablespace Preservation
--------------------------------------------------------------------------------
PROMPT ================================================================================
PROMPT TEST 1: Regular Table Tablespace Preservation
PROMPT ================================================================================

-- Create test table in specific tablespace
CREATE TABLE test_regular_table (
  id NUMBER PRIMARY KEY,
  data VARCHAR2(1000),
  created_date DATE
) TABLESPACE TS_TEST_DATA;

-- Insert test data
BEGIN
  FOR i IN 1..1000 LOOP
    INSERT INTO test_regular_table VALUES (
      i,
      RPAD('X', 1000, 'X'),
      SYSDATE
    );
  END LOOP;
  COMMIT;
END;
/

-- Check tablespace before compression
SELECT 'Before Compression:' AS status,
       tablespace_name,
       compression,
       ROUND(num_rows) AS num_rows
FROM user_tables
WHERE table_name = 'TEST_REGULAR_TABLE';

-- Compress table (should preserve TS_TEST_DATA)
EXEC PKG_COMPRESSION_EXECUTOR.compress_table(USER, 'TEST_REGULAR_TABLE', 'OLTP', TRUE, FALSE);

-- Verify tablespace preserved
SELECT 'After Compression:' AS status,
       tablespace_name,
       compression,
       ROUND(num_rows) AS num_rows
FROM user_tables
WHERE table_name = 'TEST_REGULAR_TABLE';

-- Validation
DECLARE
  v_tablespace VARCHAR2(128);
BEGIN
  SELECT tablespace_name INTO v_tablespace
  FROM user_tables
  WHERE table_name = 'TEST_REGULAR_TABLE';

  IF v_tablespace = 'TS_TEST_DATA' THEN
    DBMS_OUTPUT.PUT_LINE('✓ TEST 1 PASSED: Tablespace preserved (TS_TEST_DATA)');
  ELSE
    DBMS_OUTPUT.PUT_LINE('✗ TEST 1 FAILED: Tablespace changed to ' || v_tablespace);
  END IF;
END;
/

PROMPT

--------------------------------------------------------------------------------
-- TEST 2: Index Tablespace Preservation
--------------------------------------------------------------------------------
PROMPT ================================================================================
PROMPT TEST 2: Index Tablespace Preservation
PROMPT ================================================================================

-- Create index in specific tablespace
CREATE INDEX idx_test_data ON test_regular_table(data)
  TABLESPACE TS_TEST_INDEX;

-- Check index tablespace before rebuild
SELECT 'Before Rebuild:' AS status,
       index_name,
       tablespace_name,
       compression
FROM user_indexes
WHERE index_name = 'IDX_TEST_DATA';

-- Compress index (should preserve TS_TEST_INDEX)
EXEC PKG_COMPRESSION_EXECUTOR.compress_index(USER, 'IDX_TEST_DATA', 'ADV_LOW', TRUE);

-- Verify index tablespace preserved
SELECT 'After Rebuild:' AS status,
       index_name,
       tablespace_name,
       compression
FROM user_indexes
WHERE index_name = 'IDX_TEST_DATA';

-- Validation
DECLARE
  v_tablespace VARCHAR2(128);
BEGIN
  SELECT tablespace_name INTO v_tablespace
  FROM user_indexes
  WHERE index_name = 'IDX_TEST_DATA';

  IF v_tablespace = 'TS_TEST_INDEX' THEN
    DBMS_OUTPUT.PUT_LINE('✓ TEST 2 PASSED: Index tablespace preserved (TS_TEST_INDEX)');
  ELSE
    DBMS_OUTPUT.PUT_LINE('✗ TEST 2 FAILED: Index tablespace changed to ' || v_tablespace);
  END IF;
END;
/

PROMPT

--------------------------------------------------------------------------------
-- TEST 3: Partitioned Table Tablespace Preservation
--------------------------------------------------------------------------------
PROMPT ================================================================================
PROMPT TEST 3: Partitioned Table Tablespace Preservation
PROMPT ================================================================================

-- Create partitioned table with different tablespaces
CREATE TABLE test_partitioned_table (
  id NUMBER,
  partition_key DATE,
  data VARCHAR2(1000)
)
PARTITION BY RANGE (partition_key) (
  PARTITION p1 VALUES LESS THAN (DATE '2024-07-01') TABLESPACE TS_TEST_PART1,
  PARTITION p2 VALUES LESS THAN (DATE '2025-01-01') TABLESPACE TS_TEST_PART2
);

-- Insert test data
BEGIN
  FOR i IN 1..500 LOOP
    INSERT INTO test_partitioned_table VALUES (
      i,
      DATE '2024-01-01' + MOD(i, 365),
      RPAD('Y', 1000, 'Y')
    );
  END LOOP;
  COMMIT;
END;
/

-- Check partition tablespaces before compression
SELECT 'Before Compression:' AS status,
       partition_name,
       tablespace_name,
       compression
FROM user_tab_partitions
WHERE table_name = 'TEST_PARTITIONED_TABLE'
ORDER BY partition_position;

-- Compress partition P1 (should preserve TS_TEST_PART1)
EXEC PKG_COMPRESSION_EXECUTOR.compress_partition(USER, 'TEST_PARTITIONED_TABLE', 'P1', 'OLTP', TRUE);

-- Compress partition P2 (should preserve TS_TEST_PART2)
EXEC PKG_COMPRESSION_EXECUTOR.compress_partition(USER, 'TEST_PARTITIONED_TABLE', 'P2', 'OLTP', TRUE);

-- Verify partition tablespaces preserved
SELECT 'After Compression:' AS status,
       partition_name,
       tablespace_name,
       compression
FROM user_tab_partitions
WHERE table_name = 'TEST_PARTITIONED_TABLE'
ORDER BY partition_position;

-- Validation
DECLARE
  v_part1_ts VARCHAR2(128);
  v_part2_ts VARCHAR2(128);
BEGIN
  SELECT tablespace_name INTO v_part1_ts
  FROM user_tab_partitions
  WHERE table_name = 'TEST_PARTITIONED_TABLE' AND partition_name = 'P1';

  SELECT tablespace_name INTO v_part2_ts
  FROM user_tab_partitions
  WHERE table_name = 'TEST_PARTITIONED_TABLE' AND partition_name = 'P2';

  IF v_part1_ts = 'TS_TEST_PART1' AND v_part2_ts = 'TS_TEST_PART2' THEN
    DBMS_OUTPUT.PUT_LINE('✓ TEST 3 PASSED: Partition tablespaces preserved');
    DBMS_OUTPUT.PUT_LINE('  - P1: ' || v_part1_ts);
    DBMS_OUTPUT.PUT_LINE('  - P2: ' || v_part2_ts);
  ELSE
    DBMS_OUTPUT.PUT_LINE('✗ TEST 3 FAILED: Partition tablespaces changed');
    DBMS_OUTPUT.PUT_LINE('  - P1: ' || v_part1_ts || ' (expected: TS_TEST_PART1)');
    DBMS_OUTPUT.PUT_LINE('  - P2: ' || v_part2_ts || ' (expected: TS_TEST_PART2)');
  END IF;
END;
/

PROMPT

--------------------------------------------------------------------------------
-- TEST 4: LOB Tablespace Preservation
--------------------------------------------------------------------------------
PROMPT ================================================================================
PROMPT TEST 4: LOB Tablespace Preservation
PROMPT ================================================================================

-- Create table with LOB column in specific tablespace
CREATE TABLE test_lob_table (
  id NUMBER PRIMARY KEY,
  document CLOB
)
TABLESPACE TS_TEST_DATA
LOB (document) STORE AS (
  TABLESPACE TS_TEST_LOB
  ENABLE STORAGE IN ROW
  CHUNK 8192
);

-- Insert test LOB data
BEGIN
  FOR i IN 1..100 LOOP
    INSERT INTO test_lob_table VALUES (
      i,
      RPAD('Large LOB content ', 32000, 'X')
    );
  END LOOP;
  COMMIT;
END;
/

-- Check LOB tablespace before compression
SELECT 'Before Compression:' AS status,
       l.table_name,
       l.column_name,
       l.segment_name,
       l.tablespace_name,
       l.compression
FROM user_lobs l
WHERE l.table_name = 'TEST_LOB_TABLE';

-- Compress LOB (should preserve TS_TEST_LOB)
EXEC PKG_COMPRESSION_EXECUTOR.compress_lob(USER, 'TEST_LOB_TABLE', 'DOCUMENT', 'HIGH');

-- Verify LOB tablespace preserved
SELECT 'After Compression:' AS status,
       l.table_name,
       l.column_name,
       l.segment_name,
       l.tablespace_name,
       l.compression
FROM user_lobs l
WHERE l.table_name = 'TEST_LOB_TABLE';

-- Validation
DECLARE
  v_lob_tablespace VARCHAR2(128);
BEGIN
  SELECT tablespace_name INTO v_lob_tablespace
  FROM user_lobs
  WHERE table_name = 'TEST_LOB_TABLE' AND column_name = 'DOCUMENT';

  IF v_lob_tablespace = 'TS_TEST_LOB' THEN
    DBMS_OUTPUT.PUT_LINE('✓ TEST 4 PASSED: LOB tablespace preserved (TS_TEST_LOB)');
  ELSE
    DBMS_OUTPUT.PUT_LINE('✗ TEST 4 FAILED: LOB tablespace changed to ' || v_lob_tablespace);
  END IF;
END;
/

PROMPT

--------------------------------------------------------------------------------
-- TEST 5: Batch Partition Compression
--------------------------------------------------------------------------------
PROMPT ================================================================================
PROMPT TEST 5: Batch All Partitions Compression
PROMPT ================================================================================

-- Create another partitioned table
CREATE TABLE test_multi_partition (
  id NUMBER,
  partition_key DATE,
  data VARCHAR2(500)
)
PARTITION BY RANGE (partition_key) (
  PARTITION q1 VALUES LESS THAN (DATE '2024-04-01') TABLESPACE TS_TEST_PART1,
  PARTITION q2 VALUES LESS THAN (DATE '2024-07-01') TABLESPACE TS_TEST_PART2,
  PARTITION q3 VALUES LESS THAN (DATE '2024-10-01') TABLESPACE TS_TEST_PART1,
  PARTITION q4 VALUES LESS THAN (DATE '2025-01-01') TABLESPACE TS_TEST_PART2
);

-- Insert test data
BEGIN
  FOR i IN 1..1000 LOOP
    INSERT INTO test_multi_partition VALUES (
      i,
      DATE '2024-01-01' + MOD(i, 365),
      RPAD('Z', 500, 'Z')
    );
  END LOOP;
  COMMIT;
END;
/

-- Check all partition tablespaces before compression
SELECT 'Before Batch Compression:' AS status,
       partition_name,
       tablespace_name,
       compression
FROM user_tab_partitions
WHERE table_name = 'TEST_MULTI_PARTITION'
ORDER BY partition_position;

-- Compress all partitions (should preserve each partition's tablespace)
EXEC PKG_COMPRESSION_EXECUTOR.compress_all_partitions(USER, 'TEST_MULTI_PARTITION', 'OLTP', TRUE);

-- Verify all partition tablespaces preserved
SELECT 'After Batch Compression:' AS status,
       partition_name,
       tablespace_name,
       compression
FROM user_tab_partitions
WHERE table_name = 'TEST_MULTI_PARTITION'
ORDER BY partition_position;

-- Validation
DECLARE
  v_failed BOOLEAN := FALSE;
  v_count NUMBER := 0;
BEGIN
  FOR rec IN (
    SELECT partition_name, tablespace_name,
           CASE partition_name
             WHEN 'Q1' THEN 'TS_TEST_PART1'
             WHEN 'Q2' THEN 'TS_TEST_PART2'
             WHEN 'Q3' THEN 'TS_TEST_PART1'
             WHEN 'Q4' THEN 'TS_TEST_PART2'
           END AS expected_ts
    FROM user_tab_partitions
    WHERE table_name = 'TEST_MULTI_PARTITION'
  ) LOOP
    v_count := v_count + 1;
    IF rec.tablespace_name != rec.expected_ts THEN
      v_failed := TRUE;
      DBMS_OUTPUT.PUT_LINE('✗ Partition ' || rec.partition_name || ' in wrong tablespace: ' ||
                          rec.tablespace_name || ' (expected: ' || rec.expected_ts || ')');
    END IF;
  END LOOP;

  IF NOT v_failed THEN
    DBMS_OUTPUT.PUT_LINE('✓ TEST 5 PASSED: All ' || v_count || ' partition tablespaces preserved correctly');
  ELSE
    DBMS_OUTPUT.PUT_LINE('✗ TEST 5 FAILED: Some partition tablespaces were not preserved');
  END IF;
END;
/

PROMPT

--------------------------------------------------------------------------------
-- TEST SUMMARY
--------------------------------------------------------------------------------
PROMPT ================================================================================
PROMPT TEST SUMMARY
PROMPT ================================================================================
PROMPT
PROMPT All tests completed. Review results above:
PROMPT   TEST 1: Regular Table Tablespace Preservation
PROMPT   TEST 2: Index Tablespace Preservation
PROMPT   TEST 3: Partitioned Table Tablespace Preservation
PROMPT   TEST 4: LOB Tablespace Preservation
PROMPT   TEST 5: Batch All Partitions Compression
PROMPT
PROMPT ================================================================================

-- Query compression history
PROMPT
PROMPT Compression History:
SELECT history_id,
       object_name,
       object_type,
       compression_after,
       ROUND(size_before_bytes/1024/1024, 2) AS size_before_mb,
       ROUND(size_after_bytes/1024/1024, 2) AS size_after_mb,
       ROUND(compression_ratio, 2) AS ratio,
       status,
       TO_CHAR(start_time, 'YYYY-MM-DD HH24:MI:SS') AS start_time
FROM T_COMPRESSION_HISTORY
WHERE executed_by = USER
  AND start_time >= SYSDATE - 1
ORDER BY history_id DESC;

PROMPT

--------------------------------------------------------------------------------
-- CLEANUP (Optional - uncomment to cleanup test objects)
--------------------------------------------------------------------------------
/*
PROMPT Cleaning up test objects...
DROP TABLE test_regular_table PURGE;
DROP TABLE test_partitioned_table PURGE;
DROP TABLE test_lob_table PURGE;
DROP TABLE test_multi_partition PURGE;

DROP TABLESPACE TS_TEST_DATA INCLUDING CONTENTS AND DATAFILES;
DROP TABLESPACE TS_TEST_INDEX INCLUDING CONTENTS AND DATAFILES;
DROP TABLESPACE TS_TEST_LOB INCLUDING CONTENTS AND DATAFILES;
DROP TABLESPACE TS_TEST_PART1 INCLUDING CONTENTS AND DATAFILES;
DROP TABLESPACE TS_TEST_PART2 INCLUDING CONTENTS AND DATAFILES;

PROMPT Cleanup completed
*/

PROMPT
PROMPT ================================================================================
PROMPT Test script completed
PROMPT ================================================================================
