"""Starts a release's package publishing runs, waits for them, checks that
every registry serves the version, and writes how long each step took.

    python tools/release_watch.py start --version 0.8.0-dev.4
        (release.yml) Starts each registry's workflow with publish=true if its
        <X>_PUBLISHING variable (passed in the environment) is "true", and
        writes runs=<json> to $GITHUB_OUTPUT for the watch job.
    python tools/release_watch.py watch --version 0.8.0-dev.4 --runs '<json>'
            [--release-run ID] [--build-started-at TIME] [--summary FILE] [--out DIR]
        (release.yml) Waits for each run, re-runs its failed jobs once, then
        waits up to 15 minutes for its registry to serve the version, and
        writes the timings table. Fails if a registry is off, a run failed or
        a registry does not serve every package.
    python tools/release_watch.py watch --version 0.8.0-dev.3 --check-only
        Read only, for a past release: finds its runs, never re-runs or
        waits, and prints the table.
"""
import argparse
import datetime
import gzip
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "python"))
from core_archive import TARGETS, pep440  # noqa: E402

REPO = "potluckdb/potluckdb"
USER_AGENT = "potluckdb-release-watch (https://github.com/potluckdb/potluckdb)"
POLL = 60  # seconds between checks (GITHUB_TOKEN may make 1,000 requests an hour)
PROPAGATION = 15 * 60  # how long a registry may take to serve a finished run's packages
GOAL = 60 * 60  # every registry within 1 hour of the start (core#125)
DISPATCHES = 4  # tries to start each run: GitHub sometimes answers 5xx, sometimes after starting it
LOOK_EVERY = 15  # seconds between looks for a run started without its id
LOOK_FOR = 120  # seconds to look for it before concluding it was not started
SKEW = datetime.timedelta(seconds=5)  # between this runner's clock and GitHub's
GH_TIMEOUT = 60  # seconds for one gh command
START_BUDGET = 4 * 60  # seconds for all of start(), well within finalize's 10 minutes
START_CALL = 30  # seconds for one gh command in start(), tried once: the 5 first starts fit the budget
REGISTRIES = {  # key: (registry, workflow, the repository variable that turns it on)
    "python": ("PyPI", "python.yml", "PYPI_PUBLISHING"),
    "rust": ("crates.io", "rust.yml", "CRATES_IO_PUBLISHING"),
    "dotnet": ("NuGet", "dotnet.yml", "NUGET_PUBLISHING"),
    "node": ("npm", "node.yml", "NPM_PUBLISHING"),
    "go": ("Go module proxy", "go.yml", "GO_PUBLISHING"),
}
NUGET_IDS = ["PotluckDB.SQLitePCLRaw", "PotluckDB.Data.Sqlite"]  # dotnet/scripts/pack.py
GO_MODULES = "github.com/potluckdb/potluckdb-go"  # go/tools/dist.go


def parse_time(text):
    """A UTC time from GitHub or a registry (fractions of a second dropped)."""
    if not text:
        return None
    text = re.sub(r"\.\d+", "", text).replace("Z", "+00:00")
    return datetime.datetime.fromisoformat(text).astimezone(datetime.timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def http_get(url):
    """(status, JSON or text) of a public URL; status None if it can't be reached."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, body = response.status, response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
    except urllib.error.HTTPError as error:
        return error.code, None
    except OSError:  # unreachable, timed out
        return None, None
    try:
        return status, json.loads(body)
    except ValueError:
        return status, body.decode(errors="replace")


class ApiError(Exception):
    pass


def gh_api(path, method="GET", run=subprocess.run, sleep=time.sleep, tries=3, timeout=GH_TIMEOUT):
    """GitHub's REST API through gh (GH_TOKEN), tried 3 times (tries), each for up to GH_TIMEOUT seconds (timeout)."""
    for attempt in range(tries):
        try:
            result = run(["gh", "api", "-X", method, path], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            error = f"no answer in {timeout} seconds"
        else:
            error = result.stderr.strip()
            if result.returncode == 0:
                try:
                    return json.loads(result.stdout) if result.stdout.strip() else None
                except ValueError:
                    error = "the answer is not JSON"
        if attempt < tries - 1:
            sleep(10)
    raise ApiError(f"gh api -X {method} {path}: {error}")


def get_json(get, url):
    status, data = get(url)
    return data if status == 200 and isinstance(data, dict) else None


# Each check returns (what it checked, missing packages, the registry's own
# time for the last package, or None).
def check_pypi(get, version):
    name = f"potluckdb {pep440(version)}"
    files = (get_json(get, f"https://pypi.org/pypi/potluckdb/{pep440(version)}/json") or {}).get("urls")
    if not files:
        return name, [name], None
    return f"{name} ({len(files)} files)", [], max(parse_time(f["upload_time_iso_8601"]) for f in files)


def check_npm(get, version):
    names = [f"@potluckdb/{target}" for target in TARGETS] + ["potluckdb"]
    missing = [n for n in names if get(f"https://registry.npmjs.org/{n}/{version}")[0] != 200]
    published = None if missing else (get_json(get, "https://registry.npmjs.org/potluckdb") or {}).get("time", {}).get(version)
    return f"potluckdb and {len(TARGETS)} platform packages {version}", missing, parse_time(published)


def check_nuget(get, version):
    missing, times = [], []
    for package in NUGET_IDS:
        index = get_json(get, f"https://api.nuget.org/v3-flatcontainer/{package.lower()}/index.json") or {}
        if version.lower() not in index.get("versions", []):
            missing.append(package)
            continue
        leaf = get_json(get, f"https://api.nuget.org/v3/registration5-gz-semver2/{package.lower()}/{version.lower()}.json")
        times.append(parse_time((leaf or {}).get("published")))
    published = None if missing or None in times else max(times)
    return f"{' and '.join(NUGET_IDS)} {version}", missing, published


def check_go(get, version):
    # The driver's go.mod requires the library module of every platform it has.
    base = f"https://proxy.golang.org/{GO_MODULES}"
    driver = get_json(get, f"{base}/sqlite3/@v/v{version}.info")
    status, mod = get(f"{base}/sqlite3/@v/v{version}.mod")
    what = f"{GO_MODULES}/sqlite3 and its lib modules v{version}"
    if not driver or status != 200 or not isinstance(mod, str):
        return what, [f"{GO_MODULES}/sqlite3"], None
    libs = re.findall(rf"^\s*{re.escape(GO_MODULES)}/(lib/\S+) v{re.escape(version)}\s*$", mod, re.M)
    missing = [f"{GO_MODULES}/{lib}" for lib in libs if not get_json(get, f"{base}/{lib}/@v/v{version}.info")]
    what = f"{GO_MODULES}/sqlite3 and {len(libs)} lib modules v{version}"
    return what, missing, None if missing else parse_time(driver.get("Time"))


def check_crates(get, version):
    found = get_json(get, f"https://crates.io/api/v1/crates/potluckdb/{version}")
    name = f"potluckdb {version}"
    return (name, [], parse_time(found["version"]["created_at"])) if found else (name, [name], None)


CHECKS = {"python": check_pypi, "rust": check_crates, "dotnet": check_nuget, "node": check_npm, "go": check_go}


def run_name(version):
    """The name of a publishing run (each publishing workflow's run-name)."""
    return f"publish {version}"


def dispatch(run, workflow, version):
    """Asks GitHub once to start a publishing run: (its id or None, the error or None)."""
    command = ["gh", "workflow", "run", workflow, "-R", REPO, "-f", f"version={version}", "-f", "publish=true"]
    try:
        result = run(command, capture_output=True, text=True, timeout=START_CALL)
    except subprocess.TimeoutExpired:
        return None, f"gh workflow run gave no answer in {START_CALL} seconds"
    found = re.search(r"/actions/runs/(\d+)", result.stdout + result.stderr)  # gh 2.87 and later print it
    if found:
        return int(found[1]), None
    return None, (result.stderr or result.stdout).strip()[-300:] or "gh workflow run printed no run"


def start(version, env, run=subprocess.run, gh=None, clock=utcnow, sleep=time.sleep, runs=None):
    """Starts each registry's publishing run that is on, filling in and
    returning runs. A start that fails is tried again, up to DISPATCHES
    times, but only once looking for the run found none. All of it takes at
    most START_BUDGET seconds, even if every gh command hangs: a registry
    still without a run keeps its start time, and watch looks for it."""
    gh = gh or (lambda path: gh_api(path, tries=1, timeout=START_CALL))
    runs = {} if runs is None else runs
    deadline = clock() + datetime.timedelta(seconds=START_BUDGET)

    def fits(seconds):  # checked before each gh command and each wait
        return clock() + datetime.timedelta(seconds=seconds) <= deadline
    waiting = []
    for key, (registry, workflow, variable) in REGISTRIES.items():
        if env.get(variable) == "true":
            waiting.append(key)
            continue
        value = env.get(variable)
        print(f"{registry}: not started, the repository variable {variable} is {repr(value) if value else 'not set'}")
        runs[key] = {"off": True}
    for attempt in range(1, DISPATCHES + 1):
        for key in waiting:
            registry, workflow, _ = REGISTRIES[key]
            reg = runs.setdefault(key, {"at": iso(clock()), "run": None, "error": "not tried: no time was left"})
            if fits(START_CALL):
                reg["run"], reg["error"] = dispatch(run, workflow, version)
                print(f"{registry}: {workflow} " + (f"run {reg['run']}" if reg["run"] else f"try {attempt}: {reg['error']}"))
        waiting = [key for key in waiting if not runs[key]["run"]]
        for _ in range(2 if attempt < DISPATCHES else 0):  # GitHub may have started it despite the error
            if not waiting or not fits(LOOK_EVERY + START_CALL):
                break
            sleep(LOOK_EVERY)
            for key in waiting:
                if fits(START_CALL):
                    runs[key]["run"] = find_run(gh, REGISTRIES[key][1], parse_time(runs[key]["at"]), run_name(version),
                                                clock=clock, sleep=sleep)
                    if runs[key]["run"]:
                        print(f"{REGISTRIES[key][0]}: {REGISTRIES[key][1]} run {runs[key]['run']} started after all")
            waiting = [key for key in waiting if not runs[key]["run"]]
        if not waiting or not fits(START_CALL):
            break
    if waiting:
        print(f"no run seen yet for {', '.join(REGISTRIES[key][1] for key in waiting)}: watch looks for them")
    for reg in runs.values():
        if reg.get("run") or not reg.get("error"):
            reg.pop("error", None)
    return runs


def find_run(gh, workflow, since, name=None, look_for=0, clock=utcnow, sleep=time.sleep, log=print):
    """The oldest run of workflow on main started by hand or by release.yml at or
    after a time (less SKEW) and, if given, with that name. A new run takes a
    while to be listed: looks every LOOK_EVERY seconds for up to look_for seconds."""
    since -= SKEW
    query = urllib.parse.urlencode({"event": "workflow_dispatch", "branch": "main", "per_page": 100,
                                    "created": ">=" + iso(since)})
    until = clock() + datetime.timedelta(seconds=look_for)
    while True:
        try:
            runs = [r for r in gh(f"repos/{REPO}/actions/workflows/{workflow}/runs?{query}")["workflow_runs"]
                    if parse_time(r["created_at"]) >= since and name in (None, r.get("display_title"))]
            if runs:
                return min(runs, key=lambda r: (r["created_at"], r["id"]))["id"]
        except ApiError as error:
            log(f"could not list the {workflow} runs: {error}")
        if clock() >= until:
            return None
        sleep(LOOK_EVERY)


def watch(version, runs, gh, get, check_only=False, deadline=None, since=None, clock=utcnow, sleep=time.sleep, log=print):
    """Waits for the runs and the registries; returns the state of each registry."""
    regs = {}
    for key, (registry, workflow, variable) in REGISTRIES.items():
        given = runs.get(key, {})
        reg = regs[key] = {"registry": registry, "workflow": workflow, "variable": variable, "off": given.get("off"),
                           "error": given.get("error"), "run": given.get("run"), "reran": False, "rerun_errors": 0,
                           "final": None, "final_at": None, "unknown": None, "what": None, "missing": None,
                           "seen_missing": False, "served_at": None}
        if not reg["run"] and not reg["off"] and given.get("at"):  # start() saw no run: look for it a while
            left = (deadline - clock()).total_seconds() if deadline else LOOK_FOR
            reg["run"] = find_run(gh, workflow, parse_time(given["at"]), run_name(version),
                                  0 if check_only else max(0, min(LOOK_FOR, left)), clock, sleep, log)
        elif not reg["run"] and not reg["off"] and since:  # a past release: its runs have no run-name yet
            reg["run"] = find_run(gh, workflow, since, log=log)

    def settled(reg, now):
        if reg["off"] or not reg["run"] or reg["served_at"]:
            return True
        if check_only:
            return reg["missing"] is not None
        if not reg["final"] or reg["missing"] is None:
            return False
        return reg["final"] != "success" or (now - reg["final_at"]).total_seconds() >= PROPAGATION

    def follow(reg, now):
        run = gh(f"repos/{REPO}/actions/runs/{reg['run']}")
        if run["status"] != "completed" or (reg["reran"] and run["run_attempt"] == 1):  # running, or re-run not shown yet
            return
        if run["conclusion"] == "success" or run["run_attempt"] > 1 or check_only or reg["rerun_errors"] == 3:
            reg["final"], reg["final_at"] = run["conclusion"], now
            log(f"{iso(now)} {reg['workflow']} run {reg['run']} ended in {run['conclusion']}")
            return
        log(f"{iso(now)} {reg['workflow']} run {reg['run']} ended in {run['conclusion']}: re-running its failed jobs")
        try:
            gh(f"repos/{REPO}/actions/runs/{reg['run']}/rerun-failed-jobs", "POST")
            reg["reran"] = True
        except ApiError as error:  # tried again next round, 3 times in all
            reg["rerun_errors"] += 1
            log(f"could not re-run it: {error}")

    while True:
        now = clock()
        for key, reg in regs.items():
            if settled(reg, now):
                continue
            if not reg["final"]:
                try:
                    follow(reg, now)
                    reg["unknown"] = None
                except ApiError as error:  # unknown this round: ask again next round
                    reg["unknown"] = str(error)[-300:]
                    log(f"{iso(now)} {reg['workflow']} run {reg['run']}: no answer from GitHub this round: {error}")
                    continue
            # Ask a registry only once its run is over (or in a check of a past
            # release): proxy.golang.org caches a "not found" for 30 minutes.
            if reg["final"] or check_only:
                reg["what"], reg["missing"], published = CHECKS[key](get, version)
                if reg["missing"]:
                    reg["seen_missing"] = True
                else:
                    reg["served_at"] = now if reg["seen_missing"] or not published else published
                    log(f"{iso(now)} {reg['registry']} serves {reg['what']}")
        if all(settled(reg, now) for reg in regs.values()) or check_only or (deadline and now >= deadline):
            return regs
        sleep(POLL)


def problems(regs, version):
    """What went wrong, one line per problem."""
    found = []
    for reg in regs.values():
        name, workflow = reg["registry"], reg["workflow"]
        if reg["off"]:
            found.append(f"{name}: {workflow} was not started because the repository variable {reg['variable']} is not 'true'")
        elif not reg["run"]:
            found.append(f"{name}: {workflow} was not started{': ' + reg['error'] if reg['error'] else ''}")
        elif not reg["final"]:
            unknown = f" (GitHub's last answer: {reg['unknown']})" if reg.get("unknown") else ""
            found.append(f"{name}: {workflow} run {reg['run']} had not finished in time{unknown}")
        elif reg["final"] != "success":
            again = ", also after re-running its failed jobs" if reg["reran"] else ""
            found.append(f"{name}: {workflow} run https://github.com/{REPO}/actions/runs/{reg['run']} ended in {reg['final']}{again}")
        if reg["missing"]:
            found.append(f"{name} does not serve {version} of: {', '.join(reg['missing'])}")
    return found


def run_rows(gh, run_id, workflow):
    """(step, start, end, result) for each attempt of a run and its jobs (matrix jobs as one row)."""
    run = gh(f"repos/{REPO}/actions/runs/{run_id}")
    rows = []
    for attempt in range(1, run["run_attempt"] + 1):
        this = run if attempt == run["run_attempt"] else gh(f"repos/{REPO}/actions/runs/{run_id}/attempts/{attempt}")
        label = f"{workflow} run {run_id}" + (f", attempt {attempt}" if run["run_attempt"] > 1 else "")
        rows.append((label, parse_time(this["run_started_at"]),
                     parse_time(this["updated_at"]) if this["status"] == "completed" else None,
                     this["conclusion"] or this["status"]))
        jobs = gh(f"repos/{REPO}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")["jobs"]
        groups = {}
        for job in jobs:
            if job.get("run_attempt", attempt) == attempt and job["conclusion"] != "skipped":
                groups.setdefault(re.split(r"[ (]", job["name"])[0], []).append(job)
        for name, group in sorted(groups.items(), key=lambda g: min(j["started_at"] or "~" for j in g[1])):
            starts = [parse_time(j["started_at"]) for j in group if j["started_at"]]
            ends = [parse_time(j["completed_at"]) for j in group]
            results = sorted({j["conclusion"] or j["status"] for j in group})
            rows.append((f"- {name}" + (f" ({len(group)} jobs)" if len(group) > 1 else ""), min(starts, default=None),
                         None if None in ends else max(ends), ", ".join(results)))
    return rows


def span(start, end):
    if not start or not end:
        return ""
    seconds = int((end - start).total_seconds())
    if seconds >= 86400:
        return f"{seconds // 86400}d {seconds % 86400 // 3600}h"
    if seconds >= 3600:
        return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"
    return f"{seconds // 60}m {seconds % 60:02d}s"


def render(version, rows, origin):
    def at(t):
        return "" if not t else t.strftime("%H:%M:%S" if t.date() == origin.date() else "%m-%d %H:%M:%S")
    lines = [f"### Release {version}: timings", "",
             f"Times are UTC, on {origin:%Y-%m-%d} unless a date is shown. \"Done after\" counts from {at(origin)}.", "",
             "| Step | Start | End | Duration | Done after | Result |", "| --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {step} | {at(start)} | {at(end)} | {span(start, end)} | {span(origin, end)} | {result} |"
              for step, start, end, result in rows]
    lines += ["", "A registry's time is when it first served every package: the registry's own publish time "
                  "if it served them at the first check, else the time of the first check that found them all."]
    return "\n".join(lines) + "\n"


def timings(version, regs, gh, release_run, build_started_at):
    """The rows of the table, and the time they count from. A run GitHub
    gives no details of gets one row that says so."""
    def rows_of(run_id, workflow):
        try:
            return run_rows(gh, run_id, workflow)
        except (ApiError, KeyError, TypeError, ValueError) as error:
            return [(f"{workflow} run {run_id}", None, None, f"unknown: could not read it from GitHub ({error})"[:300])]

    rows = []
    try:
        release = gh(f"repos/{REPO}/actions/runs/{release_run}") if release_run else None
    except ApiError:
        release = None  # its row below says so
    origin = build_started_at or (parse_time(release["created_at"]) if release else utcnow())
    if build_started_at:
        rows.append(("core release-build (potluckdb/core)", build_started_at,
                     parse_time(release["created_at"]) if release else None, ""))
    if release_run:
        rows += rows_of(release_run, "release.yml")
    for reg in regs.values():
        if reg["run"]:
            rows += rows_of(reg["run"], reg["workflow"])
        if reg["off"]:
            result = f"off: {reg['variable']} is not 'true'"
        elif reg["served_at"]:
            late = (reg["served_at"] - origin).total_seconds() > GOAL
            result = "served" + (" (later than the 1 hour goal)" if late else "")
        elif reg["missing"]:
            result = "missing: " + ", ".join(reg["missing"])
        else:
            result = "not checked: no finished run"
        rows.append((f"**{reg['registry']}**: {reg['what'] or version}", None, reg["served_at"], result))
    return rows, origin


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["start", "watch"])
    parser.add_argument("--version", required=True)
    parser.add_argument("--runs", default="{}", help="JSON from start (default: find the runs)")
    parser.add_argument("--release-run", type=int, help="the release.yml run (default: the one that published the release)")
    parser.add_argument("--build-started-at", default="", help="when core's release-build run started")
    parser.add_argument("--check-only", action="store_true", help="read only: no re-runs, no waiting")
    parser.add_argument("--deadline-minutes", type=float, default=70)
    parser.add_argument("--summary", help="append the table to this file (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--out", help="write timings.md and timings.json to this folder")
    args = parser.parse_args(argv)
    version = args.version.removeprefix("v")

    if args.command == "start":
        runs = {}
        try:
            start(version, os.environ, runs=runs)
        finally:  # the release is public: watch must run, and it runs only with this output
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
                out.write(f"runs={json.dumps(runs)}\n")
        return 0

    runs = json.loads(args.runs or "{}")
    since, release_run = None, args.release_run
    if not runs or not release_run:  # a past release: find its runs from when it was published
        published = parse_time(gh_api(f"repos/{REPO}/releases/tags/v{version}")["published_at"])
        since = published
        if not release_run:
            query = urllib.parse.urlencode({"event": "workflow_dispatch", "per_page": 100, "created": "<=" + iso(published)})
            release_run = next((r["id"] for r in gh_api(f"repos/{REPO}/actions/workflows/release.yml/runs?{query}")["workflow_runs"]
                                if parse_time(r["updated_at"]) >= published), None)
    deadline = utcnow() + datetime.timedelta(minutes=args.deadline_minutes)
    regs = watch(version, runs, gh_api, http_get, args.check_only, deadline, since)
    try:
        build_started_at = parse_time(args.build_started_at)
    except ValueError:
        print(f"warning: --build-started-at {args.build_started_at!r} is not a time; the table starts at release.yml")
        build_started_at = None
    rows, origin = timings(version, regs, gh_api, release_run, build_started_at)
    table = render(version, rows, origin)
    found = problems(regs, version)
    table += "".join(f"\n- {line}" for line in found) + ("\n" if found else "")
    print(table)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as out:
            out.write(table)
    if args.out:
        folder = pathlib.Path(args.out)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "timings.md").write_text(table, encoding="utf-8")
        (folder / "timings.json").write_text(json.dumps(
            [{"step": s, "start": a and iso(a), "end": b and iso(b), "result": r} for s, a, b, r in rows], indent=1) + "\n")
    for line in found:
        print(f"::error title=Release {version}::{line}" if os.environ.get("GITHUB_ACTIONS") else f"error: {line}",
              file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
