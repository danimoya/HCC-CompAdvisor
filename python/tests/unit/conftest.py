"""
Unit-test fixtures shared by every module under tests/unit.
"""
import pytest

from hcc_advisor.utils import target_queries as tq


@pytest.fixture(autouse=True)
def _unknown_target_registry(monkeypatch):
    """Unit tests never reach the central target registry.

    execute_compression, rollback, the scheduler queue and the SQL script
    builder look a target's Oracle version / platform up with
    target_queries.target_ddl_info, which reads the central database. Here it
    reports an unknown target (modern DDL, platform unchecked), so tests that
    don't care see the pre-version-aware behaviour. Tests of version/platform
    rules patch it with their own target (see test_version_platform_ddl).
    """
    monkeypatch.setattr(tq, 'target_ddl_info',
                        lambda database_id: {'oracle_version': None, 'platform_type': None})
