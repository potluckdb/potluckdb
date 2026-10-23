# Third-party notices

PotluckDB for Go is licensed under Apache-2.0 (see `LICENSE`). Parts of it
come from the projects below, under their own licences.

## go-sqlite3 1.14.52

https://github.com/mattn/go-sqlite3, version v1.14.52 (commit
`b0be46fa28d17ee0b65c79774ac0dad84b6db068`).

Taken from it, with changes: the driver's Go and C sources and its tests
(`sqlite3/`, every file except `potluckdb*.go` and the generated files).
Where those files' headers mention "the LICENSE file", they mean the licence
below.

```
The MIT License (MIT)

Copyright (c) 2014 Yasuhiro Matsumoto

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## SQLite

The driver module holds SQLite's header (`sqlite3-binding.h`, which is
PotluckDB's `sqlite3.h`), and the library modules
(`github.com/potluckdb/potluckdb-go/lib/<platform>`) hold PotluckDB's build
of SQLite. SQLite is in the public domain. Each library module's
`THIRD_PARTY_NOTICES.txt` has the notice, and its `LICENSE.txt` has the
licence of the PotluckDB library.
