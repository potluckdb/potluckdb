package main

import (
	"fmt"
	"runtime"
	"strings"
)

// A target is one platform PotluckDB ships, named like its core archive
// (potluckdb-sqlite-<version>-<target>). Each one becomes a Go module,
// github.com/potluckdb/potluckdb-go/lib/<target>, holding its static library.
type target struct {
	Name       string // e.g. "linux-x64-gnu"
	GOOS       string
	GOARCH     string
	Musl       bool
	Constraint string   // the build constraint that selects it
	LDFlags    []string // after the library itself
	Platform   string   // for people, e.g. "Linux x64 (glibc 2.28 or later)"
	GoPlatform string   // for people, e.g. "linux/amd64"
}

var targets = []target{
	{Name: "linux-x64-gnu", GOOS: "linux", GOARCH: "amd64",
		Constraint: "linux && !android && amd64 && !musl", LDFlags: []string{"-lm", "-ldl", "-lpthread"},
		Platform: "Linux x64, glibc 2.28 or later", GoPlatform: "linux/amd64"},
	{Name: "linux-arm64-gnu", GOOS: "linux", GOARCH: "arm64",
		Constraint: "linux && !android && arm64 && !musl", LDFlags: []string{"-lm", "-ldl", "-lpthread"},
		Platform: "Linux arm64, glibc 2.28 or later", GoPlatform: "linux/arm64"},
	{Name: "linux-x64-musl", GOOS: "linux", GOARCH: "amd64", Musl: true,
		Constraint: "linux && !android && amd64 && musl", LDFlags: []string{"-lm"},
		Platform: "Linux x64, musl (Alpine)", GoPlatform: "linux/amd64 with -tags musl"},
	{Name: "linux-arm64-musl", GOOS: "linux", GOARCH: "arm64", Musl: true,
		Constraint: "linux && !android && arm64 && musl", LDFlags: []string{"-lm"},
		Platform: "Linux arm64, musl (Alpine)", GoPlatform: "linux/arm64 with -tags musl"},
	{Name: "macos-arm64", GOOS: "darwin", GOARCH: "arm64",
		Constraint: "darwin && !ios && arm64",
		Platform:   "macOS 11 or later, Apple silicon", GoPlatform: "darwin/arm64"},
	{Name: "macos-x64", GOOS: "darwin", GOARCH: "amd64",
		Constraint: "darwin && !ios && amd64",
		Platform:   "macOS 11 or later, Intel", GoPlatform: "darwin/amd64"},
	{Name: "windows-x64", GOOS: "windows", GOARCH: "amd64",
		Constraint: "windows && amd64",
		Platform:   "Windows 10 or later, x64", GoPlatform: "windows/amd64"},
	{Name: "windows-arm64", GOOS: "windows", GOARCH: "arm64",
		Constraint: "windows && arm64",
		Platform:   "Windows 11, arm64", GoPlatform: "windows/arm64"},
}

func findTarget(name string) (target, error) {
	for _, t := range targets {
		if t.Name == name {
			return t, nil
		}
	}
	return target{}, fmt.Errorf("unknown target %q; known: %s", name, strings.Join(targetNames(targets), ", "))
}

func targetNames(ts []target) []string {
	names := make([]string, len(ts))
	for i, t := range ts {
		names[i] = t.Name
	}
	return names
}

// Archive is the core archive's file name for the target.
func (t target) Archive(version string) string {
	ext := "tar.gz"
	if t.GOOS == "windows" {
		ext = "zip"
	}
	return fmt.Sprintf("potluckdb-sqlite-%s-%s.%s", version, t.Name, ext)
}

// staticLib is the static library in a core archive that cgo can link.
// On Windows that must be a MinGW library; the archives' MSVC library
// (lib/static/sqlite3.lib) does not link with MinGW (see DESIGN.md), so a
// Windows target has a module only once its archive has this file too.
const staticLib = "lib/static/libsqlite3.a"

// Module is the Go module path of the target's library module.
func (t target) Module(prefix string) string { return prefix + "/lib/" + t.Name }

// Ident is the target's name as a Go identifier fragment.
func (t target) Ident() string { return strings.ReplaceAll(t.Name, "-", "_") }

// hostTarget is the target of this machine, for the tests.
func hostTarget(musl bool) (target, error) {
	for _, t := range targets {
		if t.GOOS == runtime.GOOS && t.GOARCH == runtime.GOARCH && t.Musl == musl {
			return t, nil
		}
	}
	return target{}, fmt.Errorf("PotluckDB has no library for %s/%s", runtime.GOOS, runtime.GOARCH)
}
