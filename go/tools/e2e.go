package main

// `go run ./tools test`: the checks for one platform, run as users will run
// Go, against the modules of a distribution tree served by a module proxy
// on disk:
//
//   - quickstart: the README's program, after `go get`, prints the
//     PotluckDB and SQLite versions; its binary holds one SQLite, ours;
//   - a build from a fresh module cache downloads only this platform's
//     library module;
//   - the same program built with -trimpath, and from a vendor folder with
//     the network off;
//   - a program that imports github.com/mattn/go-sqlite3, with a replace
//     directive and no code change;
//   - CGO_ENABLED=0 builds and says that it needs cgo;
//   - go-sqlite3's own tests, with the failures in test/known-failures.txt.

import (
	"bytes"
	"errors"
	"fmt"
	"io/fs"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"time"
)

const mattnVersion = "v1.14.52"

type e2e struct {
	version string
	sqlite  string
	target  target
	goDir   string
	work    string
	tree    string
	proxy   string
	header  []byte // the release's sqlite3.h
	lib     []byte // this platform's static library
	run     bool   // false when cross-compiling: build only
	failed  []string
}

// runE2E runs the checks for target t. With missingOK, a release without a
// library module for t passes, with a notice.
func runE2E(version, coreDir, goDir, work string, t target, skipMattn, missingOK bool) error {
	e := &e2e{version: version, target: t, goDir: goDir, work: work,
		tree: filepath.Join(work, "tree"), proxy: filepath.Join(work, "proxy"),
		run: t.GOOS == runtime.GOOS && t.GOARCH == runtime.GOARCH}
	e.cleanModCaches()
	if err := os.RemoveAll(work); err != nil {
		return err
	}
	res, err := writeDist(distOptions{Version: version, CoreDir: coreDir, Out: e.tree, GoDir: goDir})
	if err != nil {
		return err
	}
	for name, why := range res.Skipped {
		e.logf("note: no module for %s: %s", name, why)
	}
	found := false
	for _, c := range res.Cores {
		if c.Target.Name == t.Name {
			found, e.sqlite = true, c.SQLite
			e.header, e.lib = c.Files["include/sqlite3.h"], c.Files[c.Static]
		}
	}
	if !found {
		why := fmt.Sprintf("PotluckDB %s has no Go library module for %s: %s", version, t.Name, res.Skipped[t.Name])
		if missingOK {
			fmt.Printf("::notice title=No Go module for %s::%s. Its checks are skipped.\n", t.Name, why)
			return nil
		}
		return errors.New(why)
	}
	modules, err := writeProxy(e.tree, version, e.proxy)
	if err != nil {
		return err
	}
	e.logf("module proxy at %s: %s", e.proxy, strings.Join(modules, ", "))

	e.step("quickstart", e.quickstart)
	e.step("fresh module cache", e.freshCache)
	e.step("-trimpath", e.trimpath)
	e.step("vendor folder, network off", e.vendor)
	e.step("replace github.com/mattn/go-sqlite3", e.replaceMattn)
	e.step("CGO_ENABLED=0", e.noCgo)
	if !skipMattn {
		e.step("go-sqlite3's tests", e.mattnTests)
	}
	if len(e.failed) > 0 {
		return fmt.Errorf("failed: %s", strings.Join(e.failed, "; "))
	}
	e.logf("ok: every check passed for %s", t.Name)
	return nil
}

func (e *e2e) logf(format string, args ...any) { fmt.Printf(format+"\n", args...) }

func (e *e2e) step(name string, f func() error) {
	e.logf("\n== %s", name)
	start := time.Now()
	if err := f(); err != nil {
		e.logf("FAIL %s: %v", name, err)
		e.failed = append(e.failed, name)
		return
	}
	e.logf("ok %s (%s)", name, time.Since(start).Round(time.Millisecond))
}

func (e *e2e) modCache(name string) string { return filepath.Join(e.work, "modcache-"+name) }

// cleanModCaches empties the module caches of an earlier run; Go makes
// their files read-only, so os.RemoveAll alone can fail.
func (e *e2e) cleanModCaches() {
	dirs, _ := filepath.Glob(filepath.Join(e.work, "modcache-*"))
	for _, d := range dirs {
		cmd := exec.Command("go", "clean", "-modcache")
		cmd.Env = append(os.Environ(), "GOMODCACHE="+d, "GOFLAGS=", "GOWORK=off")
		_ = cmd.Run()
	}
}

func fileURL(p string) string {
	p, _ = filepath.Abs(p)
	p = filepath.ToSlash(p)
	if !strings.HasPrefix(p, "/") {
		p = "/" + p // C:/... on Windows
	}
	return (&url.URL{Scheme: "file", Path: p}).String()
}

// goflags is GOFLAGS for the target: -tags=musl on musl, plus more.
func (e *e2e) goflags(more ...string) string {
	if e.target.Musl {
		more = append([]string{"-tags=musl"}, more...)
	}
	return "GOFLAGS=" + strings.Join(more, " ")
}

// env is the environment of every go command: our proxy and nothing else,
// a module cache of the step's own, and the target's platform and tags.
// extra entries replace earlier ones of the same name.
func (e *e2e) env(modCache string, extra ...string) []string {
	var env []string
	for _, kv := range os.Environ() {
		k, _, _ := strings.Cut(kv, "=")
		switch strings.ToUpper(k) {
		case "GOPROXY", "GOSUMDB", "GONOSUMDB", "GOPRIVATE", "GONOPROXY", "GOFLAGS", "GOMODCACHE",
			"GOWORK", "GOTOOLCHAIN", "CGO_ENABLED", "GOOS", "GOARCH":
			continue
		}
		env = append(env, kv)
	}
	env = append(env, "GOPROXY="+fileURL(e.proxy), "GOSUMDB=off", e.goflags(),
		"GOMODCACHE="+modCache, "GOWORK=off", "GOTOOLCHAIN=local", "CGO_ENABLED=1",
		"GOOS="+e.target.GOOS, "GOARCH="+e.target.GOARCH)
	return append(env, extra...)
}

func (e *e2e) goCmd(dir string, env []string, args ...string) (string, error) {
	e.logf("$ go %s", strings.Join(args, " "))
	cmd := exec.Command("go", args...)
	cmd.Dir, cmd.Env = dir, env
	var out bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &out
	err := cmd.Run()
	if s := strings.TrimSpace(out.String()); s != "" {
		e.logf("%s", indent(s))
	}
	if err != nil {
		return out.String(), fmt.Errorf("go %s: %w", strings.Join(args, " "), err)
	}
	return out.String(), nil
}

func indent(s string) string { return "    " + strings.ReplaceAll(s, "\n", "\n    ") }

// exe is a program's file name on the target platform.
func (e *e2e) exe(name string) string {
	if e.target.GOOS == "windows" {
		return name + ".exe"
	}
	return name
}

// copyDir copies a folder of plain files (one level).
func copyDir(from, to string) error {
	if err := os.MkdirAll(to, 0o755); err != nil {
		return err
	}
	entries, err := os.ReadDir(from)
	if err != nil {
		return err
	}
	for _, en := range entries {
		if en.Type().IsRegular() {
			data, err := os.ReadFile(filepath.Join(from, en.Name()))
			if err != nil {
				return err
			}
			if err := os.WriteFile(filepath.Join(to, en.Name()), data, 0o644); err != nil {
				return err
			}
		}
	}
	return nil
}

func (e *e2e) driver() string { return modulePrefix + "/sqlite3@v" + e.version }

// runProgram runs a built program and checks that it prints the versions.
func (e *e2e) runProgram(dir, bin string) error {
	if !e.run {
		e.logf("(built for %s/%s; not run here)", e.target.GOOS, e.target.GOARCH)
		return nil
	}
	cmd := exec.Command(filepath.Join(dir, bin))
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	e.logf("$ %s\n%s", bin, indent(strings.TrimSpace(string(out))))
	if err != nil {
		return err
	}
	if want := e.version + " " + e.sqlite; strings.TrimSpace(string(out)) != want {
		return fmt.Errorf("printed %q, want %q", strings.TrimSpace(string(out)), want)
	}
	return nil
}

func (e *e2e) checkBinary(path string) error {
	facts, err := checkBinary(path, e.header, e.lib)
	if err != nil {
		return err
	}
	for _, l := range facts.Lines {
		e.logf("  %s", l)
	}
	if len(facts.Problems) > 0 {
		return errors.New(strings.Join(facts.Problems, "; "))
	}
	return nil
}

// libZips lists the library modules a module cache has downloaded.
func libZips(modCache string) []string {
	var found []string
	root := filepath.Join(modCache, "cache", "download", filepath.FromSlash(modulePrefix), "lib")
	_ = filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err == nil && strings.HasSuffix(p, ".zip") {
			rel, _ := filepath.Rel(root, p)
			found = append(found, strings.Split(filepath.ToSlash(rel), "/")[0])
		}
		return nil
	})
	return found
}

func (e *e2e) quickstartDir() string { return filepath.Join(e.work, "quickstart") }

func (e *e2e) quickstart() error {
	dir := e.quickstartDir()
	if err := copyDir(filepath.Join(e.goDir, "test", "quickstart"), dir); err != nil {
		return err
	}
	env := e.env(e.modCache("quickstart"))
	if _, err := e.goCmd(dir, env, "get", e.driver()); err != nil {
		return err
	}
	e.logf("go get downloaded these library modules: %s", strings.Join(libZips(e.modCache("quickstart")), ", "))
	if _, err := e.goCmd(dir, env, "build", "-o", e.exe("quickstart"), "."); err != nil {
		return err
	}
	if err := e.runProgram(dir, e.exe("quickstart")); err != nil {
		return err
	}
	return e.checkBinary(filepath.Join(dir, e.exe("quickstart")))
}

// freshCache builds the quickstart (go.mod and go.sum done) with an empty
// module cache: Go must fetch the driver and this platform's library only.
func (e *e2e) freshCache() error {
	dir := e.quickstartDir()
	cache := e.modCache("fresh")
	if _, err := e.goCmd(dir, e.env(cache), "build", "-o", e.exe("quickstart-fresh"), "."); err != nil {
		return err
	}
	got := libZips(cache)
	e.logf("go build downloaded these library modules: %s", strings.Join(got, ", "))
	if len(got) != 1 || got[0] != e.target.Name {
		return fmt.Errorf("go build downloaded %v, want only %s", got, e.target.Name)
	}
	return e.runProgram(dir, e.exe("quickstart-fresh"))
}

func (e *e2e) trimpath() error {
	dir := e.quickstartDir()
	if _, err := e.goCmd(dir, e.env(e.modCache("quickstart")), "build", "-trimpath", "-o", e.exe("quickstart-trimpath"), "."); err != nil {
		return err
	}
	return e.runProgram(dir, e.exe("quickstart-trimpath"))
}

func (e *e2e) vendor() error {
	dir := filepath.Join(e.work, "vendored")
	if err := copyDir(e.quickstartDir(), dir); err != nil {
		return err
	}
	if _, err := e.goCmd(dir, e.env(e.modCache("quickstart")), "mod", "vendor"); err != nil {
		return err
	}
	lib := filepath.Join(dir, "vendor", filepath.FromSlash(e.target.Module(modulePrefix)), "libsqlite3.a")
	if _, err := os.Stat(lib); err != nil {
		return fmt.Errorf("go mod vendor left out the library: %w", err)
	}
	// No proxy and an empty module cache: everything must come from vendor/.
	env := e.env(e.modCache("empty"), "GOPROXY=off", e.goflags("-mod=vendor"))
	if _, err := e.goCmd(dir, env, "build", "-o", e.exe("quickstart-vendored"), "."); err != nil {
		return err
	}
	return e.runProgram(dir, e.exe("quickstart-vendored"))
}

func (e *e2e) replaceMattn() error {
	dir := filepath.Join(e.work, "replace")
	if err := copyDir(filepath.Join(e.goDir, "test", "replace"), dir); err != nil {
		return err
	}
	env := e.env(e.modCache("quickstart"))
	if _, err := e.goCmd(dir, env, "mod", "edit", "-replace", "github.com/mattn/go-sqlite3="+e.driver()); err != nil {
		return err
	}
	if _, err := e.goCmd(dir, env, "mod", "tidy"); err != nil {
		return err
	}
	if _, err := e.goCmd(dir, env, "build", "-o", e.exe("replace"), "."); err != nil {
		return err
	}
	if err := e.runProgram(dir, e.exe("replace")); err != nil {
		return err
	}
	return e.checkBinary(filepath.Join(dir, e.exe("replace")))
}

func (e *e2e) noCgo() error {
	dir := e.quickstartDir()
	env := e.env(e.modCache("quickstart"), "CGO_ENABLED=0")
	if _, err := e.goCmd(dir, env, "build", "-o", e.exe("quickstart-nocgo"), "."); err != nil {
		return err
	}
	if !e.run {
		return nil
	}
	out, err := exec.Command(filepath.Join(dir, e.exe("quickstart-nocgo"))).CombinedOutput()
	e.logf("%s", indent(strings.TrimSpace(string(out))))
	if err == nil || !strings.Contains(string(out), "CGO_ENABLED=0") {
		return fmt.Errorf("without cgo the program should fail and say it needs cgo")
	}
	return nil
}

// knownFailures reads test/known-failures.txt: per line a test name, where
// it fails (all, musl, or a target name), then why.
func (e *e2e) knownFailures() ([]string, error) {
	data, err := os.ReadFile(filepath.Join(e.goDir, "test", "known-failures.txt"))
	if err != nil {
		return nil, err
	}
	var names []string
	for _, line := range strings.Split(string(data), "\n") {
		f := strings.Fields(line)
		if len(f) == 0 || strings.HasPrefix(f[0], "#") {
			continue
		}
		if len(f) < 3 {
			return nil, fmt.Errorf("known-failures.txt: %q: want <test> <where> <why>", line)
		}
		if where := f[1]; where == "all" || where == e.target.Name || (where == "musl" && e.target.Musl) {
			names = append(names, f[0])
		}
	}
	return names, nil
}

// mattnTagSets are the build tag sets go-sqlite3's tests run with: none;
// the tags of features PotluckDB's library has built in; and the tags whose
// SQLite defaults the driver applies itself (see sqlite3/potluckdb.go).
var mattnTagSets = []string{
	"",
	"sqlite_vtable sqlite_preupdate_hook sqlite_unlock_notify sqlite_column_metadata sqlite_math_functions sqlite_fts5 sqlite_serialize",
	"sqlite_foreign_keys sqlite_secure_delete",
}

var testResultRE = regexp.MustCompile(`(?m)^\s*--- (PASS|FAIL|SKIP): (\S+)`)

func (e *e2e) mattnTests() error {
	skip, err := e.knownFailures()
	if err != nil {
		return err
	}
	dir := filepath.Join(e.tree, "sqlite3")
	env := e.env(e.modCache("quickstart"), e.goflags("-mod=mod")) // the driver module has no go.sum
	var problems []string
	for _, tags := range mattnTagSets {
		args := []string{"test", "-count=1", "-v"}
		if tags != "" {
			if e.target.Musl {
				tags += " musl"
			}
			args = append(args, "-tags="+strings.ReplaceAll(tags, " ", ","))
		}
		if len(skip) > 0 {
			args = append(args, "-skip=^("+strings.Join(skip, "|")+")$")
		}
		if !e.run {
			args = []string{"test", "-c", "-o", os.DevNull}
			if tags != "" {
				args = append(args, "-tags="+strings.ReplaceAll(tags, " ", ","))
			}
		}
		e.logf("$ go %s", strings.Join(args, " "))
		cmd := exec.Command("go", append(args, ".")...)
		cmd.Dir, cmd.Env = dir, env
		out, err := cmd.CombinedOutput()
		counts := map[string]int{}
		var failedTests []string
		for _, m := range testResultRE.FindAllStringSubmatch(string(out), -1) {
			counts[m[1]]++
			if m[1] == "FAIL" {
				failedTests = append(failedTests, m[2])
			}
		}
		label := "no tags"
		if tags != "" {
			label = "tags " + tags
		}
		e.logf("  %s: %d passed, %d failed, %d skipped by the tests, %d known failures not run",
			label, counts["PASS"], counts["FAIL"], counts["SKIP"], len(skip))
		if err != nil {
			e.logf("%s", indent(lastLines(string(out), 60)))
			problems = append(problems, fmt.Sprintf("%s: %v (failed: %s)", label, err, strings.Join(failedTests, ", ")))
		}
	}
	if len(problems) > 0 {
		return errors.New(strings.Join(problems, "; "))
	}
	return nil
}

func lastLines(s string, n int) string {
	lines := strings.Split(strings.TrimRight(s, "\n"), "\n")
	if len(lines) > n {
		lines = lines[len(lines)-n:]
	}
	return strings.Join(lines, "\n")
}
