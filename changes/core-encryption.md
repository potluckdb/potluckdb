type: added

Optional encryption: `potluckdb key new` makes a key file, and `potluckdb sync <folder> <bucket> --key-file <file>` encrypts everything stored in the bucket. Keys can be rotated with `potluckdb key rotate`; the bucket owner still sees object counts, sizes and timing.
