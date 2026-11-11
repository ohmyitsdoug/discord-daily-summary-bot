"""Daily game leaderboard bot.

Reads pasted daily-game results from the channels a server chooses,
keeps one leaderboard per server, and posts everything (command replies
and the midnight Pacific recap) in that server's one post channel.
"""
import datetime as dt
import os
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import tasks

import leaderboard
import parsers
from db import DB

PACIFIC = ZoneInfo("America/Los_Angeles")
TOKEN = os.environ["DISCORD_TOKEN"].strip().strip('"\'').strip()
if TOKEN.lower().startswith("bot "):
    TOKEN = TOKEN[4:].strip()
if TOKEN.count(".") != 2:
    print(f"DISCORD_TOKEN looks wrong: expected 3 dot-separated parts, got {TOKEN.count('.') + 1} "
          f"(length {len(TOKEN)}). Use the token from the Bot tab, not the Client Secret or Application ID.")

intents = discord.Intents.default()
intents.message_content = True  # also enable in Developer Portal → Bot
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
summary = app_commands.Group(name="dgs",
                             description="Daily game leaderboards for this channel")
db = DB(os.environ.get("DB_PATH", "scores.db"))


def pacific_day(when: dt.datetime) -> str:
    return when.astimezone(PACIFIC).date().isoformat()


def parse(guild_id: int, text: str):
    return parsers.parse_all(text, db.custom_games(guild_id))


KEEP_DAYS = 7


def days_ago(n: int) -> str:
    return (dt.datetime.now(PACIFIC).date() - dt.timedelta(days=n)).isoformat()


def make_embed(guild_id: int, day: str, title: str, blocks=None):
    if blocks is None:
        blocks = leaderboard.build(db.day_scores(guild_id, day))
    e = discord.Embed(title=title, color=0x753189)
    if not blocks:
        e.description = "No scores posted yet."
    for name, text in blocks[:25]:
        e.add_field(name=name, value=text[:1024], inline=False)
    return e


# ---------- Capturing scores ----------

async def capture(msg: discord.Message, react: bool = True):
    if msg.author.bot or msg.guild is None:
        return
    if msg.channel.id not in db.read_channels(msg.guild.id):
        return
    results = parse(msg.guild.id, msg.content)
    if not results:
        return
    for r in results:
        db.save(msg.guild.id, r, msg.author.id, msg.author.display_name,
                pacific_day(msg.created_at), msg.id)
    if not react:
        return len(results)
    try:
        await msg.add_reaction("📊")
    except discord.HTTPException:
        pass


async def backfill_channel(ch) -> int:
    """Read today's messages (Pacific) in one channel and add any results."""
    start = dt.datetime.now(PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0)
    total = 0
    try:
        async for msg in ch.history(after=start, limit=1000, oldest_first=True):
            total += await capture(msg, react=False) or 0
    except discord.HTTPException:
        pass
    print(f"Backfilled {total} result(s) from today in #{ch.name} ({ch.guild.name})")
    return total


async def backfill_guild(guild: discord.Guild):
    for cid in db.read_channels(guild.id):
        ch = guild.get_channel(cid)
        if ch:
            await backfill_channel(ch)


SETUP_HINT = ("👋 Thanks for adding Daily Game Score Summaries! A server manager can run "
              "`/dgs set-channel` in the channel where the daily "
              "leaderboards should be posted. Add more channels to read scores from with "
              "`/dgs watch`.")


@client.event
async def on_guild_join(guild):
    ch = guild.system_channel
    if ch and ch.permissions_for(guild.me).send_messages:
        try:
            await ch.send(SETUP_HINT)
        except discord.HTTPException:
            pass


@client.event
async def on_message(msg):
    await capture(msg)


@client.event
async def on_message_edit(_before, after):
    await capture(after)


# ---------- Slash commands ----------

async def in_game_channel(inter: discord.Interaction) -> bool:
    """True if this is the server's post channel; otherwise tells the user where to go."""
    chosen = db.get_channel(inter.guild_id) if inter.guild_id else None
    if chosen == inter.channel_id:
        return True
    if chosen is None:
        msg = ("I'm not set up yet. A server manager can run "
               "`/dgs set-channel` in the games channel.")
    else:
        msg = f"Daily game leaderboards live in <#{chosen}>. Use the command there."
    await inter.response.send_message(msg, ephemeral=True)
    return False


def missing_perms(channel, me, post: bool):
    p = channel.permissions_for(me)
    need = [("View Channel", p.view_channel), ("Read Message History", p.read_message_history),
            ("Add Reactions", p.add_reactions)]
    if post:
        need += [("Send Messages", p.send_messages), ("Embed Links", p.embed_links)]
    return [n for n, ok in need if not ok]


async def require_manager(inter: discord.Interaction) -> bool:
    if inter.guild and inter.permissions.manage_guild:
        return True
    await inter.response.send_message(
        "Only people with **Manage Server** can change where I read and post.", ephemeral=True)
    return False


@summary.command(name="set-channel",
                 description="Choose the channel where I post leaderboards and recaps")
@app_commands.describe(channel="Leave empty to use this channel")
async def set_channel(inter: discord.Interaction, channel: discord.TextChannel = None):
    if not await require_manager(inter):
        return
    channel = channel or inter.channel
    missing = missing_perms(channel, inter.guild.me, post=True)
    if missing:
        return await inter.response.send_message(
            f"I can't work in {channel.mention} yet. Give me these permissions there: "
            + ", ".join(missing) + ".", ephemeral=True)
    db.set_channel(inter.guild_id, channel.id)
    await inter.response.send_message(
        f"📊 Leaderboards and the nightly recap (midnight Pacific) will post in {channel.mention}. "
        "I'll read results posted here too. Add other channels to read from with `/dgs watch`.")
    found = await backfill_channel(channel)
    if found:
        await inter.followup.send(f"Picked up {found} result(s) already posted today.")


@summary.command(description="Also read game results from another channel")
@app_commands.describe(channel="Channel where people post results")
async def watch(inter: discord.Interaction, channel: discord.TextChannel):
    if not await require_manager(inter):
        return
    if not db.get_channel(inter.guild_id):
        return await inter.response.send_message(
            "Run `/dgs set-channel` first to choose where I post.", ephemeral=True)
    missing = missing_perms(channel, inter.guild.me, post=False)
    if missing:
        return await inter.response.send_message(
            f"I can't read {channel.mention} yet. Give me these permissions there: "
            + ", ".join(missing) + ".", ephemeral=True)
    db.add_watch(inter.guild_id, channel.id)
    await inter.response.send_message(
        f"👀 Now reading results from {channel.mention}. Leaderboards still post in "
        f"<#{db.get_channel(inter.guild_id)}>.", ephemeral=True)
    found = await backfill_channel(channel)
    if found:
        await inter.followup.send(f"Picked up {found} result(s) already posted there today.",
                                  ephemeral=True)


@summary.command(description="Stop reading game results from a channel")
async def unwatch(inter: discord.Interaction, channel: discord.TextChannel):
    if not await require_manager(inter):
        return
    if channel.id == db.get_channel(inter.guild_id):
        return await inter.response.send_message(
            "That's the post channel. Choose a different one with `/dgs set-channel` instead.",
            ephemeral=True)
    if db.remove_watch(inter.guild_id, channel.id):
        msg = f"Stopped reading {channel.mention}. Scores already collected stay on the board."
    else:
        msg = f"I wasn't reading {channel.mention}."
    await inter.response.send_message(msg, ephemeral=True)


@summary.command(description="Show where I read results and where I post")
async def channels(inter: discord.Interaction):
    post = db.get_channel(inter.guild_id) if inter.guild_id else None
    if not post:
        return await inter.response.send_message(
            "Not set up yet. A server manager can run `/dgs set-channel`.", ephemeral=True)
    reads = " ".join(f"<#{c}>" for c in db.read_channels(inter.guild_id))
    await inter.response.send_message(
        f"**Posts in:** <#{post}>\n**Reads results from:** {reads}", ephemeral=True)


@summary.command(description="See today's standings for every game")
@app_commands.describe(private="Only show it to you")
async def today(inter: discord.Interaction, private: bool = False):
    if not await in_game_channel(inter):
        return
    day = pacific_day(discord.utils.utcnow())
    await inter.response.send_message(
        embed=make_embed(inter.guild_id, day, f"🏆 Today's leaderboard · {day}"),
        ephemeral=private)


@summary.command(description="See yesterday's final standings")
@app_commands.describe(private="Only show it to you")
async def yesterday(inter: discord.Interaction, private: bool = False):
    if not await in_game_channel(inter):
        return
    day = days_ago(1)
    await inter.response.send_message(
        embed=make_embed(inter.guild_id, day, f"📜 Final results · {day}"),
        ephemeral=private)


@summary.command(description="See standings for any day in the past week")
@app_commands.describe(days_ago="0 = today, 1 = yesterday … 6", private="Only show it to you")
async def day(inter: discord.Interaction, days_ago: app_commands.Range[int, 0, KEEP_DAYS - 1],
              private: bool = False):
    if not await in_game_channel(inter):
        return
    d = globals()["days_ago"](days_ago)
    await inter.response.send_message(
        embed=make_embed(inter.guild_id, d, f"📅 Leaderboard · {d}"), ephemeral=private)


@summary.command(description="This week's standings: daily wins and average score per game")
@app_commands.describe(private="Only show it to you")
async def week(inter: discord.Interaction, private: bool = False):
    if not await in_game_channel(inter):
        return
    start, end = days_ago(KEEP_DAYS - 1), days_ago(0)
    blocks = leaderboard.build_week(db.range_scores(inter.guild_id, start, end))
    await inter.response.send_message(
        embed=make_embed(inter.guild_id, end, f"🗓️ Last 7 days · {start} → {end}", blocks),
        ephemeral=private)


@summary.command(description="List the games this server tracks")
async def games(inter: discord.Interaction):
    if not await in_game_channel(inter):
        return
    custom = [g["name"] for g in db.custom_games(inter.guild_id)]
    text = "**Built in:** Krillion, Alphablitz, Daily Banana, Wordle"
    if custom:
        text += "\n**Added here:** " + ", ".join(custom)
    await inter.response.send_message(text, ephemeral=True)


@summary.command(description="Teach me a new game by pasting a shared result")
async def addgame(inter: discord.Interaction):
    if not await in_game_channel(inter):
        return
    await inter.response.send_modal(AddGameModal())


@summary.command(description="Remove a game someone added")
async def removegame(inter: discord.Interaction, name: str):
    if not await in_game_channel(inter):
        return
    game = next((g for g in db.custom_games(inter.guild_id)
                 if g["name"].lower() == name.lower()), None)
    if not game:
        return await inter.response.send_message("No added game by that name here.", ephemeral=True)
    if game["created_by"] != inter.user.id and not inter.permissions.manage_messages:
        return await inter.response.send_message(
            "Only the person who added it (or a moderator) can remove it.", ephemeral=True)
    db.remove_custom(inter.guild_id, name)
    await inter.response.send_message(f"Removed **{game['name']}**.", ephemeral=True)


# ---------- /addgame flow ----------

class AddGameModal(discord.ui.Modal, title="Add a game"):
    name = discord.ui.TextInput(label="Game name", max_length=40, placeholder="e.g. Connections")
    sample = discord.ui.TextInput(label="Paste one shared result", style=discord.TextStyle.paragraph,
                                  max_length=1000)

    async def on_submit(self, inter: discord.Interaction):
        name, sample = self.name.value.strip(), self.sample.value
        if parsers.parse_builtin(sample):
            return await inter.response.send_message("That game is already built in. Just paste away!",
                                                     ephemeral=True)
        prefix = parsers.derive_prefix(sample)
        if len(prefix) < 3:
            return await inter.response.send_message(
                "I need the result to start with some text I can recognize (like the game's name).",
                ephemeral=True)
        nums = parsers.numbers_with_context(sample)
        if not nums:
            return await inter.response.send_message("I couldn't find a score in that paste.", ephemeral=True)
        view = MapView(inter.user.id, name, prefix, sample, nums)
        await inter.response.send_message(
            f"Results starting with **{prefix}** will count as **{name}**.\n"
            "Pick which number is the puzzle #, which is the score, and how to rank:",
            view=view, ephemeral=True)


class MapView(discord.ui.View):
    def __init__(self, user_id, name, prefix, sample, nums):
        super().__init__(timeout=600)
        self.user_id, self.name, self.prefix, self.sample = user_id, name, prefix, sample
        self.puzzle_idx, self.score_idx, self.higher = None, None, True
        opts = [discord.SelectOption(label=f"{v}", description=ctx[:100], value=str(i))
                for i, (v, ctx) in enumerate(nums[:24])]

        puzzle = discord.ui.Select(placeholder="Which number is the puzzle #?",
                                   options=[discord.SelectOption(label="No puzzle number", value="-1")] + opts)
        score = discord.ui.Select(placeholder="Which number is the score?", options=opts)
        order = discord.ui.Select(placeholder="How should scores rank?", options=[
            discord.SelectOption(label="Higher is better", value="high", default=True),
            discord.SelectOption(label="Lower is better", value="low")])

        async def on_puzzle(i):
            v = int(puzzle.values[0]); self.puzzle_idx = None if v < 0 else v
            await i.response.defer()

        async def on_score(i):
            self.score_idx = int(score.values[0]); await i.response.defer()

        async def on_order(i):
            self.higher = order.values[0] == "high"; await i.response.defer()

        puzzle.callback, score.callback, order.callback = on_puzzle, on_score, on_order
        for s in (puzzle, score, order):
            self.add_item(s)

    @discord.ui.button(label="Save game", style=discord.ButtonStyle.primary, row=4)
    async def save(self, inter: discord.Interaction, _button):
        if self.score_idx is None:
            return await inter.response.send_message("Pick the score number first.", ephemeral=True)
        game = dict(name=self.name, prefix=self.prefix, puzzle_idx=self.puzzle_idx,
                    score_idx=self.score_idx, higher_is_better=self.higher)
        test = parsers.parse_custom(self.sample, game)
        db.add_custom(inter.guild_id, self.name, self.prefix, self.puzzle_idx,
                      self.score_idx, self.higher, self.user_id)
        self.stop()
        await inter.response.edit_message(
            content=f"✅ **{self.name}** added. Your sample reads as "
                    f"score **{test.display}**. New pastes will show up in /dgs today.",
            view=None)


# ---------- Midnight recap ----------

@tasks.loop(time=dt.time(0, 0, tzinfo=PACIFIC))
async def midnight_recap():
    day = days_ago(1)
    db.prune(days_ago(KEEP_DAYS - 1))  # keep today + previous 6 days
    with_scores = set(db.channels_with_scores(day))  # server IDs with scores yesterday
    for guild_id, post_id in db.post_channels():
        if guild_id not in with_scores:
            continue
        ch = client.get_channel(post_id)
        if ch:
            try:
                await ch.send(embed=make_embed(guild_id, day, f"🌙 Daily recap · {day}"))
            except discord.HTTPException:
                pass


@client.event
async def on_ready():
    if not tree.get_command("dgs"):
        tree.add_command(summary)
    await tree.sync()
    if not midnight_recap.is_running():
        midnight_recap.start()
    for guild in client.guilds:
        await backfill_guild(guild)
    print(f"Logged in as {client.user}")


client.run(TOKEN)
