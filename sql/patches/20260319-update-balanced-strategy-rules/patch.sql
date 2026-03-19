-- Update Balanced strategy (ID=2) rules to 5-band hotness model
-- Remove old rules for strategy 2
DELETE FROM t_strategy_rules WHERE strategy_id = 2;

-- Insert new 5-band rules (never BASIC)
INSERT INTO t_strategy_rules (strategy_id, object_type, compression_type, hotness_min, hotness_max, dml_ratio_threshold, priority, enabled_flag, rule_description)
VALUES (2, 'TABLE', 'OLTP', 65, 85, NULL, 100, 'Y', 'Hot tables (65-85): OLTP compression, DML-friendly');

INSERT INTO t_strategy_rules (strategy_id, object_type, compression_type, hotness_min, hotness_max, dml_ratio_threshold, priority, enabled_flag, rule_description)
VALUES (2, 'TABLE', 'QUERY LOW', 45, 64, NULL, 90, 'Y', 'Warm tables (45-64): Query Low HCC, balanced read/write');

INSERT INTO t_strategy_rules (strategy_id, object_type, compression_type, hotness_min, hotness_max, dml_ratio_threshold, priority, enabled_flag, rule_description)
VALUES (2, 'TABLE', 'QUERY HIGH', 25, 44, NULL, 80, 'Y', 'Cool tables (25-44): Query High HCC, read-optimized');

INSERT INTO t_strategy_rules (strategy_id, object_type, compression_type, hotness_min, hotness_max, dml_ratio_threshold, priority, enabled_flag, rule_description)
VALUES (2, 'TABLE', 'ARCHIVE LOW', 10, 24, NULL, 70, 'Y', 'Cold tables (10-24): Archive Low HCC, infrequent access');

INSERT INTO t_strategy_rules (strategy_id, object_type, compression_type, hotness_min, hotness_max, dml_ratio_threshold, priority, enabled_flag, rule_description)
VALUES (2, 'TABLE', 'ARCHIVE HIGH', 0, 9, NULL, 60, 'Y', 'Frozen tables (<10): Archive High HCC, maximum compression');

COMMIT;
