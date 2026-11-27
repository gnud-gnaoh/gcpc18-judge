#!/usr/bin/env python3
"""Submit a solution to the local GCPC 2018 judge and wait for the verdict.

  python3 submit.py A sol.cpp --team "Aalto 1"
  GCPC_TEAM="Aalto 1" python3 submit.py a.cpp        (problem taken from the file name)

The server address defaults to http://127.0.0.1:8018 (override with --server or GCPC_SERVER).
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

NAMES = {"AC": "Accepted", "WA": "Wrong Answer", "TLE": "Time Limit Exceeded",
         "RTE": "Run Time Error", "CE": "Compiler Error", "JE": "Judge Error"}


def call(url, data=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("args", nargs="+", metavar="[PROBLEM] FILE")
    ap.add_argument("--team", default=os.environ.get("GCPC_TEAM"))
    ap.add_argument("--server", default=os.environ.get("GCPC_SERVER", "http://127.0.0.1:8018"))
    ap.add_argument("--no-wait", action="store_true")
    a = ap.parse_args()
    if len(a.args) == 2:
        prob, path = a.args
    else:
        path = a.args[0]
        m = re.match(r"([a-mA-M])(?![a-zA-Z0-9])", os.path.basename(path))
        if not m:
            ap.error("give the problem letter, or name the file like a.cpp / A_xyz.cpp")
        prob = m.group(1)
    if not a.team:
        ap.error("set --team or GCPC_TEAM")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    r = call(a.server + "/api/submit", {"team": a.team, "problem": prob.upper(),
                                         "filename": os.path.basename(path), "source": src})
    if "error" in r:
        sys.exit("rejected: " + r["error"])
    sid = r["id"]
    print(f"submission {sid}: {a.server}/submission/{sid}")
    if a.no_wait:
        return
    while True:
        s = call(f"{a.server}/api/submission/{sid}")
        if s.get("verdict") not in (None, "JD"):
            break
        print(f"\r  {'judging ' + s.get('progress', '') if s.get('verdict') else 'queued'}   ",
              end="", flush=True)
        time.sleep(0.5)
    res = s.get("result", {})
    print("\r" + NAMES.get(s["verdict"], s["verdict"]) + " " * 20)
    if s["verdict"] == "CE":
        print(res.get("compile_output", ""))
    for t in res.get("tests", []):
        if t["status"] != "AC":
            print(f"  {t['name']}: {t['status']} ({t['cpu']:.2f}s) {t.get('detail', '')}")
            if t.get("output") is not None:
                print("  --- your output ---\n" + t["output"])
                print("  --- expected ---\n" + t.get("expected", ""))
    sys.exit(0 if s["verdict"] == "AC" else 1)


if __name__ == "__main__":
    main()
