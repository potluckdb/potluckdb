# Third-party notices

PotluckDB for Node.js is licensed under Apache-2.0 (see `LICENSE`). Parts of it
come from the projects below, under their own licences.

## better-sqlite3 13.0.3

https://github.com/WiseLibs/better-sqlite3, commit
`dbc2ea1165fef1f599b9be12faea33fa5e9d7ffb`.

Taken from it, with changes: the JavaScript layer (`lib/`), the Node-API
addon source (`src/`), the test extension (`deps/test_extension.c`) and the
test suite (`test/better-sqlite3/test/`, unmodified).

```
The MIT License (MIT)

Copyright (c) 2017 Joshua Wise

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

## @types/better-sqlite3 9.6.0

https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/better-sqlite3

Taken from it, with changes: the TypeScript declarations (`index.d.ts`).

```
MIT License

Copyright (c) Microsoft Corporation.

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

The platform packages (`@potluckdb/<platform>`) contain PotluckDB's build of
SQLite, which is in the public domain. Their `THIRD_PARTY_NOTICES.txt` has the
notice, and their `LICENSE.txt` has the licence of the PotluckDB library.
