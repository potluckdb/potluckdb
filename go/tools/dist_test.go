package main

// Tests of the generator with made-up core archives; they need no
// PotluckDB release.

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const testVersion = "0.8.0-dev.7"

var testHeader = []byte("/* sqlite3.h */\n#define SQLITE_SOURCE_ID \"2026-10-16 14:45:20 555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6ca76\"\n")

// fakeArchive writes a core archive for t; withStatic adds the static
// library that Go links.
func fakeArchive(tb testing.TB, dir string, t target, withStatic bool) {
	tb.Helper()
	files := map[string][]byte{
		"LICENSE.txt":             []byte("PotluckDB binary licence\n"),
		"THIRD_PARTY_NOTICES.txt": []byte("SQLite is in the public domain\n"),
		"include/sqlite3.h":       testHeader,
		"include/sqlite3ext.h":    []byte("/* sqlite3ext.h */\n"),
		"include/potluckdb.h":     []byte("/* potluckdb.h */\n"),
	}
	if t.GOOS == "windows" {
		files["lib/static/sqlite3.lib"] = []byte("MSVC library")
	}
	if withStatic {
		files["lib/static/libsqlite3.a"] = []byte("!<arch>\n" + t.Name)
	}
	sums := map[string]string{}
	for name, data := range files {
		sum := sha256.Sum256(data)
		sums[name] = hex.EncodeToString(sum[:])
	}
	info, _ := json.Marshal(map[string]any{"target": t.Name, "potluckdb_version": testVersion,
		"sqlite_version": "3.54.1", "files": sums})
	files["BUILD-INFO.json"] = info

	name := t.Archive(testVersion)
	top := strings.TrimSuffix(strings.TrimSuffix(name, ".tar.gz"), ".zip") + "/"
	var b bytes.Buffer
	if strings.HasSuffix(name, ".zip") {
		zw := zip.NewWriter(&b)
		for p, data := range files {
			w, _ := zw.Create(top + p)
			w.Write(data)
		}
		zw.Close()
	} else {
		gz := gzip.NewWriter(&b)
		tw := tar.NewWriter(gz)
		for p, data := range files {
			tw.WriteHeader(&tar.Header{Name: top + p, Mode: 0o644, Size: int64(len(data)), Typeflag: tar.TypeReg})
			tw.Write(data)
		}
		tw.Close()
		gz.Close()
	}
	if err := os.WriteFile(filepath.Join(dir, name), b.Bytes(), 0o644); err != nil {
		tb.Fatal(err)
	}
}

func testGoDir(t *testing.T) string {
	dir, err := filepath.Abs("..")
	if err != nil {
		t.Fatal(err)
	}
	return dir
}

func read(t *testing.T, p string) string {
	t.Helper()
	data, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

// writeTestDist makes archives for every target (Windows ones with or
// without the MinGW library) and writes the distribution tree.
func writeTestDist(t *testing.T, windowsStatic bool) (string, *distResult) {
	t.Helper()
	cores := t.TempDir()
	for _, tg := range targets {
		fakeArchive(t, cores, tg, tg.GOOS != "windows" || windowsStatic)
	}
	out := filepath.Join(t.TempDir(), "potluckdb-go")
	res, err := writeDist(distOptions{Version: testVersion, CoreDir: cores, Out: out, GoDir: testGoDir(t)})
	if err != nil {
		t.Fatal(err)
	}
	return out, res
}

func TestDistAllPlatforms(t *testing.T) {
	out, res := writeTestDist(t, true)
	if len(res.Skipped) != 0 || len(res.Cores) != len(targets) {
		t.Fatalf("modules for %d targets, skipped %v", len(res.Cores), res.Skipped)
	}
	goMod := read(t, filepath.Join(out, "sqlite3", "go.mod"))
	for _, tg := range targets {
		lib := filepath.Join(out, "lib", tg.Name)
		if !strings.Contains(goMod, tg.Module(modulePrefix)+" v"+testVersion) {
			t.Errorf("driver go.mod does not require %s: %s", tg.Name, goMod)
		}
		if got := read(t, filepath.Join(lib, "libsqlite3.a")); got != "!<arch>\n"+tg.Name {
			t.Errorf("%s: libsqlite3.a = %q", tg.Name, got)
		}
		for _, f := range []string{"go.mod", "doc.go", "lib.go", "LICENSE.txt", "THIRD_PARTY_NOTICES.txt", "BUILD-INFO.json"} {
			if _, err := os.Stat(filepath.Join(lib, f)); err != nil {
				t.Error(err)
			}
		}
		if s := read(t, filepath.Join(lib, "lib.go")); !strings.Contains(s, "//go:build cgo && "+tg.Constraint) ||
			!strings.Contains(s, "#cgo LDFLAGS: ${SRCDIR}/libsqlite3.a") {
			t.Errorf("%s: lib.go:\n%s", tg.Name, s)
		}
		if s := read(t, filepath.Join(lib, "doc.go")); !strings.Contains(s, "const IsVersion0_8_0_dev_7 = true") {
			t.Errorf("%s: doc.go:\n%s", tg.Name, s)
		}
		drv := read(t, filepath.Join(out, "sqlite3", "potluckdb_lib_"+tg.Ident()+".go"))
		if !strings.Contains(drv, `import lib "`+tg.Module(modulePrefix)+`"`) || !strings.Contains(drv, "lib.IsVersion0_8_0_dev_7") {
			t.Errorf("%s: driver file:\n%s", tg.Name, drv)
		}
	}
	if got := read(t, filepath.Join(out, "sqlite3", "sqlite3-binding.h")); got != string(testHeader) {
		t.Errorf("sqlite3-binding.h is not the release's sqlite3.h")
	}
	for _, f := range []string{"sqlite3.go", "potluckdb.go", "LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "potluckdb.h"} {
		if _, err := os.Stat(filepath.Join(out, "sqlite3", f)); err != nil {
			t.Error(err)
		}
	}
	if _, err := os.Stat(filepath.Join(out, "sqlite3", ".gitignore")); err == nil {
		t.Error("the driver module holds go/sqlite3/.gitignore")
	}
}

// Today's archives have only an MSVC library for Windows: no Windows
// modules, and a Windows build stops with a message.
func TestDistWithoutWindowsLibrary(t *testing.T) {
	out, res := writeTestDist(t, false)
	if len(res.Skipped) != 2 || res.Skipped["windows-x64"] == "" || res.Skipped["windows-arm64"] == "" {
		t.Fatalf("skipped %v", res.Skipped)
	}
	if _, err := os.Stat(filepath.Join(out, "lib", "windows-x64")); err == nil {
		t.Error("wrote a windows-x64 module without its library")
	}
	if strings.Contains(read(t, filepath.Join(out, "sqlite3", "go.mod")), "windows") {
		t.Error("the driver requires a Windows module")
	}
	none := read(t, filepath.Join(out, "sqlite3", "potluckdb_lib_none.go"))
	if !strings.Contains(none, "!(windows && amd64)") == false || !strings.Contains(none, "#error") || strings.Contains(none, "windows/amd64") {
		t.Errorf("potluckdb_lib_none.go:\n%s", none)
	}
	if !strings.Contains(read(t, filepath.Join(out, "README.md")), "windows-x64:") {
		t.Error("README.md does not say that windows-x64 is missing")
	}
}

func TestDistRejectsWrongArchives(t *testing.T) {
	cores := t.TempDir()
	for _, tg := range targets {
		fakeArchive(t, cores, tg, true)
	}
	// A library that does not match BUILD-INFO.json.
	name := targets[0].Archive(testVersion)
	data, _ := os.ReadFile(filepath.Join(cores, name))
	sum := sha256.Sum256(data)
	sums := fmt.Sprintf("%s  %s\n", strings.Repeat("0", 64), name)
	os.WriteFile(filepath.Join(cores, "SHA256SUMS"), []byte(sums), 0o644)
	_, err := writeDist(distOptions{Version: testVersion, CoreDir: cores, Out: filepath.Join(t.TempDir(), "x"), GoDir: testGoDir(t)})
	if err == nil || !strings.Contains(err.Error(), "does not match SHA256SUMS") {
		t.Errorf("wrong SHA256SUMS: err = %v", err)
	}
	os.WriteFile(filepath.Join(cores, "SHA256SUMS"), []byte(fmt.Sprintf("%x  %s\n", sum, name)), 0o644)
	_, err = writeDist(distOptions{Version: "0.8.0-dev.8", CoreDir: cores, Out: filepath.Join(t.TempDir(), "x"), GoDir: testGoDir(t)})
	if err == nil {
		t.Error("archives of another version were accepted")
	}
	_, err = writeDist(distOptions{Version: "v0.8", CoreDir: cores, Out: filepath.Join(t.TempDir(), "x"), GoDir: testGoDir(t)})
	if err == nil {
		t.Error("a version that is not semver was accepted")
	}
}

func TestProxy(t *testing.T) {
	out, _ := writeTestDist(t, true)
	proxy := t.TempDir()
	modules, err := writeProxy(out, testVersion, proxy)
	if err != nil {
		t.Fatal(err)
	}
	if len(modules) != len(targets)+1 {
		t.Fatalf("modules: %v", modules)
	}
	at := filepath.Join(proxy, filepath.FromSlash(modulePrefix), "sqlite3", "@v")
	zr, err := zip.OpenReader(filepath.Join(at, "v"+testVersion+".zip"))
	if err != nil {
		t.Fatal(err)
	}
	defer zr.Close()
	prefix := modulePrefix + "/sqlite3@v" + testVersion + "/"
	for _, f := range zr.File {
		if !strings.HasPrefix(f.Name, prefix) || strings.Contains(f.Name, "libsqlite3.a") {
			t.Errorf("driver zip holds %s", f.Name)
		}
	}
	if got := read(t, filepath.Join(at, "list")); got != "v"+testVersion+"\n" {
		t.Errorf("list = %q", got)
	}
}

func TestCheckSQLite(t *testing.T) {
	ours := "2026-10-16 14:45:20 555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6ca76"
	other := "2025-06-06 14:52:32 b77dc5e0f596d2140d9ac682b2893ff65d3a4140aa86067a3efebe29dc914c95"
	lib := []byte("SQLite format 3\x00" + ours)
	facts := &binaryFacts{}
	checkSQLite(facts, []byte("x"+string(lib)), testHeader, lib)
	if len(facts.Problems) != 0 {
		t.Errorf("ours: %v", facts.Problems)
	}
	facts = &binaryFacts{}
	checkSQLite(facts, []byte(string(lib)+"SQLite format 3\x00"+other), testHeader, lib)
	if len(facts.Problems) != 2 {
		t.Errorf("two SQLites: %v", facts.Problems)
	}
	facts = &binaryFacts{}
	checkSQLite(facts, []byte("SQLite format 3\x00"+other), testHeader, lib)
	if len(facts.Problems) != 1 || !strings.Contains(facts.Problems[0], "does not hold PotluckDB's SQLite") {
		t.Errorf("their SQLite: %v", facts.Problems)
	}
}

func TestVerifySum(t *testing.T) {
	data := []byte("archive")
	sum := sha256.Sum256(data)
	good := fmt.Sprintf("%x  a.tar.gz\n%x *b.zip\n", sum, sum)
	if err := verifySum(data, "a.tar.gz", good, "x"); err != nil {
		t.Error(err)
	}
	if err := verifySum(data, "b.zip", good, "x"); err != nil {
		t.Error(err)
	}
	if err := verifySum(data, "c.zip", good, "x"); err == nil {
		t.Error("a file SHA256SUMS does not list passed")
	}
	if err := verifySum([]byte("other"), "a.tar.gz", good, "x"); err == nil {
		t.Error("a wrong checksum passed")
	}
}
