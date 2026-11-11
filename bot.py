"""Daily game leaderboard bot.

Watches channels for pasted daily-game results, ranks them per game,
answers /today, and posts a recap at midnight Pacific.
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
TOKEN = os.environ["DISCORD_TOKEN"]

intents = discord.Intents.default()
intents.message_content = True  # also enable in Developer Portal → Bot
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
db = DB(os.environ.get("DB_PATH", "scores.db"))


def pacific_day(when: dt.datetime) -> str:
    return when.astimezone(PACIFIC).date().isoformat()


def parse(channel_id: int, text: str):
    r = parsers.parse_builtin(text)
    if r:
        return r
    for g in db.custom_games(channel_id):
        r = parsers.parse_custom(text, g)
        if r:
            return r


KEEP_DAYS = 7


def days_ago(n: int) -> str:
    return (dt.datetime.now(PACIFIC).date() - dt.timedelta(days=n)).isoformat()


def make_embed(channel_id: int, day: str, title: str, blocks=None):
    if blocks is None:
        blocks = leaderboard.build(db.day_scores(channel_id, day))
    e = discord.Embed(title=title, color=0x753189)
    if not blocks:
        e.description = "No scores posted yet."
    for name, text in blocks[:25]:
        e.add_field(name=name, value=text[:1024], inline=False)
    return e


# ---------- Capturing scores ----------

async def capture(msg: discord.Message):
    if msg.author.bot or msg.guild is None:
        return
    r = parse(msg.channel.id, msg.content)
    if not r:
        return
    db.save(msg.channel.id, r, msg.author.id, msg.author.display_name,
            pacific_day(msg.created_at), msg.id)
    try:
        await msg.add_reaction("📊")
    except discord.HTTPException:
        pass


@client.event
async def on_message(msg):
    await capture(msg)


@client.event
async def on_message_edit(_before, after):
    await capture(after)


# ---------- Slash commands ----------

@tree.command(description="See today's standings for every game in this channel")
@app_commands.describe(public="Post it for everyone instead of just you")
async def today(inter: discord.Interaction, public: bool = False):
    day = pacific_day(discord.utils.utcnow())
    await inter.response.send_message(
        embed=make_embed(inter.channel_id, day, f"🏆 Today's leaderboard · {day}"),
        ephemeral=not public)


@tree.command(description="See yesterday's final standings in this channel")
async def yesterday(inter: discord.Interaction, public: bool = False):
    day = (dt.datetime.now(PACIFIC).date() - dt.timedelta(days=1)).isoformat()
    await inter.response.send_message(
        embed=make_embed(inter.channel_id, day, f"📜 Final results · {day}"),
        ephemeral=not public)


@tree.command(description="See standings for any day in the past week")
@app_commands.describe(days_ago="0 = today, 1 = yesterday … 6", public="Post it for everyone")
async def day(inter: discord.Interaction, days_ago: app_commands.Range[int, 0, KEEP_DAYS - 1],
              public: bool = False):
    d = globals()["days_ago"](days_ago)
    await inter.response.send_message(
        embed=make_embed(inter.channel_id, d, f"📅 Leaderboard · {d}"), ephemeral=not public)


@tree.command(description="This week's standings: daily wins and average score per game")
async def week(inter: discord.Interaction, public: bool = False):
    start, end = days_ago(KEEP_DAYS - 1), days_ago(0)
    blocks = leaderboard.build_week(db.range_scores(inter.channel_id, start, end))
    await inter.response.send_message(
        embed=make_embed(inter.channel_id, end, f"🗓️ Last 7 days · {start} → {end}", blocks),
        ephemeral=not public)


@tree.command(description="List the games this channel tracks")
async def games(inter: discord.Interaction):
    custom = [g["name"] for g in db.custom_games(inter.channel_id)]
    text = "**Built in:** Krillion, Alphablitz, Daily Banana, Wordle"
    if custom:
        text += "\n**Added here:** " + ", ".join(custom)
    await inter.response.send_message(text, ephemeral=True)


@tree.command(description="Teach this channel a new game by pasting a shared result")
async def addgame(inter: discord.Interaction):
    await inter.response.send_modal(AddGameModal())


@tree.command(description="Remove a game you added to this channel")
async def removegame(inter: discord.Interaction, name: str):
    game = next((g for g in db.custom_games(inter.channel_id)
                 if g["name"].lower() == name.lower()), None)
    if not game:
        return await inter.response.send_message("No added game by that name here.", ephemeral=True)
    if game["created_by"] != inter.user.id and not inter.permissions.manage_messages:
        return await inter.response.send_message(
            "Only the person who added it (or a moderator) can remove it.", ephemeral=True)
    db.remove_custom(inter.channel_id, name)
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
        db.add_custom(inter.channel_id, self.name, self.prefix, self.puzzle_idx,
                      self.score_idx, self.higher, self.user_id)
        self.stop()
        await inter.response.edit_message(
            content=f"✅ **{self.name}** added to this channel. Your sample reads as "
                    f"score **{test.display}**. New pastes will show up in /today.",
            view=None)


# ---------- Midnight recap ----------

@tasks.loop(time=dt.time(0, 0, tzinfo=PACIFIC))
async def midnight_recap():
    day = days_ago(1)
    db.prune(days_ago(KEEP_DAYS - 1))  # keep today + previous 6 days
    for channel_id in db.channels_with_scores(day):
        ch = client.get_channel(channel_id)
        if ch:
            try:
                await ch.send(embed=make_embed(channel_id, day, f"🌙 Daily recap · {day}"))
            except discord.HTTPException:
                pass


@client.event
async def on_ready():
    await tree.sync()
    if not midnight_recap.is_running():
        midnight_recap.start()
    print(f"Logged in as {client.user}")


client.run(TOKEN)
