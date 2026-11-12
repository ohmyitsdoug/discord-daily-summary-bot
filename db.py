"""SQLite storage. Scores and added games are scoped per server (the `channel_id`
column holds the server ID), so servers never see each other's data."""
import sqlite3
from collections import Counter
from datetime import date

SCHEMA = """
CREATE TABLE IF NOT EXISTS scores (
    channel_id  INTEGER NOT NULL,
    game        TEXT    NOT NULL,
    puzzle      TEXT    NOT NULL,   -- puzzle number, or the day for games without one
    user_id     INTEGER NOT NULL,
    user_name   TEXT    NOT NULL,
    score       REAL    NOT NULL,
    display     TEXT    NOT NULL,
    higher      INTEGER NOT NULL,
    day         TEXT    NOT NULL,   -- Pacific date of first post, YYYY-MM-DD
    message_id  INTEGER NOT NULL,
    PRIMARY KEY (channel_id, game, puzzle, user_id)
);
CREATE INDEX IF NOT EXISTS idx_scores_day ON scores(channel_id, day);
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id    INTEGER PRIMARY KEY,
    channel_id  INTEGER NOT NULL      -- the one channel the bot posts in
);
CREATE TABLE IF NOT EXISTS watch_channels (
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,     -- extra channels the bot reads results from
    PRIMARY KEY (guild_id, channel_id)
);
CREATE TABLE IF NOT EXISTS custom_games (
    channel_id  INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    prefix      TEXT    NOT NULL,
    puzzle_idx  INTEGER,
    score_idx   INTEGER NOT NULL,
    higher_is_better INTEGER NOT NULL,
    created_by  INTEGER NOT NULL,
    PRIMARY KEY (channel_id, name)
);
"""


class DB:
    def __init__(self, path="scores.db"):
        self.c = sqlite3.connect(path)
        self.c.row_factory = sqlite3.Row
        self.c.executescript(SCHEMA)
        # posted_day = the Pacific date a score was posted (added later; older rows copy `day`).
        cols = [r[1] for r in self.c.execute("PRAGMA table_info(scores)")]
        if "posted_day" not in cols:
            self.c.execute("ALTER TABLE scores ADD COLUMN posted_day TEXT")
            self.c.execute("UPDATE scores SET posted_day = day")
            self.c.commit()

    # --- scores ---
    def save(self, channel_id, r, user_id, user_name, day, message_id):
        """Save one score. `day` is the Pacific date it was posted.

        Re-posts and edits update the score but keep when it was first posted.
        For games with puzzle numbers, the day shown on leaderboards comes from
        the number itself (see _settle_days), so a puzzle posted just after
        midnight Eastern still lands on the same day as everyone else's.
        """
        puzzle = str(r.puzzle) if r.puzzle is not None else day
        self.c.execute("""
            INSERT INTO scores (channel_id, game, puzzle, user_id, user_name, score, display,
                                higher, day, message_id, posted_day)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(channel_id, game, puzzle, user_id) DO UPDATE SET
              score=excluded.score, display=excluded.display,
              user_name=excluded.user_name, message_id=excluded.message_id
        """, (channel_id, r.game, puzzle, user_id, user_name, r.score, r.display,
              int(r.higher_is_better), day, message_id, day))
        if r.puzzle is not None:
            self._settle_days(channel_id, r.game)
        self.c.commit()

    def _settle_days(self, channel_id, game):
        """Give every puzzle of a game the day its number belongs to.

        Daily puzzles go up by one each day, so (puzzle number - date) is the same
        for nearly every post. The most common value wins; a few early East Coast
        or late West Coast posts can't pull a puzzle onto the wrong day. On a tie,
        the later day wins, since early posts are the usual outlier.
        """
        rows = self.c.execute(
            "SELECT puzzle, posted_day FROM scores WHERE channel_id=? AND game=?",
            (channel_id, game)).fetchall()
        rows = [(int(p), pd) for p, pd in rows if p.isdigit() and pd]
        if not rows:
            return
        counts = Counter(p - date.fromisoformat(pd).toordinal() for p, pd in rows)
        best = max(counts.values())
        offset = min(o for o, n in counts.items() if n == best)
        for p in {p for p, _ in rows}:
            self.c.execute("UPDATE scores SET day=? WHERE channel_id=? AND game=? AND puzzle=?",
                           (date.fromordinal(p - offset).isoformat(), channel_id, game, str(p)))

    def day_scores(self, channel_id, day):
        return self.c.execute(
            "SELECT * FROM scores WHERE channel_id=? AND day=? ORDER BY game",
            (channel_id, day)).fetchall()

    def range_scores(self, channel_id, start_day, end_day):
        return self.c.execute(
            "SELECT * FROM scores WHERE channel_id=? AND day BETWEEN ? AND ?",
            (channel_id, start_day, end_day)).fetchall()

    def prune(self, keep_from_day):
        """Delete scores older than keep_from_day (YYYY-MM-DD)."""
        cur = self.c.execute("DELETE FROM scores WHERE day < ?", (keep_from_day,))
        self.c.commit()
        self.c.execute("VACUUM")
        return cur.rowcount

    def channels_with_scores(self, day):
        return [r[0] for r in self.c.execute(
            "SELECT DISTINCT channel_id FROM scores WHERE day=?", (day,))]

    # --- per-server settings ---
    def get_channel(self, guild_id):
        row = self.c.execute("SELECT channel_id FROM guild_settings WHERE guild_id=?",
                             (guild_id,)).fetchone()
        return row[0] if row else None

    def set_channel(self, guild_id, channel_id):
        self.c.execute("INSERT OR REPLACE INTO guild_settings VALUES (?,?)", (guild_id, channel_id))
        self.c.commit()

    def post_channels(self):
        """[(guild_id, post_channel_id)] for every set-up server."""
        return [tuple(r) for r in self.c.execute("SELECT guild_id, channel_id FROM guild_settings")]

    def add_watch(self, guild_id, channel_id):
        self.c.execute("INSERT OR IGNORE INTO watch_channels VALUES (?,?)", (guild_id, channel_id))
        self.c.commit()

    def remove_watch(self, guild_id, channel_id):
        cur = self.c.execute("DELETE FROM watch_channels WHERE guild_id=? AND channel_id=?",
                             (guild_id, channel_id))
        self.c.commit()
        return cur.rowcount

    def read_channels(self, guild_id):
        """Every channel the bot reads results from: the post channel plus watched ones."""
        ids = [r[0] for r in self.c.execute(
            "SELECT channel_id FROM watch_channels WHERE guild_id=?", (guild_id,))]
        post = self.get_channel(guild_id)
        return ([post] if post else []) + [i for i in ids if i != post]

    # --- custom games ---
    def custom_games(self, channel_id):
        return [dict(r) for r in self.c.execute(
            "SELECT * FROM custom_games WHERE channel_id=?", (channel_id,))]

    def add_custom(self, channel_id, name, prefix, puzzle_idx, score_idx, higher, user_id):
        self.c.execute("INSERT OR REPLACE INTO custom_games VALUES (?,?,?,?,?,?,?)",
                       (channel_id, name, prefix, puzzle_idx, score_idx, int(higher), user_id))
        self.c.commit()

    def remove_custom(self, channel_id, name):
        cur = self.c.execute("DELETE FROM custom_games WHERE channel_id=? AND lower(name)=lower(?)",
                             (channel_id, name))
        self.c.commit()
        return cur.rowcount
