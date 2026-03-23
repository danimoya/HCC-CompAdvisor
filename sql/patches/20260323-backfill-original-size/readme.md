## Backfill ORIGINAL_SIZE_BYTES from compression history

For objects that were compressed before the ORIGINAL_SIZE_BYTES column existed,
this patch recovers the pre-compression size from the earliest
`t_compression_history.original_size_bytes` record for each object.

**Prerequisite:** Patch `20260323-original-size-column` must be applied first.
