-- ===========================================================================
-- File: 02_strategies.sql
-- Description: Predefined compression strategies and rules for HCC CompAdvisor
-- Version: 1.0.0
-- Oracle Version: 23c Free (BASIC, OLTP for tables; ADVANCED LOW/HIGH for indexes)
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- STRATEGY DEFINITIONS
-- ---------------------------------------------------------------------------
-- Three core strategies balancing performance vs. space savings:
--   1. HIGH_PERFORMANCE: Minimal compression overhead, OLTP-focused
--   2. BALANCED: Optimal balance between compression and performance
--   3. MAXIMUM_COMPRESSION: Aggressive space savings, read-heavy workloads
-- ---------------------------------------------------------------------------

PROMPT Inserting compression strategies...

INSERT INTO T_STRATEGIES (
    STRATEGY_ID,
    STRATEGY_NAME,
    DESCRIPTION,
    IS_ACTIVE,
    CREATED_BY,
    CREATED_DATE
) VALUES (
    1,
    'HIGH_PERFORMANCE',
    'Minimal compression overhead strategy. Prioritizes query performance and OLTP workloads. Only compresses cold data with low write activity. Best for: High-transaction systems, real-time analytics, frequently updated tables.',
    'Y',
    USER,
    SYSTIMESTAMP
);

INSERT INTO T_STRATEGIES (
    STRATEGY_ID,
    STRATEGY_NAME,
    DESCRIPTION,
    IS_ACTIVE,
    CREATED_BY,
    CREATED_DATE
) VALUES (
    2,
    'BALANCED',
    'Balanced compression strategy. Optimizes both space savings and performance. Uses BASIC compression for warm data, OLTP for hot data. Best for: General-purpose databases, mixed workloads, moderate update patterns.',
    'Y',
    USER,
    SYSTIMESTAMP
);

INSERT INTO T_STRATEGIES (
    STRATEGY_ID,
    STRATEGY_NAME,
    DESCRIPTION,
    IS_ACTIVE,
    CREATED_BY,
    CREATED_DATE
) VALUES (
    3,
    'MAXIMUM_COMPRESSION',
    'Aggressive compression strategy. Maximizes space savings with acceptable performance trade-offs. Applies BASIC compression broadly. Best for: Archive data, read-heavy workloads, data warehouses, low-update tables.',
    'Y',
    USER,
    SYSTIMESTAMP
);

COMMIT;

-- ---------------------------------------------------------------------------
-- STRATEGY RULES: HIGH_PERFORMANCE
-- ---------------------------------------------------------------------------
-- Philosophy: Compression only where it won't impact performance
-- - Hot data (>70): Use OLTP compression (minimal overhead)
-- - Warm data (40-70): OLTP for tables, ADV_LOW for indexes
-- - Cold data (<40): Leave uncompressed or use OLTP if read-only
-- - Write-heavy objects (>50% DML): Avoid compression or use OLTP only
-- ---------------------------------------------------------------------------

PROMPT Inserting HIGH_PERFORMANCE strategy rules...

-- Rule 1: Hot tables with heavy writes - OLTP compression
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    1,
    'TABLE',
    70,
    100,
    0.5,
    1.0,
    'OLTP',
    1,
    'Hot tables with heavy writes: Use OLTP for minimal overhead while maintaining some space savings'
);

-- Rule 2: Hot tables with light writes - OLTP compression
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    1,
    'TABLE',
    70,
    100,
    0,
    0.5,
    'OLTP',
    2,
    'Hot tables with light writes: OLTP provides good balance for frequently accessed data'
);

-- Rule 3: Warm tables with heavy writes - OLTP compression
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    1,
    'TABLE',
    40,
    70,
    0.5,
    1.0,
    'OLTP',
    3,
    'Warm tables with heavy writes: OLTP minimizes write overhead while providing compression'
);

-- Rule 4: Warm tables with light writes - OLTP compression
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    1,
    'TABLE',
    40,
    70,
    0,
    0.5,
    'OLTP',
    4,
    'Warm tables with light writes: Safe to use OLTP for moderate space savings'
);

-- Rule 5: Cold tables - No compression (performance priority)
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    1,
    'TABLE',
    0,
    40,
    0,
    1.0,
    'NOCOMPRESS',
    5,
    'Cold tables: Leave uncompressed to avoid CPU overhead on infrequent access'
);

-- Rule 6: Hot indexes - ADVANCED LOW (minimal overhead)
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    1,
    'INDEX',
    60,
    100,
    0,
    1.0,
    'ADVANCED LOW',
    6,
    'Hot indexes: ADVANCED LOW provides good compression with minimal query impact'
);

-- Rule 7: Warm indexes - ADVANCED LOW
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    1,
    'INDEX',
    30,
    60,
    0,
    1.0,
    'ADVANCED LOW',
    7,
    'Warm indexes: Safe compression level for moderately accessed indexes'
);

-- Rule 8: Cold indexes - No compression
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    1,
    'INDEX',
    0,
    30,
    0,
    1.0,
    'NOCOMPRESS',
    8,
    'Cold indexes: Avoid compression overhead for rarely used indexes'
);

-- Rule 9: LOBs - No compression (Oracle 23c Free limitation)
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    1,
    'LOB',
    0,
    100,
    0,
    1.0,
    'NOCOMPRESS',
    9,
    'LOBs: Deferred to Oracle''s default SecureFile compression in 23c Free'
);

-- ---------------------------------------------------------------------------
-- STRATEGY RULES: BALANCED
-- ---------------------------------------------------------------------------
-- Philosophy: Optimize for both space and performance
-- - Hot data (>70): OLTP compression
-- - Warm data (30-70): BASIC compression (good ratio, acceptable overhead)
-- - Cold data (<30): BASIC compression (maximize space savings)
-- - Consider write patterns: Higher compression for read-heavy workloads
-- ---------------------------------------------------------------------------

PROMPT Inserting BALANCED strategy rules...

-- Rule 10: Hot tables with heavy writes - OLTP
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    2,
    'TABLE',
    70,
    100,
    0.5,
    1.0,
    'OLTP',
    10,
    'Hot write-heavy tables: OLTP balances write performance and compression'
);

-- Rule 11: Hot tables with light writes - OLTP
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    2,
    'TABLE',
    70,
    100,
    0,
    0.5,
    'OLTP',
    11,
    'Hot read-heavy tables: OLTP provides good compression for frequently queried data'
);

-- Rule 12: Warm tables with heavy writes - BASIC
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    2,
    'TABLE',
    30,
    70,
    0.5,
    1.0,
    'BASIC',
    12,
    'Warm write-heavy tables: BASIC compression acceptable for moderate update frequency'
);

-- Rule 13: Warm tables with light writes - BASIC
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    2,
    'TABLE',
    30,
    70,
    0,
    0.5,
    'BASIC',
    13,
    'Warm read-heavy tables: BASIC provides good space savings with acceptable read overhead'
);

-- Rule 14: Cold tables - BASIC compression
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    2,
    'TABLE',
    0,
    30,
    0,
    1.0,
    'BASIC',
    14,
    'Cold tables: BASIC compression maximizes space savings for infrequently accessed data'
);

-- Rule 15: Hot indexes - ADVANCED LOW
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    2,
    'INDEX',
    60,
    100,
    0,
    1.0,
    'ADVANCED LOW',
    15,
    'Hot indexes: ADVANCED LOW balances compression and query performance'
);

-- Rule 16: Warm indexes - ADVANCED LOW
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    2,
    'INDEX',
    30,
    60,
    0,
    1.0,
    'ADVANCED LOW',
    16,
    'Warm indexes: Good compression ratio for moderately used indexes'
);

-- Rule 17: Cold indexes - ADVANCED LOW
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    2,
    'INDEX',
    0,
    30,
    0,
    1.0,
    'ADVANCED LOW',
    17,
    'Cold indexes: Compress for space savings on rarely accessed indexes'
);

-- Rule 18: LOBs - No compression
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    2,
    'LOB',
    0,
    100,
    0,
    1.0,
    'NOCOMPRESS',
    18,
    'LOBs: Rely on SecureFile automatic compression in Oracle 23c Free'
);

-- ---------------------------------------------------------------------------
-- STRATEGY RULES: MAXIMUM_COMPRESSION
-- ---------------------------------------------------------------------------
-- Philosophy: Maximize space savings, acceptable performance trade-off
-- - Very hot data (>80): OLTP (maintain usability)
-- - Hot data (40-80): BASIC compression
-- - Cold data (<=40): BASIC compression
-- - Indexes: Use ADVANCED HIGH for better compression ratios
-- - Prioritize space over CPU overhead
-- ---------------------------------------------------------------------------

PROMPT Inserting MAXIMUM_COMPRESSION strategy rules...

-- Rule 19: Very hot tables with heavy writes - OLTP
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    3,
    'TABLE',
    80,
    100,
    0.5,
    1.0,
    'OLTP',
    19,
    'Very hot write-heavy tables: OLTP prevents severe write degradation'
);

-- Rule 20: Very hot tables with light writes - OLTP
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    3,
    'TABLE',
    80,
    100,
    0,
    0.5,
    'OLTP',
    20,
    'Very hot read-heavy tables: OLTP maintains query performance while compressing'
);

-- Rule 21: Hot tables with heavy writes - BASIC
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    3,
    'TABLE',
    40,
    80,
    0.5,
    1.0,
    'BASIC',
    21,
    'Hot write-heavy tables: BASIC compression for better space savings'
);

-- Rule 22: Hot tables with light writes - BASIC
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    3,
    'TABLE',
    40,
    80,
    0,
    0.5,
    'BASIC',
    22,
    'Hot read-heavy tables: BASIC provides good compression for active data'
);

-- Rule 23: Cold tables - BASIC compression
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    3,
    'TABLE',
    0,
    40,
    0,
    1.0,
    'BASIC',
    23,
    'Cold tables: Always compress with BASIC for maximum space savings'
);

-- Rule 24: Hot indexes - ADVANCED HIGH
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    3,
    'INDEX',
    60,
    100,
    0,
    1.0,
    'ADVANCED HIGH',
    24,
    'Hot indexes: ADVANCED HIGH for maximum index compression'
);

-- Rule 25: Warm indexes - ADVANCED LOW
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    3,
    'INDEX',
    30,
    60,
    0,
    1.0,
    'ADVANCED LOW',
    25,
    'Warm indexes: ADVANCED LOW provides good space savings'
);

-- Rule 26: Cold indexes - ADVANCED LOW
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    3,
    'INDEX',
    0,
    30,
    0,
    1.0,
    'ADVANCED LOW',
    26,
    'Cold indexes: Compress all indexes for maximum space recovery'
);

-- Rule 27: LOBs - No compression
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    MIN_HOTNESS_SCORE,
    MAX_HOTNESS_SCORE,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    RECOMMENDED_COMPRESSION,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    3,
    'LOB',
    0,
    100,
    0,
    1.0,
    'NOCOMPRESS',
    27,
    'LOBs: Oracle 23c Free handles LOB compression automatically via SecureFile'
);

COMMIT;

-- ---------------------------------------------------------------------------
-- VERIFICATION
-- ---------------------------------------------------------------------------

PROMPT
PROMPT Strategy Configuration Summary:
PROMPT ================================

SELECT
    STRATEGY_NAME,
    DESCRIPTION,
    IS_ACTIVE,
    TO_CHAR(CREATED_DATE, 'YYYY-MM-DD HH24:MI:SS') AS CREATED
FROM T_STRATEGIES
ORDER BY STRATEGY_ID;

PROMPT
PROMPT Strategy Rules Count:
PROMPT =====================

SELECT
    s.STRATEGY_NAME,
    COUNT(r.RULE_ID) AS RULE_COUNT,
    COUNT(CASE WHEN r.OBJECT_TYPE = 'TABLE' THEN 1 END) AS TABLE_RULES,
    COUNT(CASE WHEN r.OBJECT_TYPE = 'INDEX' THEN 1 END) AS INDEX_RULES,
    COUNT(CASE WHEN r.OBJECT_TYPE = 'LOB' THEN 1 END) AS LOB_RULES
FROM T_STRATEGIES s
LEFT JOIN T_STRATEGY_RULES r ON s.STRATEGY_ID = r.STRATEGY_ID
GROUP BY s.STRATEGY_NAME
ORDER BY s.STRATEGY_ID;

PROMPT
PROMPT Sample Rules by Strategy:
PROMPT =========================

SELECT
    s.STRATEGY_NAME,
    r.OBJECT_TYPE,
    r.MIN_HOTNESS_SCORE || '-' || r.MAX_HOTNESS_SCORE AS HOTNESS_RANGE,
    ROUND(r.MIN_WRITE_RATIO * 100) || '-' || ROUND(r.MAX_WRITE_RATIO * 100) || '%' AS WRITE_RATIO_RANGE,
    r.RECOMMENDED_COMPRESSION,
    r.PRIORITY
FROM T_STRATEGIES s
JOIN T_STRATEGY_RULES r ON s.STRATEGY_ID = r.STRATEGY_ID
WHERE r.OBJECT_TYPE = 'TABLE'
ORDER BY s.STRATEGY_ID, r.PRIORITY
FETCH FIRST 15 ROWS ONLY;

PROMPT
PROMPT Strategy setup complete!
PROMPT =======================
PROMPT 3 strategies configured with 27 total rules
PROMPT - HIGH_PERFORMANCE: 9 rules (minimal compression overhead)
PROMPT - BALANCED: 9 rules (optimal space/performance balance)
PROMPT - MAXIMUM_COMPRESSION: 9 rules (aggressive space savings)
PROMPT

-- ===========================================================================
-- END OF SCRIPT
-- ===========================================================================
