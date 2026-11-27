#!/usr/bin/env python3
"""End-to-end self test of the local judge. Spoiler-free: it never shows GCPC problems or solutions.

  python3 selftest.py          environment + GCPC data + practice server round trip (about 30 s)
  python3 selftest.py --full   also judges one official accepted C++ solution per GCPC problem
                               (prints only pass/fail, a few minutes)

The practice server runs on a free port with a temporary state folder, so the real
contest state (state/) and any running server are not touched.
"""
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import judge  # noqa: E402

results = []


def report(ok, what, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {what}" + (f"  ({detail})" if detail else ""), flush=True)


def section(title):
    print(f"\n== {title}", flush=True)


# ---------------------------------------------------------------- environment

def check_environment():
    section("Environment")
    for tool in ("g++", "gcc"):
        report(shutil.which(tool) is not None, f"{tool} found", shutil.which(tool) or "missing")
    report(sys.version_info >= (3, 8), "python3 >= 3.8", sys.version.split()[0])


def check_gcpc_data():
    section("GCPC 2018 contest data")
    judge.set_contest_dir(ROOT)
    c = judge.load_contest()
    report(len(c["problems"]) == 13, "13 problems in contest.json")
    total = 0
    for p in c["problems"]:
        n = len(judge.testcases(p["letter"]))
        s = len(judge.testcases(p["letter"], samples_only=True))
        total += n
        if n == 0 or s == 0:
            report(False, f"problem {p['letter']} has test data", f"{s} samples, {n} tests")
    report(total == 354, "all 354 test cases present", f"found {total}")
    for key in ("statement_pdf", "solutions_pdf"):
        path = os.path.join(ROOT, c[key])
        report(os.path.exists(path), f"{key} present", os.path.relpath(path, ROOT))
    sb = os.path.join(ROOT, "data", "scoreboard.json")
    teams = json.load(open(sb, encoding="utf-8")) if os.path.exists(sb) else []
    report(len(teams) == 127, "original scoreboard parsed", f"{len(teams)} teams")
    nb = os.path.join(ROOT, "..", "kactl", "kactl.pdf")
    print(f"  [info] team notebook {'found' if os.path.exists(nb) else 'not found'} at ../kactl/kactl.pdf")


# ---------------------------------------------------------------- practice server

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(url, data=None, ctype="application/json"):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


EXPECT = [  # (file, problem, expected verdict), in submission order
    ("A_wa_overflow.cpp", "A", "WA"),
    ("A_tle.cpp", "A", "TLE"),
    ("A_rte.cpp", "A", "RTE"),
    ("A_ce.cpp", "A", "CE"),
    ("A_ac.cpp", "A", "AC"),
    ("A_ac.py", "A", "AC"),
    ("B_wa_sample.py", "B", "WA"),
    ("B_wa_precision.cpp", "B", "WA"),
    ("B_ac.cpp", "B", "AC"),
]


def check_practice_server():
    section("Practice server round trip (practice/, temporary state)")
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    tmp = tempfile.mkdtemp(prefix="gcpc18-selftest-")
    log = open(os.path.join(tmp, "server.log"), "w")
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py"), "--practice",
                            "--port", str(port), "--state", os.path.join(tmp, "state")],
                           stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                if http(base + "/")[0] == 200:
                    break
            except OSError:
                time.sleep(0.2)
        else:
            report(False, "server starts", "see " + log.name)
            return
        report(True, "server starts", base)

        ex = os.path.join(ROOT, "practice", "examples")
        ids = []
        for i, (fn, prob, want) in enumerate(EXPECT):
            src = open(os.path.join(ex, fn), encoding="utf-8").read()
            if i == 0:
                # first one through the web form (multipart upload, like a browser)
                b = uuid.uuid4().hex
                parts = [("team", "selftest"), ("problem", prob), ("lang", "auto")]
                body = b"".join(
                    f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
                    for k, v in parts)
                body += (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; "
                         f"filename=\"{fn}\"\r\nContent-Type: text/x-c++src\r\n\r\n").encode()
                body += src.encode() + f"\r\n--{b}--\r\n".encode()
                req = urllib.request.Request(base + "/submit", data=body, headers={
                    "Content-Type": f"multipart/form-data; boundary={b}"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    ok = "/submission/" in r.url
                report(ok, "web form upload accepted", r.url)
                ids.append(int(r.url.rsplit("/", 1)[1]) if ok else None)
            else:
                code, out = http(base + "/api/submit", json.dumps(
                    {"team": "selftest", "problem": prob, "filename": fn, "source": src}).encode())
                ids.append(json.loads(out).get("id") if code == 200 else None)
        report(all(ids), f"{len(EXPECT)} submissions queued")

        deadline = time.time() + 180
        verdicts = {}
        while time.time() < deadline and len(verdicts) < len(ids):
            for sid in ids:
                if sid and sid not in verdicts:
                    s = json.loads(http(f"{base}/api/submission/{sid}")[1])
                    if s.get("verdict") not in (None, "JD"):
                        verdicts[sid] = s["verdict"]
            time.sleep(0.3)
        for sid, (fn, prob, want) in zip(ids, EXPECT):
            got = verdicts.get(sid, "no verdict")
            report(got == want, f"{fn:<20} -> {want}", f"got {got}")

        sb = json.loads(http(base + "/api/scoreboard")[1])
        row = next((r for r in sb["rows"] if r["name"] == "selftest"), None)
        report(row is not None, "team appears on the scoreboard")
        if row:
            a, b = row["cells"].get("A", {}), row["cells"].get("B", {})
            # A: WA, TLE, RTE count (3 tries), CE is free -> solved on try 4
            report(a.get("state") == "solved" and a.get("tries") == 4, "A solved on 4th try (CE not counted)",
                   f"{a}")
            report(b.get("state") == "solved" and b.get("tries") == 3, "B solved on 3rd try", f"{b}")
            want_pen = a.get("time", 0) + 60 + b.get("time", 0) + 40
            report(row["solved"] == 2 and row["penalty"] == want_pen,
                   "score 2 solved, penalty = time + 20 per rejected try",
                   f"{row['solved']} solved, {row['penalty']} min")

        check_pause(base)

        for path in ("/", "/problems", "/submit", "/submissions", f"/submission/{ids[0]}",
                     "/admin", "/solutions", "/sample/A/1"):
            code, _ = http(base + path)
            report(code == 200, f"page {path}", str(code))
    finally:
        srv.terminate()
        srv.wait(5)
        log.close()
        if all(results):
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"  [info] server log kept in {log.name}")


def check_pause(base):
    def clock():
        return json.loads(http(base + "/api/scoreboard")[1])

    code, _ = http(base + "/admin/pause", b"", "application/x-www-form-urlencoded")
    sb1 = clock()
    report(sb1["phase"] == "paused", "pause: phase becomes paused", sb1["phase"])
    time.sleep(1.5)
    sb2 = clock()
    report(abs(sb2["elapsed"] - sb1["elapsed"]) < 1e-6, "pause: contest clock stands still",
           f"{sb1['elapsed']:.2f}s -> {sb2['elapsed']:.2f}s")
    code, out = http(base + "/api/submit", json.dumps(
        {"team": "selftest", "problem": "A", "filename": "a.py", "source": "print(0)"}).encode())
    report(code == 400 and b"paused" in out, "pause: submissions are refused", out.decode()[:60])
    code, out = http(base + "/admin")
    report(b"Resume contest" in out, "pause: admin page offers Resume")
    http(base + "/admin/resume", b"", "application/x-www-form-urlencoded")
    time.sleep(1.0)
    sb3 = clock()
    report(sb3["phase"] == "running" and 0.5 < sb3["elapsed"] - sb2["elapsed"] < 2.5,
           "resume: clock continues where it stopped",
           f"{sb2['elapsed']:.2f}s -> {sb3['elapsed']:.2f}s after 1 s")


# ---------------------------------------------------------------- full

def check_gcpc_judging():
    section("GCPC data judged with one official accepted C++ solution per problem")
    judge.set_contest_dir(ROOT)
    c = judge.load_contest()
    for p in c["problems"]:
        sols = sorted(glob.glob(os.path.join(judge.PROBLEMS, p["letter"], "jury", "accepted", "*.cpp")))
        if p["letter"] == "M":  # this one misses #include <vector> and fails on new compilers
            sols = [s for s in sols if "gregors" not in s] or sols
        if not sols:
            report(False, f"problem {p['letter']}", "no accepted C++ jury solution")
            continue
        t0 = time.time()
        res = judge.judge(sols[0], p["letter"], contest=c)
        report(res["verdict"] == "AC", f"problem {p['letter']}",
               f"{len(res['tests'])} tests, max cpu {res.get('max_cpu', 0):.2f}s, "
               f"{time.time() - t0:.0f}s" if res["verdict"] == "AC" else res["verdict"])


def main():
    check_environment()
    check_gcpc_data()
    check_practice_server()
    if "--full" in sys.argv:
        check_gcpc_judging()
    bad = results.count(False)
    print(f"\n{'ALL CHECKS PASSED' if not bad else f'{bad} CHECK(S) FAILED'} "
          f"({len(results) - bad}/{len(results)})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
