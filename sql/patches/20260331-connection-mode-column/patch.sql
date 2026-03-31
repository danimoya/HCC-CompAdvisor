DECLARE
    v_exists NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_exists FROM user_tab_columns
    WHERE table_name = 'T_TARGET_DATABASES' AND column_name = 'CONNECTION_MODE';
    IF v_exists = 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE t_target_databases ADD (connection_mode VARCHAR2(10) DEFAULT ''NORMAL'')';
    END IF;
END;
