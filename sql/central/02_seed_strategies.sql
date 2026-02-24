/*******************************************************************************
 * HCC Compression Advisor - Seed Strategy Data for Central Database
 * Version: 2.0.0 (Centralized)
 *
 * DESCRIPTION:
 *   Seeds default compression strategies and rules into the central database.
 *   These strategies are global and apply to all target databases.
 *
 * USAGE:
 *   Connect as schema owner (COMPRESSION_MGR) to the CENTRAL database:
 *   @02_seed_strategies.sql
 *
 ******************************************************************************/

SET ECHO ON
SET FEEDBACK ON
SET SERVEROUTPUT ON SIZE UNLIMITED

PROMPT ================================================================================
PROMPT Seeding Default Compression Strategies (Central Database)
PROMPT ================================================================================

-- ============================================================================
-- STRATEGY DEFINITIONS
-- ============================================================================

PROMPT
PROMPT Inserting default strategy configurations...

-- Default Strategy: BALANCED_PRODUCTION
INSERT INTO T_COMPRESSION_STRATEGIES (
    STRATEGY_NAME,
    DESCRIPTION,
    CATEGORY,
    HOTNESS_THRESHOLD_HOT,
    HOTNESS_THRESHOLD_WARM,
    HOTNESS_THRESHOLD_COOL,
    DML_THRESHOLD_HIGH,
    DML_THRESHOLD_MEDIUM,
    DML_THRESHOLD_LOW,
    SIZE_THRESHOLD_LARGE_GB,
    SIZE_THRESHOLD_MEDIUM_GB,
    SIZE_THRESHOLD_SMALL_GB,
    MIN_COMPRESSION_RATIO,
    MIN_SPACE_SAVINGS_MB,
    ACTIVE_FLAG,
    IS_DEFAULT,
    PRIORITY
) VALUES (
    'BALANCED_PRODUCTION',
    'Balanced compression strategy for general production workloads (Oracle 23c Free)',
    'BALANCED',
    75,    -- HOT threshold
    50,    -- WARM threshold
    25,    -- COOL threshold
    5000,  -- HIGH DML
    500,   -- MEDIUM DML
    50,    -- LOW DML
    50,    -- Large GB
    5,     -- Medium GB
    0.5,   -- Small GB
    1.5,   -- Min ratio
    100,   -- Min savings MB
    'Y',
    'Y',
    100
);

-- Performance Strategy: HIGH_PERFORMANCE
INSERT INTO T_COMPRESSION_STRATEGIES (
    STRATEGY_NAME,
    DESCRIPTION,
    CATEGORY,
    HOTNESS_THRESHOLD_HOT,
    HOTNESS_THRESHOLD_WARM,
    HOTNESS_THRESHOLD_COOL,
    DML_THRESHOLD_HIGH,
    DML_THRESHOLD_MEDIUM,
    DML_THRESHOLD_LOW,
    MIN_COMPRESSION_RATIO,
    MIN_SPACE_SAVINGS_MB,
    ACTIVE_FLAG,
    IS_DEFAULT,
    PRIORITY
) VALUES (
    'HIGH_PERFORMANCE',
    'Minimal compression for high-performance OLTP systems',
    'PERFORMANCE',
    85,    -- Higher HOT threshold
    65,    -- Higher WARM threshold
    35,    -- Higher COOL threshold
    10000,
    1000,
    100,
    2.0,   -- Higher minimum ratio required
    200,   -- Higher minimum savings required
    'Y',
    'N',
    90
);

-- Space Optimization Strategy: MAXIMUM_COMPRESSION
INSERT INTO T_COMPRESSION_STRATEGIES (
    STRATEGY_NAME,
    DESCRIPTION,
    CATEGORY,
    HOTNESS_THRESHOLD_HOT,
    HOTNESS_THRESHOLD_WARM,
    HOTNESS_THRESHOLD_COOL,
    DML_THRESHOLD_HIGH,
    DML_THRESHOLD_MEDIUM,
    DML_THRESHOLD_LOW,
    MIN_COMPRESSION_RATIO,
    MIN_SPACE_SAVINGS_MB,
    ACTIVE_FLAG,
    IS_DEFAULT,
    PRIORITY
) VALUES (
    'MAXIMUM_COMPRESSION',
    'Aggressive compression for data warehouse and archival systems',
    'SPACE',
    65,    -- Lower HOT threshold
    40,    -- Lower WARM threshold
    15,    -- Lower COOL threshold
    1000,
    100,
    10,
    1.2,   -- Lower minimum ratio (more aggressive)
    50,    -- Lower minimum savings (compress more)
    'Y',
    'N',
    80
);

COMMIT;

-- ============================================================================
-- VERIFICATION
-- ============================================================================

PROMPT
PROMPT Verifying seed data...

SELECT
    STRATEGY_ID,
    STRATEGY_NAME,
    CATEGORY,
    IS_DEFAULT,
    ACTIVE_FLAG
FROM T_COMPRESSION_STRATEGIES
ORDER BY STRATEGY_ID;

PROMPT
PROMPT ================================================================================
PROMPT Strategy seeding completed successfully!
PROMPT ================================================================================
