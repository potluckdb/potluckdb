// Command tools makes and tests PotluckDB's Go modules. Run it from the
// go/ folder:
//
//	go run ./tools dist -version 0.8.0-dev.1 -out dist/potluckdb-go
//	    writes the distribution repository (github.com/potluckdb/potluckdb-go)
//	    for a release: the driver module and one module per platform.
//	go run ./tools proxy -version 0.8.0-dev.1 -tree dist/potluckdb-go -out dist/proxy
//	    serves a distribution tree as a module proxy on disk, for tests.
//	go run ./tools test -version 0.8.0-dev.1 [-target linux-x64-musl]
//	    runs every check for this platform (see e2e.go).
//	go run ./tools check-binary -header sqlite3.h -lib libsqlite3.a <program>
//	    checks that a program holds one SQLite, PotluckDB's.
//
// The core archives come from POTLUCKDB_CORE_DIR (a folder holding
// them), or else from the GitHub release v<version> of potluckdb/potluckdb.
package main

import (
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

func main() {
	if len(os.Args) < 2 {
		usage()
	}
	cmd, args := os.Args[1], os.Args[2:]
	var err error
	switch cmd {
	case "dist":
		err = cmdDist(args)
	case "proxy":
		err = cmdProxy(args)
	case "test":
		err = cmdTest(args)
	case "check-binary":
		err = cmdCheckBinary(args)
	default:
		usage()
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: go run ./tools dist|proxy|test|check-binary [flags]  (from the go/ folder)")
	os.Exit(2)
}

// goDir is the go/ folder of this repository: the working directory.
func goDir() string {
	dir, _ := os.Getwd()
	if _, err := os.Stat(filepath.Join(dir, "sqlite3", "sqlite3.go")); err != nil {
		fmt.Fprintln(os.Stderr, "error: run this from the go/ folder of github.com/potluckdb/potluckdb")
		os.Exit(2)
	}
	return dir
}

func parseTargets(list string) ([]target, error) {
	if list == "" {
		return nil, nil
	}
	var ts []target
	for _, name := range strings.Split(list, ",") {
		t, err := findTarget(strings.TrimSpace(name))
		if err != nil {
			return nil, err
		}
		ts = append(ts, t)
	}
	return ts, nil
}

func cmdDist(args []string) error {
	fs := flag.NewFlagSet("dist", flag.ExitOnError)
	version := fs.String("version", "", "PotluckDB version, e.g. 0.8.0-dev.1")
	coreDir := fs.String("core", os.Getenv("POTLUCKDB_CORE_DIR"), "folder with the core archives (default: download the release)")
	out := fs.String("out", "dist/potluckdb-go", "folder to write the distribution repository to")
	only := fs.String("targets", "", "comma-separated targets (default: all)")
	requireAll := fs.Bool("require-all", false, "fail unless every platform gets a module")
	fs.Parse(args)
	if *version == "" {
		return errors.New("-version is required")
	}
	ts, err := parseTargets(*only)
	if err != nil {
		return err
	}
	res, err := writeDist(distOptions{Version: *version, CoreDir: *coreDir, Out: *out, GoDir: goDir(), Targets: ts})
	if err != nil {
		return err
	}
	for _, c := range sortedCores(res.Cores) {
		fmt.Printf("%s: from %s\n", c.Target.Module(modulePrefix), c.Static)
	}
	for name, why := range res.Skipped {
		fmt.Printf("no module for %s: %s\n", name, why)
	}
	if *requireAll && len(res.Skipped) > 0 {
		return fmt.Errorf("%d platforms have no module", len(res.Skipped))
	}
	fmt.Printf("wrote %s\n", *out)
	return nil
}

func cmdProxy(args []string) error {
	fs := flag.NewFlagSet("proxy", flag.ExitOnError)
	version := fs.String("version", "", "PotluckDB version")
	tree := fs.String("tree", "dist/potluckdb-go", "distribution tree (from dist)")
	out := fs.String("out", "dist/proxy", "folder to write the module proxy to")
	fs.Parse(args)
	if *version == "" {
		return errors.New("-version is required")
	}
	modules, err := writeProxy(*tree, *version, *out)
	if err != nil {
		return err
	}
	fmt.Printf("GOPROXY=%s serves %d modules\n", fileURL(*out), len(modules))
	return nil
}

func cmdTest(args []string) error {
	fs := flag.NewFlagSet("test", flag.ExitOnError)
	version := fs.String("version", "", "PotluckDB version")
	coreDir := fs.String("core", os.Getenv("POTLUCKDB_CORE_DIR"), "folder with the core archives (default: download the release)")
	work := fs.String("work", filepath.Join("dist", "test"), "work folder (emptied first)")
	name := fs.String("target", "", "platform to test (default: this machine's, glibc on Linux); another one is built but not run")
	skipMattn := fs.Bool("skip-mattn-tests", false, "do not run go-sqlite3's tests")
	fs.Parse(args)
	if *version == "" {
		return errors.New("-version is required")
	}
	var t target
	var err error
	if *name != "" {
		t, err = findTarget(*name)
	} else {
		t, err = hostTarget(false)
	}
	if err != nil {
		return err
	}
	work2, err := filepath.Abs(*work)
	if err != nil {
		return err
	}
	return runE2E(*version, *coreDir, goDir(), work2, t, *skipMattn)
}

func cmdCheckBinary(args []string) error {
	fs := flag.NewFlagSet("check-binary", flag.ExitOnError)
	header := fs.String("header", "", "the release's sqlite3.h")
	lib := fs.String("lib", "", "the static library the program should hold")
	fs.Parse(args)
	if *header == "" || *lib == "" || fs.NArg() != 1 {
		return errors.New("usage: check-binary -header sqlite3.h -lib libsqlite3.a <program>")
	}
	h, err := os.ReadFile(*header)
	if err != nil {
		return err
	}
	l, err := os.ReadFile(*lib)
	if err != nil {
		return err
	}
	facts, err := checkBinary(fs.Arg(0), h, l)
	if err != nil {
		return err
	}
	for _, l := range facts.Lines {
		fmt.Println("ok:", l)
	}
	for _, p := range facts.Problems {
		fmt.Println("problem:", p)
	}
	if len(facts.Problems) > 0 {
		return fmt.Errorf("%d problems", len(facts.Problems))
	}
	return nil
}
