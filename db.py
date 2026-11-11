"""SQLite storage. Scores and added games are scoped per server (the `channel_id`
column holds the server ID), so servers never see each other's data."""
import sqlite3

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

    # --- scores ---
    def save(self, channel_id, r, user_id, user_name, day, message_id):
        puzzle = str(r.puzzle) if r.puzzle is not None else day
        # Re-posts/edits update the score but keep the original day.
        self.c.execute("""
            INSERT INTO scores VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(channel_id, game, puzzle, user_id) DO UPDATE SET
              score=excluded.score, display=excluded.display,
              user_name=excluded.user_name, message_id=excluded.message_id
        """, (channel_id, r.game, puzzle, user_id, user_name, r.score, r.display,
              int(r.higher_is_better), day, message_id))
        self.c.commit()

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
