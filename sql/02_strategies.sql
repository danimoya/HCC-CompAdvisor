-- ===========================================================================
-- File: 02_strategies.sql
-- Description: Predefined compression strategies for Exadata HCC CompAdvisor
-- Version: 3.0.0
-- Platform: Oracle Exadata (HCC - Hybrid Columnar Compression)
-- ===========================================================================
-- HCC COMPRESSION TYPES:
--   - OLTP: For write-heavy/frequently modified tables (minimal overhead)
--   - QUERY LOW: For frequently accessed read-heavy data (moderate compression)
--   - QUERY HIGH: For very frequently accessed analytics data (aggressive compression)
--   - ARCHIVE LOW: For inactive/cold data (very high compression)
--   - ARCHIVE HIGH: For archived data (maximum compression)
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- STRATEGY DEFINITIONS
-- ---------------------------------------------------------------------------
-- Three core Exadata HCC strategies balancing performance vs. space savings:
--   1. HIGH_PERFORMANCE: OLTP for writes, QUERY HIGH for frequent reads, ARCHIVE LOW for inactive
--   2. BALANCED: OLTP for writes, QUERY LOW for reads, ARCHIVE HIGH for inactive
--   3. MAXIMUM_COMPRESSION: OLTP only for writes, ARCHIVE HIGH for all read-heavy/inactive data
-- ---------------------------------------------------------------------------

PROMPT Inserting compression strategies...

-- Clear existing data (truncate rules first due to foreign key)
TRUNCATE TABLE T_STRATEGY_RULES;
TRUNCATE TABLE T_COMPRESSION_STRATEGIES;

INSERT INTO T_COMPRESSION_STRATEGIES (
    STRATEGY_ID,
    STRATEGY_NAME,
    DESCRIPTION,
    CATEGORY,
    ACTIVE_FLAG,
    CREATED_BY
) VALUES (
    1,
    'HIGH_PERFORMANCE',
    'Minimal compression overhead for transactional workloads. OLTP for write-heavy tables, HCC QUERY HIGH for frequently accessed read-only data, HCC ARCHIVE LOW for inactive tables. Best for: OLTP systems, real-time analytics, mixed read/write workloads.',
    'PERFORMANCE',
    'Y',
    USER
);

INSERT INTO T_COMPRESSION_STRATEGIES (
    STRATEGY_ID,
    STRATEGY_NAME,
    DESCRIPTION,
    CATEGORY,
    ACTIVE_FLAG,
    CREATED_BY
) VALUES (
    2,
    'BALANCED',
    'Optimal space savings and performance balance. OLTP for write-heavy tables, HCC QUERY LOW for frequently accessed data, HCC ARCHIVE HIGH for inactive/cold tables. Best for: General-purpose databases, mixed read-heavy and read-only workloads, balanced update patterns.',
    'BALANCED',
    'Y',
    USER
);

INSERT INTO T_COMPRESSION_STRATEGIES (
    STRATEGY_ID,
    STRATEGY_NAME,
    DESCRIPTION,
    CATEGORY,
    ACTIVE_FLAG,
    CREATED_BY
) VALUES (
    3,
    'MAXIMUM_COMPRESSION',
    'Maximum space savings with HCC ARCHIVE HIGH compression. OLTP only for write-heavy tables, HCC ARCHIVE HIGH for all read-only and inactive data. Best for: Data warehouses, analytics systems, archive data, read-heavy workloads, cost-sensitive storage environments.',
    'SPACE',
    'Y',
    USER
);

COMMIT;

-- ---------------------------------------------------------------------------
-- STRATEGY RULES: HIGH_PERFORMANCE
-- ---------------------------------------------------------------------------
-- Philosophy: Minimize compression overhead for OLTP, maximize compression for read-only
-- - Hot/frequently modified tables (high write ratio): OLTP (minimal overhead)
-- - Frequently accessed reads (>70 hotness, low writes): HCC QUERY HIGH (excellent compression, optimized for frequent access)
-- - Cold/inactive data (<40 hotness): HCC ARCHIVE LOW (maximum space savings, minimal access impact)
-- ---------------------------------------------------------------------------

PROMPT Inserting HIGH_PERFORMANCE strategy rules...

-- Rule 1: Hot tables with heavy writes - OLTP compression
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'Hot tables with heavy writes: Use OLTP for minimal overhead while maintaining compression'
);

-- Rule 2: Hot tables with light writes - HCC QUERY HIGH
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'QUERY HIGH',
    2,
    'Frequently accessed tables with low writes: HCC QUERY HIGH for excellent compression and fast query performance'
);

-- Rule 3: Warm tables with heavy writes - OLTP compression
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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

-- Rule 4: Warm tables with light writes - HCC QUERY LOW
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'QUERY LOW',
    4,
    'Warm tables with light writes: HCC QUERY LOW for good compression on moderately accessed data'
);

-- Rule 5: Cold tables - HCC ARCHIVE LOW
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'ARCHIVE LOW',
    5,
    'Inactive/cold tables with rare access: HCC ARCHIVE LOW for maximum space savings with minimal performance impact'
);

-- Rule 6: Hot indexes - HCC QUERY HIGH
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'QUERY HIGH',
    6,
    'Hot indexes: HCC QUERY HIGH provides good compression with excellent query performance'
);

-- Rule 7: Warm indexes - HCC QUERY LOW
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'QUERY LOW',
    7,
    'Warm indexes: HCC QUERY LOW provides balanced compression for moderately accessed indexes'
);

-- Rule 8: Cold indexes - HCC ARCHIVE LOW
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'ARCHIVE LOW',
    8,
    'Rarely used indexes with minimal access: HCC ARCHIVE LOW for excellent space savings'
);

-- Rule 9: LOBs - No compression
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'LOBs: Deferred to Oracle''s default SecureFile compression in Exadata'
);

-- ---------------------------------------------------------------------------
-- STRATEGY RULES: BALANCED
-- ---------------------------------------------------------------------------
-- Philosophy: Optimize for both space and performance
-- - Hot data (>70): OLTP compression (write-heavy) or QUERY HIGH (read-heavy)
-- - Warm data (40-70): OLTP (write-heavy) or QUERY LOW (read-heavy)
-- - Cold data (<40): ARCHIVE HIGH (maximize space savings)
-- - Consider write patterns: Higher compression for read-heavy workloads
-- ---------------------------------------------------------------------------

PROMPT Inserting BALANCED strategy rules...

-- Rule 10: Hot tables with heavy writes - OLTP
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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

-- Rule 11: Hot tables with light writes - HCC QUERY HIGH
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'QUERY HIGH',
    11,
    'Hot read-heavy tables: HCC QUERY HIGH provides excellent compression for frequently queried data'
);

-- Rule 12: Warm tables with heavy writes - OLTP
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    2,
    'TABLE',
    40,
    70,
    0.5,
    1.0,
    'OLTP',
    12,
    'Warm write-heavy tables: OLTP compression maintains write performance'
);

-- Rule 13: Warm tables with light writes - HCC QUERY LOW
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    2,
    'TABLE',
    40,
    70,
    0,
    0.5,
    'QUERY LOW',
    13,
    'Warm read-heavy tables: HCC QUERY LOW provides good space savings with acceptable read overhead'
);

-- Rule 14: Cold tables - HCC ARCHIVE HIGH
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
    PRIORITY,
    RULE_DESCRIPTION
) VALUES (
    SEQ_STRATEGY_RULES.NEXTVAL,
    2,
    'TABLE',
    0,
    40,
    0,
    1.0,
    'ARCHIVE HIGH',
    14,
    'Cold tables: HCC ARCHIVE HIGH maximizes space savings for infrequently accessed data'
);

-- Rule 15: Hot indexes - HCC QUERY HIGH
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'QUERY HIGH',
    15,
    'Hot indexes: HCC QUERY HIGH balances compression and query performance'
);

-- Rule 16: Warm indexes - HCC QUERY LOW
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'QUERY LOW',
    16,
    'Warm indexes: HCC QUERY LOW provides good compression ratio for moderately used indexes'
);

-- Rule 17: Cold indexes - HCC ARCHIVE HIGH
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'ARCHIVE HIGH',
    17,
    'Cold indexes: HCC ARCHIVE HIGH maximizes space recovery for rarely accessed indexes'
);

-- Rule 18: LOBs - No compression
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'LOBs: Rely on SecureFile automatic compression in Exadata'
);

-- ---------------------------------------------------------------------------
-- STRATEGY RULES: MAXIMUM_COMPRESSION
-- ---------------------------------------------------------------------------
-- Philosophy: Maximize space savings, acceptable performance trade-off
-- - Very hot data (>80): OLTP (maintain usability)
-- - Hot data (40-80): QUERY HIGH for read-heavy, OLTP for write-heavy
-- - Cold data (<=40): ARCHIVE HIGH (maximize space savings)
-- - Indexes: Use HCC ARCHIVE HIGH for better compression ratios
-- - Prioritize space over CPU overhead
-- ---------------------------------------------------------------------------

PROMPT Inserting MAXIMUM_COMPRESSION strategy rules...

-- Rule 19: Very hot tables with heavy writes - OLTP
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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

-- Rule 20: Very hot tables with light writes - HCC QUERY HIGH
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'QUERY HIGH',
    20,
    'Very hot read-heavy tables: HCC QUERY HIGH maintains query performance while compressing'
);

-- Rule 21: Hot tables with heavy writes - OLTP
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'OLTP',
    21,
    'Hot write-heavy tables: OLTP compression for better space savings'
);

-- Rule 22: Hot tables with light writes - HCC QUERY HIGH
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'QUERY HIGH',
    22,
    'Hot read-heavy tables: HCC QUERY HIGH provides excellent compression for active data'
);

-- Rule 23: Cold tables - HCC ARCHIVE HIGH
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'ARCHIVE HIGH',
    23,
    'Cold tables: Always use HCC ARCHIVE HIGH for maximum space savings'
);

-- Rule 24: Hot indexes - HCC QUERY HIGH
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'QUERY HIGH',
    24,
    'Hot indexes: HCC QUERY HIGH for maximum index compression'
);

-- Rule 25: Warm indexes - HCC QUERY HIGH
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'QUERY HIGH',
    25,
    'Warm indexes: HCC QUERY HIGH provides excellent space savings'
);

-- Rule 26: Cold indexes - HCC ARCHIVE HIGH
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'ARCHIVE HIGH',
    26,
    'Cold indexes: Compress all indexes with HCC ARCHIVE HIGH for maximum space recovery'
);

-- Rule 27: LOBs - No compression
INSERT INTO T_STRATEGY_RULES (
    RULE_ID,
    STRATEGY_ID,
    OBJECT_TYPE,
    HOTNESS_MIN,
    HOTNESS_MAX,
    MIN_WRITE_RATIO,
    MAX_WRITE_RATIO,
    COMPRESSION_TYPE,
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
    'LOBs: Oracle Exadata handles LOB compression automatically via SecureFile'
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
    ACTIVE_FLAG,
    TO_CHAR(CREATED_DATE, 'YYYY-MM-DD HH24:MI:SS') AS CREATED
FROM T_COMPRESSION_STRATEGIES
ORDER BY STRATEGY_ID;

PROMPT
PROMPT Strategy Rules Count:
PROMPT =====================

SELECT
    s.STRATEGY_ID,
    s.STRATEGY_NAME,
    COUNT(r.RULE_ID) AS RULE_COUNT,
    COUNT(CASE WHEN r.OBJECT_TYPE = 'TABLE' THEN 1 END) AS TABLE_RULES,
    COUNT(CASE WHEN r.OBJECT_TYPE = 'INDEX' THEN 1 END) AS INDEX_RULES,
    COUNT(CASE WHEN r.OBJECT_TYPE = 'LOB' THEN 1 END) AS LOB_RULES
FROM T_COMPRESSION_STRATEGIES s
LEFT JOIN T_STRATEGY_RULES r ON s.STRATEGY_ID = r.STRATEGY_ID
GROUP BY s.STRATEGY_ID, s.STRATEGY_NAME
ORDER BY s.STRATEGY_ID;

PROMPT
PROMPT Sample Rules by Strategy:
PROMPT =========================

SELECT
    s.STRATEGY_NAME,
    r.OBJECT_TYPE,
    r.HOTNESS_MIN || '-' || r.HOTNESS_MAX AS HOTNESS_RANGE,
    ROUND(r.MIN_WRITE_RATIO * 100) || '-' || ROUND(r.MAX_WRITE_RATIO * 100) || '%' AS WRITE_RATIO_RANGE,
    r.COMPRESSION_TYPE,
    r.PRIORITY
FROM T_COMPRESSION_STRATEGIES s
JOIN T_STRATEGY_RULES r ON s.STRATEGY_ID = r.STRATEGY_ID
WHERE r.OBJECT_TYPE = 'TABLE'
ORDER BY s.STRATEGY_ID, r.PRIORITY
FETCH FIRST 15 ROWS ONLY;

PROMPT
PROMPT Strategy setup complete!
PROMPT =======================
PROMPT 3 strategies configured with 27 total rules
PROMPT - HIGH_PERFORMANCE: 9 rules (OLTP, QUERY HIGH, ARCHIVE LOW)
PROMPT - BALANCED: 9 rules (OLTP, QUERY HIGH/LOW, ARCHIVE HIGH)
PROMPT - MAXIMUM_COMPRESSION: 9 rules (OLTP, QUERY HIGH, ARCHIVE HIGH)
PROMPT

-- ===========================================================================
-- END OF SCRIPT
-- ===========================================================================
