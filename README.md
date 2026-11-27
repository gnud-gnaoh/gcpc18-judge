# GCPC 2018: offline virtual contest

A local judge and a virtual scoreboard for the German Collegiate Programming Contest 2018
(Codeforces Gym [102021](https://codeforces.com/gym/102021)). You compete against the 127 teams of the
original contest: their solves appear on the scoreboard at the minute they happened.

Everything runs offline once `setup.py` has run (it needs the internet once). It needs only Python 3 and g++.

## Before contest day: test the setup

Automated check (about 30 s, spoiler-free). It submits a solution for each verdict to a practice server
on a temporary port and checks verdicts, penalties and pages:

```sh
python3 selftest.py          # add --full to also judge one official solution per GCPC problem (~1 min)
```

Try it by hand in the practice contest. It has two dummy problems (A: sum, B: average), starts at once,
uses its own `practice/state/` and does not touch the real contest:

```sh
python3 server.py --practice                       # http://127.0.0.1:8019
python3 submit.py --server http://127.0.0.1:8019 --team test practice/examples/A_wa_overflow.cpp
```

`practice/examples/` has one file for each verdict: `A_ac.cpp`, `A_ac.py`, `A_wa_overflow.cpp`,
`A_tle.cpp`, `A_rte.cpp`, `A_ce.cpp`, `B_ac.cpp`, `B_wa_precision.cpp`, `B_wa_sample.py`. Upload them on
the Submit page too. Afterwards, `python3 server.py --practice --reset` clears the practice state.

## Quick start

```sh
python3 setup.py            # once: downloads the official archives (~136 MB) and unpacks them
python3 server.py           # http://127.0.0.1:8018
```

Open http://127.0.0.1:8018/admin and press **Start**, or start from the command line:

```sh
python3 server.py --start-in 5     # contest starts in 5 minutes
```

To pause (a break, a power cut, lunch), press **Pause contest** on `/admin`. The clock stops, submissions
are refused and the original teams' solves stop appearing. **Resume contest** continues where it stopped,
so the contest ends later by the time spent paused. A pause survives a server restart.

For teammates on other laptops in the same network:

```sh
python3 server.py --host 0.0.0.0   # then open http://<this machine's IP>:8018
```

**Warning:** submissions run as your own user, without a sandbox. Only open the server to people whose code
you would run yourself, and do not use `--host 0.0.0.0` on an untrusted network.

## During the contest

| Page | What it does |
|---|---|
| `/` Scoreboard | Your team(s) highlighted, ranked against the original teams. Refreshes every 20 s. |
| `/problems` | Problem set PDF (hidden until the start), samples, time limits, and `/notebook.pdf` (the KACTL PDF from `../kactl/kactl.pdf`). |
| `/submit` | Upload a file or paste code. The team name is remembered in a cookie. |
| `/submissions` | All submissions with live judging progress. |
| `/solutions` | Solution slides and jury code. Locked until the contest ends. |

Submitting from the terminal:

```sh
export GCPC_TEAM="Aalto 1"
python3 submit.py A sol.cpp      # or: python3 submit.py a.cpp  (letter taken from the file name)
```

Testing on samples without submitting (no penalty, shows diffs):

```sh
python3 judge.py A sol.cpp --samples
```

## Rules as configured (`contest.json`)

- 5 hours, 13 problems (A–M), 20 penalty minutes per rejected try. Compiler errors are free.
- Languages: C++ (`g++ -std=gnu++20 -O2`), C, Python 3 (CPython, not PyPy).
- Memory limit 1024 MB. The stack limit equals the memory limit, so deep recursion works.
- Time limits are the CPU time limits Kattis uses for the same problems, except E, F and M. Those are
  tightened to 2 s, 1 s and 3 s (Kattis: 7 s, 2 s, 8 s), because the jury's too-slow solutions passed the
  Kattis limits on this machine. The original DOMjudge limits were not published.
- Scoreboard freeze in the last hour, as in the real contest. It applies only to the original teams: local
  teams stay live. `/?unfreeze=1` shows the unfrozen board.
- During the contest, a submission page shows details only for the sample tests. Secret test details appear
  after the contest.
- Submissions after the end are judged (upsolving) but do not change the scoreboard.

## How the virtual scoreboard works

`setup.py` parses the official final scoreboard (`downloads/scoreboard_2018.html`, from
https://2018.gcpc.nwerc.eu/). For every team and problem it gives the minute of the accepted submission
and the total number of tries. The rebuilt final board matches the official ranks and penalties for all
127 teams.

Limits of that data:

- A solve at minute *t* shows once minute *t* has fully passed.
- The times of wrong tries are unknown. Before a team solves a problem, its wrong tries do not show.
  Tries on unsolved problems show only after the contest.
- Four teams marked *online* took part in the parallel online contest. They are ranked together with the rest.

## Checkers

There were no output validators in the official archives, so `checkers.py` provides them:

| Problems | Checker |
|---|---|
| A, C, D, E, I, M | token comparison, case-insensitive (like the default Kattis/DOMjudge validator) |
| B, G, K | numbers within absolute or relative error 1e-7 |
| F | any pair of monsters whose fight leaves the winner with power 1 |
| H | any (n, s) with n ≥ 3 and 1^(n-1) + … + s^(n-1) = m |
| J | any valid assembly, in any rotation |
| L | any grid that matches all clues |

`python3 judge.py --jury` runs all official C++ jury submissions and checks that the accepted ones pass
and the others fail. The last run is in `logs/jury-check.txt`. It skips the jury's Java files and its
Python files (all Python 2). Known differences, none of them a checker problem:

- `J/wrong_answer/jigsaw_martin_internal0.cpp` passes. It is byte-identical to the accepted
  `jigsaw_martin.cpp`, so the jury filed it in the wrong folder.
- `M/accepted/mountaineers_gregors.cpp` does not compile. It uses `vector` without `#include <vector>`,
  which today's g++ rejects.

## Files

```
contest.json         problems, time limits, checker types, contest length
setup.py             downloads the archives (if missing), extracts data, parses the scoreboard
server.py            web judge + scoreboard
judge.py             compile/run/check, also the command line tester
checkers.py          output validators
submit.py            command line submit client
downloads/           official files: data_2018.zip, jury_2018.zip, problemset/solution PDFs, scoreboard
problems/<L>/data/   sample and secret tests
problems/<L>/jury/   official jury submissions, sorted by intended verdict (spoilers)
data/scoreboard.json parsed original scoreboard
state/               your contest: start time and submissions (created on first start)
selftest.py          end-to-end test of the setup
practice/            practice contest: contest.json, generate.py, problems/, examples/
```

To run the contest again: stop the server, then run `python3 server.py --reset`. It moves `state/` to
`state-backup-<date>/`.

## After the contest

- `/solutions`: official slides and jury code.
- `../icpc-problems/problems/gcpc.md#gcpc-2018` has topic tags and the key idea of every problem.
