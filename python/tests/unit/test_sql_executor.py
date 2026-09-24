"""
Unit tests for the SQL*Plus-aware script splitter and runner
(hcc_advisor.utils.sql_executor), used by the schema install and the SQL
patch applier.

- parse_sql_text drops SQL*Plus directives and comments, splits statements on
  a trailing ';' (or a '/' line), keeps DECLARE/BEGIN blocks whole up to the
  '/' line (semicolons, blank lines and comments inside included) and
  classifies each statement.
- Directive words are only directives between statements: a SET line of an
  UPDATE / MERGE or an EXIT WHEN inside a block is kept (the shipped
  backfill-original-size patch lost its MERGE ... SET clause before).
- execute_sql_file runs every statement, fetches SELECTs, commits DML, counts
  errors and stops at the first one only when asked.
- The shipped central schema parses into executable statements only.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hcc_advisor.utils.sql_executor import execute_sql_file, parse_sql_file, parse_sql_text

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.unit
class TestParseSqlText:

    def test_directives_and_comments_are_dropped(self):
        script = """
SET SERVEROUTPUT ON
SET ECHO OFF
PROMPT Creating tables...
SPOOL install.log
WHENEVER SQLERROR EXIT FAILURE
DEFINE owner = HR
COLUMN name FORMAT a30
@@other_script.sql
-- a line comment
/* a one-line block comment */
/*
   a multi-line
   block comment; with a semicolon
*/
CREATE TABLE t (id NUMBER);
SHOW ERRORS
SPOOL OFF
EXIT
"""
        assert parse_sql_text(script) == [('DDL', 'CREATE TABLE t (id NUMBER)')]

    def test_multi_line_statement_ends_at_trailing_semicolon(self):
        script = "INSERT INTO t (a, b)\n  VALUES (1,\n          'x');\nSELECT * FROM t;\n"
        assert parse_sql_text(script) == [
            ('DML', "INSERT INTO t (a, b)\n  VALUES (1,\n          'x')"),
            ('SELECT', 'SELECT * FROM t'),
        ]

    def test_semicolon_inside_a_line_does_not_split(self):
        script = "COMMENT ON TABLE t IS 'a;b';\n"
        assert parse_sql_text(script) == [('DDL', "COMMENT ON TABLE t IS 'a;b'")]

    @pytest.mark.parametrize('statement, kind', [
        ('CREATE INDEX i ON t (a)', 'DDL'),
        ('alter table t add (c number)', 'DDL'),
        ('DROP TABLE t', 'DDL'),
        ('GRANT SELECT ON t TO r', 'DDL'),
        ('REVOKE SELECT ON t FROM r', 'DDL'),
        ('TRUNCATE TABLE t', 'DDL'),
        ('INSERT INTO t VALUES (1)', 'DML'),
        ('UPDATE t SET a = 1', 'DML'),
        ('DELETE FROM t', 'DML'),
        ('MERGE INTO t USING s ON (t.id = s.id) WHEN MATCHED THEN UPDATE SET t.a = s.a', 'DML'),
        ('select 1 from dual', 'SELECT'),
        ('COMMIT', 'COMMIT'),
        ('COMMENT ON COLUMN t.a IS \'x\'', 'DDL'),   # anything else runs as DDL
    ])
    def test_classification(self, statement, kind):
        assert parse_sql_text(statement + ';') == [(kind, statement)]

    def test_plsql_block_is_kept_whole(self):
        script = """CREATE TABLE a (id NUMBER);
DECLARE
  v NUMBER;

  -- comment inside the block is kept
BEGIN
  SELECT COUNT(*) INTO v FROM a;
  IF v = 0 THEN
    INSERT INTO a VALUES (1);
  END IF;
END;
/
BEGIN
  NULL;
END;
/
COMMIT;
"""
        statements = parse_sql_text(script)
        assert [kind for kind, _ in statements] == ['DDL', 'PLSQL', 'PLSQL', 'COMMIT']
        block = statements[1][1]
        assert block.startswith('DECLARE') and block.endswith('END;')
        assert '-- comment inside the block is kept' in block
        assert 'INSERT INTO a VALUES (1);' in block
        assert statements[2][1] == 'BEGIN\n  NULL;\nEND;'

    def test_plsql_block_flushes_a_pending_statement(self):
        script = "CREATE TABLE a (id NUMBER)\nBEGIN\n  NULL;\nEND;\n/\n"
        assert parse_sql_text(script) == [
            ('DDL', 'CREATE TABLE a (id NUMBER)'),
            ('PLSQL', 'BEGIN\n  NULL;\nEND;'),
        ]

    def test_unterminated_input_is_flushed_at_the_end(self):
        assert parse_sql_text("SELECT 1 FROM dual") == [('SELECT', 'SELECT 1 FROM dual')]
        assert parse_sql_text("BEGIN\n  NULL;\nEND;") == [('PLSQL', 'BEGIN\n  NULL;\nEND;')]

    def test_stray_slash_and_empty_input(self):
        assert parse_sql_text("/\nCOMMIT;\n/\n") == [('COMMIT', 'COMMIT')]
        assert parse_sql_text('') == []
        assert parse_sql_text('-- only a comment\n\n') == []

    def test_directive_words_inside_a_statement_are_sql(self):
        """SET / EXIT / HOST at the start of a line are SQL*Plus commands only
        between statements; inside one they are SQL and must be kept (they
        used to be dropped, breaking UPDATE ... SET and EXIT WHEN)."""
        script = """SET ECHO OFF
UPDATE t
SET a = 1
WHERE b = 2;
SELECT id,
       host
FROM servers;
BEGIN
  LOOP
    EXIT WHEN done;
  END LOOP;
  UPDATE t
     SET a = 2;
END;
/
EXIT
"""
        assert parse_sql_text(script) == [
            ('DML', 'UPDATE t\nSET a = 1\nWHERE b = 2'),
            ('SELECT', 'SELECT id,\n       host\nFROM servers'),
            ('PLSQL', 'BEGIN\n  LOOP\n    EXIT WHEN done;\n  END LOOP;\n'
                      '  UPDATE t\n     SET a = 2;\nEND;'),
        ]

    def test_slash_ends_a_statement_without_semicolon(self):
        script = "SELECT 1 FROM dual\n/\nSET ECHO OFF\nSELECT 2 FROM dual\n/\n"
        assert parse_sql_text(script) == [('SELECT', 'SELECT 1 FROM dual'),
                                          ('SELECT', 'SELECT 2 FROM dual')]

    def test_backfill_patch_keeps_its_merge_set_clause(self):
        patch = _REPO_ROOT / 'sql' / 'patches' / '20260323-backfill-original-size' / 'patch.sql'
        (kind, merge), (_, commit) = parse_sql_file(patch)
        assert (kind, commit) == ('DML', 'COMMIT')
        assert 'WHEN MATCHED THEN UPDATE\n    SET a.original_size_bytes = h.original_size_bytes' \
            in merge

    def test_parse_sql_file_reads_utf8(self, tmp_path):
        path = tmp_path / 'script.sql'
        path.write_text("INSERT INTO t VALUES ('café');\n", encoding='utf-8')
        assert parse_sql_file(path) == [('DML', "INSERT INTO t VALUES ('café')")]

    def test_central_schema_parses_into_executable_statements(self):
        statements = parse_sql_file(_REPO_ROOT / 'sql' / 'central' / '01_central_schema.sql')
        assert len(statements) > 10
        for kind, text in statements:
            assert kind in ('DDL', 'DML', 'PLSQL', 'SELECT', 'COMMIT')
            first = text.split(None, 1)[0].upper()
            assert first not in ('SET', 'PROMPT', 'SPOOL', 'WHENEVER', 'EXIT', '@@', '/')
            if kind != 'PLSQL':
                assert not text.endswith(';')


class _Cursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql):
        self.conn.executed.append(sql)
        if sql in self.conn.fail:
            raise RuntimeError(f"ORA-00942: table or view does not exist ({sql})")

    def fetchall(self):
        self.conn.fetched += 1
        return []

    def close(self):
        pass


class _Conn:
    def __init__(self, fail=()):
        self.fail = set(fail)
        self.executed = []
        self.fetched = 0
        self.commits = 0

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1


@pytest.mark.unit
class TestExecuteSqlFile:

    @pytest.fixture
    def script(self, tmp_path):
        path = tmp_path / 'install.sql'
        path.write_text(
            "SET ECHO OFF\n"
            "CREATE TABLE t (id NUMBER);\n"
            "INSERT INTO t VALUES (1);\n"
            "SELECT * FROM missing;\n"
            "BEGIN\n  NULL;\nEND;\n/\n"
            "COMMIT;\n")
        return path

    def test_runs_everything_and_reports_progress(self, script):
        conn = _Conn()
        progress = MagicMock()

        ok, errors, messages = execute_sql_file(conn, script, on_progress=progress)

        assert (ok, errors) == (5, 0)
        assert conn.executed[0] == 'CREATE TABLE t (id NUMBER)'
        assert conn.fetched == 1          # the SELECT is fetched
        assert conn.commits == 2          # after the INSERT and the COMMIT
        assert messages[0] == '[OK] DDL: CREATE TABLE t (id NUMBER)'
        assert progress.call_args_list[0].args[:3] == (0, 5, 'DDL')
        assert progress.call_args_list[-1].args == (5, 5, 'DONE', 'Completed: 5 ok, 0 errors')

    def test_errors_are_counted_and_execution_continues(self, script):
        conn = _Conn(fail={'SELECT * FROM missing'})
        ok, errors, messages = execute_sql_file(conn, script)
        assert (ok, errors) == (4, 1)
        assert len(conn.executed) == 5
        assert any(m.startswith('[ERROR] SELECT: SELECT * FROM missing -> ORA-00942')
                   for m in messages)

    def test_stop_on_error(self, script):
        conn = _Conn(fail={'SELECT * FROM missing'})
        ok, errors, _ = execute_sql_file(conn, script, stop_on_error=True)
        assert (ok, errors) == (2, 1)
        assert conn.executed[-1] == 'SELECT * FROM missing'
