"""Quick checks for the parsers and leaderboard. Run: python test_parsers.py"""
import leaderboard
import parsers
from db import DB

S = {
    "k": "Krillion #119 🦐\n360\n\n🦑🦑🦑🐟🦑🦑🐟",
    "a": "Alphablitz Online #16\n⚡ 1,021 Blitz · ⏱ 1:08 · 1,170 pts\n🟨🟨🟥🟥🟦",
    "b": "Daily Banana #008 · 406/600\n🟫 🟨 💯 🟫 ⬜ 🟨\ndailybanana.io",
}
for k, v in S.items():
    r = parsers.parse_builtin(v)
    assert r, k
    print(k, r)

# Wordle is not tracked
assert parsers.parse_builtin("Wordle 1971 4/6") is None
assert parsers.parse_all("just chatting about krillion") == []

# Several games in one message
assert [r.game for r in parsers.parse_all("\n\n".join(S.values()))] == \
    ["Krillion", "Alphablitz", "Daily Banana"]

# Player-added game
g = dict(name="Mini", prefix=parsers.derive_prefix("Mini Crossword 1:23 #44"),
         puzzle_idx=2, score_idx=0, higher_is_better=False)
print(parsers.parse_custom("Mini Crossword 2:05 #45", g))

# Leaderboard: higher is better, ties share a rank, servers stay separate
db = DB(":memory:")
for i, (u, s) in enumerate([("Doug", 360), ("Sam", 410), ("Adam", 360), ("Jo", 290)]):
    db.save(1, parsers.parse_builtin(f"Krillion #119\n{s}"), hash(u), u, "2026-11-11", i)
db.save(2, parsers.parse_builtin(S["b"]), 9, "Other", "2026-11-11", 99)
for t, txt in leaderboard.build(db.day_scores(1, "2026-11-11")):
    print("##", t); print(txt)
assert [r["user_name"] for r in db.day_scores(2, "2026-11-11")] == ["Other"]

db.save(1, parsers.parse_builtin("Krillion #120\n500"), hash("Jo"), "Jo", "2026-11-12", 50)
for t, txt in leaderboard.build_week(db.range_scores(1, "2026-11-06", "2026-11-12")):
    print("##", t); print(txt)
print("all checks passed")
