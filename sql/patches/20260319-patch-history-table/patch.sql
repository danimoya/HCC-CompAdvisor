DECLARE
    v_exists NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_exists FROM user_tables WHERE table_name = 'T_PATCH_HISTORY';
    IF v_exists = 0 THEN
        EXECUTE IMMEDIATE '
            CREATE TABLE T_PATCH_HISTORY (
                patch_id      NUMBER GENERATED ALWAYS AS IDENTITY,
                patch_name    VARCHAR2(200) NOT NULL,
                applied_date  TIMESTAMP DEFAULT SYSTIMESTAMP,
                applied_by    VARCHAR2(100) DEFAULT USER,
                status        VARCHAR2(20),
                error_message VARCHAR2(4000),
                CONSTRAINT PK_PATCH_HISTORY PRIMARY KEY (patch_id)
            )
        ';
        DBMS_OUTPUT.PUT_LINE('T_PATCH_HISTORY created');
    ELSE
        DBMS_OUTPUT.PUT_LINE('T_PATCH_HISTORY already exists');
    END IF;
END;
