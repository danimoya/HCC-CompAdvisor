-- ============================================================================
-- File: 06_ords.sql
-- Description: ORDS REST API Configuration for HCC Compression Advisor
-- Module: compression_mgmt
-- Base Path: /compression/v1/
-- ============================================================================

-- ============================================================================
-- Enable Schema for ORDS
-- ============================================================================
BEGIN
    ORDS.ENABLE_SCHEMA(
        p_enabled             => TRUE,
        p_schema              => USER,
        p_url_mapping_type    => 'BASE_PATH',
        p_url_mapping_pattern => 'compression',
        p_auto_rest_auth      => FALSE
    );
    COMMIT;
END;
/

-- ============================================================================
-- Define ORDS Module
-- ============================================================================
BEGIN
    ORDS.DEFINE_MODULE(
        p_module_name    => 'compression_mgmt',
        p_base_path      => '/compression/v1/',
        p_items_per_page => 25,
        p_status         => 'PUBLISHED',
        p_comments       => 'HCC Compression Advisor REST API v1.0'
    );
    COMMIT;
END;
/

-- ============================================================================
-- ENDPOINT 1: POST /analyze - Trigger Compression Analysis
-- ============================================================================
-- cURL Example:
-- curl -X POST "https://server/ords/compression/compression/v1/analyze" \
--   -H "Content-Type: application/json" \
--   -d '{"owner":"MYSCHEMA","strategy_id":2}'
-- ============================================================================

BEGIN
    ORDS.DEFINE_TEMPLATE(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'analyze',
        p_priority       => 0,
        p_etag_type      => 'HASH',
        p_etag_query     => NULL,
        p_comments       => 'Trigger compression analysis for schema objects'
    );

    ORDS.DEFINE_HANDLER(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'analyze',
        p_method         => 'POST',
        p_source_type    => 'plsql/block',
        p_mimes_allowed  => 'application/json',
        p_comments       => 'Execute compression analysis',
        p_source         => q'[
DECLARE
    l_owner         VARCHAR2(128) := :owner;
    l_strategy_id   NUMBER := NVL(:strategy_id, 2);
    l_run_id        NUMBER;
    l_status        VARCHAR2(100);
BEGIN
    -- Validate strategy exists
    BEGIN
        SELECT strategy_id INTO l_strategy_id
        FROM t_compression_strategies
        WHERE strategy_id = l_strategy_id
          AND is_active = 'Y';
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            :status_code := 400;
            :response := JSON_OBJECT(
                'status' VALUE 'error',
                'message' VALUE 'Invalid or inactive strategy_id'
            );
            RETURN;
    END;

    -- Execute analysis
    PKG_COMPRESSION_ADVISOR.run_analysis(
        p_owner       => l_owner,
        p_strategy_id => l_strategy_id
    );

    -- Get latest run_id
    SELECT MAX(run_id) INTO l_run_id
    FROM t_compression_analysis;

    :status_code := 200;
    :response := JSON_OBJECT(
        'status' VALUE 'success',
        'run_id' VALUE l_run_id,
        'owner' VALUE NVL(l_owner, 'ALL'),
        'strategy_id' VALUE l_strategy_id,
        'message' VALUE 'Compression analysis completed successfully',
        'timestamp' VALUE TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS.FF3"Z"')
    );

EXCEPTION
    WHEN OTHERS THEN
        :status_code := 500;
        :response := JSON_OBJECT(
            'status' VALUE 'error',
            'message' VALUE SQLERRM,
            'sqlcode' VALUE SQLCODE
        );
END;
]'
    );
    COMMIT;
END;
/

-- ============================================================================
-- ENDPOINT 2: GET /recommendations - Get Compression Recommendations
-- ============================================================================
-- cURL Example:
-- curl "https://server/ords/compression/compression/v1/recommendations?strategy_id=2&min_savings_pct=20"
-- ============================================================================

BEGIN
    ORDS.DEFINE_TEMPLATE(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'recommendations',
        p_priority       => 0,
        p_etag_type      => 'HASH',
        p_comments       => 'Get compression recommendations based on strategy'
    );

    ORDS.DEFINE_HANDLER(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'recommendations',
        p_method         => 'GET',
        p_source_type    => 'json/collection',
        p_items_per_page => 50,
        p_comments       => 'Retrieve compression candidates',
        p_source         => q'[
SELECT
    owner,
    object_name,
    object_type,
    partition_name,
    current_size_mb,
    estimated_compressed_mb,
    estimated_savings_mb,
    estimated_savings_pct,
    recommended_compression,
    compression_ratio,
    priority_score,
    strategy_name,
    compression_feasibility,
    compression_benefit,
    last_analyzed
FROM v_compression_candidates
WHERE (:strategy_id IS NULL OR strategy_id = :strategy_id)
  AND (:min_savings_pct IS NULL OR estimated_savings_pct >= :min_savings_pct)
  AND (:owner IS NULL OR owner = :owner)
ORDER BY priority_score DESC, estimated_savings_mb DESC
]'
    );

    -- Add parameters
    ORDS.DEFINE_PARAMETER(
        p_module_name        => 'compression_mgmt',
        p_pattern            => 'recommendations',
        p_method             => 'GET',
        p_name               => 'strategy_id',
        p_bind_variable_name => 'strategy_id',
        p_source_type        => 'QUERY',
        p_param_type         => 'INT',
        p_access_method      => 'INPUT'
    );

    ORDS.DEFINE_PARAMETER(
        p_module_name        => 'compression_mgmt',
        p_pattern            => 'recommendations',
        p_method             => 'GET',
        p_name               => 'min_savings_pct',
        p_bind_variable_name => 'min_savings_pct',
        p_source_type        => 'QUERY',
        p_param_type         => 'DOUBLE',
        p_access_method      => 'INPUT'
    );

    ORDS.DEFINE_PARAMETER(
        p_module_name        => 'compression_mgmt',
        p_pattern            => 'recommendations',
        p_method             => 'GET',
        p_name               => 'owner',
        p_bind_variable_name => 'owner',
        p_source_type        => 'QUERY',
        p_param_type         => 'STRING',
        p_access_method      => 'INPUT'
    );

    COMMIT;
END;
/

-- ============================================================================
-- ENDPOINT 3: POST /execute - Execute Compression Operation
-- ============================================================================
-- cURL Example:
-- curl -X POST "https://server/ords/compression/compression/v1/execute" \
--   -H "Content-Type: application/json" \
--   -d '{"owner":"SALES","object_name":"ORDERS","object_type":"TABLE","compression_type":"QUERY HIGH","online":"Y"}'
-- ============================================================================

BEGIN
    ORDS.DEFINE_TEMPLATE(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'execute',
        p_priority       => 0,
        p_etag_type      => 'HASH',
        p_comments       => 'Execute compression operation on a table or partition'
    );

    ORDS.DEFINE_HANDLER(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'execute',
        p_method         => 'POST',
        p_source_type    => 'plsql/block',
        p_mimes_allowed  => 'application/json',
        p_comments       => 'Compress table or partition',
        p_source         => q'[
DECLARE
    l_history_id NUMBER;
BEGIN
    -- Validate required parameters
    IF :owner IS NULL OR :object_name IS NULL OR :compression_type IS NULL THEN
        :status_code := 400;
        :response := JSON_OBJECT(
            'status' VALUE 'error',
            'message' VALUE 'Required parameters: owner, object_name, compression_type'
        );
        RETURN;
    END IF;

    -- Execute compression
    PKG_COMPRESSION_EXECUTOR.compress_table(
        p_owner            => :owner,
        p_table_name       => :object_name,
        p_partition_name   => :partition_name,
        p_compression_type => :compression_type,
        p_online           => NVL(:online, 'N')
    );

    -- Get the history record
    SELECT MAX(history_id) INTO l_history_id
    FROM t_compression_history
    WHERE owner = :owner
      AND object_name = :object_name
      AND NVL(partition_name, 'NULL') = NVL(:partition_name, 'NULL');

    :status_code := 200;
    :response := JSON_OBJECT(
        'status' VALUE 'success',
        'history_id' VALUE l_history_id,
        'owner' VALUE :owner,
        'object_name' VALUE :object_name,
        'partition_name' VALUE :partition_name,
        'compression_type' VALUE :compression_type,
        'online' VALUE NVL(:online, 'N'),
        'message' VALUE 'Compression operation completed successfully',
        'timestamp' VALUE TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS.FF3"Z"')
    );

EXCEPTION
    WHEN OTHERS THEN
        :status_code := 500;
        :response := JSON_OBJECT(
            'status' VALUE 'error',
            'message' VALUE SQLERRM,
            'sqlcode' VALUE SQLCODE,
            'details' VALUE JSON_OBJECT(
                'owner' VALUE :owner,
                'object_name' VALUE :object_name,
                'compression_type' VALUE :compression_type
            )
        );
END;
]'
    );
    COMMIT;
END;
/

-- ============================================================================
-- ENDPOINT 4: GET /history - Get Compression Execution History
-- ============================================================================
-- cURL Example:
-- curl "https://server/ords/compression/compression/v1/history?days_back=30&owner=SALES"
-- ============================================================================

BEGIN
    ORDS.DEFINE_TEMPLATE(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'history',
        p_priority       => 0,
        p_etag_type      => 'HASH',
        p_comments       => 'Get compression execution history'
    );

    ORDS.DEFINE_HANDLER(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'history',
        p_method         => 'GET',
        p_source_type    => 'json/collection',
        p_items_per_page => 50,
        p_comments       => 'Retrieve compression history records',
        p_source         => q'[
SELECT
    history_id,
    owner,
    object_name,
    object_type,
    partition_name,
    operation_type,
    compression_type,
    operation_status,
    size_before_mb,
    size_after_mb,
    space_saved_mb,
    compression_ratio,
    duration_seconds,
    online_operation,
    ddl_statement,
    error_message,
    execution_date
FROM v_compression_history
WHERE execution_date >= SYSTIMESTAMP - NUMTODSINTERVAL(NVL(:days_back, 30), 'DAY')
  AND (:owner IS NULL OR owner = :owner)
  AND (:status IS NULL OR operation_status = :status)
ORDER BY execution_date DESC
]'
    );

    -- Add parameters
    ORDS.DEFINE_PARAMETER(
        p_module_name        => 'compression_mgmt',
        p_pattern            => 'history',
        p_method             => 'GET',
        p_name               => 'days_back',
        p_bind_variable_name => 'days_back',
        p_source_type        => 'QUERY',
        p_param_type         => 'INT',
        p_access_method      => 'INPUT'
    );

    ORDS.DEFINE_PARAMETER(
        p_module_name        => 'compression_mgmt',
        p_pattern            => 'history',
        p_method             => 'GET',
        p_name               => 'owner',
        p_bind_variable_name => 'owner',
        p_source_type        => 'QUERY',
        p_param_type         => 'STRING',
        p_access_method      => 'INPUT'
    );

    ORDS.DEFINE_PARAMETER(
        p_module_name        => 'compression_mgmt',
        p_pattern            => 'history',
        p_method             => 'GET',
        p_name               => 'status',
        p_bind_variable_name => 'status',
        p_source_type        => 'QUERY',
        p_param_type         => 'STRING',
        p_access_method      => 'INPUT'
    );

    COMMIT;
END;
/

-- ============================================================================
-- ENDPOINT 5: GET /summary - Get Advisor Summary Dashboard
-- ============================================================================
-- cURL Example:
-- curl "https://server/ords/compression/compression/v1/summary"
-- ============================================================================

BEGIN
    ORDS.DEFINE_TEMPLATE(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'summary',
        p_priority       => 0,
        p_etag_type      => 'HASH',
        p_comments       => 'Get compression advisor summary metrics'
    );

    ORDS.DEFINE_HANDLER(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'summary',
        p_method         => 'GET',
        p_source_type    => 'json/collection',
        p_comments       => 'Retrieve dashboard summary',
        p_source         => q'[
SELECT
    metric_category,
    metric_name,
    metric_value,
    metric_unit,
    trend_indicator,
    last_updated
FROM v_advisor_summary
ORDER BY
    CASE metric_category
        WHEN 'Overview' THEN 1
        WHEN 'Savings Potential' THEN 2
        WHEN 'Execution Stats' THEN 3
        WHEN 'Performance' THEN 4
        ELSE 5
    END,
    metric_name
]'
    );
    COMMIT;
END;
/

-- ============================================================================
-- ENDPOINT 6: GET /strategies - List Available Compression Strategies
-- ============================================================================
-- cURL Example:
-- curl "https://server/ords/compression/compression/v1/strategies"
-- ============================================================================

BEGIN
    ORDS.DEFINE_TEMPLATE(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'strategies',
        p_priority       => 0,
        p_etag_type      => 'HASH',
        p_comments       => 'List available compression strategies'
    );

    ORDS.DEFINE_HANDLER(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'strategies',
        p_method         => 'GET',
        p_source_type    => 'json/collection',
        p_comments       => 'Retrieve compression strategies',
        p_source         => q'[
SELECT
    strategy_id,
    strategy_name,
    description,
    is_active,
    created_date,
    modified_date,
    JSON_OBJECT(
        'default_compression' VALUE default_compression,
        'priority_weights' VALUE JSON_OBJECT(
            'size_weight' VALUE size_weight,
            'access_weight' VALUE access_weight,
            'modification_weight' VALUE modification_weight
        )
    ) as configuration
FROM t_compression_strategies
WHERE :active_only IS NULL OR is_active = 'Y'
ORDER BY strategy_id
]'
    );

    -- Add parameter
    ORDS.DEFINE_PARAMETER(
        p_module_name        => 'compression_mgmt',
        p_pattern            => 'strategies',
        p_method             => 'GET',
        p_name               => 'active_only',
        p_bind_variable_name => 'active_only',
        p_source_type        => 'QUERY',
        p_param_type         => 'STRING',
        p_access_method      => 'INPUT'
    );

    COMMIT;
END;
/

-- ============================================================================
-- ENDPOINT 7: GET /strategy/:id/rules - Get Rules for Specific Strategy
-- ============================================================================
-- cURL Example:
-- curl "https://server/ords/compression/compression/v1/strategy/2/rules"
-- ============================================================================

BEGIN
    ORDS.DEFINE_TEMPLATE(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'strategy/:id/rules',
        p_priority       => 0,
        p_etag_type      => 'HASH',
        p_comments       => 'Get rules for a specific compression strategy'
    );

    ORDS.DEFINE_HANDLER(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'strategy/:id/rules',
        p_method         => 'GET',
        p_source_type    => 'json/collection',
        p_comments       => 'Retrieve strategy rules',
        p_source         => q'[
SELECT
    r.rule_id,
    r.rule_order,
    r.rule_name,
    r.condition_type,
    r.condition_value,
    r.compression_type,
    r.is_active,
    s.strategy_name,
    JSON_OBJECT(
        'priority' VALUE r.priority,
        'min_size_mb' VALUE r.min_size_mb,
        'max_size_mb' VALUE r.max_size_mb,
        'table_pattern' VALUE r.table_pattern,
        'exclude_pattern' VALUE r.exclude_pattern
    ) as rule_details
FROM t_strategy_rules r
JOIN t_compression_strategies s ON r.strategy_id = s.strategy_id
WHERE r.strategy_id = :id
  AND (:active_only IS NULL OR r.is_active = 'Y')
ORDER BY r.rule_order, r.priority DESC
]'
    );

    -- Add parameter
    ORDS.DEFINE_PARAMETER(
        p_module_name        => 'compression_mgmt',
        p_pattern            => 'strategy/:id/rules',
        p_method             => 'GET',
        p_name               => 'active_only',
        p_bind_variable_name => 'active_only',
        p_source_type        => 'QUERY',
        p_param_type         => 'STRING',
        p_access_method      => 'INPUT'
    );

    COMMIT;
END;
/

-- ============================================================================
-- ENDPOINT 8: POST /batch-execute - Execute Batch Compression
-- ============================================================================
-- cURL Example:
-- curl -X POST "https://server/ords/compression/compression/v1/batch-execute" \
--   -H "Content-Type: application/json" \
--   -d '{"strategy_id":2,"max_tables":10,"max_size_gb":100,"online":"Y"}'
-- ============================================================================

BEGIN
    ORDS.DEFINE_TEMPLATE(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'batch-execute',
        p_priority       => 0,
        p_etag_type      => 'HASH',
        p_comments       => 'Execute batch compression based on recommendations'
    );

    ORDS.DEFINE_HANDLER(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'batch-execute',
        p_method         => 'POST',
        p_source_type    => 'plsql/block',
        p_mimes_allowed  => 'application/json',
        p_comments       => 'Execute batch compression operations',
        p_source         => q'[
DECLARE
    l_strategy_id      NUMBER := NVL(:strategy_id, 2);
    l_max_tables       NUMBER := NVL(:max_tables, 10);
    l_max_size_gb      NUMBER := NVL(:max_size_gb, 100);
    l_online           VARCHAR2(1) := NVL(:online, 'N');
    l_objects_processed NUMBER := 0;
    l_total_savings_mb NUMBER := 0;
    l_success_count    NUMBER := 0;
    l_error_count      NUMBER := 0;

    CURSOR c_candidates IS
        SELECT owner, object_name, object_type, partition_name,
               recommended_compression, estimated_savings_mb
        FROM v_compression_candidates
        WHERE strategy_id = l_strategy_id
          AND current_size_mb <= (l_max_size_gb * 1024)
        ORDER BY priority_score DESC, estimated_savings_mb DESC
        FETCH FIRST l_max_tables ROWS ONLY;
BEGIN
    -- Validate strategy
    BEGIN
        SELECT strategy_id INTO l_strategy_id
        FROM t_compression_strategies
        WHERE strategy_id = l_strategy_id
          AND is_active = 'Y';
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            :status_code := 400;
            :response := JSON_OBJECT(
                'status' VALUE 'error',
                'message' VALUE 'Invalid or inactive strategy_id'
            );
            RETURN;
    END;

    -- Execute batch compression
    FOR rec IN c_candidates LOOP
        BEGIN
            PKG_COMPRESSION_EXECUTOR.compress_table(
                p_owner            => rec.owner,
                p_table_name       => rec.object_name,
                p_partition_name   => rec.partition_name,
                p_compression_type => rec.recommended_compression,
                p_online           => l_online
            );

            l_objects_processed := l_objects_processed + 1;
            l_success_count := l_success_count + 1;
            l_total_savings_mb := l_total_savings_mb + rec.estimated_savings_mb;

        EXCEPTION
            WHEN OTHERS THEN
                l_error_count := l_error_count + 1;
                -- Log error but continue processing
                NULL;
        END;
    END LOOP;

    :status_code := 200;
    :response := JSON_OBJECT(
        'status' VALUE 'success',
        'objects_processed' VALUE l_objects_processed,
        'success_count' VALUE l_success_count,
        'error_count' VALUE l_error_count,
        'total_estimated_savings_mb' VALUE ROUND(l_total_savings_mb, 2),
        'total_estimated_savings_gb' VALUE ROUND(l_total_savings_mb/1024, 2),
        'strategy_id' VALUE l_strategy_id,
        'online_mode' VALUE l_online,
        'message' VALUE 'Batch compression completed',
        'timestamp' VALUE TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS.FF3"Z"')
    );

EXCEPTION
    WHEN OTHERS THEN
        :status_code := 500;
        :response := JSON_OBJECT(
            'status' VALUE 'error',
            'message' VALUE SQLERRM,
            'sqlcode' VALUE SQLCODE,
            'objects_processed' VALUE l_objects_processed,
            'success_count' VALUE l_success_count,
            'error_count' VALUE l_error_count
        );
END;
]'
    );
    COMMIT;
END;
/

-- ============================================================================
-- Additional Utility Endpoints
-- ============================================================================

-- ============================================================================
-- ENDPOINT 9: GET /health - API Health Check
-- ============================================================================
-- cURL Example:
-- curl "https://server/ords/compression/compression/v1/health"
-- ============================================================================

BEGIN
    ORDS.DEFINE_TEMPLATE(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'health',
        p_priority       => 0,
        p_etag_type      => 'HASH',
        p_comments       => 'API health check endpoint'
    );

    ORDS.DEFINE_HANDLER(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'health',
        p_method         => 'GET',
        p_source_type    => 'plsql/block',
        p_comments       => 'Check API and database health',
        p_source         => q'[
DECLARE
    l_table_count NUMBER;
    l_last_run TIMESTAMP;
BEGIN
    -- Check if tables exist
    SELECT COUNT(*) INTO l_table_count
    FROM user_tables
    WHERE table_name IN ('T_COMPRESSION_ANALYSIS', 'T_COMPRESSION_HISTORY', 'T_COMPRESSION_STRATEGIES');

    -- Get last analysis run
    SELECT MAX(analysis_date) INTO l_last_run
    FROM t_compression_analysis;

    :status_code := 200;
    :response := JSON_OBJECT(
        'status' VALUE 'healthy',
        'api_version' VALUE '1.0',
        'database_schema' VALUE USER,
        'tables_installed' VALUE l_table_count,
        'last_analysis_run' VALUE TO_CHAR(l_last_run, 'YYYY-MM-DD"T"HH24:MI:SS.FF3"Z"'),
        'timestamp' VALUE TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS.FF3"Z"')
    );

EXCEPTION
    WHEN OTHERS THEN
        :status_code := 500;
        :response := JSON_OBJECT(
            'status' VALUE 'error',
            'message' VALUE SQLERRM
        );
END;
]'
    );
    COMMIT;
END;
/

-- ============================================================================
-- ENDPOINT 10: GET /metadata - API Metadata and Capabilities
-- ============================================================================
-- cURL Example:
-- curl "https://server/ords/compression/compression/v1/metadata"
-- ============================================================================

BEGIN
    ORDS.DEFINE_TEMPLATE(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'metadata',
        p_priority       => 0,
        p_etag_type      => 'HASH',
        p_comments       => 'API metadata and capabilities'
    );

    ORDS.DEFINE_HANDLER(
        p_module_name    => 'compression_mgmt',
        p_pattern        => 'metadata',
        p_method         => 'GET',
        p_source_type    => 'plsql/block',
        p_comments       => 'Get API capabilities and endpoint information',
        p_source         => q'[
BEGIN
    :status_code := 200;
    :response := JSON_OBJECT(
        'api_name' VALUE 'HCC Compression Advisor REST API',
        'version' VALUE '1.0',
        'base_path' VALUE '/compression/v1/',
        'schema' VALUE USER,
        'endpoints' VALUE JSON_ARRAY(
            JSON_OBJECT('method' VALUE 'POST', 'path' VALUE '/analyze', 'description' VALUE 'Trigger compression analysis'),
            JSON_OBJECT('method' VALUE 'GET', 'path' VALUE '/recommendations', 'description' VALUE 'Get compression recommendations'),
            JSON_OBJECT('method' VALUE 'POST', 'path' VALUE '/execute', 'description' VALUE 'Execute compression operation'),
            JSON_OBJECT('method' VALUE 'GET', 'path' VALUE '/history', 'description' VALUE 'Get execution history'),
            JSON_OBJECT('method' VALUE 'GET', 'path' VALUE '/summary', 'description' VALUE 'Get advisor summary'),
            JSON_OBJECT('method' VALUE 'GET', 'path' VALUE '/strategies', 'description' VALUE 'List compression strategies'),
            JSON_OBJECT('method' VALUE 'GET', 'path' VALUE '/strategy/:id/rules', 'description' VALUE 'Get strategy rules'),
            JSON_OBJECT('method' VALUE 'POST', 'path' VALUE '/batch-execute', 'description' VALUE 'Execute batch compression'),
            JSON_OBJECT('method' VALUE 'GET', 'path' VALUE '/health', 'description' VALUE 'Health check'),
            JSON_OBJECT('method' VALUE 'GET', 'path' VALUE '/metadata', 'description' VALUE 'API metadata')
        ),
        'compression_types' VALUE JSON_ARRAY(
            'BASIC',
            'OLTP',
            'QUERY LOW',
            'QUERY HIGH',
            'ARCHIVE LOW',
            'ARCHIVE HIGH'
        ),
        'timestamp' VALUE TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS.FF3"Z"')
    );
END;
]'
    );
    COMMIT;
END;
/

-- ============================================================================
-- Display Module Information
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT ORDS REST API Configuration Complete
PROMPT ============================================================================
PROMPT
PROMPT Module: compression_mgmt
PROMPT Base Path: /compression/v1/
PROMPT
PROMPT Available Endpoints:
PROMPT   POST   /analyze                - Trigger compression analysis
PROMPT   GET    /recommendations        - Get compression recommendations
PROMPT   POST   /execute                - Execute compression operation
PROMPT   GET    /history                - Get execution history
PROMPT   GET    /summary                - Get advisor summary
PROMPT   GET    /strategies             - List compression strategies
PROMPT   GET    /strategy/:id/rules     - Get strategy rules
PROMPT   POST   /batch-execute          - Execute batch compression
PROMPT   GET    /health                 - API health check
PROMPT   GET    /metadata               - API metadata
PROMPT
PROMPT Example URLs:
PROMPT   https://your-server/ords/compression/compression/v1/analyze
PROMPT   https://your-server/ords/compression/compression/v1/recommendations
PROMPT   https://your-server/ords/compression/compression/v1/summary
PROMPT
PROMPT ============================================================================
PROMPT

-- ============================================================================
-- Verification Query
-- ============================================================================

SELECT
    module_name,
    uri_prefix as base_path,
    status,
    items_per_page,
    comments
FROM user_ords_modules
WHERE module_name = 'compression_mgmt';

SELECT
    module_name,
    template_pattern as endpoint,
    COUNT(*) as handler_count
FROM user_ords_templates
WHERE module_name = 'compression_mgmt'
GROUP BY module_name, template_pattern
ORDER BY template_pattern;

PROMPT
PROMPT Verification complete. Review module and template configurations above.
PROMPT

-- ============================================================================
-- End of File: 06_ords.sql
-- ============================================================================
