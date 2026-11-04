---
title: Platforms
description: The platforms PotluckDB is built for, and the archive for each.
---

| Platform | Archive | Runs on |
| --- | --- | --- |
| Linux x64 (glibc) | `linux-x64-gnu.tar.gz` | glibc 2.28 and newer |
| Linux ARM64 (glibc) | `linux-arm64-gnu.tar.gz` | glibc 2.28 and newer |
| Linux x64 (musl) | `linux-x64-musl.tar.gz` | Alpine and other musl systems |
| Linux ARM64 (musl) | `linux-arm64-musl.tar.gz` | Alpine and other musl systems |
| macOS, Apple silicon | `macos-arm64.tar.gz` | macOS 11 and newer |
| macOS, Intel | `macos-x64.tar.gz` | macOS 11 and newer |
| Windows x64 | `windows-x64.zip` | Windows 10 and newer |
| Windows ARM64 | `windows-arm64.zip` | Windows 11 |

Archive names are `potluckdb-sqlite-<version>-<platform>`. iOS, Android and
the browser follow during the 0.8 series.

The Windows archives hold two static libraries: `lib/static/sqlite3.lib` for
Microsoft's compiler, and `lib/static/libsqlite3.a` for MinGW-w64 compilers
(which Go uses). `libsqlite3.a` is tested with MinGW-w64 compilers for
Microsoft's UCRT runtime (llvm-mingw, GCC) and for the older MSVCRT runtime
(GCC, x64): the results are the same with either.
