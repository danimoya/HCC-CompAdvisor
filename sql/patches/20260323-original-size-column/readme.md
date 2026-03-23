## Add ORIGINAL_SIZE_BYTES to T_COMPRESSION_ANALYSIS

Adds a column to preserve the original (uncompressed) segment size separately
from the current size. After compression, SIZE_BYTES reflects the current
(compressed) size while ORIGINAL_SIZE_BYTES retains the pre-compression size.

Also adds virtual columns SAVINGS_BYTES and SAVINGS_PCT for quick calculations.

Backfills ORIGINAL_SIZE_BYTES from t_compression_history.original_size_bytes
for objects that were already compressed.
