#!/usr/bin/env python3
"""Local judge + virtual scoreboard for GCPC 2018.

  python3 server.py                      serve on http://127.0.0.1:8018
  python3 server.py --host 0.0.0.0       let teammates' laptops on the LAN connect
  python3 server.py --start-in 10        start the contest 10 minutes from now
  python3 server.py --reset              archive all submissions and the start time

Submissions run as your own user without a sandbox. Do not expose the server
to people whose code you would not run yourself.
"""
import argparse
import email.parser
import email.policy
import glob
import html
import json
import os
import queue
import shutil
import sys
import threading
import time
import traceback
import urllib.parse
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import judge

ROOT = os.path.dirname(os.path.abspath(__file__))
# set by init(): the contest folder (contest.json, problems/, data/) and the state folder
CDIR = STATE = None
CONTEST = LETTERS = PROB = ORIGINAL = None
DURATION = FREEZE_AT = PENALTY = 0


def init(contest_dir, state_dir=None):
    global CDIR, STATE, CONTEST, LETTERS, PROB, ORIGINAL, DURATION, FREEZE_AT, PENALTY
    judge.set_contest_dir(contest_dir)
    CDIR = judge.CONTEST_DIR
    STATE = os.path.abspath(state_dir or os.path.join(CDIR, "state"))
    CONTEST = judge.load_contest()
    LETTERS = [p["letter"] for p in CONTEST["problems"]]
    PROB = {p["letter"]: p for p in CONTEST["problems"]}
    DURATION = CONTEST["duration_minutes"] * 60
    FREEZE_AT = (CONTEST["duration_minutes"] - CONTEST["freeze_minutes"]) * 60
    PENALTY = CONTEST["penalty_minutes"]
    sb = os.path.join(CDIR, "data", "scoreboard.json")
    ORIGINAL = []
    if os.path.exists(sb):
        with open(sb, encoding="utf-8") as f:
            ORIGINAL = json.load(f)


def contest_file(key):
    """Path of an optional file named in contest.json (statement_pdf, solutions_pdf)."""
    rel = CONTEST.get(key)
    return os.path.join(CDIR, rel) if rel else None


lock = threading.RLock()
jobs = queue.Queue()
# start: epoch of the start; paused_at: epoch when paused (None if running);
# paused_total: seconds spent paused before the current pause
state = {"start": None, "paused_at": None, "paused_total": 0.0}
subs = []  # submission dicts, ordered by id
NOTEBOOK = None


# ---------------------------------------------------------------- persistence

def save_state():
    os.makedirs(STATE, exist_ok=True)
    tmp = os.path.join(STATE, "contest.json.tmp")
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, os.path.join(STATE, "contest.json"))


def save_sub(s):
    d = os.path.join(STATE, "submissions", f"{s['id']:05d}")
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "meta.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(d, "meta.json"))


def load():
    p = os.path.join(STATE, "contest.json")
    if os.path.exists(p):
        with open(p) as f:
            state.update(json.load(f))
    for m in sorted(glob.glob(os.path.join(STATE, "submissions", "*", "meta.json"))):
        with open(m, encoding="utf-8") as f:
            s = json.load(f)
        subs.append(s)
        if s["verdict"] in (None, "JD"):
            s["verdict"] = None
            jobs.put(s["id"])


def sub_dir(s):
    return os.path.join(STATE, "submissions", f"{s['id']:05d}")


# ---------------------------------------------------------------- judging

def worker():
    while True:
        sid = jobs.get()
        with lock:
            s = subs[sid - 1]
            s["verdict"] = "JD"
            s["progress"] = ""
        src = os.path.join(sub_dir(s), s["filename"])

        def progress(i, n, s=s):
            s["progress"] = f"{i + 1}/{n}"

        try:
            res = judge.judge(src, s["problem"], s["lang"], contest=CONTEST,
                              progress=progress)
        except Exception:
            res = {"verdict": "JE", "tests": [], "compile_output": traceback.format_exc()}
        with lock:
            s["verdict"] = res["verdict"]
            s["result"] = res
            s["judged_at"] = time.time()
            s.pop("progress", None)
            save_sub(s)


# ---------------------------------------------------------------- contest clock

def elapsed(now=None):
    """Contest time in seconds, not counting pauses. Stands still while paused."""
    if state["start"] is None:
        return None
    t = state["paused_at"] if state["paused_at"] is not None else (now or time.time())
    return t - state["start"] - state["paused_total"]


def phase():
    e = elapsed()
    if e is None:
        return "not started"
    if e < 0:
        return "countdown"
    if state["paused_at"] is not None:
        return "paused"
    if e < DURATION:
        return "frozen" if CONTEST["freeze_minutes"] and e >= FREEZE_AT else "running"
    return "over"


def fmt_clock(sec):
    sec = int(max(0, sec))
    return f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}"


# ---------------------------------------------------------------- scoreboard

def build_scoreboard(unfreeze=False):
    e = elapsed()
    ph = phase()
    over = ph == "over"
    # how far into the original contest we may reveal
    if e is None or e < 0:
        horizon = -1
    elif over or unfreeze:
        horizon = min(e, DURATION)
    else:
        horizon = min(e, FREEZE_AT) if CONTEST["freeze_minutes"] else e
    rows = []
    for t in ORIGINAL:
        cells, solved, pen = {}, 0, 0
        for L, c in t["problems"].items():
            if c["solved"] and c["time"] * 60 + 59 <= horizon:
                cells[L] = {"state": "solved", "time": c["time"], "tries": c["tries"]}
                solved += 1
                pen += c["time"] + PENALTY * (c["tries"] - 1)
            elif over and not c["solved"]:
                cells[L] = {"state": "attempted", "tries": c["tries"]}
        rows.append({"name": t["name"], "aff": t["affiliation"], "online": t["online"],
                     "local": False, "solved": solved, "penalty": pen, "cells": cells})
    with lock:
        teams = {}
        for s in subs:
            if s.get("post_contest"):
                continue
            teams.setdefault(s["team"], []).append(s)
    for name, lst in teams.items():
        cells, solved, pen = {}, 0, 0
        for L in LETTERS:
            ps = [s for s in lst if s["problem"] == L]
            if not ps:
                continue
            wrong, pending = 0, 0
            cell = None
            for s in ps:
                v = s["verdict"]
                if v in (None, "JD"):
                    pending += 1
                elif v == "AC":
                    m = int(s["elapsed"] // 60)
                    cell = {"state": "solved", "time": m, "tries": wrong + 1}
                    solved += 1
                    pen += m + PENALTY * wrong
                    break
                elif v not in ("CE", "JE"):
                    wrong += 1
            if cell is None:
                if pending:
                    cell = {"state": "pending", "tries": wrong + pending}
                else:
                    cell = {"state": "attempted", "tries": wrong}
                if cell["tries"] == 0:
                    continue
            cells[L] = cell
        rows.append({"name": name, "aff": "local team", "online": False, "local": True,
                     "solved": solved, "penalty": pen, "cells": cells})
    # first solves
    first = {}
    for r in rows:
        for L, c in r["cells"].items():
            if c["state"] == "solved" and (L not in first or c["time"] < first[L]):
                first[L] = c["time"]
    for r in rows:
        for L, c in r["cells"].items():
            c["first"] = c["state"] == "solved" and c["time"] == first[L]
    rows.sort(key=lambda r: (-r["solved"], r["penalty"], not r["local"], r["name"]))
    rank = 0
    prev = None
    for i, r in enumerate(rows):
        if (r["solved"], r["penalty"]) != prev:
            rank = i + 1
            prev = (r["solved"], r["penalty"])
        r["rank"] = rank
    stats = {L: {"solved": 0, "tries": 0} for L in LETTERS}
    for r in rows:
        for L, c in r["cells"].items():
            stats[L]["solved"] += c["state"] == "solved"
            stats[L]["tries"] += c["tries"]
    frozen_view = (not over and not unfreeze and bool(CONTEST["freeze_minutes"])
                   and e is not None and e >= FREEZE_AT)
    return {"phase": ph, "elapsed": e, "frozen_view": frozen_view,
            "rows": rows, "stats": stats}


# ---------------------------------------------------------------- HTML

CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#ddd;--card:#f6f6f6;--ok:#5cb85c;--ok2:#1e7e34;
--bad:#e05d5d;--pend:#e0b84d;--local:#fff6d6;--link:#1f5fbf}
@media (prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#e8e8e8;--muted:#9a9a9a;--line:#33363c;
--card:#1f2228;--local:#3a3420;--link:#7fb0ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
a{color:var(--link)}header{display:flex;flex-wrap:wrap;gap:6px 18px;align-items:center;
padding:10px 16px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:2}
header b{font-size:16px}nav a{margin-right:12px;text-decoration:none}nav a:hover{text-decoration:underline}
#clock{margin-left:auto;font:600 18px ui-monospace,monospace}.phase{color:var(--muted);font-size:12px;margin-left:6px}
main{padding:14px 16px;max-width:1400px;margin:auto}table{border-collapse:collapse}
td,th{border-bottom:1px solid var(--line);padding:3px 6px;text-align:left;vertical-align:top}
.sb{width:100%;overflow-x:auto}.sb table{min-width:900px;width:100%}
.sb td.c,.sb th.c{text-align:center;width:52px;padding:2px}.sb td.n{max-width:330px}
.cell{border-radius:4px;padding:2px 0;font-size:12px;line-height:1.2;color:#fff}
.cell small{display:block;opacity:.85;font-size:10px}
.solved{background:var(--ok)}.first{background:var(--ok2)}.attempted{background:var(--bad)}
.pending{background:var(--pend);color:#222}tr.local td{background:var(--local);font-weight:600}
.aff{color:var(--muted);font-size:12px;font-weight:400}.muted{color:var(--muted)}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:3px;vertical-align:-1px}
.box{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:12px 14px;margin:10px 0}
pre{background:var(--card);border:1px solid var(--line);padding:8px;overflow:auto;max-height:420px;font-size:12px}
input,select,textarea,button{font:inherit;color:inherit;background:var(--card);border:1px solid var(--line);
border-radius:4px;padding:5px 8px}button{cursor:pointer}textarea{width:100%;font-family:ui-monospace,monospace}
.v-AC{color:var(--ok)}.v-WA,.v-TLE,.v-RTE,.v-CE,.v-JE{color:var(--bad)}.v-pend{color:var(--pend)}
form.inline{display:inline}label{display:block;margin:8px 0 3px;font-weight:600}
"""


def esc(x):
    return html.escape(str(x), quote=True)


def page(title, body, refresh=None):
    e = elapsed()
    start = None if state["start"] is None else state["start"] + state["paused_total"]
    paused = e if state["paused_at"] is not None else None
    clock_js = f"""<script>
const START={json.dumps(start)},PAUSED={json.dumps(paused)},DUR={DURATION},SKEW=Date.now()/1000-{time.time():.3f};
function f(s){{s=Math.max(0,Math.floor(s));return Math.floor(s/3600)+':'+String(Math.floor(s/60)%60).padStart(2,'0')+':'+String(s%60).padStart(2,'0')}}
function tick(){{const el=document.getElementById('clock');if(START===null){{el.textContent='--:--:--';return}}
if(PAUSED!==null){{el.textContent=f(PAUSED)+' / '+f(DUR-PAUSED)+' left · PAUSED';return}}
const e=Date.now()/1000-SKEW-START;el.textContent=e<0?'starts in '+f(-e):e<DUR?f(e)+' / '+f(DUR-e)+' left':'contest over'}}
tick();setInterval(tick,1000);</script>"""
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{meta}
<title>{esc(title)} · {esc(CONTEST['name'])}</title><style>{CSS}</style></head><body>
<header><b>{esc(CONTEST['name'])}</b><nav><a href="/">Scoreboard</a><a href="/problems">Problems</a>
<a href="/submit">Submit</a><a href="/submissions">Submissions</a><a href="/solutions">Solutions</a>
<a href="/admin">Admin</a></nav><span id="clock"></span><span class="phase">{esc(phase())}</span></header>
<main>{body}</main>{clock_js}</body></html>"""


def render_scoreboard(unfreeze):
    sb = build_scoreboard(unfreeze)
    ph = sb["phase"]
    notes = []
    if ph in ("not started", "countdown"):
        notes.append("The contest has not started. Start it on the <a href='/admin'>Admin</a> page.")
    if sb["frozen_view"]:
        notes.append(f"Scoreboard frozen for the original teams since "
                     f"{CONTEST['duration_minutes'] - CONTEST['freeze_minutes']}:00 "
                     f"(as in the real contest). Local teams stay live. "
                     f"<a href='/?unfreeze=1'>Peek unfrozen</a>")
    notes.append("Original teams: a solve appears once its minute has fully passed. "
                 "Their wrong tries are known only as totals, so they show only "
                 "together with the solve, and unsolved attempts appear after the contest. "
                 "Teams marked <i>online</i> took part in the parallel online contest.")
    head = "".join(f"<th class='c' title='{esc(PROB[L]['name'])}'>"
                   f"<span class='dot' style='background:{PROB[L]['color']}'></span>{L}</th>"
                   for L in LETTERS)
    trs = []
    for r in sb["rows"]:
        tds = []
        for L in LETTERS:
            c = r["cells"].get(L)
            if not c:
                tds.append("<td class='c'></td>")
                continue
            if c["state"] == "solved":
                cls = "first" if c["first"] else "solved"
                txt = f"{c['time']}<small>{c['tries']} {'try' if c['tries'] == 1 else 'tries'}</small>"
            elif c["state"] == "pending":
                cls, txt = "pending", f"?<small>{c['tries']} tr</small>"
            else:
                cls, txt = "attempted", f"&minus;<small>{c['tries']} tr</small>"
            tds.append(f"<td class='c'><div class='cell {cls}'>{txt}</div></td>")
        tag = " <span class='aff'>(online)</span>" if r["online"] else ""
        trs.append(f"<tr class='{'local' if r['local'] else ''}'><td>{r['rank']}</td>"
                   f"<td class='n'>{esc(r['name'])}{tag}<br><span class='aff'>{esc(r['aff'])}</span></td>"
                   f"<td><b>{r['solved']}</b></td><td>{r['penalty']}</td>{''.join(tds)}</tr>")
    st = "".join(f"<td class='c muted'>{sb['stats'][L]['solved']}/{sb['stats'][L]['tries']}</td>"
                 for L in LETTERS)
    body = (f"<div class='box'>{'<br>'.join(notes)}</div><div class='sb'><table>"
            f"<tr><th>#</th><th>Team</th><th>Solved</th><th>Time</th>{head}</tr>{''.join(trs)}"
            f"<tr><td></td><td class='muted'>solved / tries</td><td></td><td></td>{st}</tr>"
            f"</table></div>")
    return page("Scoreboard", body, refresh=20)


def render_problems():
    ph = phase()
    if ph in ("not started", "countdown"):
        return page("Problems", "<div class='box'>Problems are available once the contest starts.</div>")
    rows = []
    for p in CONTEST["problems"]:
        samples = sorted(glob.glob(os.path.join(judge.PROBLEMS, p["letter"], "data", "sample", "*.in")))
        links = " ".join(
            f"<a href='/sample/{p['letter']}/{esc(os.path.basename(s)[:-3])}'>{i + 1}</a>"
            for i, s in enumerate(samples))
        rows.append(f"<tr><td><span class='dot' style='background:{p['color']}'></span>"
                    f"<b>{p['letter']}</b></td><td>{esc(p['name'])}</td>"
                    f"<td>{p['time_limit']} s</td><td>{links}</td></tr>")
    nb = ("<a href='/notebook.pdf'>Team notebook (KACTL)</a> · " if NOTEBOOK else "")
    pdf = ("<a href='/statement.pdf'><b>Problem set (PDF)</b></a> · "
           if contest_file("statement_pdf") else "")
    body = (f"<div class='box'>{pdf}{nb}"
            f"Memory limit {CONTEST['memory_limit_mb']} MB for all problems. "
            f"Languages: {', '.join(judge.LANGS.values())}.<br>"
            f"<span class='muted'>Time limits: {esc(CONTEST['time_limit_source'])}.</span></div>"
            f"<table><tr><th></th><th>Problem</th><th>Time limit</th><th>Samples</th></tr>"
            f"{''.join(rows)}</table>{CONTEST.get('statement_html', '')}")
    return page("Problems", body)


def render_sample(letter, name):
    base = os.path.join(judge.PROBLEMS, letter, "data", "sample", name)
    if letter not in PROB or "/" in name or not os.path.exists(base + ".in"):
        return None
    i = open(base + ".in", encoding="utf-8", errors="replace").read()
    a = open(base + ".ans", encoding="utf-8", errors="replace").read()
    return page(f"Sample {letter}", f"<h3>{letter} · {esc(PROB[letter]['name'])} · {esc(name)}</h3>"
                f"<b>Input</b><pre>{esc(i)}</pre><b>Output</b><pre>{esc(a)}</pre>")


def render_submit(team, msg=""):
    teams = sorted({s["team"] for s in subs})
    opts = "".join(f"<option value='{L}'>{L} · {esc(PROB[L]['name'])}</option>" for L in LETTERS)
    langs = "".join(f"<option value='{k}'>{esc(v)}</option>" for k, v in judge.LANGS.items())
    dl = "".join(f"<option value='{esc(t)}'>" for t in teams)
    warn = ""
    if phase() == "over":
        warn = "<div class='box'>The contest is over. New submissions are judged but do not count.</div>"
    body = f"""{msg}{warn}<form method="post" action="/submit" enctype="multipart/form-data">
<label>Team</label><input name="team" list="teams" value="{esc(team)}" required maxlength="60">
<datalist id="teams">{dl}</datalist>
<label>Problem</label><select name="problem" id="prob">{opts}</select>
<label>Language</label><select name="lang" id="lang"><option value="auto">detect from file name</option>{langs}</select>
<label>Source file</label><input type="file" name="file" id="file">
<label>…or paste the code</label><textarea name="code" rows="14" placeholder="paste source here"></textarea>
<p><button type="submit"><b>Submit</b></button></p></form>
<p class="muted">Command line: <code>python3 submit.py A sol.cpp --team NAME</code></p>
<script>document.getElementById('file').addEventListener('change',e=>{{const f=e.target.files[0];if(!f)return;
const m=f.name.match(/^([a-mA-M])[^a-zA-Z0-9]?/);if(m)document.getElementById('prob').value=m[1].toUpperCase();}});</script>"""
    return page("Submit", body)


def verdict_html(s):
    v = s["verdict"]
    if v in (None, "JD"):
        p = s.get("progress")
        return f"<span class='v-pend'>{'judging ' + p if p else 'pending'}</span>"
    return f"<span class='v-{v}'>{esc(judge.VERDICT_NAMES.get(v, v))}</span>"


def render_submissions(team_filter):
    with lock:
        lst = [s for s in subs if not team_filter or s["team"] == team_filter][::-1]
    rows = "".join(
        f"<tr><td><a href='/submission/{s['id']}'>{s['id']}</a></td>"
        f"<td>{fmt_clock(s['elapsed'])}{' <span class=muted>(after)</span>' if s.get('post_contest') else ''}</td>"
        f"<td><a href='/submissions?team={urllib.parse.quote(s['team'])}'>{esc(s['team'])}</a></td>"
        f"<td>{s['problem']}</td><td>{esc(s['lang'])}</td><td>{verdict_html(s)}</td></tr>"
        for s in lst)
    pending = any(s["verdict"] in (None, "JD") for s in lst)
    filt = f"<p>Team <b>{esc(team_filter)}</b> · <a href='/submissions'>all teams</a></p>" if team_filter else ""
    body = (f"{filt}<table><tr><th>#</th><th>Time</th><th>Team</th><th>Problem</th><th>Lang</th>"
            f"<th>Verdict</th></tr>{rows}</table>")
    return page("Submissions", body, refresh=3 if pending else None)


def render_submission(sid):
    with lock:
        if not 1 <= sid <= len(subs):
            return None
        s = json.loads(json.dumps(subs[sid - 1]))
    src = open(os.path.join(sub_dir(s), s["filename"]), encoding="utf-8", errors="replace").read()
    res = s.get("result") or {}
    full = phase() == "over" or s.get("post_contest")
    parts = [f"<h3>Submission {s['id']} · {esc(s['team'])} · problem {s['problem']} "
             f"({esc(PROB[s['problem']]['name'])}) · {fmt_clock(s['elapsed'])}</h3>",
             f"<p style='font-size:18px'>{verdict_html(s)}"
             + (f" <span class='muted'>max CPU {res.get('max_cpu', 0):.2f}s of "
                f"{PROB[s['problem']]['time_limit']}s</span>" if res.get("tests") else "") + "</p>"]
    if res.get("verdict") == "CE" or (res.get("compile_output") or "").strip():
        parts.append(f"<b>Compiler output</b><pre>{esc(res.get('compile_output', ''))}</pre>")
    tests = res.get("tests", [])
    if tests:
        rows = []
        for t in tests:
            sample = t["name"].startswith("sample")
            if not (full or sample):
                continue
            rows.append(f"<tr><td>{esc(t['name'])}</td><td class='v-{t['status']}'>{t['status']}</td>"
                        f"<td>{t['cpu']:.2f}s</td><td>{t['mem_kb'] // 1024} MB</td>"
                        f"<td class='muted'>{esc(t.get('detail', '') if t['status'] != 'AC' or sample else '')}</td></tr>")
            if t.get("output") is not None:
                rows.append(f"<tr><td colspan=5><b>Your output</b><pre>{esc(t['output'])}</pre>"
                            f"<b>Expected</b><pre>{esc(t.get('expected', ''))}</pre>"
                            + (f"<b>stderr</b><pre>{esc(t.get('stderr', ''))}</pre>" if t.get('stderr') else "")
                            + "</td></tr>")
        hidden = "" if full else (f"<p class='muted'>{len(tests)} test cases run; secret test details "
                                  f"are shown after the contest, like on the real judge.</p>")
        parts.append(f"{hidden}<table><tr><th>Test</th><th>Result</th><th>CPU</th><th>Memory</th>"
                     f"<th></th></tr>{''.join(rows)}</table>")
    parts.append(f"<b>Source</b> ({esc(s['filename'])})<pre>{esc(src)}</pre>")
    return page(f"Submission {sid}", "".join(parts),
                refresh=2 if s["verdict"] in (None, "JD") else None)


def jury_files():
    out = {}
    for L in LETTERS:
        fs = sorted(f for f in glob.glob(os.path.join(judge.PROBLEMS, L, "jury", "*", "*"))
                    if os.path.isfile(f))
        out[L] = [os.path.relpath(f, os.path.join(judge.PROBLEMS, L, "jury")) for f in fs]
    return out


def render_solutions(force):
    if phase() != "over" and not force:
        return page("Solutions", "<div class='box'>Solution slides and jury code unlock when the "
                    "contest is over.<br><a href='/solutions?reveal=1'>Show them anyway</a> "
                    "(spoilers)</div>")
    parts = ["<div class='box'><a href='/solutions.pdf'><b>Official solution slides (PDF)</b></a> · "
             "jury submissions below are sorted by their intended verdict</div><table>"]
    for L, fs in jury_files().items():
        links = " ".join(f"<a href='/jury/{L}/{urllib.parse.quote(f)}'"
                         f"{'' if f.startswith('accepted/') else ' class=muted'}>{esc(f)}</a>"
                         for f in fs)
        parts.append(f"<tr><td><b>{L}</b></td><td>{esc(PROB[L]['name'])}</td><td>{links}</td></tr>")
    parts.append("</table>")
    return page("Solutions", "".join(parts))


def render_admin(msg=""):
    ph = phase()
    start = state["start"]
    info = ("not scheduled" if start is None else
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start)))
    ctrl = ""
    if start is None:
        ctrl = """<form method="post" action="/admin/start"><label>Start the contest</label>
<select name="delay"><option value="0">now</option><option value="1">in 1 minute</option>
<option value="5">in 5 minutes</option><option value="10">in 10 minutes</option></select>
<button type="submit"><b>Start</b></button></form>"""
    elif ph == "countdown":
        ctrl = """<form method="post" action="/admin/unschedule"><button>Cancel scheduled start</button></form>"""
    elif ph in ("running", "frozen"):
        ctrl = """<form method="post" action="/admin/pause"><button type="submit"><b>Pause contest</b></button>
<span class="muted">stops the clock and blocks submissions until you resume</span></form>"""
    elif ph == "paused":
        ctrl = (f"<form method='post' action='/admin/resume'><button type='submit'><b>Resume contest</b>"
                f"</button> <span class='muted'>paused since "
                f"{esc(time.strftime('%H:%M:%S', time.localtime(state['paused_at'])))}</span></form>")
    pause_info = ""
    total = state["paused_total"] + (time.time() - state["paused_at"]
                                     if state["paused_at"] is not None else 0)
    if total:
        pause_info = f"<br>Paused so far: {fmt_clock(total)} (the contest ends that much later)"
    body = (f"{msg}<div class='box'>Phase: <b>{esc(ph)}</b><br>Start time: {esc(info)}{pause_info}<br>"
            f"Length {CONTEST['duration_minutes']} min, scoreboard freeze for original teams in the "
            f"last {CONTEST['freeze_minutes']} min, {PENALTY} penalty minutes per rejected try "
            f"(compiler errors are free).</div>{ctrl}"
            f"<p class='muted'>Reset everything (keeps a backup): stop the server and run "
            f"<code>python3 server.py --reset</code>.</p>")
    return page("Admin", body)


# ---------------------------------------------------------------- HTTP

def add_submission(team, problem, lang, filename, code):
    team = " ".join(team.split())[:60]
    if not team:
        return None, "team name missing"
    problem = problem.upper()
    if problem not in PROB:
        return None, "unknown problem"
    if lang in (None, "", "auto"):
        lang = judge.lang_of(filename or "")
    if lang not in judge.LANGS:
        return None, "unknown language; choose one or use a .cpp/.c/.py file name"
    if not code.strip():
        return None, "empty source"
    if len(code) > 256 * 1024:
        return None, "source larger than 256 KB"
    e = elapsed()
    if e is None or e < 0:
        return None, "the contest has not started"
    if state["paused_at"] is not None:
        return None, "the contest is paused"
    ext = {"cpp": ".cpp", "c": ".c", "py": ".py"}[lang]
    base = os.path.basename(filename or "") or "main" + ext
    if not base.endswith(ext) or not all(ch.isalnum() or ch in "._-" for ch in base):
        base = "main" + ext
    with lock:
        s = {"id": len(subs) + 1, "team": team, "problem": problem, "lang": lang,
             "filename": base, "time": time.time(), "elapsed": e,
             "post_contest": e >= DURATION, "verdict": None}
        os.makedirs(sub_dir(s), exist_ok=True)
        with open(os.path.join(sub_dir(s), base), "w", encoding="utf-8") as f:
            f.write(code)
        subs.append(s)
        save_sub(s)
    jobs.put(s["id"])
    return s, None


def public_sub(s):
    """JSON view of a submission, hiding secret test details during the contest."""
    s = json.loads(json.dumps(s))
    full = phase() == "over" or s.get("post_contest")
    res = s.get("result")
    if res and not full:
        res["tests"] = [t for t in res["tests"] if t["name"].startswith("sample")
                        or t["status"] != "AC"]
        for t in res["tests"]:
            if not t["name"].startswith("sample"):
                t["name"] = "secret"
                t.pop("detail", None)
    return s


class Handler(BaseHTTPRequestHandler):
    server_version = "gcpc18-judge"

    def log_message(self, fmt, *args):
        if "/api/" not in self.path:
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def send(self, body, status=200, ctype="text/html; charset=utf-8", extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, to, extra=None):
        self.send_response(303)
        self.send_header("Location", to)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def file(self, path, ctype):
        if not path or not os.path.exists(path):
            return self.send(page("Not found", "Not found"), 404)
        with open(path, "rb") as f:
            self.send(f.read(), ctype=ctype)

    def team_cookie(self):
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return urllib.parse.unquote(c["team"].value) if "team" in c else ""

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        p = u.path
        try:
            if p == "/":
                return self.send(render_scoreboard("unfreeze" in q))
            if p == "/problems":
                return self.send(render_problems())
            if p.startswith("/sample/"):
                _, _, L, name = p.split("/", 3)
                r = render_sample(L, urllib.parse.unquote(name))
                return self.send(r) if r else self.send(page("Not found", "Not found"), 404)
            if p == "/statement.pdf":
                if phase() in ("not started", "countdown"):
                    return self.send(page("Problems", "Not before the contest starts."), 403)
                return self.file(contest_file("statement_pdf"), "application/pdf")
            if p == "/notebook.pdf":
                return self.file(NOTEBOOK, "application/pdf")
            if p == "/solutions":
                return self.send(render_solutions("reveal" in q))
            if p == "/solutions.pdf":
                return self.file(contest_file("solutions_pdf"), "application/pdf")
            if p.startswith("/jury/"):
                _, _, L, rel = p.split("/", 3)
                rel = urllib.parse.unquote(rel)
                if L in PROB and rel in jury_files()[L]:
                    return self.file(os.path.join(judge.PROBLEMS, L, "jury", rel),
                                     "text/plain; charset=utf-8")
                return self.send(page("Not found", "Not found"), 404)
            if p == "/submit":
                return self.send(render_submit(self.team_cookie()))
            if p == "/submissions":
                return self.send(render_submissions(q.get("team", [""])[0]))
            if p.startswith("/submission/"):
                r = render_submission(int(p.rsplit("/", 1)[1]))
                return self.send(r) if r else self.send(page("Not found", "Not found"), 404)
            if p == "/admin":
                return self.send(render_admin())
            if p == "/api/scoreboard":
                return self.send(json.dumps(build_scoreboard(), ensure_ascii=False),
                                 ctype="application/json")
            if p.startswith("/api/submission/"):
                sid = int(p.rsplit("/", 1)[1])
                with lock:
                    if not 1 <= sid <= len(subs):
                        return self.send("{}", 404, "application/json")
                    s = public_sub(subs[sid - 1])
                return self.send(json.dumps(s, ensure_ascii=False), ctype="application/json")
            return self.send(page("Not found", "Not found"), 404)
        except (ValueError, IndexError):
            return self.send(page("Bad request", "Bad request"), 400)

    def read_body(self):
        n = int(self.headers.get("Content-Length", 0))
        if n > 2 * 1024 * 1024:
            raise ValueError("request too large")
        return self.rfile.read(n)

    def do_POST(self):
        p = urllib.parse.urlsplit(self.path).path
        try:
            body = self.read_body()
        except ValueError:
            return self.send("too large", 413, "text/plain")
        if p == "/submit":
            form = parse_multipart(self.headers.get("Content-Type", ""), body)
            code, fname = form.get("code", ""), ""
            if form.get("file") and form["file"][1].strip():
                fname, code = form["file"]
            s, err = add_submission(form.get("team", ""), form.get("problem", ""),
                                    form.get("lang", "auto"), fname or "", code)
            if err:
                return self.send(render_submit(form.get("team", ""),
                                               f"<div class='box v-WA'>{esc(err)}</div>"), 400)
            ck = f"team={urllib.parse.quote(s['team'])}; Path=/; Max-Age=31536000; SameSite=Lax"
            return self.redirect(f"/submission/{s['id']}", {"Set-Cookie": ck})
        if p == "/api/submit":
            try:
                d = json.loads(body)
            except ValueError:
                return self.send('{"error":"bad json"}', 400, "application/json")
            s, err = add_submission(d.get("team", ""), d.get("problem", ""), d.get("lang"),
                                    d.get("filename", ""), d.get("source", ""))
            if err:
                return self.send(json.dumps({"error": err}), 400, "application/json")
            return self.send(json.dumps({"id": s["id"]}), ctype="application/json")
        if p == "/admin/start":
            form = urllib.parse.parse_qs(body.decode())
            delay = int(form.get("delay", ["0"])[0])
            with lock:
                if state["start"] is None:
                    state["start"] = time.time() + 60 * delay
                    save_state()
            return self.redirect("/admin")
        if p == "/admin/pause":
            with lock:
                if phase() in ("running", "frozen"):
                    state["paused_at"] = time.time()
                    save_state()
            return self.redirect("/admin")
        if p == "/admin/resume":
            with lock:
                if state["paused_at"] is not None:
                    state["paused_total"] += time.time() - state["paused_at"]
                    state["paused_at"] = None
                    save_state()
            return self.redirect("/admin")
        if p == "/admin/unschedule":
            with lock:
                if phase() == "countdown":
                    state["start"] = None
                    save_state()
            return self.redirect("/admin")
        return self.send("not found", 404, "text/plain")


def parse_multipart(ctype, body):
    """Returns {name: value} for text fields and {name: (filename, text)} for files."""
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
    out = {}
    if not msg.is_multipart():
        return out
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        raw = part.get_payload(decode=True) or b""
        text = raw.decode("utf-8", "replace")
        fn = part.get_filename()
        out[name] = (fn, text) if fn is not None else text
    return out


def reset():
    if not os.path.exists(STATE):
        print("nothing to reset")
        return
    dst = STATE + "-backup-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.move(STATE, dst)
    print(f"moved old state to {dst}")


def main():
    global NOTEBOOK
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, help="default 8018, or 8019 with --practice")
    ap.add_argument("--start-in", type=float, metavar="MIN",
                    help="schedule the contest start this many minutes from now")
    ap.add_argument("--reset", action="store_true", help="archive submissions and start time")
    ap.add_argument("--practice", action="store_true",
                    help="run the spoiler-free practice contest (practice/), started at once")
    ap.add_argument("--state", help="folder for submissions and start time "
                    "(default: state/ inside the contest folder)")
    ap.add_argument("--notebook", default=os.path.join(ROOT, "..", "kactl", "kactl.pdf"),
                    help="team notebook PDF to serve at /notebook.pdf")
    a = ap.parse_args()
    init(os.path.join(ROOT, "practice") if a.practice else ROOT, a.state)
    if a.port is None:
        a.port = 8019 if a.practice else 8018
    if a.reset:
        return reset()
    NOTEBOOK = os.path.abspath(a.notebook) if os.path.exists(a.notebook) else None
    load()
    if a.practice and state["start"] is None and a.start_in is None:
        a.start_in = 0
    if a.start_in is not None:
        if state["start"] is not None and phase() != "countdown":
            sys.exit("contest already started; use --reset first")
        state["start"] = time.time() + 60 * a.start_in
        save_state()
    threading.Thread(target=worker, daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"{CONTEST['name']} judge on http://{a.host}:{a.port}/  (phase: {phase()}, "
          f"{len(subs)} submissions loaded)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
