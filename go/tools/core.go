package main

// Reading the PotluckDB core archives (potluckdb-sqlite-<version>-<target>
// .tar.gz or .zip), the files the Go modules are made from.
//
// Where the archives come from:
//   - POTLUCKDB_CORE_DIR (or -core): a folder holding them, checked against
//     its SHA256SUMS if it has one;
//   - otherwise the GitHub release v<version> of potluckdb/potluckdb,
//     checked against the release's SHA256SUMS and cached in .cache/.

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strings"
)

const releases = "https://github.com/potluckdb/potluckdb/releases/download"

// A core is the unpacked content of one archive that the Go modules need.
type core struct {
	Target  target
	Version string
	SQLite  string            // SQLite version, from BUILD-INFO.json
	Files   map[string][]byte // path in the archive (without its top folder) -> content
	Static  string            // the static library's path in the archive
}

type buildInfo struct {
	Target           string            `json:"target"`
	PotluckDBVersion string            `json:"potluckdb_version"`
	SQLiteVersion    string            `json:"sqlite_version"`
	Files            map[string]string `json:"files"`
}

// wanted are the files the modules are made from, with the static library
// (staticLib).
var wanted = []string{
	"BUILD-INFO.json",
	"LICENSE.txt",
	"THIRD_PARTY_NOTICES.txt",
	"include/sqlite3.h",
	"include/potluckdb.h",
}

// loadCores reads the archives of the given targets. A target whose
// archive has no static library that Go can link is left out, with the
// reason in skipped.
func loadCores(version, dir string, ts []target) (cores []*core, skipped map[string]string, err error) {
	skipped = map[string]string{}
	for _, t := range ts {
		c, err := loadCore(version, dir, t)
		var noLib errNoStaticLib
		if errors.As(err, &noLib) {
			skipped[t.Name] = noLib.Error()
			continue
		}
		if err != nil {
			return nil, nil, err
		}
		cores = append(cores, c)
	}
	if len(cores) == 0 {
		return nil, nil, fmt.Errorf("no target has a static library Go can link: %v", skipped)
	}
	// Every module is built from the same headers.
	for _, c := range cores[1:] {
		for _, f := range []string{"include/sqlite3.h", "include/potluckdb.h"} {
			if !bytes.Equal(c.Files[f], cores[0].Files[f]) {
				return nil, nil, fmt.Errorf("%s differs between %s and %s", f, cores[0].Target.Name, c.Target.Name)
			}
		}
	}
	return cores, skipped, nil
}

type errNoStaticLib struct{ archive string }

func (e errNoStaticLib) Error() string {
	return fmt.Sprintf("%s has no static library that cgo can link (lib/static/libsqlite3.a)", e.archive)
}

func loadCore(version, dir string, t target) (*core, error) {
	name := t.Archive(version)
	data, err := readArchive(version, dir, name)
	if err != nil {
		return nil, err
	}
	members, err := unpack(name, data)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", name, err)
	}
	c := &core{Target: t, Version: version, Files: map[string][]byte{}}
	var info buildInfo
	if err := json.Unmarshal(members["BUILD-INFO.json"], &info); err != nil {
		return nil, fmt.Errorf("%s: BUILD-INFO.json: %w", name, err)
	}
	if info.Target != t.Name || info.PotluckDBVersion != version {
		return nil, fmt.Errorf("%s holds %s %s, not %s %s", name, info.Target, info.PotluckDBVersion, t.Name, version)
	}
	c.SQLite = info.SQLiteVersion
	for _, f := range wanted {
		if err := c.take(members, info, f); err != nil {
			return nil, fmt.Errorf("%s: %w", name, err)
		}
	}
	if _, ok := members[staticLib]; !ok {
		return nil, errNoStaticLib{name}
	}
	if err := c.take(members, info, staticLib); err != nil {
		return nil, fmt.Errorf("%s: %w", name, err)
	}
	c.Static = staticLib
	return c, nil
}

// take copies an archive member, checking it against BUILD-INFO.json
// (BUILD-INFO.json itself excepted).
func (c *core) take(members map[string][]byte, info buildInfo, f string) error {
	data, ok := members[f]
	if !ok {
		return fmt.Errorf("has no %s", f)
	}
	if f != "BUILD-INFO.json" {
		sum := sha256.Sum256(data)
		if want := info.Files[f]; want != hex.EncodeToString(sum[:]) {
			return fmt.Errorf("%s does not match its SHA-256 in BUILD-INFO.json", f)
		}
	}
	c.Files[f] = data
	return nil
}

func (c *core) sha256(f string) string {
	sum := sha256.Sum256(c.Files[f])
	return hex.EncodeToString(sum[:])
}

// readArchive returns an archive's bytes, checked against SHA256SUMS.
func readArchive(version, dir, name string) ([]byte, error) {
	if dir != "" {
		data, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			return nil, fmt.Errorf("POTLUCKDB_CORE_DIR=%s: %w", dir, err)
		}
		if sums, err := os.ReadFile(filepath.Join(dir, "SHA256SUMS")); err == nil {
			if err := verifySum(data, name, string(sums), dir); err != nil {
				return nil, err
			}
		}
		return data, nil
	}
	cache := filepath.Join(goDir(), ".cache", "downloads", version)
	if data, err := os.ReadFile(filepath.Join(cache, name)); err == nil {
		return data, nil
	}
	base := fmt.Sprintf("%s/v%s", releases, version)
	fmt.Fprintf(os.Stderr, "downloading %s/%s\n", base, name)
	data, err := download(base + "/" + name)
	if err != nil {
		return nil, err
	}
	sums, err := download(base + "/SHA256SUMS")
	if err != nil {
		return nil, err
	}
	if err := verifySum(data, name, string(sums), "v"+version); err != nil {
		return nil, err
	}
	if err := os.MkdirAll(cache, 0o755); err != nil {
		return nil, err
	}
	return data, os.WriteFile(filepath.Join(cache, name), data, 0o644)
}

func download(url string) ([]byte, error) {
	resp, err := http.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("download failed: %s: HTTP %d", url, resp.StatusCode)
	}
	return io.ReadAll(resp.Body)
}

// verifySum fails unless SHA256SUMS lists name with data's SHA-256.
func verifySum(data []byte, name, sums, where string) error {
	sum := sha256.Sum256(data)
	for _, line := range strings.Split(sums, "\n") {
		fields := strings.Fields(line)
		if len(fields) == 2 && strings.TrimPrefix(fields[1], "*") == name {
			if fields[0] != hex.EncodeToString(sum[:]) {
				return fmt.Errorf("%s does not match SHA256SUMS of %s", name, where)
			}
			return nil
		}
	}
	return fmt.Errorf("SHA256SUMS of %s does not list %s", where, name)
}

// unpack returns an archive's regular files by path, without the
// archive's top folder (potluckdb-sqlite-<version>-<target>/).
func unpack(name string, data []byte) (map[string][]byte, error) {
	top := strings.TrimSuffix(strings.TrimSuffix(name, ".tar.gz"), ".zip") + "/"
	files := map[string][]byte{}
	add := func(p string, r io.Reader) error {
		p = path.Clean(strings.ReplaceAll(p, "\\", "/"))
		if !strings.HasPrefix(p, top) {
			return fmt.Errorf("%s is outside %s", p, top)
		}
		b, err := io.ReadAll(r)
		files[strings.TrimPrefix(p, top)] = b
		return err
	}
	if strings.HasSuffix(name, ".zip") {
		zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
		if err != nil {
			return nil, err
		}
		for _, f := range zr.File {
			if f.FileInfo().Mode().IsRegular() {
				r, err := f.Open()
				if err != nil {
					return nil, err
				}
				err = add(f.Name, r)
				r.Close()
				if err != nil {
					return nil, err
				}
			}
		}
		return files, nil
	}
	gz, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	tr := tar.NewReader(gz)
	for {
		h, err := tr.Next()
		if err == io.EOF {
			return files, nil
		}
		if err != nil {
			return nil, err
		}
		if h.Typeflag == tar.TypeReg {
			if err := add(h.Name, tr); err != nil {
				return nil, err
			}
		}
	}
}
