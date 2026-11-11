"""Share-text parsers. Each returns a Result or None."""
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class Result:
    game: str
    puzzle: Optional[int]   # None = game has no puzzle number (day is used instead)
    score: float
    display: str            # what the leaderboard shows
    higher_is_better: bool


def _n(s: str) -> int:
    return int(s.replace(",", ""))


# ---------- Built-in games ----------

def parse_krillion(t: str):
    m = re.search(r"Krillion\s*#\s*(\d+)[^\n]*\n\s*([\d,]+)", t, re.I)
    if m:
        s = _n(m[2])
        return Result("Krillion", int(m[1]), s, f"{s:,}", True)


def parse_alphablitz(t: str):
    m = re.search(
        r"Alphablitz(?:\s+Online)?\s*#\s*(\d+).*?([\d,]+)\s*Blitz.*?⏱\s*([\d:]+).*?([\d,]+)\s*pts",
        t, re.I | re.S)
    if m:
        pts = _n(m[4])
        return Result("Alphablitz", int(m[1]), pts,
                      f"{pts:,} pts  (⚡{m[2]} · ⏱{m[3]})", True)


def parse_daily_banana(t: str):
    m = re.search(r"Daily\s*Banana\s*#\s*(\d+)[^\d\n]*([\d,]+)\s*/\s*([\d,]+)", t, re.I)
    if m:
        s = _n(m[2])
        return Result("Daily Banana", int(m[1]), s, f"{s}/{_n(m[3])}", True)


BUILTINS = [parse_krillion, parse_alphablitz, parse_daily_banana]
BUILTIN_NAMES = {"krillion", "alphablitz", "daily banana"}


def parse_builtin(text: str):
    for p in BUILTINS:
        r = p(text)
        if r:
            return r


# Line starts that begin a built-in game's result, used to split a message
# that contains several games into one chunk per game.
BUILTIN_HEADER = r"Krillion\s*#|Alphablitz(?:\s+Online)?\s*#|Daily\s*Banana\s*#"


def parse_all(text: str, custom_games=()):
    """Every game result in a message, one per game (first wins)."""
    alts = [BUILTIN_HEADER] + [re.escape(g["prefix"]) for g in custom_games if g.get("prefix")]
    header = re.compile(r"^[ \t]*(?:" + "|".join(alts) + ")", re.I | re.M)
    starts = [m.start() for m in header.finditer(text)] or [0]
    starts[0] = 0 if not text[:starts[0]].strip() else starts[0]
    chunks = [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]

    results, seen = [], set()
    for chunk in chunks:
        chunk = chunk.strip()
        r = parse_builtin(chunk)
        if not r:
            for g in custom_games:
                r = parse_custom(chunk, g)
                if r:
                    break
        if r and r.game not in seen:
            seen.add(r.game)
            results.append(r)
    return results


# ---------- Player-added games ----------
# A custom game is: a name, a "prefix" (the text its share starts with),
# which number in the paste is the puzzle #, which is the score, and sort direction.

NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_with_context(sample: str):
    """[(value_str, context_snippet)] for every number in a sample paste."""
    out = []
    for m in NUM_RE.finditer(sample):
        a, b = max(0, m.start() - 12), min(len(sample), m.end() + 12)
        ctx = sample[a:b].replace("\n", " ⏎ ")
        out.append((m.group(), ctx))
    return out


def derive_prefix(sample: str) -> str:
    """Text at the start of the paste, before the first number or '#'."""
    first = sample.strip().splitlines()[0] if sample.strip() else ""
    m = re.match(r"[^\d#]*", first)
    return (m.group() if m else "").strip()


def parse_custom(text: str, game: dict):
    if not text.strip().lower().startswith(game["prefix"].lower()):
        return None
    nums = NUM_RE.findall(text)
    need = max(game["score_idx"], game["puzzle_idx"] if game["puzzle_idx"] is not None else -1)
    if len(nums) <= need:
        return None
    score_s = nums[game["score_idx"]]
    score = float(score_s.replace(",", ""))
    puzzle = None
    if game["puzzle_idx"] is not None:
        puzzle = int(float(nums[game["puzzle_idx"]].replace(",", "")))
    return Result(game["name"], puzzle, score, score_s, bool(game["higher_is_better"]))

