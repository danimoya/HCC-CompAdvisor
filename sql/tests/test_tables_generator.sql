/*******************************************************************************
 * Test Tables Generator for Compression Type Evaluation
 * Version: 1.0.0
 * Date: 2025-12-04
 *
 * DESCRIPTION:
 *   Generates realistic test tables optimized as candidates for each compression type.
 *   Each table is designed with data patterns that make it a good target for specific
 *   compression strategies.
 *
 * DATA VOLUME:
 *   ~52 Million total records across 8 tables
 *   ~20+ GB of test data for production-scale testing
 *   (10x scale from smaller test configurations)
 *
 * COMPRESSION TYPES DEMONSTRATED:
 *   - BASIC: General purpose, small to medium tables
 *   - OLTP: High write activity, low compression overhead
 *   - ADV_LOW: Query-optimized, moderate compression
 *   - ADV_HIGH: Query-optimized, aggressive compression
 *   - QUERY_LOW (HCC): Exadata query-optimized, low overhead
 *   - QUERY_HIGH (HCC): Exadata query-optimized, high compression
 *   - ARCHIVE_LOW (HCC): Exadata archival, high compression
 *   - ARCHIVE_HIGH (HCC): Exadata archival, maximum compression
 *
 * USAGE:
 *   @test_tables_generator.sql
 *   Or execute individual procedures:
 *   EXEC create_basic_compression_table;
 *   EXEC create_oltp_compression_table;
 *   etc.
 *
 ******************************************************************************/

SET DEFINE OFF
SET ECHO ON
SET FEEDBACK ON
SET SERVEROUTPUT ON SIZE UNLIMITED
SET LINESIZE 200

PROMPT ================================================================================
PROMPT Test Tables Generator for Compression Type Evaluation
PROMPT ================================================================================

-- ============================================================================
-- SECTION 1: PACKAGE SPECIFICATION
-- ============================================================================

PROMPT
PROMPT Creating test table generation package...

CREATE OR REPLACE PACKAGE PKG_TEST_TABLE_GENERATOR AS

  -- Package version
  C_VERSION CONSTANT VARCHAR2(10) := '1.0.0';

  -- Procedures to create test tables for each compression type

  /**
   * Create test table optimized for BASIC compression
   * Small to medium sized table with moderate repetition
   */
  PROCEDURE create_basic_compression_table;

  /**
   * Create test table optimized for OLTP compression
   * High write activity, frequent updates and inserts
   */
  PROCEDURE create_oltp_compression_table;

  /**
   * Create test table optimized for ADV_LOW (QUERY LOW) compression
   * Read-heavy, moderate data repetition, good for queries
   */
  PROCEDURE create_adv_low_compression_table;

  /**
   * Create test table optimized for ADV_HIGH (QUERY HIGH) compression
   * Read-heavy, high data repetition, aggressive compression
   */
  PROCEDURE create_adv_high_compression_table;

  /**
   * Create test table optimized for QUERY_LOW (HCC) compression
   * Exadata-optimized, query-heavy, balanced compression
   */
  PROCEDURE create_hcc_query_low_table;

  /**
   * Create test table optimized for QUERY_HIGH (HCC) compression
   * Exadata-optimized, query-heavy, high compression
   */
  PROCEDURE create_hcc_query_high_table;

  /**
   * Create test table optimized for ARCHIVE_LOW (HCC) compression
   * Exadata-optimized, archival data, high compression
   */
  PROCEDURE create_hcc_archive_low_table;

  /**
   * Create test table optimized for ARCHIVE_HIGH (HCC) compression
   * Exadata-optimized, archival data, maximum compression
   */
  PROCEDURE create_hcc_archive_high_table;

  /**
   * Create all test tables at once
   */
  PROCEDURE create_all_test_tables;

  /**
   * Drop all test tables
   */
  PROCEDURE drop_all_test_tables;

  /**
   * Report on test tables and their sizes
   */
  PROCEDURE report_test_tables;

END PKG_TEST_TABLE_GENERATOR;
/

-- ============================================================================
-- SECTION 2: PACKAGE BODY
-- ============================================================================

CREATE OR REPLACE PACKAGE BODY PKG_TEST_TABLE_GENERATOR AS

  -- Helper procedure to log messages
  PROCEDURE log_message(p_message IN VARCHAR2) IS
  BEGIN
    DBMS_OUTPUT.PUT_LINE('[' || TO_CHAR(SYSDATE, 'HH24:MI:SS') || '] ' || p_message);
  END log_message;

  -- ========================================================================
  -- 1. BASIC COMPRESSION TABLE (Small to Medium)
  -- ========================================================================
  PROCEDURE create_basic_compression_table IS
  BEGIN
    log_message('Creating TEST_BASIC_COMPRESSION table...');

    -- Drop if exists
    BEGIN
      EXECUTE IMMEDIATE 'DROP TABLE TEST_BASIC_COMPRESSION';
    EXCEPTION
      WHEN OTHERS THEN NULL;
    END;

    -- Create table
    EXECUTE IMMEDIATE 'CREATE TABLE TEST_BASIC_COMPRESSION (id NUMBER PRIMARY KEY, customer_id NUMBER NOT NULL, order_id NUMBER NOT NULL, product_code VARCHAR2(20), category VARCHAR2(30), order_date DATE, amount NUMBER(10,2), quantity NUMBER, status VARCHAR2(20), description VARCHAR2(500), created_date DATE DEFAULT SYSDATE, updated_date DATE DEFAULT SYSDATE)';

    -- Insert representative data (general purpose) using EXECUTE IMMEDIATE
    EXECUTE IMMEDIATE 'INSERT INTO TEST_BASIC_COMPRESSION SELECT ROWNUM as id, MOD(ROWNUM, 1000) + 1 as customer_id, MOD(ROWNUM, 500) + 1 as order_id, ''PROD'' || LPAD(MOD(ROWNUM, 100), 5, ''0'') as product_code, CASE MOD(ROWNUM, 5) WHEN 0 THEN ''Electronics'' WHEN 1 THEN ''Clothing'' WHEN 2 THEN ''Books'' WHEN 3 THEN ''Home'' ELSE ''Sports'' END as category, TRUNC(SYSDATE - MOD(ROWNUM, 365)) as order_date, ROUND(DBMS_RANDOM.VALUE(10, 1000), 2) as amount, TRUNC(DBMS_RANDOM.VALUE(1, 50)) as quantity, CASE MOD(ROWNUM, 4) WHEN 0 THEN ''PENDING'' WHEN 1 THEN ''SHIPPED'' WHEN 2 THEN ''DELIVERED'' ELSE ''CANCELLED'' END as status, ''Order for customer '' || MOD(ROWNUM, 1000) as description, TRUNC(SYSDATE - MOD(ROWNUM, 30)) as created_date, TRUNC(SYSDATE) as updated_date FROM dual CONNECT BY LEVEL <= 1000000';

    COMMIT;
    log_message('✓ TEST_BASIC_COMPRESSION table created with 1,000,000 rows');

  EXCEPTION
    WHEN OTHERS THEN
      log_message('✗ ERROR creating TEST_BASIC_COMPRESSION: ' || SQLERRM);
  END create_basic_compression_table;

  -- ========================================================================
  -- 2. OLTP COMPRESSION TABLE (High Write Activity)
  -- ========================================================================
  PROCEDURE create_oltp_compression_table IS
  BEGIN
    log_message('Creating TEST_OLTP_COMPRESSION table...');

    BEGIN
      EXECUTE IMMEDIATE 'DROP TABLE TEST_OLTP_COMPRESSION';
    EXCEPTION
      WHEN OTHERS THEN NULL;
    END;

    -- Create table optimized for OLTP (frequent updates/inserts)
    EXECUTE IMMEDIATE 'CREATE TABLE TEST_OLTP_COMPRESSION (transaction_id NUMBER PRIMARY KEY, user_id NUMBER NOT NULL, session_id VARCHAR2(50), transaction_type VARCHAR2(20), amount NUMBER(12,2), status VARCHAR2(20), transaction_time TIMESTAMP DEFAULT SYSTIMESTAMP, updated_time TIMESTAMP, notes VARCHAR2(200), error_code NUMBER, retry_count NUMBER DEFAULT 0)';

    -- Insert OLTP-style data (many similar short-lived records) using EXECUTE IMMEDIATE
    EXECUTE IMMEDIATE 'INSERT INTO TEST_OLTP_COMPRESSION SELECT ROWNUM as transaction_id, MOD(ROWNUM, 500) + 1 as user_id, ''SESSION_'' || LPAD(MOD(ROWNUM, 100), 5, ''0'') as session_id, CASE MOD(ROWNUM, 3) WHEN 0 THEN ''DEPOSIT'' WHEN 1 THEN ''WITHDRAWAL'' ELSE ''TRANSFER'' END as transaction_type, ROUND(DBMS_RANDOM.VALUE(100, 5000), 2) as amount, CASE MOD(ROWNUM, 2) WHEN 0 THEN ''COMPLETED'' ELSE ''PENDING'' END as status, SYSTIMESTAMP - NUMTODSINTERVAL(MOD(ROWNUM, 1440), ''MINUTE'') as transaction_time, SYSTIMESTAMP as updated_time, ''Transaction for user '' || MOD(ROWNUM, 500) as notes, CASE WHEN MOD(ROWNUM, 1000) = 0 THEN 1 ELSE NULL END as error_code, TRUNC(DBMS_RANDOM.VALUE(0, 3)) as retry_count FROM dual CONNECT BY LEVEL <= 2000000';

    COMMIT;
    log_message('✓ TEST_OLTP_COMPRESSION table created with 2,000,000 rows');

  EXCEPTION
    WHEN OTHERS THEN
      log_message('✗ ERROR creating TEST_OLTP_COMPRESSION: ' || SQLERRM);
  END create_oltp_compression_table;

  -- ========================================================================
  -- 3. ADV_LOW COMPRESSION TABLE (Query-Optimized, Moderate Compression)
  -- ========================================================================
  PROCEDURE create_adv_low_compression_table IS
  BEGIN
    log_message('Creating TEST_ADV_LOW_COMPRESSION table...');

    BEGIN
      EXECUTE IMMEDIATE 'DROP TABLE TEST_ADV_LOW_COMPRESSION';
    EXCEPTION
      WHEN OTHERS THEN NULL;
    END;

    EXECUTE IMMEDIATE 'CREATE TABLE TEST_ADV_LOW_COMPRESSION (record_id NUMBER PRIMARY KEY, region VARCHAR2(30), country VARCHAR2(50), city VARCHAR2(50), department VARCHAR2(50), employee_id NUMBER, employee_name VARCHAR2(100), salary NUMBER(10,2), hire_date DATE, performance VARCHAR2(20), skill_level VARCHAR2(20), project_code VARCHAR2(20), hours_logged NUMBER, billing_rate NUMBER(10,2), revenue NUMBER(12,2))';

    -- Insert data with good repetition (good for QUERY LOW) using batch inserts
    DECLARE
      v_batch_size CONSTANT NUMBER := 500000;
      v_total_rows CONSTANT NUMBER := 3000000;
      v_inserted NUMBER := 0;
      v_batch_num NUMBER := 0;
    BEGIN
      WHILE v_inserted < v_total_rows LOOP
        v_batch_num := v_batch_num + 1;
        EXECUTE IMMEDIATE 'INSERT INTO TEST_ADV_LOW_COMPRESSION SELECT ' || v_inserted || ' + ROWNUM as record_id, CASE MOD(' || v_inserted || ' + ROWNUM, 10) WHEN 0 THEN ''North America'' WHEN 1 THEN ''Europe'' WHEN 2 THEN ''Asia'' WHEN 3 THEN ''South America'' WHEN 4 THEN ''Africa'' WHEN 5 THEN ''Australia'' WHEN 6 THEN ''Middle East'' WHEN 7 THEN ''Central America'' WHEN 8 THEN ''Eastern Europe'' ELSE ''Southeast Asia'' END as region, CASE MOD(' || v_inserted || ' + ROWNUM, 50) WHEN 0 THEN ''United States'' WHEN 1 THEN ''Canada'' WHEN 2 THEN ''Mexico'' WHEN 3 THEN ''UK'' WHEN 4 THEN ''Germany'' WHEN 5 THEN ''France'' WHEN 6 THEN ''Japan'' WHEN 7 THEN ''China'' WHEN 8 THEN ''India'' WHEN 9 THEN ''Brazil'' ELSE ''Australia'' END as country, CASE MOD(' || v_inserted || ' + ROWNUM, 20) WHEN 0 THEN ''New York'' WHEN 1 THEN ''Los Angeles'' WHEN 2 THEN ''Chicago'' WHEN 3 THEN ''London'' WHEN 4 THEN ''Paris'' WHEN 5 THEN ''Tokyo'' WHEN 6 THEN ''Delhi'' WHEN 7 THEN ''Sao Paulo'' WHEN 8 THEN ''Toronto'' WHEN 9 THEN ''Sydney'' ELSE ''Singapore'' END as city, CASE MOD(' || v_inserted || ' + ROWNUM, 8) WHEN 0 THEN ''Sales'' WHEN 1 THEN ''Engineering'' WHEN 2 THEN ''Operations'' WHEN 3 THEN ''Finance'' WHEN 4 THEN ''Marketing'' WHEN 5 THEN ''HR'' WHEN 6 THEN ''Legal'' ELSE ''Support'' END as department, MOD(' || v_inserted || ' + ROWNUM, 1000) + 1 as employee_id, ''Employee '' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 1000), 5, ''0'') as employee_name, 50000 + ROUND(DBMS_RANDOM.VALUE(0, 100000), 2) as salary, TRUNC(SYSDATE - MOD(' || v_inserted || ' + ROWNUM, 3650)) as hire_date, CASE MOD(' || v_inserted || ' + ROWNUM, 5) WHEN 0 THEN ''Excellent'' WHEN 1 THEN ''Good'' WHEN 2 THEN ''Average'' WHEN 3 THEN ''Below Average'' ELSE ''Poor'' END as performance, CASE MOD(' || v_inserted || ' + ROWNUM, 4) WHEN 0 THEN ''Expert'' WHEN 1 THEN ''Advanced'' WHEN 2 THEN ''Intermediate'' ELSE ''Beginner'' END as skill_level, ''PROJ'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 100), 5, ''0'') as project_code, ROUND(DBMS_RANDOM.VALUE(10, 50), 1) as hours_logged, 150 + ROUND(DBMS_RANDOM.VALUE(0, 200), 2) as billing_rate, (ROUND(DBMS_RANDOM.VALUE(10, 50), 1) * (150 + ROUND(DBMS_RANDOM.VALUE(0, 200), 2))) as revenue FROM dual CONNECT BY LEVEL <= ' || LEAST(v_batch_size, v_total_rows - v_inserted);
        v_inserted := v_inserted + SQL%ROWCOUNT;
        COMMIT;
        log_message('  Batch ' || v_batch_num || ': Inserted ' || SQL%ROWCOUNT || ' rows (Total: ' || v_inserted || ')');
      END LOOP;
    END;

    COMMIT;
    log_message('✓ TEST_ADV_LOW_COMPRESSION table created with 3,000,000 rows');

  EXCEPTION
    WHEN OTHERS THEN
      log_message('✗ ERROR creating TEST_ADV_LOW_COMPRESSION: ' || SQLERRM);
  END create_adv_low_compression_table;

  -- ========================================================================
  -- 4. ADV_HIGH COMPRESSION TABLE (Query-Optimized, Aggressive Compression)
  -- ========================================================================
  PROCEDURE create_adv_high_compression_table IS
  BEGIN
    log_message('Creating TEST_ADV_HIGH_COMPRESSION table...');

    BEGIN
      EXECUTE IMMEDIATE 'DROP TABLE TEST_ADV_HIGH_COMPRESSION';
    EXCEPTION
      WHEN OTHERS THEN NULL;
    END;

    EXECUTE IMMEDIATE 'CREATE TABLE TEST_ADV_HIGH_COMPRESSION (event_id NUMBER PRIMARY KEY, event_type VARCHAR2(50), event_category VARCHAR2(50), event_status VARCHAR2(30), severity_level VARCHAR2(20), source_system VARCHAR2(50), source_location VARCHAR2(100), event_time TIMESTAMP, event_date DATE, description VARCHAR2(500), details VARCHAR2(1000), resolution VARCHAR2(500), tags VARCHAR2(200), metadata VARCHAR2(500))';

    -- Insert data with very high repetition (good for QUERY HIGH aggressive compression) using batch inserts
    DECLARE
      v_batch_size CONSTANT NUMBER := 500000;
      v_total_rows CONSTANT NUMBER := 5000000;
      v_inserted NUMBER := 0;
      v_batch_num NUMBER := 0;
    BEGIN
      WHILE v_inserted < v_total_rows LOOP
        v_batch_num := v_batch_num + 1;
        EXECUTE IMMEDIATE 'INSERT INTO TEST_ADV_HIGH_COMPRESSION SELECT ' || v_inserted || ' + ROWNUM as event_id, CASE MOD(' || v_inserted || ' + ROWNUM, 6) WHEN 0 THEN ''ERROR'' WHEN 1 THEN ''WARNING'' WHEN 2 THEN ''INFO'' WHEN 3 THEN ''DEBUG'' WHEN 4 THEN ''CRITICAL'' ELSE ''NOTICE'' END as event_type, CASE MOD(' || v_inserted || ' + ROWNUM, 5) WHEN 0 THEN ''Database'' WHEN 1 THEN ''Application'' WHEN 2 THEN ''Network'' WHEN 3 THEN ''System'' ELSE ''Security'' END as event_category, CASE MOD(' || v_inserted || ' + ROWNUM, 4) WHEN 0 THEN ''RESOLVED'' WHEN 1 THEN ''PENDING'' WHEN 2 THEN ''IN_PROGRESS'' ELSE ''CLOSED'' END as event_status, CASE MOD(' || v_inserted || ' + ROWNUM, 5) WHEN 0 THEN ''CRITICAL'' WHEN 1 THEN ''HIGH'' WHEN 2 THEN ''MEDIUM'' WHEN 3 THEN ''LOW'' ELSE ''INFO'' END as severity_level, CASE MOD(' || v_inserted || ' + ROWNUM, 8) WHEN 0 THEN ''APP_SERVER_01'' WHEN 1 THEN ''APP_SERVER_02'' WHEN 2 THEN ''DB_SERVER_01'' WHEN 3 THEN ''DB_SERVER_02'' WHEN 4 THEN ''WEB_SERVER_01'' WHEN 5 THEN ''CACHE_SERVER_01'' WHEN 6 THEN ''LOAD_BALANCER_01'' ELSE ''MONITORING_SERVER'' END as source_system, ''Location_'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 20), 3, ''0'') as source_location, SYSTIMESTAMP - NUMTODSINTERVAL(MOD(' || v_inserted || ' + ROWNUM, 87600), ''HOUR'') as event_time, TRUNC(SYSDATE - MOD(' || v_inserted || ' + ROWNUM, 730)) as event_date, ''Event description for record '' || (' || v_inserted || ' + ROWNUM) as description, ''Detailed information: System='' || MOD(' || v_inserted || ' + ROWNUM, 8) || '', Code='' || MOD(' || v_inserted || ' + ROWNUM, 1000) as details, CASE MOD(' || v_inserted || ' + ROWNUM, 5) WHEN 0 THEN ''Restarted service'' WHEN 1 THEN ''Cleared cache'' WHEN 2 THEN ''Applied patch'' WHEN 3 THEN ''Reconfigured system'' ELSE ''Escalated to team'' END as resolution, ''tag1,tag2,tag'' || MOD(' || v_inserted || ' + ROWNUM, 10) as tags, ''env='' || CASE MOD(' || v_inserted || ' + ROWNUM, 3) WHEN 0 THEN ''prod'' WHEN 1 THEN ''staging'' ELSE ''dev'' END || '',version=1.0,build='' || MOD(' || v_inserted || ' + ROWNUM, 100) as metadata FROM dual CONNECT BY LEVEL <= ' || LEAST(v_batch_size, v_total_rows - v_inserted);
        v_inserted := v_inserted + SQL%ROWCOUNT;
        COMMIT;
        log_message('  Batch ' || v_batch_num || ': Inserted ' || SQL%ROWCOUNT || ' rows (Total: ' || v_inserted || ')');
      END LOOP;
    END;

    COMMIT;
    log_message('✓ TEST_ADV_HIGH_COMPRESSION table created with 5,000,000 rows');

  EXCEPTION
    WHEN OTHERS THEN
      log_message('✗ ERROR creating TEST_ADV_HIGH_COMPRESSION: ' || SQLERRM);
  END create_adv_high_compression_table;

  -- ========================================================================
  -- 5. HCC QUERY_LOW TABLE (Exadata-Optimized, Query-Heavy)
  -- ========================================================================
  PROCEDURE create_hcc_query_low_table IS
  BEGIN
    log_message('Creating TEST_HCC_QUERY_LOW table...');

    BEGIN
      EXECUTE IMMEDIATE 'DROP TABLE TEST_HCC_QUERY_LOW';
    EXCEPTION
      WHEN OTHERS THEN NULL;
    END;

    EXECUTE IMMEDIATE 'CREATE TABLE TEST_HCC_QUERY_LOW (transaction_id NUMBER PRIMARY KEY, customer_id NUMBER NOT NULL, order_id NUMBER NOT NULL, sku VARCHAR2(30), product_line VARCHAR2(50), channel VARCHAR2(30), store_id NUMBER, warehouse_id NUMBER, quantity_sold NUMBER, unit_price NUMBER(10,2), sale_amount NUMBER(12,2), cost_amount NUMBER(12,2), margin_percent NUMBER(5,2), transaction_date DATE, region VARCHAR2(50), country VARCHAR2(50), customer_segment VARCHAR2(30), payment_method VARCHAR2(20), promo_code VARCHAR2(20), discount_applied NUMBER(5,2))';

    -- Insert large volume of query-optimized data (good for QUERY LOW HCC) using batch inserts
    DECLARE
      v_batch_size CONSTANT NUMBER := 500000;
      v_total_rows CONSTANT NUMBER := 10000000;
      v_inserted NUMBER := 0;
      v_batch_num NUMBER := 0;
    BEGIN
      WHILE v_inserted < v_total_rows LOOP
        v_batch_num := v_batch_num + 1;
        EXECUTE IMMEDIATE 'INSERT INTO TEST_HCC_QUERY_LOW SELECT ' || v_inserted || ' + ROWNUM as transaction_id, MOD(' || v_inserted || ' + ROWNUM, 5000) + 1 as customer_id, MOD(' || v_inserted || ' + ROWNUM, 2000) + 1 as order_id, ''SKU'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 500), 5, ''0'') as sku, CASE MOD(' || v_inserted || ' + ROWNUM, 10) WHEN 0 THEN ''Electronics'' WHEN 1 THEN ''Clothing'' WHEN 2 THEN ''Home & Garden'' WHEN 3 THEN ''Sports'' WHEN 4 THEN ''Books'' WHEN 5 THEN ''Toys'' WHEN 6 THEN ''Beauty'' WHEN 7 THEN ''Health'' WHEN 8 THEN ''Food'' ELSE ''Other'' END as product_line, CASE MOD(' || v_inserted || ' + ROWNUM, 5) WHEN 0 THEN ''Online'' WHEN 1 THEN ''Retail'' WHEN 2 THEN ''Wholesale'' WHEN 3 THEN ''Direct'' ELSE ''Partner'' END as channel, MOD(' || v_inserted || ' + ROWNUM, 100) + 1 as store_id, MOD(' || v_inserted || ' + ROWNUM, 50) + 1 as warehouse_id, TRUNC(DBMS_RANDOM.VALUE(1, 100)) as quantity_sold, ROUND(DBMS_RANDOM.VALUE(10, 1000), 2) as unit_price, TRUNC(DBMS_RANDOM.VALUE(1, 100)) * ROUND(DBMS_RANDOM.VALUE(10, 1000), 2) as sale_amount, ROUND(DBMS_RANDOM.VALUE(5, 500), 2) as cost_amount, ROUND(DBMS_RANDOM.VALUE(10, 50), 2) as margin_percent, TRUNC(SYSDATE - MOD(' || v_inserted || ' + ROWNUM, 730)) as transaction_date, CASE MOD(' || v_inserted || ' + ROWNUM, 7) WHEN 0 THEN ''North America'' WHEN 1 THEN ''Europe'' WHEN 2 THEN ''Asia Pacific'' WHEN 3 THEN ''Latin America'' WHEN 4 THEN ''Middle East'' WHEN 5 THEN ''Africa'' ELSE ''Oceania'' END as region, CASE MOD(' || v_inserted || ' + ROWNUM, 50) WHEN 0 THEN ''USA'' WHEN 1 THEN ''Canada'' WHEN 2 THEN ''Mexico'' WHEN 3 THEN ''UK'' WHEN 4 THEN ''Germany'' WHEN 5 THEN ''Japan'' WHEN 6 THEN ''China'' WHEN 7 THEN ''India'' WHEN 8 THEN ''Brazil'' ELSE ''Other'' END as country, CASE MOD(' || v_inserted || ' + ROWNUM, 4) WHEN 0 THEN ''Premium'' WHEN 1 THEN ''Standard'' WHEN 2 THEN ''Economy'' ELSE ''VIP'' END as customer_segment, CASE MOD(' || v_inserted || ' + ROWNUM, 6) WHEN 0 THEN ''Credit Card'' WHEN 1 THEN ''Debit Card'' WHEN 2 THEN ''PayPal'' WHEN 3 THEN ''Bank Transfer'' WHEN 4 THEN ''Check'' ELSE ''Cash'' END as payment_method, CASE WHEN MOD(' || v_inserted || ' + ROWNUM, 20) = 0 THEN ''SUMMER20'' ELSE NULL END as promo_code, CASE WHEN MOD(' || v_inserted || ' + ROWNUM, 20) = 0 THEN 20 ELSE 0 END as discount_applied FROM dual CONNECT BY LEVEL <= ' || LEAST(v_batch_size, v_total_rows - v_inserted);
        v_inserted := v_inserted + SQL%ROWCOUNT;
        COMMIT;
        log_message('  Batch ' || v_batch_num || ': Inserted ' || SQL%ROWCOUNT || ' rows (Total: ' || v_inserted || ')');
      END LOOP;
    END;

    COMMIT;
    log_message('✓ TEST_HCC_QUERY_LOW table created with 10,000,000 rows');

  EXCEPTION
    WHEN OTHERS THEN
      log_message('✗ ERROR creating TEST_HCC_QUERY_LOW: ' || SQLERRM);
  END create_hcc_query_low_table;

  -- ========================================================================
  -- 6. HCC QUERY_HIGH TABLE (Exadata, Query-Heavy, High Compression)
  -- ========================================================================
  PROCEDURE create_hcc_query_high_table IS
  BEGIN
    log_message('Creating TEST_HCC_QUERY_HIGH table...');

    BEGIN
      EXECUTE IMMEDIATE 'DROP TABLE TEST_HCC_QUERY_HIGH';
    EXCEPTION
      WHEN OTHERS THEN NULL;
    END;

    EXECUTE IMMEDIATE 'CREATE TABLE TEST_HCC_QUERY_HIGH (log_id NUMBER PRIMARY KEY, timestamp TIMESTAMP, log_date DATE, log_time VARCHAR2(20), server_name VARCHAR2(50), service_name VARCHAR2(50), process_id NUMBER, thread_id NUMBER, log_level VARCHAR2(20), log_message VARCHAR2(500), error_code VARCHAR2(20), error_message VARCHAR2(500), stack_trace VARCHAR2(1000), user_id VARCHAR2(50), session_id VARCHAR2(50), request_id VARCHAR2(50), correlation_id VARCHAR2(50), environment VARCHAR2(20), version VARCHAR2(30), component VARCHAR2(100))';

    -- Insert high-volume repetitive log data (good for QUERY HIGH HCC) using batch inserts
    DECLARE
      v_batch_size CONSTANT NUMBER := 500000;
      v_total_rows CONSTANT NUMBER := 20000000;
      v_inserted NUMBER := 0;
      v_batch_num NUMBER := 0;
    BEGIN
      WHILE v_inserted < v_total_rows LOOP
        v_batch_num := v_batch_num + 1;
        EXECUTE IMMEDIATE 'INSERT INTO TEST_HCC_QUERY_HIGH SELECT ' || v_inserted || ' + ROWNUM as log_id, SYSTIMESTAMP - NUMTODSINTERVAL(MOD(' || v_inserted || ' + ROWNUM, 1440), ''MINUTE'') as timestamp, TRUNC(SYSDATE - MOD(' || v_inserted || ' + ROWNUM, 30)) as log_date, LPAD(TRUNC(MOD(' || v_inserted || ' + ROWNUM, 1440) / 60), 2, ''0'') || '':'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 60), 2, ''0'') as log_time, CASE MOD(' || v_inserted || ' + ROWNUM, 20) WHEN 0 THEN ''SERVER_PROD_01'' WHEN 1 THEN ''SERVER_PROD_02'' WHEN 2 THEN ''SERVER_PROD_03'' WHEN 3 THEN ''SERVER_STAGE_01'' WHEN 4 THEN ''SERVER_DEV_01'' ELSE ''SERVER_LOAD_'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 10), 2, ''0'') END as server_name, CASE MOD(' || v_inserted || ' + ROWNUM, 10) WHEN 0 THEN ''DATABASE'' WHEN 1 THEN ''APPLICATION'' WHEN 2 THEN ''WEB_SERVER'' WHEN 3 THEN ''API_SERVER'' WHEN 4 THEN ''CACHE'' WHEN 5 THEN ''QUEUE'' WHEN 6 THEN ''SCHEDULER'' WHEN 7 THEN ''MONITOR'' WHEN 8 THEN ''SECURITY'' ELSE ''OTHER'' END as service_name, TRUNC(DBMS_RANDOM.VALUE(1, 10000)) as process_id, TRUNC(DBMS_RANDOM.VALUE(1, 1000)) as thread_id, CASE MOD(' || v_inserted || ' + ROWNUM, 6) WHEN 0 THEN ''DEBUG'' WHEN 1 THEN ''INFO'' WHEN 2 THEN ''WARN'' WHEN 3 THEN ''ERROR'' WHEN 4 THEN ''FATAL'' ELSE ''TRACE'' END as log_level, ''Log entry for process '' || TRUNC(DBMS_RANDOM.VALUE(1, 10000)) as log_message, CASE WHEN MOD(' || v_inserted || ' + ROWNUM, 100) < 5 THEN ''ERR_'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 100), 3, ''0'') ELSE NULL END as error_code, CASE WHEN MOD(' || v_inserted || ' + ROWNUM, 100) < 5 THEN ''Error occurred in module X'' ELSE NULL END as error_message, CASE WHEN MOD(' || v_inserted || ' + ROWNUM, 100) < 5 THEN ''at module.function:'' || MOD(' || v_inserted || ' + ROWNUM, 1000) ELSE NULL END as stack_trace, ''USER_'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 1000), 5, ''0'') as user_id, ''SESSION_'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 5000), 5, ''0'') as session_id, ''REQ_'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 10000), 8, ''0'') as request_id, ''CORR_'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 1000), 5, ''0'') as correlation_id, CASE MOD(' || v_inserted || ' + ROWNUM, 3) WHEN 0 THEN ''PRODUCTION'' WHEN 1 THEN ''STAGING'' ELSE ''DEVELOPMENT'' END as environment, ''2.0.'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 100), 2, ''0'') as version, CASE MOD(' || v_inserted || ' + ROWNUM, 5) WHEN 0 THEN ''com.company.app.core'' WHEN 1 THEN ''com.company.app.service'' WHEN 2 THEN ''com.company.app.dao'' WHEN 3 THEN ''com.company.app.util'' ELSE ''com.company.app.web'' END as component FROM dual CONNECT BY LEVEL <= ' || LEAST(v_batch_size, v_total_rows - v_inserted);
        v_inserted := v_inserted + SQL%ROWCOUNT;
        COMMIT;
        log_message('  Batch ' || v_batch_num || ': Inserted ' || SQL%ROWCOUNT || ' rows (Total: ' || v_inserted || ')');
      END LOOP;
    END;

    COMMIT;
    log_message('✓ TEST_HCC_QUERY_HIGH table created with 20,000,000 rows');

  EXCEPTION
    WHEN OTHERS THEN
      log_message('✗ ERROR creating TEST_HCC_QUERY_HIGH: ' || SQLERRM);
  END create_hcc_query_high_table;

  -- ========================================================================
  -- 7. HCC ARCHIVE_LOW TABLE (Archival Data, High Compression)
  -- ========================================================================
  PROCEDURE create_hcc_archive_low_table IS
  BEGIN
    log_message('Creating TEST_HCC_ARCHIVE_LOW table...');

    BEGIN
      EXECUTE IMMEDIATE 'DROP TABLE TEST_HCC_ARCHIVE_LOW';
    EXCEPTION
      WHEN OTHERS THEN NULL;
    END;

    EXECUTE IMMEDIATE 'CREATE TABLE TEST_HCC_ARCHIVE_LOW (archive_id NUMBER PRIMARY KEY, fiscal_year NUMBER, fiscal_quarter VARCHAR2(3), fiscal_month NUMBER, quarter_name VARCHAR2(20), month_name VARCHAR2(20), date_key DATE, region VARCHAR2(50), country VARCHAR2(50), state VARCHAR2(50), city VARCHAR2(50), customer_type VARCHAR2(30), product_category VARCHAR2(50), revenue NUMBER(12,2), cost NUMBER(12,2), gross_profit NUMBER(12,2), units_sold NUMBER(10), avg_price NUMBER(10,2), market_share NUMBER(5,2), growth_rate NUMBER(5,2), status VARCHAR2(20), archive_date DATE, created_by VARCHAR2(50), notes VARCHAR2(500))';

    -- Insert historical/archival data (good for ARCHIVE LOW HCC) using batch inserts
    DECLARE
      v_batch_size CONSTANT NUMBER := 500000;
      v_total_rows CONSTANT NUMBER := 5000000;
      v_inserted NUMBER := 0;
      v_batch_num NUMBER := 0;
    BEGIN
      WHILE v_inserted < v_total_rows LOOP
        v_batch_num := v_batch_num + 1;
        EXECUTE IMMEDIATE 'INSERT INTO TEST_HCC_ARCHIVE_LOW SELECT ' || v_inserted || ' + ROWNUM as archive_id, 2000 + TRUNC((' || v_inserted || ' + ROWNUM - 1) / 100000) as fiscal_year, ''Q'' || (MOD((' || v_inserted || ' + ROWNUM - 1), 4) + 1) as fiscal_quarter, MOD((' || v_inserted || ' + ROWNUM - 1), 12) + 1 as fiscal_month, CASE MOD((' || v_inserted || ' + ROWNUM - 1), 4) + 1 WHEN 1 THEN ''Q1 - Jan/Feb/Mar'' WHEN 2 THEN ''Q2 - Apr/May/Jun'' WHEN 3 THEN ''Q3 - Jul/Aug/Sep'' ELSE ''Q4 - Oct/Nov/Dec'' END as quarter_name, CASE MOD((' || v_inserted || ' + ROWNUM - 1), 12) + 1 WHEN 1 THEN ''January'' WHEN 2 THEN ''February'' WHEN 3 THEN ''March'' WHEN 4 THEN ''April'' WHEN 5 THEN ''May'' WHEN 6 THEN ''June'' WHEN 7 THEN ''July'' WHEN 8 THEN ''August'' WHEN 9 THEN ''September'' WHEN 10 THEN ''October'' WHEN 11 THEN ''November'' ELSE ''December'' END as month_name, TRUNC(SYSDATE - MOD(' || v_inserted || ' + ROWNUM, 7300)) as date_key, CASE MOD(' || v_inserted || ' + ROWNUM, 7) WHEN 0 THEN ''North America'' WHEN 1 THEN ''Europe'' WHEN 2 THEN ''Asia'' WHEN 3 THEN ''Latin America'' WHEN 4 THEN ''Africa'' WHEN 5 THEN ''Middle East'' ELSE ''Oceania'' END as region, CASE MOD(' || v_inserted || ' + ROWNUM, 50) WHEN 0 THEN ''USA'' WHEN 1 THEN ''Canada'' WHEN 2 THEN ''UK'' WHEN 3 THEN ''Germany'' WHEN 4 THEN ''France'' WHEN 5 THEN ''Japan'' WHEN 6 THEN ''China'' WHEN 7 THEN ''India'' WHEN 8 THEN ''Brazil'' ELSE ''Other'' END as country, CASE MOD(' || v_inserted || ' + ROWNUM, 10) WHEN 0 THEN ''CA'' WHEN 1 THEN ''NY'' WHEN 2 THEN ''TX'' ELSE ''Other'' END as state, CASE MOD(' || v_inserted || ' + ROWNUM, 20) WHEN 0 THEN ''New York'' WHEN 1 THEN ''Los Angeles'' WHEN 2 THEN ''Chicago'' WHEN 3 THEN ''Houston'' WHEN 4 THEN ''Phoenix'' ELSE ''Other City'' END as city, CASE MOD(' || v_inserted || ' + ROWNUM, 3) WHEN 0 THEN ''Consumer'' WHEN 1 THEN ''Enterprise'' ELSE ''Government'' END as customer_type, CASE MOD(' || v_inserted || ' + ROWNUM, 8) WHEN 0 THEN ''Electronics'' WHEN 1 THEN ''Clothing'' WHEN 2 THEN ''Food'' WHEN 3 THEN ''Furniture'' WHEN 4 THEN ''Appliances'' WHEN 5 THEN ''Beauty'' WHEN 6 THEN ''Books'' ELSE ''Other'' END as product_category, ROUND(DBMS_RANDOM.VALUE(100000, 10000000), 2) as revenue, ROUND(DBMS_RANDOM.VALUE(50000, 5000000), 2) as cost, ROUND(DBMS_RANDOM.VALUE(50000, 5000000), 2) as gross_profit, TRUNC(DBMS_RANDOM.VALUE(1000, 100000)) as units_sold, ROUND(DBMS_RANDOM.VALUE(10, 1000), 2) as avg_price, ROUND(DBMS_RANDOM.VALUE(5, 30), 2) as market_share, ROUND(DBMS_RANDOM.VALUE(-10, 25), 2) as growth_rate, ''ARCHIVED'' as status, TRUNC(SYSDATE - MOD(' || v_inserted || ' + ROWNUM, 3650)) as archive_date, ''BATCH_LOADER'' as created_by, ''Historical data for archive '' || (' || v_inserted || ' + ROWNUM) as notes FROM dual CONNECT BY LEVEL <= ' || LEAST(v_batch_size, v_total_rows - v_inserted);
        v_inserted := v_inserted + SQL%ROWCOUNT;
        COMMIT;
        log_message('  Batch ' || v_batch_num || ': Inserted ' || SQL%ROWCOUNT || ' rows (Total: ' || v_inserted || ')');
      END LOOP;
    END;

    COMMIT;
    log_message('✓ TEST_HCC_ARCHIVE_LOW table created with 5,000,000 rows');

  EXCEPTION
    WHEN OTHERS THEN
      log_message('✗ ERROR creating TEST_HCC_ARCHIVE_LOW: ' || SQLERRM);
  END create_hcc_archive_low_table;

  -- ========================================================================
  -- 8. HCC ARCHIVE_HIGH TABLE (Archival Data, Maximum Compression)
  -- ========================================================================
  PROCEDURE create_hcc_archive_high_table IS
  BEGIN
    log_message('Creating TEST_HCC_ARCHIVE_HIGH table...');

    BEGIN
      EXECUTE IMMEDIATE 'DROP TABLE TEST_HCC_ARCHIVE_HIGH';
    EXCEPTION
      WHEN OTHERS THEN NULL;
    END;

    EXECUTE IMMEDIATE 'CREATE TABLE TEST_HCC_ARCHIVE_HIGH (record_id NUMBER PRIMARY KEY, year_month VARCHAR2(7), year NUMBER, month NUMBER, week_num NUMBER, day_num NUMBER, record_date DATE, source_system VARCHAR2(50), data_type VARCHAR2(30), status VARCHAR2(20), severity VARCHAR2(20), priority NUMBER, assigned_to VARCHAR2(50), department VARCHAR2(50), cost_center VARCHAR2(20), project_id VARCHAR2(20), budget_code VARCHAR2(20), amount NUMBER(12,2), currency VARCHAR2(3), description VARCHAR2(500), long_description CLOB, reference_id VARCHAR2(50), related_items VARCHAR2(500), comments VARCHAR2(500), approval_status VARCHAR2(20), approved_by VARCHAR2(50), approval_date DATE, effective_date DATE, expiry_date DATE, last_modified DATE)';

    -- Insert massive archival dataset with high repetition (good for ARCHIVE HIGH HCC) using batch inserts
    DECLARE
      v_batch_size CONSTANT NUMBER := 500000;
      v_total_rows CONSTANT NUMBER := 10000000;
      v_inserted NUMBER := 0;
      v_batch_num NUMBER := 0;
    BEGIN
      WHILE v_inserted < v_total_rows LOOP
        v_batch_num := v_batch_num + 1;
        EXECUTE IMMEDIATE 'INSERT INTO TEST_HCC_ARCHIVE_HIGH SELECT ' || v_inserted || ' + ROWNUM as record_id, TO_CHAR(TRUNC(SYSDATE - MOD(' || v_inserted || ' + ROWNUM, 7300)), ''YYYY-MM'') as year_month, 2000 + TRUNC((' || v_inserted || ' + ROWNUM - 1) / 100000) as year, MOD((' || v_inserted || ' + ROWNUM - 1), 12) + 1 as month, TRUNC(MOD((' || v_inserted || ' + ROWNUM - 1), 52)) + 1 as week_num, TRUNC(MOD((' || v_inserted || ' + ROWNUM - 1), 365)) + 1 as day_num, TRUNC(SYSDATE - MOD(' || v_inserted || ' + ROWNUM, 7300)) as record_date, CASE MOD(' || v_inserted || ' + ROWNUM, 20) WHEN 0 THEN ''LEGACY_SYSTEM_01'' WHEN 1 THEN ''LEGACY_SYSTEM_02'' WHEN 2 THEN ''ERP_SYSTEM'' WHEN 3 THEN ''CRM_SYSTEM'' WHEN 4 THEN ''DW_SYSTEM'' ELSE ''ARCHIVE_SYSTEM'' END as source_system, CASE MOD(' || v_inserted || ' + ROWNUM, 8) WHEN 0 THEN ''TRANSACTION'' WHEN 1 THEN ''INVOICE'' WHEN 2 THEN ''PAYMENT'' WHEN 3 THEN ''JOURNAL'' WHEN 4 THEN ''REPORT'' WHEN 5 THEN ''AUDIT'' WHEN 6 THEN ''LOG'' ELSE ''OTHER'' END as data_type, CASE MOD(' || v_inserted || ' + ROWNUM, 5) WHEN 0 THEN ''ACTIVE'' WHEN 1 THEN ''ARCHIVED'' WHEN 2 THEN ''OBSOLETE'' WHEN 3 THEN ''DELETED'' ELSE ''RETAINED'' END as status, CASE MOD(' || v_inserted || ' + ROWNUM, 6) WHEN 0 THEN ''CRITICAL'' WHEN 1 THEN ''HIGH'' WHEN 2 THEN ''MEDIUM'' WHEN 3 THEN ''LOW'' WHEN 4 THEN ''INFO'' ELSE ''DEBUG'' END as severity, TRUNC(DBMS_RANDOM.VALUE(1, 5)) as priority, ''USER_'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 50), 3, ''0'') as assigned_to, CASE MOD(' || v_inserted || ' + ROWNUM, 10) WHEN 0 THEN ''Finance'' WHEN 1 THEN ''Operations'' WHEN 2 THEN ''Sales'' WHEN 3 THEN ''IT'' WHEN 4 THEN ''HR'' WHEN 5 THEN ''Legal'' WHEN 6 THEN ''Compliance'' WHEN 7 THEN ''Audit'' WHEN 8 THEN ''Archive'' ELSE ''General'' END as department, ''CC'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 100), 4, ''0'') as cost_center, ''PROJ'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 1000), 5, ''0'') as project_id, ''BDG'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 100), 4, ''0'') as budget_code, ROUND(DBMS_RANDOM.VALUE(100, 100000), 2) as amount, CASE MOD(' || v_inserted || ' + ROWNUM, 5) WHEN 0 THEN ''EUR'' WHEN 1 THEN ''GBP'' WHEN 2 THEN ''JPY'' ELSE ''USD'' END as currency, ''Archived record description '' || (' || v_inserted || ' + ROWNUM) as description, ''Long form description for archival record number '' || (' || v_inserted || ' + ROWNUM) || '' containing detailed information about the transaction, including context, notes, and supplementary details for compliance and audit purposes.'' as long_description, ''REF'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 100000), 6, ''0'') as reference_id, ''ITEM_'' || LPAD(MOD(' || v_inserted || ' + ROWNUM, 100), 4, ''0'') || '','' || ''ITEM_'' || LPAD(MOD(' || v_inserted || ' + ROWNUM + 1, 100), 4, ''0'') as related_items, ''Archived on '' || TO_CHAR(SYSDATE, ''YYYY-MM-DD'') as comments, CASE MOD(' || v_inserted || ' + ROWNUM, 4) WHEN 0 THEN ''APPROVED'' ELSE ''ARCHIVED'' END as approval_status, ''ADMIN'' as approved_by, TRUNC(SYSDATE - MOD(' || v_inserted || ' + ROWNUM, 3650)) as approval_date, TRUNC(SYSDATE - MOD(' || v_inserted || ' + ROWNUM, 3650)) as effective_date, TRUNC(SYSDATE - MOD(' || v_inserted || ' + ROWNUM, 3600)) + 365 as expiry_date, TRUNC(SYSDATE - MOD(' || v_inserted || ' + ROWNUM, 30)) as last_modified FROM dual CONNECT BY LEVEL <= ' || LEAST(v_batch_size, v_total_rows - v_inserted);
        v_inserted := v_inserted + SQL%ROWCOUNT;
        COMMIT;
        log_message('  Batch ' || v_batch_num || ': Inserted ' || SQL%ROWCOUNT || ' rows (Total: ' || v_inserted || ')');
      END LOOP;
    END;

    COMMIT;
    log_message('✓ TEST_HCC_ARCHIVE_HIGH table created with 10,000,000 rows');

  EXCEPTION
    WHEN OTHERS THEN
      log_message('✗ ERROR creating TEST_HCC_ARCHIVE_HIGH: ' || SQLERRM);
  END create_hcc_archive_high_table;

  -- ========================================================================
  -- Create All Tables
  -- ========================================================================
  PROCEDURE create_all_test_tables IS
  BEGIN
    log_message('=== Creating All Test Tables ===');
    create_basic_compression_table;
    create_oltp_compression_table;
    create_adv_low_compression_table;
    create_adv_high_compression_table;
    create_hcc_query_low_table;
    create_hcc_query_high_table;
    create_hcc_archive_low_table;
    create_hcc_archive_high_table;
    log_message('=== All Test Tables Created Successfully ===');
  END create_all_test_tables;

  -- ========================================================================
  -- Drop All Tables
  -- ========================================================================
  PROCEDURE drop_all_test_tables IS
    TYPE table_name_table IS TABLE OF VARCHAR2(50);
    v_tables table_name_table := table_name_table(
      'TEST_BASIC_COMPRESSION', 'TEST_OLTP_COMPRESSION', 'TEST_ADV_LOW_COMPRESSION',
      'TEST_ADV_HIGH_COMPRESSION', 'TEST_HCC_QUERY_LOW', 'TEST_HCC_QUERY_HIGH',
      'TEST_HCC_ARCHIVE_LOW', 'TEST_HCC_ARCHIVE_HIGH'
    );
  BEGIN
    log_message('=== Dropping All Test Tables ===');

    FOR i IN 1 .. v_tables.COUNT LOOP
      BEGIN
        EXECUTE IMMEDIATE 'DROP TABLE ' || v_tables(i);
        log_message('✓ Dropped ' || v_tables(i));
      EXCEPTION
        WHEN OTHERS THEN
          log_message('! ' || v_tables(i) || ' not found (OK)');
      END;
    END LOOP;

    log_message('=== All Test Tables Dropped ===');
  END drop_all_test_tables;

  -- ========================================================================
  -- Report on Test Tables
  -- ========================================================================
  PROCEDURE report_test_tables IS
    v_owner VARCHAR2(30) := USER;
  BEGIN
    log_message('=== Test Tables Size Report ===');
    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE(RPAD('Table Name', 40) || RPAD('Rows', 15) || RPAD('Size (MB)', 15));
    DBMS_OUTPUT.PUT_LINE(RPAD('-', 40, '-') || RPAD('-', 15, '-') || RPAD('-', 15, '-'));

    FOR rec IN (
      SELECT table_name, num_rows,
             ROUND((blocks * 8192 / 1024 / 1024), 2) as size_mb
      FROM user_tables
      WHERE table_name LIKE 'TEST_%'
      ORDER BY table_name
    ) LOOP
      DBMS_OUTPUT.PUT_LINE(RPAD(rec.table_name, 40) ||
                          RPAD(NVL(rec.num_rows, 0), 15) ||
                          RPAD(NVL(rec.size_mb, 0), 15));
    END LOOP;

    DBMS_OUTPUT.PUT_LINE('');
    DECLARE
      v_total_size NUMBER;
    BEGIN
      SELECT ROUND(SUM(blocks * 8192 / 1024 / 1024), 2)
      INTO v_total_size
      FROM user_tables
      WHERE table_name LIKE 'TEST_%';
      DBMS_OUTPUT.PUT_LINE('Total size: ' || NVL(v_total_size, 0) || ' MB');
    END;
  END report_test_tables;

BEGIN
  -- Initialization
  NULL;
END PKG_TEST_TABLE_GENERATOR;
/

-- ============================================================================
-- SECTION 3: EXECUTION
-- ============================================================================

PROMPT
PROMPT ================================================================================
PROMPT Executing Test Table Generation
PROMPT ================================================================================

-- Create all test tables
BEGIN
  PKG_TEST_TABLE_GENERATOR.create_all_test_tables;
END;
/

-- Report on created tables
BEGIN
  PKG_TEST_TABLE_GENERATOR.report_test_tables;
END;
/

PROMPT
PROMPT ================================================================================
PROMPT Test Tables Created Successfully!
PROMPT ================================================================================
PROMPT
PROMPT Test Tables Summary:
PROMPT   1. TEST_BASIC_COMPRESSION (1M) - BASIC
PROMPT   2. TEST_OLTP_COMPRESSION (2M) - OLTP
PROMPT   3. TEST_ADV_LOW_COMPRESSION (3M) - QUERY LOW
PROMPT   4. TEST_ADV_HIGH_COMPRESSION (5M) - QUERY HIGH
PROMPT   5. TEST_HCC_QUERY_LOW (10M) - HCC QUERY LOW (Exadata)
PROMPT   6. TEST_HCC_QUERY_HIGH (20M) - HCC QUERY HIGH (Exadata)
PROMPT   7. TEST_HCC_ARCHIVE_LOW (5M) - HCC ARCHIVE LOW (Exadata)
PROMPT   8. TEST_HCC_ARCHIVE_HIGH (10M) - HCC ARCHIVE HIGH (Exadata)
PROMPT
PROMPT Total: ~52 Million Records / ~15+ GB test data
PROMPT
PROMPT Next steps:
PROMPT   EXEC PKG_COMPRESSION_ADVISOR.run_analysis;
PROMPT   EXEC PKG_COMPRESSION_EXECUTOR.compress_table('&OWNER', 'TEST_TABLE_NAME', 'COMPRESSION_TYPE');
PROMPT   EXEC PKG_TEST_TABLE_GENERATOR.drop_all_test_tables;
PROMPT
PROMPT ================================================================================

SET ECHO OFF
SET DEFINE ON
