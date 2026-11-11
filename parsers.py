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


def parse_wordle(t: str):
    m = re.search(r"Wordle\s+([\d,]+)\s+([1-6X])/6", t, re.I)
    if m:
        g = m[2].upper()
        return Result("Wordle", _n(m[1]), 7 if g == "X" else int(g), f"{g}/6", False)


BUILTINS = [parse_krillion, parse_alphablitz, parse_daily_banana, parse_wordle]
BUILTIN_NAMES = {"krillion", "alphablitz", "daily banana", "wordle"}


def parse_builtin(text: str):
    for p in BUILTINS:
        r = p(text)
        if r:
            return r


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
