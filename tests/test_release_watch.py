import contextlib
import datetime
import gzip
import http.client
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import release_watch as rw  # noqa: E402

V = "0.8.0-dev.3"
T0 = rw.parse_time("2026-10-24T00:59:40Z")
GO = "https://proxy.golang.org/github.com/potluckdb/potluckdb-go"
# What the registries answered for 0.8.0-dev.3 (trimmed). Go and crates.io are
# from 0.8.0-dev.2, which they serve.
SERVED = {
    "https://pypi.org/pypi/potluckdb/0.8.0.dev3/json": {"urls": [
        {"upload_time_iso_8601": "2026-10-24T01:06:50.983966Z"}, {"upload_time_iso_8601": "2026-10-24T01:07:59.773379Z"}]},
    **{f"https://registry.npmjs.org/{n}/{V}": {"version": V}
       for n in ["potluckdb"] + [f"@potluckdb/{t}" for t in rw.TARGETS]},
    "https://registry.npmjs.org/potluckdb": {"time": {V: "2026-11-03T18:15:55.528Z"}},
    "https://api.nuget.org/v3-flatcontainer/potluckdb.data.sqlite/index.json": {"versions": ["0.8.0-dev.2", V]},
    "https://api.nuget.org/v3-flatcontainer/potluckdb.sqlitepclraw/index.json": {"versions": ["0.8.0-dev.2", V]},
    f"https://api.nuget.org/v3/registration5-gz-semver2/potluckdb.data.sqlite/{V}.json":
        {"published": "2026-10-24T01:18:44.363+00:00"},
    f"https://api.nuget.org/v3/registration5-gz-semver2/potluckdb.sqlitepclraw/{V}.json":
        {"published": "2026-10-24T01:18:43.64+00:00"},
    f"{GO}/sqlite3/@v/v0.8.0-dev.2.info": {"Version": "v0.8.0-dev.2", "Time": "2026-10-23T22:36:34Z"},
    f"{GO}/sqlite3/@v/v0.8.0-dev.2.mod": "module github.com/potluckdb/potluckdb-go/sqlite3\n\ngo 1.21\n\nrequire (\n"
        "\tgithub.com/potluckdb/potluckdb-go/lib/linux-x64-gnu v0.8.0-dev.2\n"
        "\tgithub.com/potluckdb/potluckdb-go/lib/macos-arm64 v0.8.0-dev.2\n)\n",
    f"{GO}/lib/linux-x64-gnu/@v/v0.8.0-dev.2.info": {"Version": "v0.8.0-dev.2"},
    "https://crates.io/api/v1/crates/potluckdb/0.8.0-dev.2": {"version": {"created_at": "2026-10-23T22:34:14.541915Z"}},
}


def registry(answers, missing_calls=0):
    """A fake http_get; every URL is missing for its first missing_calls requests."""
    asked = {}

    def get(url):
        asked[url] = asked.get(url, 0) + 1
        return (200, answers[url]) if url in answers and asked[url] > missing_calls else (404, None)
    get.asked = asked
    return get


def run(id, status="completed", conclusion="success", attempt=1, started="2026-10-24T00:59:44Z",
        updated="2026-10-24T01:04:00Z"):
    return {"id": id, "status": status, "conclusion": conclusion if status == "completed" else None,
            "run_attempt": attempt, "created_at": started, "run_started_at": started, "updated_at": updated}


class GitHub:
    """A fake gh_api: each run's states, and each workflow's lists of runs, are
    returned in turn (the last one stays)."""

    def __init__(self, states=None, attempts=None, jobs=None, listed=None, post_errors=None):
        self.states, self.attempts, self.jobs, self.listed = states or {}, attempts or {}, jobs or {}, listed or {}
        self.post_errors, self.calls, self.options = post_errors or [], [], []

    def __call__(self, path, method="GET", **options):
        self.calls.append((method, path))
        self.options.append(options)
        answer = self.answer(path, method)
        if isinstance(answer, Exception):  # GitHub did not answer
            raise answer
        return answer

    def answer(self, path, method):
        parts = path.split("?")[0].split("/")[4:]  # e.g. runs, 7, attempts, 1, jobs
        if parts[0] == "workflows":
            lists = self.listed.get(parts[1], [[]])
            return {"workflow_runs": lists.pop(0) if len(lists) > 1 else lists[0]}
        run_id, states = int(parts[1]), self.states.get(int(parts[1]))
        if method == "POST":
            return self.post_errors.pop(0) if self.post_errors else None
        if parts[-1] == "jobs" and isinstance(self.jobs.get((run_id, int(parts[3]))), Exception):
            return self.jobs[(run_id, int(parts[3]))]
        if len(parts) == 2:
            return states.pop(0) if len(states) > 1 else states[0]
        if parts[-1] == "jobs":
            return {"jobs": self.jobs.get((run_id, int(parts[3])), [])}
        return self.attempts[(run_id, int(parts[3]))]

    def reruns(self):
        return [path for method, path in self.calls if method == "POST"]


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += datetime.timedelta(seconds=seconds)


def only(key, **given):
    return {k: (given if k == key else {"off": True}) for k in rw.REGISTRIES}


def watch(runs, gh, get, clock=None, **kw):
    clock = clock or Clock()
    return rw.watch(V, runs, gh, get, clock=clock, sleep=clock.sleep, log=lambda *a: None, **kw)


class RegistryTest(unittest.TestCase):
    def test_each_registry_served_dev3_or_dev2(self):
        get = registry(SERVED)
        self.assertEqual(rw.check_pypi(get, V), ("potluckdb 0.8.0.dev3 (2 files)", [], rw.parse_time("2026-10-24T01:07:59Z")))
        self.assertEqual(rw.check_npm(get, V)[1:], ([], rw.parse_time("2026-11-03T18:15:55Z")))
        self.assertEqual(rw.check_nuget(get, V)[1:], ([], rw.parse_time("2026-10-24T01:18:44Z")))
        self.assertEqual(rw.check_crates(get, "0.8.0-dev.2")[1:], ([], rw.parse_time("2026-10-23T22:34:14Z")))
        # The driver's go.mod names two library modules; the proxy has one.
        what, missing, published = rw.check_go(get, "0.8.0-dev.2")
        self.assertEqual((what, missing, published), (
            "github.com/potluckdb/potluckdb-go/sqlite3 and 2 lib modules v0.8.0-dev.2",
            ["github.com/potluckdb/potluckdb-go/lib/macos-arm64"], None))

    def test_missing_packages_are_named(self):
        answers = {u: a for u, a in SERVED.items() if "linux-arm64-musl" not in u and "sqlitepclraw" not in u}
        get = registry(answers)
        self.assertEqual(rw.check_npm(get, V)[1:], (["@potluckdb/linux-arm64-musl"], None))
        self.assertEqual(rw.check_nuget(get, V)[1:], (["PotluckDB.SQLitePCLRaw"], None))
        self.assertEqual(rw.check_crates(get, V)[1], ["potluckdb 0.8.0-dev.3"])
        self.assertEqual(rw.check_go(get, V)[1], ["github.com/potluckdb/potluckdb-go/sqlite3"])
        self.assertEqual(rw.check_pypi(registry({}), V)[1], ["potluckdb 0.8.0.dev3"])


def listed(id, created, name=rw.run_name(V)):
    return {"id": id, "created_at": created, "display_title": name}


def start(fake_run, gh=None):
    clock = Clock()
    env = {"PYPI_PUBLISHING": "true", "CRATES_IO_PUBLISHING": "true", "NUGET_PUBLISHING": "true",
           "NPM_PUBLISHING": "false"}
    with contextlib.redirect_stdout(io.StringIO()):
        runs = rw.start(V, env, run=fake_run, gh=gh or GitHub(), clock=clock, sleep=clock.sleep)
    return runs, clock.now - T0


class StartTest(unittest.TestCase):
    def test_starts_the_registries_that_are_on(self):
        started = []

        def fake_run(cmd, **kw):
            started.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, f"https://github.com/potluckdb/potluckdb/actions/runs/{len(started)}\n", "")
        runs, took = start(fake_run)
        self.assertEqual([c[3] for c in started], ["python.yml", "rust.yml", "dotnet.yml"])
        self.assertEqual(started[0], ["gh", "workflow", "run", "python.yml", "-R", "potluckdb/potluckdb",
                                      "-f", f"version={V}", "-f", "publish=true"])
        self.assertEqual(runs["python"], {"at": "2026-10-24T00:59:40Z", "run": 1})
        self.assertEqual((runs["node"], runs["go"]), ({"off": True}, {"off": True}))
        self.assertEqual(took, datetime.timedelta(0))

    def test_a_start_that_fails_is_looked_for_before_it_is_tried_again(self):
        # Every first try gets a 502. python's run started anyway (listed at the
        # second look), dotnet's starts at the second try, rust's never does.
        started = []

        def fake_run(cmd, **kw):
            started.append(cmd[3])
            if cmd[3] == "dotnet.yml" and len(started) > 3:
                return subprocess.CompletedProcess(cmd, 0, "https://github.com/potluckdb/potluckdb/actions/runs/5\n", "")
            if cmd[3] == "rust.yml" and len(started) == 4:
                raise subprocess.TimeoutExpired(cmd, kw["timeout"])
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 502: Bad Gateway")
        gh = GitHub(listed={"python.yml": [[], [listed(4, "2026-10-24T00:59:41Z")]]})
        runs, took = start(fake_run, gh)
        self.assertEqual(started, ["python.yml", "rust.yml", "dotnet.yml", "rust.yml", "dotnet.yml", "rust.yml", "rust.yml"])
        self.assertEqual(runs["python"], {"at": "2026-10-24T00:59:40Z", "run": 4})
        self.assertEqual(runs["dotnet"], {"at": "2026-10-24T00:59:40Z", "run": 5})
        self.assertEqual(runs["rust"], {"at": "2026-10-24T00:59:40Z", "run": None, "error": "HTTP 502: Bad Gateway"})
        self.assertEqual(took, datetime.timedelta(seconds=3 * 2 * rw.LOOK_EVERY))  # 4 tries in about 2 minutes

    def test_start_ends_within_its_budget_when_every_gh_command_hangs(self):
        clock, real_start = Clock(), rw.start

        def hang_run(cmd, **kw):
            clock.sleep(kw["timeout"])
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])

        def hang_gh(path):
            clock.sleep(rw.START_CALL)
            raise rw.ApiError(f"gh api -X GET {path}: no answer in {rw.START_CALL} seconds")

        def hanging_start(version, env, runs):
            return real_start(version, env, run=hang_run, gh=hang_gh, clock=clock, sleep=clock.sleep, runs=runs)
        with tempfile.TemporaryDirectory() as folder:
            output = pathlib.Path(folder, "output")
            env = {variable: "true" for _, _, variable in rw.REGISTRIES.values()}
            with mock.patch.object(rw, "start", hanging_start), mock.patch.dict(os.environ, {**env, "GITHUB_OUTPUT": str(output)}), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(rw.main(["start", "--version", V]), 0)
            written = output.read_text(encoding="utf-8")
        # Every first start (5 x 30 s), one wait and the 2 lookups that still fit.
        self.assertEqual(clock.now - T0, datetime.timedelta(seconds=225))
        self.assertLessEqual(clock.now - T0, datetime.timedelta(seconds=rw.START_BUDGET))
        runs = json.loads(written.removeprefix("runs="))
        self.assertEqual(runs["python"], {"at": "2026-10-24T00:59:40Z", "run": None,
                                          "error": "gh workflow run gave no answer in 30 seconds"})
        self.assertEqual(runs["go"], {"at": "2026-10-24T01:01:40Z", "run": None,
                                      "error": "gh workflow run gave no answer in 30 seconds"})

    def test_the_output_is_written_even_if_start_fails(self):
        def failing_start(version, env, runs):
            runs["python"] = {"at": "2026-10-24T00:59:40Z", "run": 4}
            raise RuntimeError("start failed half way")
        with tempfile.TemporaryDirectory() as folder:
            output = pathlib.Path(folder, "output")
            with mock.patch.object(rw, "start", failing_start), mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                with self.assertRaises(RuntimeError):
                    rw.main(["start", "--version", V])
            self.assertEqual(output.read_text(encoding="utf-8"), 'runs={"python": {"at": "2026-10-24T00:59:40Z", "run": 4}}\n')

    def test_a_run_started_despite_a_hung_start_is_found_by_watch(self):
        # Each start hangs, but GitHub started python's run; it is listed only
        # after start() has given up.
        clock = Clock()
        shows_up = T0 + datetime.timedelta(seconds=rw.START_BUDGET + 30)

        def hang_run(cmd, **kw):
            clock.sleep(kw["timeout"])
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])

        def gh(path, method="GET"):
            if path.endswith("/runs/4"):
                return run(4)
            return {"workflow_runs": [listed(4, "2026-10-24T00:59:41Z")] if clock.now >= shows_up else []}
        with contextlib.redirect_stdout(io.StringIO()):
            runs = rw.start(V, {"PYPI_PUBLISHING": "true"}, run=hang_run, gh=gh, clock=clock, sleep=clock.sleep)
        self.assertEqual(runs["python"]["run"], None)
        self.assertLessEqual(clock.now - T0, datetime.timedelta(seconds=rw.START_BUDGET))
        regs = rw.watch(V, json.loads(json.dumps(runs)), gh, registry(SERVED), clock=clock, sleep=clock.sleep,
                        log=lambda *a: None)
        self.assertEqual((regs["python"]["run"], regs["python"]["final"], regs["python"]["missing"]), (4, "success", []))
        self.assertFalse([line for line in rw.problems(regs, V) if line.startswith("PyPI")])


class WatchTest(unittest.TestCase):
    def test_a_failed_run_is_rerun_once_and_its_registry_waited_for(self):
        gh = GitHub(states={7: [run(7, "in_progress"), run(7, conclusion="failure"),
                                run(7, conclusion="failure"),  # the re-run is not visible yet
                                run(7, "queued", attempt=2), run(7, attempt=2)]})
        clock = Clock()
        regs = watch(only("python", at="2026-10-24T00:59:40Z", run=7), gh, registry(SERVED, missing_calls=2), clock)
        self.assertEqual(gh.reruns(), ["repos/potluckdb/potluckdb/actions/runs/7/rerun-failed-jobs"])
        python = regs["python"]
        self.assertEqual((python["final"], python["reran"], python["missing"]), ("success", True, []))
        # Missing at the first two checks after the run: the third check's time.
        self.assertEqual(python["served_at"], T0 + datetime.timedelta(seconds=6 * rw.POLL))
        self.assertEqual(rw.problems(regs, V), [
            f"{rw.REGISTRIES[k][0]}: {rw.REGISTRIES[k][1]} was not started because the repository variable "
            f"{rw.REGISTRIES[k][2]} is not 'true'" for k in ["rust", "dotnet", "node", "go"]])

    def test_a_registry_gets_until_the_goal_and_at_least_30_minutes_after_its_run(self):
        # NuGet listed 0.8.0-dev.4 20 minutes after its run: in time for the 1 hour goal.
        goal = T0 + datetime.timedelta(minutes=40)
        regs = watch(only("dotnet", run=7), GitHub(states={7: [run(7)]}), registry(SERVED, missing_calls=20), goal=goal)
        self.assertEqual(regs["dotnet"]["served_at"], T0 + datetime.timedelta(seconds=20 * rw.POLL))
        self.assertFalse([line for line in rw.problems(regs, V) if line.startswith("NuGet")])
        # Never served: reported at the goal, or 30 minutes after the run if that is later.
        for goal, ends in [(goal, 40), (T0 + datetime.timedelta(minutes=5), 30), (None, 30)]:
            clock = Clock()
            regs = watch(only("dotnet", run=7), GitHub(states={7: [run(7)]}), registry({}), clock, goal=goal)
            self.assertEqual(clock.now, T0 + datetime.timedelta(minutes=ends))
            self.assertIn("NuGet does not serve 0.8.0-dev.3 of: PotluckDB.SQLitePCLRaw, PotluckDB.Data.Sqlite",
                          rw.problems(regs, V))

    def test_an_answer_the_check_does_not_understand_is_asked_for_again(self):
        url = "https://crates.io/api/v1/crates/potluckdb/0.8.0-dev.3"
        odd, good = {"version": {}}, {"version": {"created_at": "2026-10-24T01:02:03Z"}}
        regs = watch(only("rust", run=7), GitHub(states={7: [run(7)]}), registry({url: odd}))
        self.assertIn("crates.io: could not check whether it serves 0.8.0-dev.3: "
                      "its last answer was not understood (KeyError('created_at'))", rw.problems(regs, V))
        rows = rw.timings(V, regs, GitHub(states={7: [run(7)]}), None, None, None, T0)
        self.assertIn(("**crates.io**: 0.8.0-dev.3", None, None,
                       "unknown: its last answer was not understood (KeyError('created_at'))"), rows)
        answers = [odd, odd, good]

        def get(url):
            return 200, answers.pop(0)
        regs = watch(only("rust", run=7), GitHub(states={7: [run(7)]}), get)
        self.assertEqual(regs["rust"]["served_at"], rw.parse_time("2026-10-24T01:02:03Z"))
        self.assertFalse([line for line in rw.problems(regs, V) if line.startswith("crates.io")])

    def test_an_answer_cut_off_is_no_answer(self):
        class Response:
            status, headers = 200, {"Content-Encoding": "gzip"}

            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *error):
                return False

            def read(self):
                if isinstance(self.body, Exception):
                    raise self.body
                return self.body
        body = gzip.compress(b'{"versions": []}')
        corrupt = body[:10] + b"\x07" + bytes(8)  # a deflate block of a type that does not exist
        for answer, expected in [(body, (200, {"versions": []})), (body[:-5], (None, None)), (corrupt, (None, None)),
                                 (http.client.IncompleteRead(b"{"), (None, None))]:
            with mock.patch.object(rw.urllib.request, "urlopen", return_value=Response(answer)):
                self.assertEqual(rw.http_get("https://api.nuget.org/x"), expected)

    def test_a_run_that_fails_again_is_not_rerun_twice(self):
        gh = GitHub(states={7: [run(7, conclusion="failure"), run(7, "in_progress", attempt=2),
                                run(7, conclusion="failure", attempt=2)]})
        regs = watch(only("node", run=7), gh, registry({}))
        self.assertEqual(len(gh.reruns()), 1)
        self.assertIn("npm: node.yml run https://github.com/potluckdb/potluckdb/actions/runs/7 ended in failure, "
                      "also after re-running its failed jobs", rw.problems(regs, V))
        self.assertIn("npm does not serve 0.8.0-dev.3 of: " + ", ".join(
            [f"@potluckdb/{t}" for t in rw.TARGETS] + ["potluckdb"]), rw.problems(regs, V))

    def test_a_registry_is_not_asked_before_its_run_is_over(self):
        gh = GitHub(states={7: [run(7, "in_progress")]})
        get = registry(SERVED)
        regs = watch(only("go", run=7), gh, get, deadline=T0 + datetime.timedelta(minutes=10))
        self.assertEqual(get.asked, {})
        self.assertEqual(rw.problems(regs, V)[-1], "Go module proxy: go.yml run 7 had not finished in time")

    def test_no_answer_from_github_is_unknown_for_that_round(self):
        no_answer = rw.ApiError("gh api: HTTP 503: Service Unavailable")
        gh = GitHub(states={7: [no_answer, run(7, "in_progress"), run(7, conclusion="failure"),
                                run(7, conclusion="failure"), run(7, attempt=2)]}, post_errors=[no_answer])
        regs = watch(only("python", run=7), gh, registry(SERVED))
        self.assertEqual(len(gh.reruns()), 2)  # the first re-run got no answer: asked again next round
        self.assertEqual((regs["python"]["final"], regs["python"]["missing"]), ("success", []))
        # GitHub never answers: asked every round until the deadline, then reported.
        clock = Clock()
        regs = watch(only("python", run=7), GitHub(states={7: [no_answer]}), registry(SERVED), clock,
                     deadline=T0 + datetime.timedelta(minutes=10))
        self.assertEqual(clock.now, T0 + datetime.timedelta(minutes=10))
        self.assertIn("PyPI: python.yml run 7 had not finished in time "
                      "(GitHub's last answer: gh api: HTTP 503: Service Unavailable)", rw.problems(regs, V))
        # An answer without the run's fields, or an empty one, is no answer either.
        regs = watch(only("python", run=7), GitHub(states={7: [{}, None, run(7)]}), registry(SERVED))
        self.assertEqual(regs["python"]["final"], "success")

    def test_a_slow_github_does_not_hold_watch_past_the_deadline(self):
        clock = Clock()

        def slow(path, method="GET"):  # 3 tries of 60 seconds, 2 waits of 10
            clock.sleep(200)
            raise rw.ApiError("gh api: no answer in 60 seconds")
        runs = {key: {"run": i} for i, key in enumerate(rw.REGISTRIES, 1)}
        regs = watch(runs, slow, registry(SERVED), clock, deadline=T0 + datetime.timedelta(minutes=5))
        self.assertLessEqual(clock.now, T0 + datetime.timedelta(minutes=5, seconds=200))  # 5 runs would be 1,000 a round
        self.assertEqual(len([line for line in rw.problems(regs, V) if "had not finished in time" in line]), 5)

    def test_a_gh_command_that_hangs_is_a_failed_try(self):
        answers = [subprocess.TimeoutExpired("gh", 60), subprocess.CompletedProcess([], 1, "", "HTTP 502"),
                   subprocess.CompletedProcess([], 0, '{"id": 7}', "")]

        def fake_run(cmd, **kw):
            self.assertEqual(kw["timeout"], rw.GH_TIMEOUT)
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        self.assertEqual(rw.gh_api("repos/x", run=fake_run, sleep=lambda s: None), {"id": 7})
        answers[:] = [subprocess.TimeoutExpired("gh", 60)] * 3
        with self.assertRaisesRegex(rw.ApiError, "no answer in 60 seconds"):
            rw.gh_api("repos/x", run=fake_run, sleep=lambda s: None)

    def test_check_only_reads_and_never_reruns_or_waits(self):
        gh = GitHub(states={7: [run(7, conclusion="failure")]})
        clock = Clock()
        regs = watch(only("dotnet", run=7), gh, registry(SERVED), clock, check_only=True)
        self.assertEqual((gh.reruns(), clock.now), ([], T0))
        self.assertEqual(regs["dotnet"]["served_at"], rw.parse_time("2026-10-24T01:18:44Z"))  # NuGet's own time

    def test_a_run_without_an_id_is_looked_for_by_its_name_and_time(self):
        # Listed at the third look: the oldest run named for this version that
        # was created at most 5 seconds before it was started.
        runs = [listed(6, "2026-10-24T00:59:30Z"), listed(7, "2026-10-24T00:59:41Z", name="python"),
                listed(9, "2026-10-24T01:30:00Z"), listed(8, "2026-10-24T00:59:42Z")]
        gh = GitHub(states={8: [run(8)]}, listed={"python.yml": [[], [], runs]})
        regs = watch(only("python", at="2026-10-24T00:59:40Z", run=None, error="HTTP 502"), gh, registry(SERVED))
        self.assertEqual((regs["python"]["run"], regs["python"]["final"]), (8, "success"))
        self.assertIn(("GET", "repos/potluckdb/potluckdb/actions/workflows/python.yml/runs?event=workflow_dispatch"
                       "&branch=main&per_page=100&created=%3E%3D2026-10-24T00%3A59%3A35Z"), gh.calls)
        # Never listed: not started, after looking for 2 minutes.
        clock = Clock()
        regs = watch(only("python", at="2026-10-24T00:59:40Z", run=None, error="HTTP 502"), GitHub(), registry(SERVED), clock)
        self.assertEqual(clock.now - T0, datetime.timedelta(seconds=rw.LOOK_FOR))
        self.assertIn("PyPI: python.yml was not started: HTTP 502", rw.problems(regs, V))


class TableTest(unittest.TestCase):
    def test_rows_group_matrix_jobs_and_show_each_attempt(self):
        def job(name, start, end, conclusion="success", attempt=1):
            return {"name": name, "status": "completed", "conclusion": conclusion, "run_attempt": attempt,
                    "started_at": f"2026-10-24T{start}Z", "completed_at": f"2026-10-24T{end}Z"}
        gh = GitHub(states={7: [run(7, attempt=2, started="2026-10-24T01:10:00Z", updated="2026-10-24T01:20:00Z")]},
                    attempts={(7, 1): run(7, conclusion="failure", updated="2026-10-24T01:00:32Z")}, jobs={
            (7, 1): [job("plan", "00:59:47", "00:59:49"), job("native linux-x64-musl", "00:59:52", "01:00:05", "failure"),
                     job("native macos-x64", "00:59:52", "01:00:11"), job("publish", "01:00:12", "01:00:12", "skipped")],
            (7, 2): [job("plan", "00:59:47", "00:59:49"),  # kept from attempt 1
                     job("native linux-x64-musl", "01:10:05", "01:11:00", attempt=2),
                     job("publish", "01:15:00", "01:18:44", attempt=2)]})
        rows = rw.run_rows(gh, 7, "dotnet.yml")
        self.assertEqual([(r[0], r[3]) for r in rows], [
            ("dotnet.yml run 7, attempt 1", "failure"), ("- plan", "success"), ("- native (2 jobs)", "failure, success"),
            ("dotnet.yml run 7, attempt 2", "success"), ("- native", "success"), ("- publish", "success")])
        table = rw.render(V, [rows[1], ("**NuGet**: x", None, rw.parse_time("2026-11-03T18:15:55Z"), "served")], T0)
        self.assertIn("| - plan | 00:59:47 | 00:59:49 | 0m 02s | 0m 09s | success |", table)
        self.assertIn("| **NuGet**: x |  | 11-03 18:15:55 |  | 10d 17h | served |", table)

    def test_the_table_is_written_when_github_gives_no_details(self):
        # Every run succeeded and every registry serves the version, but GitHub
        # does not answer for release.yml's run or for python's jobs.
        no_answer = rw.ApiError("gh api: HTTP 502: Bad Gateway")
        gh = GitHub(states={**{i: [run(i)] for i in range(1, 6)}, 99: [no_answer]}, jobs={(1, 1): no_answer})
        served = {key: (lambda get, version, key=key: (f"{key} {version}", [], T0)) for key in rw.REGISTRIES}
        runs = {key: {"at": "2026-10-24T00:59:40Z", "run": i} for i, key in enumerate(rw.REGISTRIES, 1)}
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(rw, "gh_api", gh), \
                mock.patch.dict(rw.CHECKS, served), mock.patch.object(rw, "watch", wraps=rw.watch) as spy, \
                contextlib.redirect_stdout(io.StringIO()):
            summary = pathlib.Path(folder, "summary.md")
            code = rw.main(["watch", "--version", V, "--runs", json.dumps(runs), "--release-run", "99",
                            "--build-started-at", "2026-10-24T00:49:55Z", "--summary", str(summary), "--out", folder])
            table = summary.read_text(encoding="utf-8")
            self.assertEqual(table, pathlib.Path(folder, "timings.md").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)  # only a registry that is off, not served or whose run failed is a problem
        self.assertEqual(spy.call_args.kwargs["goal"], rw.parse_time("2026-10-24T01:49:55Z"))  # 1 hour after core's start
        unknown = "unknown: could not read it from GitHub (gh api: HTTP 502: Bad Gateway)"
        self.assertIn(f"| release.yml run 99 |  |  |  |  | {unknown} |", table)
        self.assertIn(f"| python.yml run 1 |  |  |  |  | {unknown} |", table)
        self.assertIn("| rust.yml run 2 | 00:59:44 | 01:04:00 | 4m 16s | 14m 05s | success |", table)
        self.assertIn("| **PyPI**: python 0.8.0-dev.3 |  | 00:59:40 |  | 9m 45s | served |", table)

    def test_without_cores_start_the_goal_and_the_table_count_from_release_yml(self):
        gh = GitHub(states={i: [run(i, started="2026-10-24T00:50:00Z" if i == 99 else "2026-10-24T00:59:44Z")]
                            for i in [*range(1, 6), 99]})
        served = {key: (lambda get, version, key=key: (f"{key} {version}", [], T0)) for key in rw.REGISTRIES}
        runs = {key: {"at": "2026-10-24T00:59:40Z", "run": i} for i, key in enumerate(rw.REGISTRIES, 1)}
        output = io.StringIO()
        with mock.patch.object(rw, "gh_api", gh), mock.patch.dict(rw.CHECKS, served), \
                mock.patch.object(rw, "watch", wraps=rw.watch) as spy, contextlib.redirect_stdout(output):
            code = rw.main(["watch", "--version", V, "--runs", json.dumps(runs), "--release-run", "99"])
        self.assertEqual(code, 0)
        self.assertEqual(spy.call_args.kwargs["goal"], rw.parse_time("2026-10-24T01:50:00Z"))
        self.assertIn('"Done after" counts from 00:50:00.', output.getvalue())
        self.assertNotIn("core release-build", output.getvalue())

    def test_past_the_deadline_the_table_asks_github_once_and_quickly(self):
        gh = GitHub(states={i: [run(i)] for i in [*range(1, 6), 99]})
        runs = {key: {"run": i} for i, key in enumerate(rw.REGISTRIES, 1)}
        with mock.patch.object(rw, "gh_api", gh), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            code = rw.main(["watch", "--version", V, "--runs", json.dumps(runs), "--release-run", "99",
                            "--deadline-minutes", "-1"])
        self.assertEqual(code, 1)  # no run was followed
        self.assertEqual(gh.options[0], {})  # release.yml's start, before watch
        self.assertEqual(len(gh.options), 13)  # each of the 6 runs and its jobs
        self.assertTrue(all(options == {"tries": 1, "timeout": 15} for options in gh.options[1:]))


@unittest.skipUnless(shutil.which("git") and shutil.which("bash") and (os.name != "nt" or os.environ.get("MSYSTEM")),
                     "needs git and bash (on Windows, Git Bash)")
class GoPublishTest(unittest.TestCase):
    def test_a_push_that_fails_leaves_no_tags_so_a_rerun_can_publish(self):
        # go/scripts/publish.sh pushes main and every module's tag at once. One
        # rejected tag must reject them all: a re-run refuses to add to tags
        # that already exist.
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            for module in ["sqlite3", "lib/linux-x64-gnu"]:
                (folder / "tree" / module).mkdir(parents=True)
                (folder / "tree" / module / "go.mod").write_text(f"module example.com/{module}\n")
            (folder / "config").write_text("")
            env = {**os.environ, "GIT_CONFIG_GLOBAL": str(folder / "config"), "GIT_CONFIG_NOSYSTEM": "1"}
            remote = folder / "remote.git"
            subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, env=env)
            hook = remote / "hooks" / "update"
            hook.write_text('#!/bin/sh\ncase "$1" in refs/tags/sqlite3/*) echo "rejected $1" >&2; exit 1;; esac\n')
            hook.chmod(0o755)
            publish = [shutil.which("bash"), str(pathlib.Path(__file__).parent.parent / "go/scripts/publish.sh"),
                       (folder / "tree").as_posix(), "0.8.0-dev.9", remote.as_posix()]

            def refs():
                listed = subprocess.run(["git", "ls-remote", str(remote)], capture_output=True, text=True, env=env)
                return sorted(line.split("\t")[1] for line in listed.stdout.splitlines())
            failed = subprocess.run(publish, capture_output=True, text=True, env=env)
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(refs(), [])
            hook.unlink()  # the cause is gone: the re-run publishes everything
            subprocess.run(publish, check=True, capture_output=True, env=env)
            self.assertEqual(refs(), ["refs/heads/main", "refs/tags/lib/linux-x64-gnu/v0.8.0-dev.9",
                                      "refs/tags/sqlite3/v0.8.0-dev.9"])


if __name__ == "__main__":
    unittest.main()
