"""
Unit tests for the pure helpers at the top of hcc_advisor.utils.target_queries
that guard and normalise what goes into generated DDL and history rows:

- _validate_identifier / _validate_parallel_degree reject anything that could
  break out of the interpolated DDL;
- is_supported_compression_type / canonical_compression accept the spellings
  the app uses and make equivalent encodings (OLTP == ADVANCED) compare equal;
- the value coercions used on DataFrame rows (_blank_to_none, _safe_int,
  _safe_float, _lob_text, _py_datetime, _history_compression_type) and the
  audit user fallback (_acting_user).
"""
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from hcc_advisor.utils import target_queries as tq
from hcc_advisor.utils.target_queries import (
    SUPPORTED_COMPRESSION_TYPES, canonical_compression, is_supported_compression_type,
)


@pytest.mark.unit
class TestValidateIdentifier:

    @pytest.mark.parametrize('value', ['ORDERS', 'o', 'SYS_P1$#', 'A' * 128, 'Mixed_Case1'])
    def test_valid_names_are_returned(self, value):
        assert tq._validate_identifier(value) == value

    @pytest.mark.parametrize('value', [
        None, '', 'A' * 129, '1TABLE', '_TABLE', 'MY TABLE', 'APP.ORDERS', '"ORDERS"',
        "ORDERS'", 'ORDERS]', 'ORDERS\n', 'ORDERS;DROP', 42,
    ])
    def test_unsafe_values_raise(self, value):
        with pytest.raises(ValueError, match='Invalid Oracle partition'):
            tq._validate_identifier(value, 'partition')


@pytest.mark.unit
class TestValidateParallelDegree:

    @pytest.mark.parametrize('value, expected', [(1, 1), ('8', 8), (128, 128), (4.0, 4)])
    def test_valid(self, value, expected):
        assert tq._validate_parallel_degree(value) == expected

    @pytest.mark.parametrize('value', [0, -1, 129, '8; DROP', None, float('nan'), 'abc'])
    def test_invalid(self, value):
        with pytest.raises(ValueError, match='parallel_degree'):
            tq._validate_parallel_degree(value)


@pytest.mark.unit
class TestCompressionTypes:

    @pytest.mark.parametrize('value', sorted(SUPPORTED_COMPRESSION_TYPES) +
                             [' query high ', 'oltp', 'Archive_Low'])
    def test_supported(self, value):
        assert is_supported_compression_type(value) is True

    @pytest.mark.parametrize('value', [None, '', 'ADVANCED', 'ZSTD', 'QUERY-HIGH',
                                       'OLTP; DROP TABLE X'])
    def test_unsupported(self, value):
        assert is_supported_compression_type(value) is False

    @pytest.mark.parametrize('value, canonical', [
        ('ADVANCED', 'OLTP'), ('oltp', 'OLTP'), ('ADV_LOW', 'OLTP'), ('ADV_HIGH', 'OLTP'),
        ('BASIC', 'BASIC'),
        ('QUERY_LOW', 'QUERY LOW'), ('query high', 'QUERY HIGH'),
        ('ARCHIVE_LOW', 'ARCHIVE LOW'), (' ARCHIVE HIGH ', 'ARCHIVE HIGH'),
        (None, 'NONE'), ('', 'NONE'), ('NOCOMPRESS', 'NONE'), ('DISABLED', 'NONE'),
        ('zstd', 'ZSTD'),                     # unknown values pass through, upper-cased
    ])
    def test_canonical_compression(self, value, canonical):
        assert canonical_compression(value) == canonical

    def test_every_supported_type_has_a_canonical_label(self):
        for value in SUPPORTED_COMPRESSION_TYPES:
            assert canonical_compression(value) in (
                'NONE', 'BASIC', 'OLTP', 'QUERY LOW', 'QUERY HIGH', 'ARCHIVE LOW', 'ARCHIVE HIGH')

    @pytest.mark.parametrize('value, stored', [
        ('QUERY_HIGH', 'QUERY HIGH'), ('archive_low', 'ARCHIVE LOW'), ('OLTP', 'OLTP'),
        (' basic ', 'BASIC'), (None, ''),
    ])
    def test_history_compression_type(self, value, stored):
        assert tq._history_compression_type(value) == stored


@pytest.mark.unit
class TestValueCoercion:

    @pytest.mark.parametrize('value', [None, float('nan'), '', '  ', 'None', 'nan'])
    def test_blank_to_none(self, value):
        assert tq._blank_to_none(value) is None

    @pytest.mark.parametrize('value', ['P1', 0, 'NONE_PART'])
    def test_blank_to_none_keeps_values(self, value):
        assert tq._blank_to_none(value) == value

    @pytest.mark.parametrize('value, as_int, as_float', [
        (None, 0, 0.0), (float('nan'), 0, 0.0), (3, 3, 3.0), (2.7, 2, 2.7), ('5', 5, 5.0),
    ])
    def test_safe_int_and_float(self, value, as_int, as_float):
        assert tq._safe_int(value) == as_int
        assert tq._safe_float(value) == as_float

    def test_lob_text(self):
        class Lob:
            def __init__(self, text=None, fail=False):
                self.text, self.fail = text, fail

            def read(self):
                if self.fail:
                    raise RuntimeError('DPI-1080: connection was closed')
                return self.text

        assert tq._lob_text(None) is None
        assert tq._lob_text('') is None
        assert tq._lob_text('ORA-01652') == 'ORA-01652'
        assert tq._lob_text(Lob('x' * 5000)) == 'x' * 4000
        assert tq._lob_text(Lob('abc'), limit=2) == 'ab'
        assert tq._lob_text(Lob(fail=True)) is None

    def test_py_datetime(self):
        moment = datetime(2026, 9, 24, 12, 30)
        assert tq._py_datetime(None) is None
        assert tq._py_datetime(pd.NaT) is None
        converted = tq._py_datetime(pd.Timestamp(moment))
        assert converted == moment and type(converted) is datetime
        assert tq._py_datetime(moment) is moment
        assert tq._py_datetime([1, 2]) == [1, 2]   # not NA-checkable: returned as is

    def test_segment_label(self):
        assert tq._segment_label('APP', 'ORDERS') == 'APP.ORDERS'
        assert tq._segment_label('APP', 'ORDERS', 'P1') == 'APP.ORDERS partition P1'
        assert tq._segment_label('APP', 'ORDERS', 'P1', 'SP1') == 'APP.ORDERS subpartition SP1'


@pytest.mark.unit
class TestActingUser:

    def test_session_user(self, monkeypatch):
        monkeypatch.setattr(tq, 'st', SimpleNamespace(session_state={'username': 'operator'}))
        assert tq._acting_user() == 'operator'

    def test_long_name_is_truncated(self, monkeypatch):
        monkeypatch.setattr(tq, 'st', SimpleNamespace(session_state={'username': 'u' * 300}))
        assert tq._acting_user() == 'u' * 128

    @pytest.mark.parametrize('state', [{}, {'username': None}, {'username': ''}])
    def test_no_user_falls_back(self, monkeypatch, state):
        monkeypatch.setattr(tq, 'st', SimpleNamespace(session_state=state))
        assert tq._acting_user() == 'HCC_ADVISOR'

    def test_no_session_falls_back(self, monkeypatch):
        class NoSession:
            @property
            def session_state(self):
                raise RuntimeError('no script run context')
        monkeypatch.setattr(tq, 'st', NoSession())
        assert tq._acting_user() == 'HCC_ADVISOR'
