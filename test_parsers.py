import parsers, leaderboard
from db import DB
S = {
"k":"Krillion #119 🦐\n360\n\n🦑🦑🦑🐟🦑🦑🐟",
"a":"Alphablitz Online #16\n⚡ 1,021 Blitz · ⏱ 1:08 · 1,170 pts\n🟨🟨🟥🟥🟦",
"b":"Daily Banana #008 · 406/600\n🟫 🟨 💯 🟫 ⬜ 🟨\ndailybanana.io",
"w":"Wordle 1971 4/6\n\n⬛⬛⬛⬛🟦\n🟦🟦⬛⬛⬛\n⬛⬛⬛🟦🟧\n🟧🟧🟧🟧🟧",
"wx":"Wordle 1,971 X/6\n⬛⬛⬛⬛⬛",
}
for k,v in S.items(): print(k, parsers.parse_builtin(v))
assert parsers.parse_builtin("hello 5/6 wordle") is None
c="Connections\nPuzzle #512\n🟨🟨🟨🟨"
g=dict(name="Conn",prefix=parsers.derive_prefix("Mini Crossword 1:23 #44"),puzzle_idx=2,score_idx=0,higher_is_better=False)
print(g["prefix"], parsers.parse_custom("Mini Crossword 2:05 #45",g))
db=DB(":memory:")
for i,(u,t) in enumerate([("Doug",S["w"]),("Sam",S["wx"]),("Adam","Wordle 1971 3/6"),("Jo","Wordle 1971 4/6"),("Doug",S["k"])]):
    db.save(1, parsers.parse_builtin(t), hash(u), u, "2026-11-11", i)
db.save(2, parsers.parse_builtin(S["b"]), 9, "Other", "2026-11-11", 99)
for t,txt in leaderboard.build(db.day_scores(1,"2026-11-11")): print("##",t); print(txt)
print("ch2:", [r["user_name"] for r in db.day_scores(2,"2026-11-11")])
db.save(1, parsers.parse_builtin("Wordle 1972 2/6"), hash("Sam"), "Sam", "2026-11-12", 50)
db.save(1, parsers.parse_builtin("Wordle 1972 5/6"), hash("Doug"), "Doug", "2026-11-12", 51)
db.save(1, parsers.parse_builtin("Wordle 1960 5/6"), hash("Doug"), "Doug", "2026-11-01", 52)
for t,txt in leaderboard.build_week(db.range_scores(1,"2026-11-06","2026-11-12")): print("##",t); print(txt)
print("pruned:", db.prune("2026-11-06"))
