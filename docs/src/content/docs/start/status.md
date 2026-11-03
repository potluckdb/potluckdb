---
title: What works today
description: What the current pre-release does, and what comes next.
sidebar:
  order: 2
---

PotluckDB is built in small steps, each a whole, tested capability. The
[changelog](https://github.com/potluckdb/potluckdb/blob/main/CHANGELOG.md)
says what each release does.

**Today nothing syncs.** The current pre-releases are the SQLite drop-in
library and its language packages. 0.8.0-dev.1 to dev.3 had a first sync
engine and a `potluckdb` command for folders; both were removed, to be rebuilt
step by step as below.

| Version | What it adds |
| --- | --- |
| 0.8.0 | The SQLite drop-in library on Linux, macOS and Windows, installed from each language's registry. No sync |
| 0.8.1 | One device backs a folder up to a bucket; any version restores |
| 0.8.2 | A database in use backs up, and restores to any version |
| 0.8.3 | Other devices receive each version of a folder |
| 0.8.4 | A database syncs from one writing device to many; Python and Node.js add-ons |
| 0.8.5 | DuckDB does what SQLite does by 0.8.4 |
| 0.8.6 | Folders sync both ways |
| 0.8.7 | Optional encryption |
| 0.8.8 | Only changed pages travel |
| 0.8.9 | A new device answers before its download ends |
| 0.8.10 | Several devices write; no write is lost |
| 0.8.11 | Conflicting writes re-run by themselves |
| 0.8.12 | The same for DuckDB |
| 0.8.13 | Everything runs within one memory budget |
| 0.8.14 | iOS and Android |
| 0.8.15 | The browser |
| 0.8.16 | Every other language, JDBC and ODBC |
| 0.9.0 | Feature complete |
| 1.0.0 | Stable, for production use |
