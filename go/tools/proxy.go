package main

// Writes a module proxy on disk (GOPROXY=file:///...) that serves the
// modules of a distribution tree at one version, as proxy.golang.org will
// serve them once the tree is tagged in potluckdb-go. The tests use it to
// run `go get` and `go build` exactly as users will, before anything is
// published.

import (
	"archive/zip"
	"bufio"
	"bytes"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

func writeProxy(tree, version, out string) ([]string, error) {
	var modules []string
	err := filepath.WalkDir(tree, func(p string, e fs.DirEntry, err error) error {
		if err != nil || !e.IsDir() {
			return err
		}
		if _, err := os.Stat(filepath.Join(p, "go.mod")); err == nil {
			m, err := writeProxyModule(p, "v"+version, out)
			modules = append(modules, m)
			return err
		}
		return nil
	})
	return modules, err
}

func modulePath(goMod []byte) (string, error) {
	s := bufio.NewScanner(bytes.NewReader(goMod))
	for s.Scan() {
		if f := strings.Fields(s.Text()); len(f) == 2 && f[0] == "module" {
			return f[1], nil
		}
	}
	return "", fmt.Errorf("go.mod has no module line")
}

func writeProxyModule(dir, version, out string) (string, error) {
	goMod, err := os.ReadFile(filepath.Join(dir, "go.mod"))
	if err != nil {
		return "", err
	}
	mod, err := modulePath(goMod)
	if err != nil {
		return "", fmt.Errorf("%s: %w", dir, err)
	}
	// Module paths here are lower case, so they need no escaping.
	at := filepath.Join(out, filepath.FromSlash(mod), "@v")
	if err := os.MkdirAll(at, 0o755); err != nil {
		return "", err
	}
	info := fmt.Sprintf(`{"Version":%q,"Time":"2026-01-01T00:00:00Z"}`, version)
	for name, data := range map[string][]byte{
		"list":            []byte(version + "\n"),
		version + ".info": []byte(info),
		version + ".mod":  goMod,
	} {
		if err := os.WriteFile(filepath.Join(at, name), data, 0o644); err != nil {
			return "", err
		}
	}
	var b bytes.Buffer
	zw := zip.NewWriter(&b)
	err = filepath.WalkDir(dir, func(p string, e fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(dir, p)
		if e.IsDir() {
			if rel != "." {
				if _, err := os.Stat(filepath.Join(p, "go.mod")); err == nil {
					return filepath.SkipDir // a module of its own
				}
			}
			return nil
		}
		data, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		w, err := zw.Create(mod + "@" + version + "/" + filepath.ToSlash(rel))
		if err != nil {
			return err
		}
		_, err = w.Write(data)
		return err
	})
	if err != nil {
		return "", err
	}
	if err := zw.Close(); err != nil {
		return "", err
	}
	return mod, os.WriteFile(filepath.Join(at, version+".zip"), b.Bytes(), 0o644)
}
