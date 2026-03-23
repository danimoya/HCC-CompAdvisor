## Allow NULL ADVISOR_RUN_ID in T_COMPRESSION_ANALYSIS

Quick Scan creates analysis results without a formal advisor run record.
This patch makes ADVISOR_RUN_ID nullable so Quick Scan can MERGE results
without violating the NOT NULL constraint.
