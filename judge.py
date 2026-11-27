#!/usr/bin/env python3
"""Compile, run and check submissions against the GCPC 2018 test data.

Library used by server.py, and a command line tool:

  python3 judge.py A sol.cpp            judge one file on all tests (like a real submission)
  python3 judge.py A sol.cpp --samples  only the sample tests, with diffs on failure
  python3 judge.py --jury [A B ...]     run the official jury submissions and compare verdicts

The programs run as your own user without a sandbox: only judge code you trust.
"""
import argparse
import glob
import json
import math
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

import checkers

ROOT = os.path.dirname(os.path.abspath(__file__))
CONTEST_DIR = ROOT  # folder with contest.json and problems/; practice/ for the test contest
PROBLEMS = os.path.join(ROOT, "problems")

LANGS = {
    "cpp": "C++ (g++ -std=gnu++20 -O2)",
    "c": "C (gcc -std=gnu17 -O2)",
    "py": "Python 3",
}
EXT = {".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".c": "c", ".py": "py"}

VERDICT_NAMES = {
    "AC": "Accepted", "WA": "Wrong Answer", "TLE": "Time Limit Exceeded",
    "RTE": "Run Time Error", "CE": "Compiler Error", "JE": "Judge Error",
}


def set_contest_dir(d):
    global CONTEST_DIR, PROBLEMS
    CONTEST_DIR = os.path.abspath(d)
    PROBLEMS = os.path.join(CONTEST_DIR, "problems")


def load_contest():
    with open(os.path.join(CONTEST_DIR, "contest.json")) as f:
        return json.load(f)


def problem_by_letter(contest, letter):
    for p in contest["problems"]:
        if p["letter"] == letter.upper():
            return p
    raise KeyError(f"no problem {letter}")


def testcases(letter, samples_only=False):
    base = os.path.join(PROBLEMS, letter, "data")
    groups = ["sample"] if samples_only else ["sample", "secret"]
    out = []
    for g in groups:
        ins = sorted(glob.glob(os.path.join(base, g, "**", "*.in"), recursive=True))
        out += [(os.path.relpath(i, base)[:-3], i, i[:-3] + ".ans") for i in ins]
    return out


def lang_of(filename):
    return EXT.get(os.path.splitext(filename)[1].lower())


# ---------------------------------------------------------------- compile

def compile_source(src_path, lang, workdir):
    """Returns (ok, message, run_cmd)."""
    if lang == "cpp" or lang == "c":
        exe = os.path.join(workdir, "a.out")
        cmd = (["g++", "-x", "c++", "-std=gnu++20"] if lang == "cpp"
               else ["gcc", "-x", "c", "-std=gnu17"])
        cmd += ["-O2", "-pipe", "-DONLINE_JUDGE", "-o", exe, src_path, "-lm"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        msg = r.stderr.replace(os.path.dirname(os.path.abspath(src_path)) + os.sep, "")
        return r.returncode == 0, msg[-20000:], [exe]
    if lang == "py":
        dst = os.path.join(workdir, "main.py")
        shutil.copyfile(src_path, dst)
        r = subprocess.run([sys.executable, "-c",
                            "import sys; compile(open(sys.argv[1], 'rb').read(), sys.argv[2], 'exec')",
                            dst, os.path.basename(src_path)],
                           capture_output=True, text=True, timeout=60)
        return r.returncode == 0, r.stderr[-20000:], ["python3", dst]
    return False, f"unknown language {lang}", None


# ---------------------------------------------------------------- run

def run_one(cmd, inp, outp, errp, time_limit, mem_mb, workdir):
    """Run cmd on one input file. Returns dict(status, cpu, wall, mem_kb, exit)."""
    mem = mem_mb * 1024 * 1024
    cpu_cap = math.ceil(time_limit) + 1

    def limits():
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_cap, cpu_cap + 1))
        resource.setrlimit(resource.RLIMIT_AS, (mem + (64 << 20),) * 2)
        resource.setrlimit(resource.RLIMIT_STACK, (mem,) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (256 << 20,) * 2)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    with open(inp, "rb") as fi, open(outp, "wb") as fo, open(errp, "wb") as fe:
        start = time.monotonic()
        p = subprocess.Popen(cmd, stdin=fi, stdout=fo, stderr=fe, cwd=workdir,
                             preexec_fn=limits, start_new_session=True)
        killed = []

        def kill():
            killed.append(1)
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        timer = threading.Timer(2 * time_limit + 2, kill)
        timer.start()
        _, status, ru = os.wait4(p.pid, 0)
        timer.cancel()
        p.returncode = 0  # reaped ourselves; keep Popen from complaining
        wall = time.monotonic() - start
    cpu = ru.ru_utime + ru.ru_stime
    res = {"cpu": round(cpu, 3), "wall": round(wall, 3), "mem_kb": ru.ru_maxrss}
    sig = os.WTERMSIG(status) if os.WIFSIGNALED(status) else None
    code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else None
    if killed or cpu > time_limit or sig == signal.SIGXCPU:
        res["status"] = "TLE"
    elif sig is not None:
        res["status"] = "RTE"
        res["detail"] = f"killed by signal {signal.Signals(sig).name}"
        if sig == signal.SIGXFSZ:
            res["detail"] = "output limit exceeded (256 MB)"
    elif code != 0:
        res["status"] = "RTE"
        res["detail"] = f"exit code {code}"
    else:
        res["status"] = "OK"
    return res


# ---------------------------------------------------------------- judge

def judge(src_path, letter, lang=None, samples_only=False, contest=None,
          progress=None, keep_going=False):
    """Judge one submission. Returns a result dict."""
    contest = contest or load_contest()
    prob = problem_by_letter(contest, letter)
    lang = lang or lang_of(src_path)
    result = {"problem": prob["letter"], "lang": lang, "tests": [], "verdict": None}
    work = tempfile.mkdtemp(prefix="gcpc18-")
    try:
        try:
            ok, msg, cmd = compile_source(src_path, lang, work)
        except subprocess.TimeoutExpired:
            ok, msg, cmd = False, "compilation timed out", None
        result["compile_output"] = msg
        if not ok:
            result["verdict"] = "CE"
            return result
        tests = testcases(prob["letter"], samples_only)
        if not tests:
            result["verdict"] = "JE"
            result["message"] = "no test data found, run setup.py"
            return result
        tl = prob["time_limit"]
        out = os.path.join(work, "team.out")
        err = os.path.join(work, "team.err")
        for i, (name, inp, ans) in enumerate(tests):
            if progress:
                progress(i, len(tests))
            r = run_one(cmd, inp, out, err, tl, contest["memory_limit_mb"], work)
            r["name"] = name
            if r["status"] == "OK":
                good, why = checkers.check(prob["checker"], inp, ans, out)
                r["status"] = "AC" if good else "WA"
                r["detail"] = why
            if r["status"] != "AC" and name.startswith("sample"):
                r["output"] = _head(out)
                r["expected"] = _head(ans)
                r["stderr"] = _head(err)
            result["tests"].append(r)
            if r["status"] != "AC" and result["verdict"] is None:
                result["verdict"] = r["status"]
                if not keep_going:
                    break
        result["verdict"] = result["verdict"] or "AC"
        result["max_cpu"] = max((t["cpu"] for t in result["tests"]), default=0)
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _head(path, limit=4000):
    try:
        with open(path, "rb") as f:
            data = f.read(limit + 1)
    except OSError:
        return ""
    s = data[:limit].decode("utf-8", "replace")
    return s + ("\n[... truncated]" if len(data) > limit else "")


# ---------------------------------------------------------------- CLI

def print_result(res, verbose=True):
    if res["verdict"] == "CE":
        print(res["compile_output"])
    for t in res["tests"]:
        line = f"  {t['name']:<40} {t['status']:<4} {t['cpu']:6.2f}s"
        if t["status"] != "AC" and t.get("detail"):
            line += "  " + t["detail"]
        if verbose or t["status"] != "AC":
            print(line)
        if t.get("output") is not None and t["status"] != "AC":
            print("  --- your output ---\n" + t["output"])
            print("  --- expected ---\n" + t.get("expected", ""))
            if t.get("stderr"):
                print("  --- stderr ---\n" + t["stderr"])
    print(f"{VERDICT_NAMES.get(res['verdict'], res['verdict'])}"
          + (f"  (max cpu {res.get('max_cpu', 0):.2f}s)" if res["tests"] else ""))


EXPECTED = {"accepted": "AC", "wrong_answer": "WA", "time_limit_exceeded": "TLE",
            "run_time_error": "RTE"}


def is_python2(path):
    code = open(path, encoding="utf-8", errors="replace").read()
    return bool(re.search(r"\braw_input\b|\bxrange\b|^\s*print\s+[^\s(=]", code, re.M))


def jury_check(letters, contest):
    rows = []
    for p in contest["problems"]:
        if letters and p["letter"] not in letters:
            continue
        for f in sorted(glob.glob(os.path.join(PROBLEMS, p["letter"], "jury", "*", "*"))):
            cat = os.path.basename(os.path.dirname(f))
            lang = lang_of(f)
            if lang is None:
                continue
            if lang == "py" and is_python2(f):
                print(f"-- {p['letter']} {cat:<20} {os.path.basename(f):<42} skipped (Python 2 source)")
                continue
            t0 = time.time()
            res = judge(f, p["letter"], lang, contest=contest)
            want = EXPECTED.get(cat, "?")
            got = res["verdict"]
            if got == want:
                mark = "ok "
            elif (want == "AC") == (got == "AC") and got not in ("CE", "JE"):
                mark = "~  "  # rejected, but with a different verdict
            else:
                mark = "XX "
            line = (f"{mark}{p['letter']} {cat:<20} {os.path.basename(f):<42} "
                    f"{got:<4} cpu {res.get('max_cpu', 0):5.2f}s  [{time.time() - t0:.0f}s]")
            if got != "AC" and res["tests"]:
                bad = res["tests"][-1]
                line += f"  {bad['name']}: {bad.get('detail', '')}"[:200]
            if got == "CE":
                line += "  " + res["compile_output"].strip().splitlines()[-1][:150] \
                    if res["compile_output"].strip() else ""
            print(line, flush=True)
            rows.append((p["letter"], cat, os.path.basename(f), want, got))
    bad = [r for r in rows if r[3] == "AC" and r[4] != "AC"
           or r[3] != "AC" and r[4] == "AC"]
    print(f"\n{len(rows)} jury submissions, {len(bad)} with the wrong accept/reject outcome")
    for r in bad:
        print("   ", *r)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("problem", nargs="?", help="problem letter A-M")
    ap.add_argument("source", nargs="?", help="source file (.cpp .c .py)")
    ap.add_argument("--samples", action="store_true", help="only run sample tests")
    ap.add_argument("--all", action="store_true", help="do not stop at the first failure")
    ap.add_argument("-q", "--quiet", action="store_true", help="only print failing tests")
    ap.add_argument("--jury", nargs="*", metavar="LETTER",
                    help="run all jury submissions (optionally for some problems)")
    ap.add_argument("--practice", action="store_true",
                    help="use the spoiler-free practice contest in practice/")
    a = ap.parse_args()
    if a.practice:
        set_contest_dir(os.path.join(ROOT, "practice"))
    contest = load_contest()
    if a.jury is not None:
        letters = [x.upper() for x in a.jury]
        if a.problem:
            letters.append(a.problem.upper())
        jury_check(letters, contest)
        return
    if not a.problem or not a.source:
        ap.error("need a problem letter and a source file")
    if not lang_of(a.source):
        ap.error("unknown language; use .cpp .c or .py")
    res = judge(a.source, a.problem, samples_only=a.samples, contest=contest,
                keep_going=a.all)
    print_result(res, verbose=not a.quiet)
    sys.exit(0 if res["verdict"] == "AC" else 1)


if __name__ == "__main__":
    main()
