"""Turns score rows into per-game ranked text blocks."""
from collections import defaultdict

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def build(rows, max_per_game=None):
    """Returns [(game_title, text)] with tied scores sharing a rank."""
    by_game = defaultdict(list)
    for r in rows:
        by_game[(r["game"], r["puzzle"])].append(r)

    blocks = []
    for (game, puzzle), entries in sorted(by_game.items()):
        higher = bool(entries[0]["higher"])
        entries.sort(key=lambda e: -e["score"] if higher else e["score"])
        lines, rank, prev = [], 0, None
        for i, e in enumerate(entries, 1):
            if e["score"] != prev:
                rank, prev = i, e["score"]
            if max_per_game and i > max_per_game:
                lines.append(f"…and {len(entries) - max_per_game} more")
                break
            lines.append(f"{MEDALS.get(rank, f'`{rank}.`')} **{e['user_name']}** — {e['display']}")
        title = f"{game} #{puzzle}" if puzzle.isdigit() else game
        blocks.append((title, "\n".join(lines)))
    return blocks


def build_week(rows, max_per_game=None):
    """Per game: ranked by average score over the week, with days played and daily wins."""
    by_game = defaultdict(list)
    for r in rows:
        by_game[r["game"]].append(r)

    blocks = []
    for game, entries in sorted(by_game.items()):
        higher = bool(entries[0]["higher"])
        # daily wins: best score on each puzzle (ties all count)
        wins = defaultdict(int)
        by_puzzle = defaultdict(list)
        for e in entries:
            by_puzzle[e["puzzle"]].append(e)
        for es in by_puzzle.values():
            best = (max if higher else min)(x["score"] for x in es)
            for x in es:
                if x["score"] == best:
                    wins[x["user_id"]] += 1

        players = defaultdict(list)
        names = {}
        for e in entries:
            players[e["user_id"]].append(e["score"])
            names[e["user_id"]] = e["user_name"]
        stats = [(uid, sum(v) / len(v), len(v)) for uid, v in players.items()]
        # rank by wins first, then average
        stats.sort(key=lambda t: (-wins[t[0]], -t[1] if higher else t[1]))

        lines = []
        for i, (uid, avg, n) in enumerate(stats, 1):
            if max_per_game and i > max_per_game:
                lines.append(f"…and {len(stats) - max_per_game} more")
                break
            avg_s = f"{avg:,.0f}" if avg >= 100 else f"{avg:.1f}"
            lines.append(f"{MEDALS.get(i, f'`{i}.`')} **{names[uid]}** — "
                         f"{wins[uid]} 🏆 · avg {avg_s} · {n} day{'s' if n != 1 else ''}")
        blocks.append((f"{game} · {len(by_puzzle)} puzzle{'s' if len(by_puzzle) != 1 else ''}", "\n".join(lines)))
    return blocks
