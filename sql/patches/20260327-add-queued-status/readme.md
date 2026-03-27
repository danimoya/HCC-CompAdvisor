## Add QUEUED to operation_status check constraint

The Scheduler persistent queue stores pending items as QUEUED rows in
t_compression_history. The existing check constraint only allows
IN_PROGRESS/SUCCESS/FAILED/ROLLED_BACK/PARTIAL_SUCCESS.

This patch drops and recreates the constraint to include QUEUED.
