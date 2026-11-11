# Discord Daily Summary Bot

**[Add to Discord](https://discord.com/oauth2/authorize?client_id=1570160234176184440&permissions=85056&integration_type=0&scope=bot)**

Reads pasted daily-game results in a channel and keeps a per-game leaderboard for each channel.

**Built-in games:** Krillion, Alphablitz, Daily Banana, Wordle

## Commands
- `/dgs set-channel` — choose the one channel the bot watches and posts in (needs **Manage Server**; run it in that channel or pick one)
- `/dgs today` — today's standings for every game (posted for everyone; `private:True` to see it alone)
- `/dgs yesterday` — yesterday's final standings
- `/dgs day days_ago:N` — standings for any day in the past week (0 = today … 6)
- `/dgs week` — last 7 days per game: daily wins 🏆, average score, days played
- `/dgs games` — list the games this channel tracks
- `/dgs addgame` — paste a sample result, pick which number is the puzzle # and which is the score, choose higher/lower is better
- `/dgs removegame name` — remove an added game (creator or moderator only)

A recap of the previous day posts automatically at 12:00 AM Pacific in the chosen channel, if it had scores.

## How data stays separate
Every score and every added game is stored with its channel ID, and every lookup filters by it. A game added in one channel only works in that channel.

## Rules
- The bot only reads and posts in the channel chosen with `set-channel`, one per server. Commands used anywhere else point people to that channel.
- When a channel is chosen (and whenever the bot restarts), it reads back through today's messages in that channel and adds any results it finds, without reacting to them.
- One message can hold several games; each one is captured.
- Only the last 7 days of scores are kept; older ones are deleted at midnight Pacific. Added games are kept.
- One score per player, per game, per puzzle. Re-posting or editing updates the score.
- A day is the Pacific date of the first post.
- Ties share a rank. Wordle X/6 ranks below 6/6.
- The bot reacts 📊 to posts it captured.

## Setup
1. https://discord.com/developers/applications → New Application → **Bot** → Reset Token (copy it).
2. On the Bot page, turn on **Message Content Intent**.
3. OAuth2 → URL Generator: scopes `bot` + `applications.commands`; permissions: View Channels, Send Messages, Embed Links, Read Message History, Add Reactions. Open the URL to invite it.
4. Run:
   ```
   pip install -r requirements.txt
   DISCORD_TOKEN=your-token python bot.py
   ```
   (Windows PowerShell: `$env:DISCORD_TOKEN="your-token"; python bot.py`)

Slash commands can take a few minutes to appear the first time.

## Hosting
It must stay running for the recap and for capturing posts. Railway, fly.io, or a Raspberry Pi all work. Set `DB_PATH` to a persistent volume so scores survive restarts.

## Tests
`python test_parsers.py` checks the parsers against real sample pastes.

## Deploying to Fly.io (Windows)
1. Install flyctl in PowerShell: `iwr https://fly.io/install.ps1 -useb | iex`, then reopen PowerShell.
2. `fly auth signup` (or `fly auth login`) and add a card.
3. In this folder:
   ```
   fly apps create smidgen-daily-games-bot
   fly volumes create bot_data --size 1 --region iad -a smidgen-daily-games-bot
   fly secrets set DISCORD_TOKEN=your-token -a smidgen-daily-games-bot
   fly deploy --ha=false
   ```
4. `fly logs` should show `Logged in as …`.

Updating later: edit the code, run `fly deploy`. Scores live on the volume and survive deploys.
Backup: `fly ssh sftp get /data/scores.db`.

## Policies
- Privacy Policy: https://ohmyitsdoug.github.io/discord-daily-summary-bot/privacy.html
- Terms of Service: https://ohmyitsdoug.github.io/discord-daily-summary-bot/terms.html
