-- ============================================================================
-- Script: 04-generate-testdata.sql
-- Description: Generate ~1GB of realistic test data for compression analysis
-- Database: Oracle 23c Free Edition (Target Test Database)
--
-- Tables created (~1GB total):
--   1. SALES_TRANSACTIONS  (2M rows, ~400MB) - OLTP-style, high DML
--   2. SENSOR_READINGS     (3M rows, ~350MB) - Time-series IoT data
--   3. AUDIT_LOG           (2M rows, ~250MB) - Archival log data, high repetition
--   4. CUSTOMER_ACCOUNTS   (500K rows, ~80MB) - Master data, low change rate
-- ============================================================================

SET ECHO ON
SET SERVEROUTPUT ON SIZE UNLIMITED
SET TIMING ON

PROMPT ========================================
PROMPT Generating ~1GB Test Data
PROMPT ========================================

-- ============================================================================
-- Table 1: SALES_TRANSACTIONS (~400MB, OLTP candidate)
-- ============================================================================

PROMPT Creating SALES_TRANSACTIONS...

BEGIN EXECUTE IMMEDIATE 'DROP TABLE SALES_TRANSACTIONS PURGE'; EXCEPTION WHEN OTHERS THEN NULL; END;
/

CREATE TABLE SALES_TRANSACTIONS (
    TXN_ID              NUMBER PRIMARY KEY,
    CUSTOMER_ID         NUMBER NOT NULL,
    STORE_ID            NUMBER NOT NULL,
    PRODUCT_SKU         VARCHAR2(30) NOT NULL,
    PRODUCT_CATEGORY    VARCHAR2(50),
    PRODUCT_LINE        VARCHAR2(50),
    CHANNEL             VARCHAR2(20),
    TXN_DATE            DATE NOT NULL,
    TXN_TIMESTAMP       TIMESTAMP DEFAULT SYSTIMESTAMP,
    QUANTITY            NUMBER,
    UNIT_PRICE          NUMBER(10,2),
    TOTAL_AMOUNT        NUMBER(12,2),
    DISCOUNT_PCT        NUMBER(5,2),
    TAX_AMOUNT          NUMBER(10,2),
    PAYMENT_METHOD      VARCHAR2(20),
    CURRENCY_CODE       VARCHAR2(3),
    SALES_REP_ID        NUMBER,
    REGION              VARCHAR2(30),
    STATUS              VARCHAR2(20),
    NOTES               VARCHAR2(200)
) TABLESPACE TEST_DATA_TS;

DECLARE
    v_batch CONSTANT NUMBER := 500000;
    v_total CONSTANT NUMBER := 2000000;
    v_done  NUMBER := 0;
BEGIN
    WHILE v_done < v_total LOOP
        INSERT INTO SALES_TRANSACTIONS
        SELECT v_done + ROWNUM,
               MOD(v_done + ROWNUM, 50000) + 1,
               MOD(v_done + ROWNUM, 200) + 1,
               'SKU' || LPAD(MOD(v_done + ROWNUM, 5000), 6, '0'),
               CASE MOD(v_done + ROWNUM, 10)
                   WHEN 0 THEN 'Electronics' WHEN 1 THEN 'Clothing'
                   WHEN 2 THEN 'Home & Garden' WHEN 3 THEN 'Sports'
                   WHEN 4 THEN 'Books' WHEN 5 THEN 'Toys'
                   WHEN 6 THEN 'Beauty' WHEN 7 THEN 'Health'
                   WHEN 8 THEN 'Food' ELSE 'Automotive' END,
               CASE MOD(v_done + ROWNUM, 6)
                   WHEN 0 THEN 'Premium' WHEN 1 THEN 'Standard'
                   WHEN 2 THEN 'Economy' WHEN 3 THEN 'Luxury'
                   WHEN 4 THEN 'Budget' ELSE 'Outlet' END,
               CASE MOD(v_done + ROWNUM, 5)
                   WHEN 0 THEN 'Online' WHEN 1 THEN 'Retail'
                   WHEN 2 THEN 'Wholesale' WHEN 3 THEN 'Mobile'
                   ELSE 'Partner' END,
               TRUNC(SYSDATE - MOD(v_done + ROWNUM, 730)),
               SYSTIMESTAMP - NUMTODSINTERVAL(MOD(v_done + ROWNUM, 43800), 'MINUTE'),
               TRUNC(DBMS_RANDOM.VALUE(1, 50)),
               ROUND(DBMS_RANDOM.VALUE(5, 2000), 2),
               TRUNC(DBMS_RANDOM.VALUE(1, 50)) * ROUND(DBMS_RANDOM.VALUE(5, 2000), 2),
               CASE WHEN MOD(v_done + ROWNUM, 5) = 0 THEN ROUND(DBMS_RANDOM.VALUE(5, 30), 2) ELSE 0 END,
               ROUND(DBMS_RANDOM.VALUE(1, 500), 2),
               CASE MOD(v_done + ROWNUM, 6)
                   WHEN 0 THEN 'Credit Card' WHEN 1 THEN 'Debit Card'
                   WHEN 2 THEN 'PayPal' WHEN 3 THEN 'Bank Transfer'
                   WHEN 4 THEN 'Apple Pay' ELSE 'Cash' END,
               CASE MOD(v_done + ROWNUM, 4) WHEN 0 THEN 'USD' WHEN 1 THEN 'EUR' WHEN 2 THEN 'GBP' ELSE 'JPY' END,
               MOD(v_done + ROWNUM, 500) + 1,
               CASE MOD(v_done + ROWNUM, 7)
                   WHEN 0 THEN 'North America' WHEN 1 THEN 'Europe'
                   WHEN 2 THEN 'Asia Pacific' WHEN 3 THEN 'Latin America'
                   WHEN 4 THEN 'Middle East' WHEN 5 THEN 'Africa'
                   ELSE 'Oceania' END,
               CASE MOD(v_done + ROWNUM, 4)
                   WHEN 0 THEN 'COMPLETED' WHEN 1 THEN 'SHIPPED'
                   WHEN 2 THEN 'PENDING' ELSE 'REFUNDED' END,
               'Order ' || (v_done + ROWNUM) || ' for customer ' || (MOD(v_done + ROWNUM, 50000) + 1)
        FROM dual CONNECT BY LEVEL <= LEAST(v_batch, v_total - v_done);
        v_done := v_done + SQL%ROWCOUNT;
        COMMIT;
        DBMS_OUTPUT.PUT_LINE('  SALES_TRANSACTIONS: ' || v_done || '/' || v_total || ' rows');
    END LOOP;
END;
/

EXEC DBMS_STATS.GATHER_TABLE_STATS(USER, 'SALES_TRANSACTIONS');
PROMPT SALES_TRANSACTIONS created with 2M rows


-- ============================================================================
-- Table 2: SENSOR_READINGS (~350MB, time-series / IoT candidate)
-- ============================================================================

PROMPT Creating SENSOR_READINGS...

BEGIN EXECUTE IMMEDIATE 'DROP TABLE SENSOR_READINGS PURGE'; EXCEPTION WHEN OTHERS THEN NULL; END;
/

CREATE TABLE SENSOR_READINGS (
    READING_ID          NUMBER PRIMARY KEY,
    DEVICE_ID           VARCHAR2(30) NOT NULL,
    DEVICE_TYPE         VARCHAR2(30),
    LOCATION_CODE       VARCHAR2(20),
    FACILITY            VARCHAR2(50),
    READING_TIMESTAMP   TIMESTAMP NOT NULL,
    READING_DATE        DATE,
    TEMPERATURE_C       NUMBER(6,2),
    HUMIDITY_PCT        NUMBER(5,2),
    PRESSURE_HPA        NUMBER(7,2),
    VIBRATION_HZ        NUMBER(8,3),
    POWER_WATTS         NUMBER(8,2),
    SIGNAL_STRENGTH     NUMBER(5,2),
    STATUS_CODE         VARCHAR2(10),
    ALERT_LEVEL         VARCHAR2(20),
    BATTERY_PCT         NUMBER(5,2),
    FIRMWARE_VER        VARCHAR2(20),
    RAW_DATA            VARCHAR2(500)
) TABLESPACE TEST_DATA_TS;

DECLARE
    v_batch CONSTANT NUMBER := 500000;
    v_total CONSTANT NUMBER := 3000000;
    v_done  NUMBER := 0;
BEGIN
    WHILE v_done < v_total LOOP
        INSERT INTO SENSOR_READINGS
        SELECT v_done + ROWNUM,
               'DEV' || LPAD(MOD(v_done + ROWNUM, 1000), 5, '0'),
               CASE MOD(v_done + ROWNUM, 6)
                   WHEN 0 THEN 'TEMPERATURE' WHEN 1 THEN 'HUMIDITY'
                   WHEN 2 THEN 'PRESSURE' WHEN 3 THEN 'VIBRATION'
                   WHEN 4 THEN 'POWER' ELSE 'MULTI' END,
               'LOC' || LPAD(MOD(v_done + ROWNUM, 100), 4, '0'),
               CASE MOD(v_done + ROWNUM, 8)
                   WHEN 0 THEN 'Plant A - Building 1' WHEN 1 THEN 'Plant A - Building 2'
                   WHEN 2 THEN 'Plant B - Main' WHEN 3 THEN 'Warehouse North'
                   WHEN 4 THEN 'Warehouse South' WHEN 5 THEN 'Data Center 1'
                   WHEN 6 THEN 'Data Center 2' ELSE 'Office Complex' END,
               SYSTIMESTAMP - NUMTODSINTERVAL(MOD(v_done + ROWNUM, 525600), 'MINUTE'),
               TRUNC(SYSDATE - MOD(v_done + ROWNUM, 365)),
               ROUND(20 + DBMS_RANDOM.VALUE(-10, 30), 2),
               ROUND(40 + DBMS_RANDOM.VALUE(-20, 40), 2),
               ROUND(1013 + DBMS_RANDOM.VALUE(-50, 50), 2),
               ROUND(DBMS_RANDOM.VALUE(0, 100), 3),
               ROUND(DBMS_RANDOM.VALUE(50, 5000), 2),
               ROUND(DBMS_RANDOM.VALUE(-100, -20), 2),
               CASE MOD(v_done + ROWNUM, 10)
                   WHEN 0 THEN 'ERR' WHEN 1 THEN 'WARN' ELSE 'OK' END,
               CASE MOD(v_done + ROWNUM, 20)
                   WHEN 0 THEN 'CRITICAL' WHEN 1 THEN 'HIGH'
                   WHEN 2 THEN 'MEDIUM' ELSE 'NORMAL' END,
               ROUND(DBMS_RANDOM.VALUE(10, 100), 2),
               'v' || TRUNC(DBMS_RANDOM.VALUE(1, 5)) || '.' || TRUNC(DBMS_RANDOM.VALUE(0, 10)) || '.0',
               '{"ts":' || (v_done + ROWNUM) || ',"val":' ||
                   ROUND(DBMS_RANDOM.VALUE(0, 100), 2) || ',"unit":"C","q":' ||
                   TRUNC(DBMS_RANDOM.VALUE(90, 100)) || '}'
        FROM dual CONNECT BY LEVEL <= LEAST(v_batch, v_total - v_done);
        v_done := v_done + SQL%ROWCOUNT;
        COMMIT;
        DBMS_OUTPUT.PUT_LINE('  SENSOR_READINGS: ' || v_done || '/' || v_total || ' rows');
    END LOOP;
END;
/

EXEC DBMS_STATS.GATHER_TABLE_STATS(USER, 'SENSOR_READINGS');
PROMPT SENSOR_READINGS created with 3M rows


-- ============================================================================
-- Table 3: AUDIT_LOG (~250MB, archival candidate, high repetition)
-- ============================================================================

PROMPT Creating AUDIT_LOG...

BEGIN EXECUTE IMMEDIATE 'DROP TABLE AUDIT_LOG PURGE'; EXCEPTION WHEN OTHERS THEN NULL; END;
/

CREATE TABLE AUDIT_LOG (
    LOG_ID              NUMBER PRIMARY KEY,
    EVENT_TIMESTAMP     TIMESTAMP NOT NULL,
    EVENT_DATE          DATE,
    EVENT_TYPE          VARCHAR2(30),
    EVENT_CATEGORY      VARCHAR2(30),
    SEVERITY            VARCHAR2(20),
    USER_ID             VARCHAR2(50),
    SESSION_ID          VARCHAR2(50),
    SOURCE_IP           VARCHAR2(45),
    SOURCE_APP          VARCHAR2(50),
    TARGET_OBJECT       VARCHAR2(100),
    ACTION_PERFORMED    VARCHAR2(100),
    RESULT_STATUS       VARCHAR2(20),
    ERROR_CODE          VARCHAR2(20),
    ERROR_MESSAGE       VARCHAR2(500),
    ENVIRONMENT         VARCHAR2(20),
    SERVER_NAME         VARCHAR2(50),
    CORRELATION_ID      VARCHAR2(50)
) TABLESPACE TEST_DATA_TS;

DECLARE
    v_batch CONSTANT NUMBER := 500000;
    v_total CONSTANT NUMBER := 2000000;
    v_done  NUMBER := 0;
BEGIN
    WHILE v_done < v_total LOOP
        INSERT INTO AUDIT_LOG
        SELECT v_done + ROWNUM,
               SYSTIMESTAMP - NUMTODSINTERVAL(MOD(v_done + ROWNUM, 525600), 'MINUTE'),
               TRUNC(SYSDATE - MOD(v_done + ROWNUM, 365)),
               CASE MOD(v_done + ROWNUM, 8)
                   WHEN 0 THEN 'LOGIN' WHEN 1 THEN 'LOGOUT'
                   WHEN 2 THEN 'SELECT' WHEN 3 THEN 'INSERT'
                   WHEN 4 THEN 'UPDATE' WHEN 5 THEN 'DELETE'
                   WHEN 6 THEN 'DDL' ELSE 'ADMIN' END,
               CASE MOD(v_done + ROWNUM, 5)
                   WHEN 0 THEN 'AUTHENTICATION' WHEN 1 THEN 'DATA_ACCESS'
                   WHEN 2 THEN 'DATA_CHANGE' WHEN 3 THEN 'SCHEMA_CHANGE'
                   ELSE 'SYSTEM' END,
               CASE MOD(v_done + ROWNUM, 6)
                   WHEN 0 THEN 'CRITICAL' WHEN 1 THEN 'HIGH'
                   WHEN 2 THEN 'MEDIUM' WHEN 3 THEN 'LOW'
                   WHEN 4 THEN 'INFO' ELSE 'DEBUG' END,
               'USER_' || LPAD(MOD(v_done + ROWNUM, 200), 4, '0'),
               'SES_' || LPAD(MOD(v_done + ROWNUM, 5000), 6, '0'),
               '10.' || MOD(v_done + ROWNUM, 255) || '.' || MOD(v_done + ROWNUM, 255) || '.' || MOD(v_done + ROWNUM, 254 ) + 1,
               CASE MOD(v_done + ROWNUM, 5)
                   WHEN 0 THEN 'WebApp' WHEN 1 THEN 'API'
                   WHEN 2 THEN 'BatchJob' WHEN 3 THEN 'Admin Console'
                   ELSE 'Mobile App' END,
               CASE MOD(v_done + ROWNUM, 4)
                   WHEN 0 THEN 'SCHEMA.CUSTOMERS' WHEN 1 THEN 'SCHEMA.ORDERS'
                   WHEN 2 THEN 'SCHEMA.PRODUCTS' ELSE 'SCHEMA.INVENTORY' END,
               CASE MOD(v_done + ROWNUM, 8)
                   WHEN 0 THEN 'Authenticated user' WHEN 1 THEN 'User logged out'
                   WHEN 2 THEN 'Queried records' WHEN 3 THEN 'Inserted row'
                   WHEN 4 THEN 'Updated record' WHEN 5 THEN 'Deleted record'
                   WHEN 6 THEN 'Altered table' ELSE 'System maintenance' END,
               CASE MOD(v_done + ROWNUM, 20)
                   WHEN 0 THEN 'FAILURE' ELSE 'SUCCESS' END,
               CASE WHEN MOD(v_done + ROWNUM, 20) = 0
                   THEN 'ERR-' || LPAD(MOD(v_done + ROWNUM, 50), 4, '0')
                   ELSE NULL END,
               CASE WHEN MOD(v_done + ROWNUM, 20) = 0
                   THEN 'Operation failed: permission denied on object'
                   ELSE NULL END,
               CASE MOD(v_done + ROWNUM, 3)
                   WHEN 0 THEN 'PRODUCTION' WHEN 1 THEN 'STAGING'
                   ELSE 'DEVELOPMENT' END,
               'SRV' || LPAD(MOD(v_done + ROWNUM, 20), 3, '0'),
               'CORR-' || LPAD(MOD(v_done + ROWNUM, 10000), 8, '0')
        FROM dual CONNECT BY LEVEL <= LEAST(v_batch, v_total - v_done);
        v_done := v_done + SQL%ROWCOUNT;
        COMMIT;
        DBMS_OUTPUT.PUT_LINE('  AUDIT_LOG: ' || v_done || '/' || v_total || ' rows');
    END LOOP;
END;
/

EXEC DBMS_STATS.GATHER_TABLE_STATS(USER, 'AUDIT_LOG');
PROMPT AUDIT_LOG created with 2M rows


-- ============================================================================
-- Table 4: CUSTOMER_ACCOUNTS (~80MB, master data, low DML)
-- ============================================================================

PROMPT Creating CUSTOMER_ACCOUNTS...

BEGIN EXECUTE IMMEDIATE 'DROP TABLE CUSTOMER_ACCOUNTS PURGE'; EXCEPTION WHEN OTHERS THEN NULL; END;
/

CREATE TABLE CUSTOMER_ACCOUNTS (
    ACCOUNT_ID          NUMBER PRIMARY KEY,
    CUSTOMER_NAME       VARCHAR2(100) NOT NULL,
    EMAIL               VARCHAR2(150),
    PHONE               VARCHAR2(30),
    ADDRESS_LINE1       VARCHAR2(200),
    ADDRESS_LINE2       VARCHAR2(200),
    CITY                VARCHAR2(50),
    STATE_PROVINCE      VARCHAR2(50),
    POSTAL_CODE         VARCHAR2(20),
    COUNTRY             VARCHAR2(50),
    ACCOUNT_TYPE        VARCHAR2(20),
    TIER                VARCHAR2(20),
    CREDIT_LIMIT        NUMBER(12,2),
    BALANCE             NUMBER(12,2),
    CREATED_DATE        DATE,
    LAST_ACTIVITY_DATE  DATE,
    STATUS              VARCHAR2(20),
    INDUSTRY            VARCHAR2(50),
    COMPANY_SIZE        VARCHAR2(20),
    NOTES               VARCHAR2(500)
) TABLESPACE TEST_DATA_TS;

DECLARE
    v_batch CONSTANT NUMBER := 250000;
    v_total CONSTANT NUMBER := 500000;
    v_done  NUMBER := 0;
BEGIN
    WHILE v_done < v_total LOOP
        INSERT INTO CUSTOMER_ACCOUNTS
        SELECT v_done + ROWNUM,
               'Customer ' || LPAD(v_done + ROWNUM, 7, '0'),
               'user' || (v_done + ROWNUM) || '@' ||
                   CASE MOD(v_done + ROWNUM, 5) WHEN 0 THEN 'gmail.com' WHEN 1 THEN 'company.com'
                   WHEN 2 THEN 'outlook.com' WHEN 3 THEN 'yahoo.com' ELSE 'business.org' END,
               '+1-' || LPAD(MOD(v_done + ROWNUM, 999), 3, '0') || '-' ||
                   LPAD(MOD(v_done + ROWNUM, 9999), 4, '0'),
               (v_done + ROWNUM) || ' Main Street',
               CASE WHEN MOD(v_done + ROWNUM, 3) = 0 THEN 'Suite ' || MOD(v_done + ROWNUM, 500) ELSE NULL END,
               CASE MOD(v_done + ROWNUM, 12)
                   WHEN 0 THEN 'New York' WHEN 1 THEN 'Los Angeles' WHEN 2 THEN 'Chicago'
                   WHEN 3 THEN 'Houston' WHEN 4 THEN 'Phoenix' WHEN 5 THEN 'Dallas'
                   WHEN 6 THEN 'San Jose' WHEN 7 THEN 'Austin' WHEN 8 THEN 'Denver'
                   WHEN 9 THEN 'Seattle' WHEN 10 THEN 'Boston' ELSE 'Miami' END,
               CASE MOD(v_done + ROWNUM, 10)
                   WHEN 0 THEN 'CA' WHEN 1 THEN 'NY' WHEN 2 THEN 'TX'
                   WHEN 3 THEN 'FL' WHEN 4 THEN 'IL' WHEN 5 THEN 'PA'
                   WHEN 6 THEN 'OH' WHEN 7 THEN 'GA' WHEN 8 THEN 'WA' ELSE 'CO' END,
               LPAD(MOD(v_done + ROWNUM, 99999), 5, '0'),
               CASE MOD(v_done + ROWNUM, 5)
                   WHEN 0 THEN 'USA' WHEN 1 THEN 'Canada' WHEN 2 THEN 'UK'
                   WHEN 3 THEN 'Germany' ELSE 'Australia' END,
               CASE MOD(v_done + ROWNUM, 3) WHEN 0 THEN 'BUSINESS' WHEN 1 THEN 'PERSONAL' ELSE 'ENTERPRISE' END,
               CASE MOD(v_done + ROWNUM, 4)
                   WHEN 0 THEN 'GOLD' WHEN 1 THEN 'SILVER' WHEN 2 THEN 'PLATINUM' ELSE 'BRONZE' END,
               ROUND(DBMS_RANDOM.VALUE(1000, 500000), 2),
               ROUND(DBMS_RANDOM.VALUE(0, 100000), 2),
               TRUNC(SYSDATE - DBMS_RANDOM.VALUE(30, 3650)),
               TRUNC(SYSDATE - MOD(v_done + ROWNUM, 90)),
               CASE MOD(v_done + ROWNUM, 10) WHEN 0 THEN 'INACTIVE' WHEN 1 THEN 'SUSPENDED' ELSE 'ACTIVE' END,
               CASE MOD(v_done + ROWNUM, 8)
                   WHEN 0 THEN 'Technology' WHEN 1 THEN 'Healthcare'
                   WHEN 2 THEN 'Finance' WHEN 3 THEN 'Retail'
                   WHEN 4 THEN 'Manufacturing' WHEN 5 THEN 'Education'
                   WHEN 6 THEN 'Government' ELSE 'Services' END,
               CASE MOD(v_done + ROWNUM, 4)
                   WHEN 0 THEN 'Small' WHEN 1 THEN 'Medium'
                   WHEN 2 THEN 'Large' ELSE 'Enterprise' END,
               'Account established ' || TO_CHAR(TRUNC(SYSDATE - DBMS_RANDOM.VALUE(30, 3650)), 'YYYY-MM-DD') ||
                   '. Tier: ' || CASE MOD(v_done + ROWNUM, 4)
                   WHEN 0 THEN 'Gold' WHEN 1 THEN 'Silver' WHEN 2 THEN 'Platinum' ELSE 'Bronze' END
        FROM dual CONNECT BY LEVEL <= LEAST(v_batch, v_total - v_done);
        v_done := v_done + SQL%ROWCOUNT;
        COMMIT;
        DBMS_OUTPUT.PUT_LINE('  CUSTOMER_ACCOUNTS: ' || v_done || '/' || v_total || ' rows');
    END LOOP;
END;
/

EXEC DBMS_STATS.GATHER_TABLE_STATS(USER, 'CUSTOMER_ACCOUNTS');
PROMPT CUSTOMER_ACCOUNTS created with 500K rows


-- ============================================================================
-- Summary
-- ============================================================================

PROMPT
PROMPT ========================================
PROMPT Test Data Generation Summary
PROMPT ========================================

SELECT table_name,
       TO_CHAR(num_rows, '999,999,999') AS row_count,
       TO_CHAR(ROUND(blocks * 8192 / 1024 / 1024, 1), '9,999.9') AS size_mb
FROM user_tables
WHERE table_name IN ('SALES_TRANSACTIONS', 'SENSOR_READINGS', 'AUDIT_LOG', 'CUSTOMER_ACCOUNTS')
ORDER BY table_name;

SELECT 'TOTAL' AS label,
       TO_CHAR(SUM(num_rows), '999,999,999') AS total_rows,
       TO_CHAR(ROUND(SUM(blocks * 8192 / 1024 / 1024), 1), '9,999.9') AS total_mb
FROM user_tables
WHERE table_name IN ('SALES_TRANSACTIONS', 'SENSOR_READINGS', 'AUDIT_LOG', 'CUSTOMER_ACCOUNTS');

PROMPT ========================================
PROMPT Test data generation complete!
PROMPT ========================================
