## Remove stale composite partition rows from T_COMPRESSION_ANALYSIS

Old scans created PARTITION-type rows for composite partitions which cannot
be compressed directly (ORA-14257). These rows should not exist — only their
SUBPARTITION children are valid compression targets.

This patch deletes PARTITION rows that have corresponding SUBPARTITION rows
for the same table, indicating they are composite partitions.
