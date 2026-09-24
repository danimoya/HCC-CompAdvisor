"""
Hotness scoring for the HCC Compression Advisor.

Pure functions only (no database, no Streamlit), so the model can be unit
tested in isolation. ``TargetQueries`` fetches the raw activity counters from
the target database and calls :func:`compute_hotness` once per object.

Model (see :func:`compute_hotness` for the details)
----------------------------------------------------
The score is an ABSOLUTE 0-100 measure of how actively an object is used.
It does not depend on which other tables happen to be in the same scan.

* **Write rate** (rows/blocks changed per day) is the highest of:
    - DML counters from ``DBA/ALL_TAB_MODIFICATIONS`` divided by the days since
      ``LAST_ANALYZED`` (those counters reset whenever statistics are gathered,
      so a raw count is meaningless without its time window);
    - ``db block changes`` per day from ``V$SEGMENT_STATISTICS`` (since instance
      startup; unaffected by statistics gathering);
    - ``db block changes`` per day from AWR ``DBA_HIST_SEG_STAT`` (only when the
      Diagnostics Pack licence has been acknowledged).
  Each source can under-count (a stats gather resets the counters, AWR only
  keeps top-N segments per snapshot, V$ averages since startup), so the
  highest observed rate wins.
* **Read rate** (block reads per day) is the highest of logical + physical
  reads per day from ``V$SEGMENT_STATISTICS`` and from AWR.
* Rates map to intensities on a log scale: 1M DML/day and 1G block reads/day
  are the maximum. When ``NUM_ROWS`` is known, write intensity also takes
  churn into account (DML/day as a fraction of ``NUM_ROWS``), so 10K DML/day
  is hotter on a 50K-row table than on a 1B-row table.
* ``score = 100 * (1 - (1 - W) * (1 - 0.6 * R))``: writes can reach 100,
  reads alone reach at most 60 (WARM). Read-mostly data is still a good HCC
  QUERY candidate; HOT is reserved for objects that are also written.
  The score never goes down when any activity input goes up.

Categories match the ``HOTNESS_CATEGORY`` virtual column in the central
schema and the strategy thresholds: HOT >= 75, WARM >= 50, COOL >= 25,
COLD otherwise.
"""

import math
from datetime import date, datetime, time as dtime
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

# Category thresholds (keep in sync with T_COMPRESSION_ANALYSIS.HOTNESS_CATEGORY
# and T_COMPRESSION_STRATEGIES.HOTNESS_THRESHOLD_* defaults).
HOT_THRESHOLD = 75.0
WARM_THRESHOLD = 50.0
COOL_THRESHOLD = 25.0

# Absolute log-scale anchors (rate that maps to intensity 1.0).
WRITE_FULL_SCALE_PER_DAY = 1_000_000.0      # 1M DML/day ~ 12 changes/s sustained
READ_FULL_SCALE_PER_DAY = 1_000_000_000.0   # 1G block reads/day ~ 11.6K gets/s

# Churn: DML/day as a fraction of NUM_ROWS. 0.01%/day -> 0, 100%/day -> 1.
CHURN_FLOOR_PER_DAY = 1e-4
CHURN_WEIGHT = 0.4          # share of write intensity driven by churn

# Reads can push the score to at most READ_WEIGHT * 100 on their own.
READ_WEIGHT = 0.6

# Rate windows: never extrapolate from less than one hour of observation.
MIN_WINDOW_DAYS = 1.0 / 24.0
# Window assumed when it is unknown (e.g. table never analyzed). Short on
# purpose: over-estimating activity leads to lighter (safer) compression.
DEFAULT_WINDOW_DAYS = 1.0

SOURCE_DML = 'TAB_MODIFICATIONS'
SOURCE_SEGSTATS = 'V$SEGMENT_STATISTICS'
SOURCE_AWR = 'AWR'

_ZERO_DML = {'inserts': 0, 'updates': 0, 'deletes': 0}
_SEG_METRICS = ('logical_reads', 'physical_reads', 'block_changes')


# ----------------------------------------------------------------------------
# Small coercion helpers (tolerate None / NaN / Decimal / NaT from pandas)
# ----------------------------------------------------------------------------

def _num(value: Any) -> float:
    """Coerce a counter to a finite, non-negative float (None/NaN/junk -> 0)."""
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(f) or f < 0:
        return 0.0
    return f


def _optional_float(value: Any) -> Optional[float]:
    """Coerce to float, or None when missing/NaN (negative values are kept)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _name(value: Any) -> Optional[str]:
    """Normalize a dictionary name column: None/NaN/'' -> None."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value)
    return text or None


def _as_datetime(value: Any) -> Optional[datetime]:
    """datetime/date/pandas Timestamp -> naive datetime; None/NaT -> None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value != value:  # pandas NaT
            return None
        if value.tzinfo is not None:
            value = value.astimezone().replace(tzinfo=None)
        return value
    if isinstance(value, date):
        return datetime.combine(value, dtime.min)
    return None


def _window_days(explicit_days: Any, since: Any = None,
                 now: Optional[datetime] = None,
                 default_days: float = DEFAULT_WINDOW_DAYS) -> float:
    """Length of an observation window in days, clamped to MIN_WINDOW_DAYS.

    ``explicit_days`` (e.g. ``SYSDATE - LAST_ANALYZED`` computed on the
    target, which avoids app/DB clock skew) wins over ``now - since``.
    """
    days = _optional_float(explicit_days)
    if days is None:
        since_dt = _as_datetime(since)
        if since_dt is not None:
            now_dt = _as_datetime(now) or datetime.now()
            days = (now_dt - since_dt).total_seconds() / 86400.0
    if days is None:
        days = default_days
    return max(days, MIN_WINDOW_DAYS)


# ----------------------------------------------------------------------------
# Intensities and categories
# ----------------------------------------------------------------------------

def _log_intensity(rate: float, full_scale: float) -> float:
    """log10(1 + rate) / log10(1 + full_scale), clamped to [0, 1]."""
    if rate <= 0:
        return 0.0
    return min(1.0, math.log10(1.0 + rate) / math.log10(1.0 + full_scale))


def write_intensity(dml_per_day: Any, num_rows: Any = None) -> float:
    """Write intensity in [0, 1] from DML/day, blended with churn when
    NUM_ROWS is known (> 0). Non-decreasing in ``dml_per_day``."""
    rate = _num(dml_per_day)
    absolute = _log_intensity(rate, WRITE_FULL_SCALE_PER_DAY)
    rows = _num(num_rows)
    if rate <= 0 or rows <= 0:
        return absolute
    churn = rate / rows
    floor_log = math.log10(CHURN_FLOOR_PER_DAY)
    churn_intensity = min(1.0, max(0.0, (math.log10(churn) - floor_log) / -floor_log))
    return (1.0 - CHURN_WEIGHT) * absolute + CHURN_WEIGHT * churn_intensity


def read_intensity(reads_per_day: Any) -> float:
    """Read intensity in [0, 1] from block reads/day (absolute log scale)."""
    return _log_intensity(_num(reads_per_day), READ_FULL_SCALE_PER_DAY)


def combine_intensities(write: float, read: float) -> float:
    """0-100 score: ``100 * (1 - (1 - W) * (1 - READ_WEIGHT * R))``.

    Behaves like a probabilistic OR: either signal alone produces a non-zero
    score, both together score higher than either, and reads alone are capped
    at ``READ_WEIGHT * 100``. Rounded to 2 decimals (HOTNESS_SCORE NUMBER(5,2)).
    """
    w = min(1.0, max(0.0, write))
    r = min(1.0, max(0.0, read))
    score = 100.0 * (1.0 - (1.0 - w) * (1.0 - READ_WEIGHT * r))
    return round(min(100.0, max(0.0, score)), 2)


def hotness_category(score: Any) -> str:
    """HOT / WARM / COOL / COLD, identical to the central HOTNESS_CATEGORY column."""
    s = _num(score)
    if s >= HOT_THRESHOLD:
        return 'HOT'
    if s >= WARM_THRESHOLD:
        return 'WARM'
    if s >= COOL_THRESHOLD:
        return 'COOL'
    return 'COLD'


def _fmt_rate(value: float) -> str:
    for threshold, suffix in ((1e9, 'G'), (1e6, 'M'), (1e3, 'K')):
        if value >= threshold:
            return f"{value / threshold:.1f}{suffix}"
    if value >= 10 or value == 0:
        return f"{value:.0f}"
    return f"{value:.1f}"


# ----------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------

def compute_hotness(
    dml: Optional[Mapping[str, Any]] = None,
    *,
    num_rows: Any = None,
    last_analyzed: Any = None,
    dml_window_days: Any = None,
    segment_stats: Optional[Mapping[str, Any]] = None,
    awr_stats: Optional[Mapping[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Score how active an object (table, partition or subpartition) is.

    Every source argument uses the same convention: ``None`` means the source
    could not be read (no privilege / not licensed) and is ignored; a mapping
    (possibly all zeros) means the source was read and is evidence.

    Args:
        dml: ``{'inserts', 'updates', 'deletes'}`` from DBA/ALL_TAB_MODIFICATIONS
            (counted since the last statistics gather).
        num_rows: NUM_ROWS from the dictionary (enables the churn component).
        last_analyzed: LAST_ANALYZED; start of the DML counter window.
        dml_window_days: days since LAST_ANALYZED computed on the target
            (preferred over ``last_analyzed`` / ``now``).
        segment_stats: ``{'logical_reads', 'physical_reads', 'block_changes',
            'window_days'}`` from V$SEGMENT_STATISTICS (window = instance uptime).
        awr_stats: same shape, from DBA_HIST_SEG_STAT (window = AWR lookback).
        now: reference time for ``last_analyzed`` (defaults to ``datetime.now()``).

    Returns:
        dict with ``hotness_score`` (0-100, 2 decimals), ``hotness_category``,
        the DML counters, ``dml_per_day`` / ``reads_per_day`` (None when no
        source covers them), raw ``logical_reads`` / ``physical_reads``,
        ``read_ratio`` / ``write_ratio`` (fractions), the intensities,
        ``sources`` and a human-readable ``basis``.
    """
    sources = []
    write_rates = []
    read_rates = []

    counts = dict(_ZERO_DML)
    if dml is not None:
        sources.append(SOURCE_DML)
        counts = {k: int(_num(dml.get(k))) for k in _ZERO_DML}
    total_dml = sum(counts.values())
    if dml is not None:
        write_rates.append(total_dml / _window_days(dml_window_days, last_analyzed, now))

    logical_reads = physical_reads = None
    for label, stats in ((SOURCE_SEGSTATS, segment_stats), (SOURCE_AWR, awr_stats)):
        if stats is None:
            continue
        sources.append(label)
        window = _window_days(stats.get('window_days'))
        lr = _num(stats.get('logical_reads'))
        pr = _num(stats.get('physical_reads'))
        bc = _num(stats.get('block_changes'))
        # physical reads include direct-path / smart-scan reads that bypass
        # the buffer cache (and so never show up as logical reads)
        read_rates.append((lr + pr) / window)
        write_rates.append(bc / window)
        if logical_reads is None:
            logical_reads, physical_reads = int(lr), int(pr)

    dml_per_day = max(write_rates) if write_rates else None
    reads_per_day = max(read_rates) if read_rates else None

    w = write_intensity(dml_per_day, num_rows)
    r = read_intensity(reads_per_day)
    score = combine_intensities(w, r)

    read_ratio = write_ratio = None
    ops = (dml_per_day or 0.0) + (reads_per_day or 0.0)
    if ops > 0:
        read_ratio = round((reads_per_day or 0.0) / ops, 2)
        write_ratio = round((dml_per_day or 0.0) / ops, 2)

    if not sources:
        basis = 'activity data unavailable'
    elif not dml_per_day and not reads_per_day:
        basis = f"no DML or reads observed [{', '.join(sources)}]"
    else:
        parts = []
        if dml_per_day is not None:
            parts.append(f"{_fmt_rate(dml_per_day)} writes/day")
        if reads_per_day is not None:
            parts.append(f"{_fmt_rate(reads_per_day)} block reads/day")
        basis = f"{', '.join(parts)} [{', '.join(sources)}]"

    return {
        'hotness_score': score,
        'hotness_category': hotness_category(score),
        'inserts': counts['inserts'],
        'updates': counts['updates'],
        'deletes': counts['deletes'],
        'total_dml': total_dml,
        'dml_per_day': round(dml_per_day, 2) if dml_per_day is not None else None,
        'reads_per_day': round(reads_per_day, 2) if reads_per_day is not None else None,
        'logical_reads': logical_reads,
        'physical_reads': physical_reads,
        'read_ratio': read_ratio,
        'write_ratio': write_ratio,
        'write_intensity': round(w, 4),
        'read_intensity': round(r, 4),
        'sources': tuple(sources),
        'basis': basis,
    }


# ----------------------------------------------------------------------------
# Indexing of batch-fetched dictionary rows
# ----------------------------------------------------------------------------

def index_dml_rows(rows: Iterable[Mapping[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Index TAB_MODIFICATIONS rows (all levels) by (owner, table_name).

    Each row needs ``owner`` (or ``table_owner``), ``table_name``,
    ``partition_name``, ``subpartition_name``, ``inserts``, ``updates``,
    ``deletes``. Use :func:`lookup_dml` to read the result.
    """
    index: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in rows:
        owner = _name(row.get('owner', row.get('table_owner')))
        table = _name(row.get('table_name'))
        if not owner or not table:
            continue
        entry = index.setdefault((owner, table), {
            'table': None, 'partitions': {}, 'subpartitions': {}, 'children': {},
        })
        counts = {k: int(_num(row.get(k))) for k in _ZERO_DML}
        part = _name(row.get('partition_name'))
        sub = _name(row.get('subpartition_name'))
        if sub:
            entry['subpartitions'][sub] = counts
            if part:
                entry['children'].setdefault(part, []).append(counts)
        elif part:
            entry['partitions'][part] = counts
        else:
            entry['table'] = counts
    return index


def _sum_counts(items: Iterable[Mapping[str, int]]) -> Dict[str, int]:
    total = dict(_ZERO_DML)
    for c in items:
        for k in total:
            total[k] += c.get(k, 0)
    return total


def _max_counts(*candidates: Optional[Mapping[str, int]]) -> Dict[str, int]:
    out = dict(_ZERO_DML)
    for c in candidates:
        if c:
            for k in out:
                out[k] = max(out[k], c.get(k, 0))
    return out


def lookup_dml(index: Mapping[Tuple[str, str], Mapping[str, Any]], owner: str, table_name: str,
               partition_name: Optional[str] = None,
               subpartition_name: Optional[str] = None) -> Dict[str, int]:
    """DML counters for a table / partition / subpartition (zeros if none).

    A partitioned table's table-level row can be missing or lag behind its
    partition rows (e.g. after incremental or partition-level stats gathers),
    so each level takes, per counter, the maximum of its own row and the sum of
    its children.
    """
    entry = index.get((owner, table_name))
    if not entry:
        return dict(_ZERO_DML)
    if subpartition_name:
        return dict(entry['subpartitions'].get(subpartition_name, _ZERO_DML))
    if partition_name:
        return _max_counts(entry['partitions'].get(partition_name),
                           _sum_counts(entry['children'].get(partition_name, ())))
    return _max_counts(entry['table'],
                       _sum_counts(entry['partitions'].values()),
                       _sum_counts(entry['subpartitions'].values()))


def index_segment_rows(rows: Iterable[Mapping[str, Any]]) -> Dict[Tuple[str, str], Dict[Optional[str], Dict[str, float]]]:
    """Index per-segment activity rows (V$SEGMENT_STATISTICS / AWR) by
    (owner, object_name) -> {subobject_name or None: metrics}."""
    index: Dict[Tuple[str, str], Dict[Optional[str], Dict[str, float]]] = {}
    for row in rows:
        owner = _name(row.get('owner'))
        table = _name(row.get('object_name'))
        if not owner or not table:
            continue
        segs = index.setdefault((owner, table), {})
        sub = _name(row.get('subobject_name'))
        metrics = segs.setdefault(sub, {m: 0.0 for m in _SEG_METRICS})
        for m in _SEG_METRICS:
            metrics[m] += _num(row.get(m))
    return index


def lookup_segment(source: Mapping[str, Any], owner: str, table_name: str,
                   subobject_name: Optional[str] = None) -> Dict[str, float]:
    """Segment metrics plus ``window_days`` for one object.

    ``source`` is ``{'window_days': float, 'objects': index_segment_rows(...)}``.
    Table level (``subobject_name=None``) sums every segment of the table
    (partitions and subpartitions included). A partition or subpartition is
    looked up by its own name (unique within a table). Objects without a row
    get zeros: the source was read and saw no activity for them.
    """
    segs = (source.get('objects') or {}).get((owner, table_name), {})
    if subobject_name:
        picked = [segs[subobject_name]] if subobject_name in segs else []
    else:
        picked = list(segs.values())
    out = {m: sum(p.get(m, 0.0) for p in picked) for m in _SEG_METRICS}
    out['window_days'] = source.get('window_days')
    return out
