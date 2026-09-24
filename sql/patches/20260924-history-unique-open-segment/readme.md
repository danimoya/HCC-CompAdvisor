## One open row per segment in T_COMPRESSION_HISTORY (recommended)

Two users adding the same segment to the Scheduler queue at the same instant
could both pass the "already QUEUED / IN_PROGRESS?" check and queue it twice
(the second copy then ran a second MOVE after the first). A direct compression
of a segment that was already queued or running could also start a second MOVE.

This patch creates a function-based unique index, `UNQ_HISTORY_OPEN_SEGMENT`,
that only covers open rows:

```sql
CREATE UNIQUE INDEX UNQ_HISTORY_OPEN_SEGMENT ON T_COMPRESSION_HISTORY(
    CASE WHEN OPERATION_STATUS IN ('QUEUED', 'IN_PROGRESS') THEN DATABASE_ID END,
    CASE WHEN OPERATION_STATUS IN ('QUEUED', 'IN_PROGRESS') THEN OWNER END,
    CASE WHEN OPERATION_STATUS IN ('QUEUED', 'IN_PROGRESS') THEN OBJECT_NAME END,
    CASE WHEN OPERATION_STATUS IN ('QUEUED', 'IN_PROGRESS') THEN NVL(PARTITION_NAME, '~') END,
    CASE WHEN OPERATION_STATUS IN ('QUEUED', 'IN_PROGRESS') THEN NVL(SUBPARTITION_NAME, '~') END
)
```

Closed rows (SUCCESS, FAILED, ROLLED_BACK, PARTIAL_SUCCESS) have an all-NULL
key, which Oracle does not index, so history never collides. Claiming a queued
row (QUEUED to IN_PROGRESS) and putting it back are updates of the same row and
keep its key; closing a row frees the key. The application also works without
this patch, with a check that is not race-free. With the patch, a racing
second add is counted as "already queued or running", and a direct compression
of such a segment is refused before any MOVE runs.

**Existing duplicate open rows** are handled before the index is created. No
row is deleted:

- **Extra QUEUED copies of a segment** (nothing has run for them yet) are
  marked FAILED with the message "Duplicate open row closed by patch
  20260924-history-unique-open-segment: history_id N is already queued or
  running for this segment". The row kept is the segment's IN_PROGRESS row, or
  else its oldest QUEUED row (its place in the queue).
- **A segment with more than one IN_PROGRESS row**: the patch fails and changes
  nothing. The error lists the segments and their history_ids. These rows may
  still have a scheduler job or MOVE running, and closing one would lose its
  real outcome. Wait until they finish, run **Scheduler > Reconcile stale
  operations** (or mark the stale rows FAILED by hand), then apply the patch
  again.

Creating the index needs a short lock on T_COMPRESSION_HISTORY. If it fails
with ORA-00054 (resource busy) or ORA-01452 (a duplicate was added while the
patch ran), apply it again.

The central schema script (`sql/central/01_central_schema.sql`) creates the
same index on fresh installs, so this patch is detected as applied there.
