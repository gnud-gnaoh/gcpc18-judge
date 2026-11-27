"""Output checkers for GCPC 2018.

Every checker has the signature  check(inp, ans, out) -> (accepted, message)
where inp/ans/out are file paths (test input, jury answer, team output).

The default comparison follows the Kattis/DOMjudge default validator:
whitespace-insensitive and case-insensitive token comparison.
"""
import math


def _tokens(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8", "replace").split()


def _same(a, b):
    return a == b or a.lower() == b.lower()


def _as_float(tok):
    try:
        x = float(tok)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def exact(inp, ans, out):
    j, t = _tokens(ans), _tokens(out)
    for i, (a, b) in enumerate(zip(j, t)):
        if not _same(a, b):
            return False, f"token {i + 1}: expected {a[:40]!r}, got {b[:40]!r}"
    if len(t) < len(j):
        return False, f"output too short: {len(t)} tokens, expected {len(j)}"
    if len(t) > len(j):
        return False, f"trailing output: {len(t)} tokens, expected {len(j)}"
    return True, "ok"


def float_tol(inp, ans, out, eps=1e-7):
    j, t = _tokens(ans), _tokens(out)
    worst = 0.0
    for i, (a, b) in enumerate(zip(j, t)):
        fa = _as_float(a)
        if fa is None or a.lower() in ("nan", "inf", "-inf", "infinity"):
            if not _same(a, b):
                return False, f"token {i + 1}: expected {a[:40]!r}, got {b[:40]!r}"
            continue
        fb = _as_float(b)
        if fb is None:
            return False, f"token {i + 1}: expected a number, got {b[:40]!r}"
        err = abs(fa - fb)
        rel = err / abs(fa) if fa != 0 else math.inf
        e = min(err, rel)
        if e > eps:
            return False, (f"token {i + 1}: expected {a}, got {b} "
                           f"(abs err {err:.3g}, rel err {rel:.3g})")
        worst = max(worst, e)
    if len(t) != len(j):
        return False, f"{len(t)} tokens, expected {len(j)}"
    return True, f"ok (max error {worst:.3g})"


def _impossible_gate(j, t):
    """Shared handling of 'impossible'. Returns a verdict tuple or None to continue."""
    jury_imp = len(j) == 1 and j[0].lower() == "impossible"
    team_imp = len(t) >= 1 and t[0].lower() == "impossible"
    if jury_imp:
        if team_imp and len(t) == 1:
            return True, "ok (impossible)"
        return False, "answer exists according to team, jury says impossible"
    if team_imp:
        return False, "team says impossible, but a solution exists"
    return None


def _ints(toks, k):
    if len(toks) != k:
        return None
    try:
        return [int(x) for x in toks]
    except ValueError:
        return None


def fightingmonsters(inp, ans, out):
    j, t = _tokens(ans), _tokens(out)
    g = _impossible_gate(j, t)
    if g:
        return g
    v = _ints(t, 2)
    if v is None:
        return False, "expected exactly two integers"
    n, *m = map(int, _tokens(inp))
    i, k = v
    if not (1 <= i <= n and 1 <= k <= n) or i == k:
        return False, f"invalid indices {i} {k}"
    a, b = m[i - 1], m[k - 1]
    for _ in range(10**7):
        b -= a
        if b <= 0:
            win = a
            break
        a -= b
        if a <= 0:
            win = b
            break
    else:
        return False, "fight did not terminate"
    if win != 1:
        return False, f"winner has power {win}, not 1"
    return True, "ok"


def hyperilluminati(inp, ans, out):
    j, t = _tokens(ans), _tokens(out)
    g = _impossible_gate(j, t)
    if g:
        return g
    v = _ints(t, 2)
    if v is None:
        return False, "expected exactly two integers"
    m = int(_tokens(inp)[0])
    n, s = v
    if n < 3 or s < 1:
        return False, f"invalid n={n}, s={s}"
    if s >= 2 and n > 70:
        return False, "pyramid too large"
    total = 0
    for k in range(1, s + 1):
        total += k ** (n - 1)
        if total > m:
            return False, f"pyramid ({n}, {s}) uses more than {m} blocks"
    if total != m:
        return False, f"pyramid ({n}, {s}) uses {total} blocks, not {m}"
    return True, "ok"


def logicpuzzle(inp, ans, out):
    j, t = _tokens(ans), _tokens(out)
    g = _impossible_gate(j, t)
    if g:
        return g
    it = iter(_tokens(inp))
    h, w = int(next(it)), int(next(it))
    clue = [[int(next(it)) for _ in range(w + 2)] for _ in range(h + 2)]
    if len(t) != h:
        return False, f"expected {h} rows, got {len(t)}"
    for r, row in enumerate(t):
        if len(row) != w or set(row) - set("X."):
            return False, f"row {r + 1} is malformed: {row[:40]!r}"
    black = [[0] * (w + 2) for _ in range(h + 2)]
    for r in range(h):
        for c in range(w):
            black[r + 1][c + 1] = t[r][c] == "X"
    for r in range(h + 2):
        for c in range(w + 2):
            cnt = sum(black[rr][cc]
                      for rr in range(max(0, r - 1), min(h + 2, r + 2))
                      for cc in range(max(0, c - 1), min(w + 2, c + 2)))
            if cnt != clue[r][c]:
                return False, f"clue at ({r}, {c}) is {clue[r][c]}, grid gives {cnt}"
    return True, "ok"


def jigsaw(inp, ans, out):
    j, t = _tokens(ans), _tokens(out)
    g = _impossible_gate(j, t)
    if g:
        return g
    it = iter(_tokens(inp))
    n = int(next(it))
    piece = [[int(next(it)) for _ in range(4)] for _ in range(n)]
    try:
        vals = [int(x) for x in t]
    except ValueError:
        return False, "non-integer token in output"
    if len(vals) < 2:
        return False, "missing dimensions"
    h, w = vals[0], vals[1]
    if h < 1 or w < 1 or h * w != n:
        return False, f"bad dimensions {h} x {w} for {n} pieces"
    grid = vals[2:]
    if len(grid) != n:
        return False, f"expected {n} piece numbers, got {len(grid)}"
    if sorted(grid) != list(range(1, n + 1)):
        return False, "pieces are not a permutation of 1..n"
    grid = [p - 1 for p in grid]
    pos = [{e: k for k, e in enumerate(pc) if e} for pc in piece]
    # sides in counter-clockwise order: 0 top, 1 left, 2 bottom, 3 right
    DR = (-1, 0, 1, 0)
    DC = (0, -1, 0, 1)

    def attempt(r0):
        rot = [-1] * n
        rot[0] = r0
        stack = [0]
        while stack:
            cell = stack.pop()
            r, c = divmod(cell, w)
            pc = piece[grid[cell]]
            for k in range(4):
                v = pc[(k + rot[cell]) % 4]
                nr, nc = r + DR[k], c + DC[k]
                if not (0 <= nr < h and 0 <= nc < w):
                    if v != 0:
                        return f"piece {grid[cell] + 1} at ({r + 1}, {c + 1}) has an irregular edge on the border"
                    continue
                if v == 0:
                    return f"piece {grid[cell] + 1} at ({r + 1}, {c + 1}) has a straight edge inside"
                d = nr * w + nc
                idx = pos[grid[d]].get(v)
                if idx is None:
                    return f"pieces at ({r + 1}, {c + 1}) and ({nr + 1}, {nc + 1}) do not fit"
                need = (idx - (k + 2)) % 4
                if rot[d] == -1:
                    rot[d] = need
                    stack.append(d)
                elif rot[d] != need:
                    return f"piece at ({nr + 1}, {nc + 1}) cannot be rotated consistently"
        return None

    err = None
    for r0 in range(4):
        err = attempt(r0)
        if err is None:
            return True, "ok"
    return False, err


CHECKERS = {
    "exact": exact,
    "float": float_tol,
    "fightingmonsters": fightingmonsters,
    "hyperilluminati": hyperilluminati,
    "logicpuzzle": logicpuzzle,
    "jigsaw": jigsaw,
}


def check(kind, inp, ans, out):
    try:
        return CHECKERS[kind](inp, ans, out)
    except (ValueError, IndexError, StopIteration) as e:
        return False, f"could not parse output ({type(e).__name__})"
