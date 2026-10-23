# Vendored pysqlite3 sources

The C sources of the `potluckdb._sqlite3` extension come from pysqlite3.

| | |
| --- | --- |
| Project | pysqlite3, https://github.com/coleifer/pysqlite3 (https://pypi.org/project/pysqlite3/) |
| Version | 0.6.0 |
| Taken from | https://files.pythonhosted.org/packages/fa/84/6e586bef5f6337dee60066eef752c73fa6fcb93c1e7997b550d3105ed4f9/pysqlite3-0.6.0.tar.gz |
| sha256 of that file | `ecf5112b62a4e6c04438957e343fe9672707bd3191f789ecae6c95b226aa6bb6` (matches PyPI) |
| Files taken | `src/*.c`, `src/*.h` and `LICENSE` |
| Licence | zlib (`LICENSE`; the same text heads every source file) |

pysqlite3's `pyproject.toml` says `license = "MIT"`, but its `LICENSE` file and
every source file carry the zlib licence text; the zlib text is what applies.

## Modifications

None yet: these are the files exactly as released.
