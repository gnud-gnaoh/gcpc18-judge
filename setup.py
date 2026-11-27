#!/usr/bin/env python3
"""Prepare the GCPC 2018 virtual contest.

- downloads the official archives from https://2018.gcpc.nwerc.eu/ if they are missing
- extracts test data into problems/<letter>/data/{sample,secret}
- extracts jury submissions into problems/<letter>/jury/<verdict>/
- parses the official final scoreboard into data/scoreboard.json
- generates the practice contest's test data (practice/problems/)

Safe to re-run: existing problem folders are left alone unless --force is given.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DL = os.path.join(ROOT, "downloads")
BASE_URL = "https://2018.gcpc.nwerc.eu/"
FILES = {
    "data_2018.zip": "data_2018.zip",
    "jury_2018.zip": "jury_2018.zip",
    "problemset_2018.pdf": "problemset_2018.pdf",
    "solution_2018.pdf": "solution_2018.pdf",
    "scoreboard_2018.html": "",  # the scoreboard is the site's index page
}


def load_contest():
    with open(os.path.join(ROOT, "contest.json")) as f:
        return json.load(f)


def download():
    os.makedirs(DL, exist_ok=True)
    for local, remote in FILES.items():
        path = os.path.join(DL, local)
        if os.path.exists(path):
            continue
        url = BASE_URL + remote
        print(f"downloading {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "gcpc18-local-judge"})
        with urllib.request.urlopen(req) as r, open(path + ".part", "wb") as f:
            shutil.copyfileobj(r, f)
        os.replace(path + ".part", path)


def extract(contest, force):
    pdir = os.path.join(ROOT, "problems")
    os.makedirs(pdir, exist_ok=True)
    data = zipfile.ZipFile(os.path.join(DL, "data_2018.zip"))
    jury = zipfile.ZipFile(os.path.join(DL, "jury_2018.zip"))
    for p in contest["problems"]:
        dest = os.path.join(pdir, p["letter"])
        if os.path.exists(dest):
            if not force:
                continue
            shutil.rmtree(dest)
        print(f"extracting {p['letter']} ({p['shortname']})")
        prefix = p["shortname"] + "/"
        for zf in (data, jury):
            for info in zf.infolist():
                if not info.filename.startswith(prefix) or info.is_dir():
                    continue
                rel = info.filename[len(prefix):]
                if rel.startswith("submissions/"):
                    rel = "jury/" + rel[len("submissions/"):]
                out = os.path.normpath(os.path.join(dest, rel))
                if not out.startswith(dest + os.sep):
                    raise SystemExit(f"refusing suspicious path {info.filename}")
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with zf.open(info) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)


def parse_scoreboard(contest):
    with open(os.path.join(DL, "scoreboard_2018.html"), encoding="utf-8") as f:
        h = f.read()
    letters = [p["letter"] for p in contest["problems"]]
    teams = []
    for row in re.findall(r'<tr class="team">(.*?)</tr\s*>', h, re.S):
        def grab(pat):
            m = re.search(pat, row, re.S)
            return html.unescape(m.group(1)).strip() if m else ""
        uni = grab(r'university name">(.*?)</span')
        team = {
            "rank": int(grab(r'class="rank">([^<]*)') or 0),
            "name": grab(r'team name">(.*?)</span'),
            "affiliation": uni,
            "online": uni == "Online",
            "solved": int(grab(r'class="score">(\d+)')),
            "penalty": int(grab(r'class="penalty">(\d+)')),
            "problems": {},
        }
        for cell in re.finditer(
            r'class="problem ([A-Z]) (\w+)">(.*?)</td\s*>', row, re.S
        ):
            letter, state, body = cell.groups()
            t = re.search(r'solve_time">(\d*)<', body)
            a = re.search(r'attempts">(\d+) tr', body)
            tries = int(a.group(1)) if a else 0
            if tries == 0:
                continue
            team["problems"][letter] = {
                "solved": state.startswith("solved"),
                "first": state == "solved_first",
                "time": int(t.group(1)) if t and t.group(1) else None,
                "tries": tries,
            }
        # sanity check: recompute penalty with ICPC rules
        pen = sum(
            c["time"] + contest["penalty_minutes"] * (c["tries"] - 1)
            for c in team["problems"].values() if c["solved"]
        )
        solved = sum(c["solved"] for c in team["problems"].values())
        if (solved, pen) != (team["solved"], team["penalty"]):
            print(f"warning: score mismatch for {team['name']}: "
                  f"{(solved, pen)} vs {(team['solved'], team['penalty'])}")
        assert set(team["problems"]) <= set(letters)
        teams.append(team)
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    with open(os.path.join(ROOT, "data", "scoreboard.json"), "w", encoding="utf-8") as f:
        json.dump(teams, f, ensure_ascii=False, indent=1)
    print(f"parsed {len(teams)} teams from the official scoreboard "
          f"({sum(t['online'] for t in teams)} online)")


def practice_data():
    if not os.path.isdir(os.path.join(ROOT, "practice", "problems")):
        print("generating practice contest data")
        subprocess.run([sys.executable, os.path.join(ROOT, "practice", "generate.py")], check=True)


def main():
    force = "--force" in sys.argv
    contest = load_contest()
    download()
    extract(contest, force)
    parse_scoreboard(contest)
    practice_data()
    print("done")


if __name__ == "__main__":
    main()
