# Pebble

Pebble is a feature-rich Discord bot designed to help couples stay connected and organised. It provides prompts and fun activities to strengthen relationships while offering practical tools like reminders and shared lists.

## Features
- Daily conversation starters and prompts
- Countdown timers and calendar events
- Reminders with optional repetition
- Important date tracking
- Bedroom lists for shared to-dos and watch lists
- Mini games including Rock–Paper–Scissors, Tic-Tac-Toe and Would You Rather
- Music playback and playlists
- Customisation options and administrative commands
- Built-in `/help` command that lists all available slash commands

## Installation
1. Clone the repository.
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Environment Variables
Create a `config.env.txt` file in the project root containing your Discord bot token:

```
DISCORD_TOKEN=your-token-here
```

## Running the Bot
After installing dependencies and setting up the environment file, run:

```bash
python bot.py
```

Pebble looks for its fonts in the `fonts/` directory and prompt files in
`prompt_bank/`. These folders are created automatically on startup if they do
not already exist, so you can drop custom assets in there as needed.

## Commands
Use the `/help` command in Discord to see a paginated list of Pebble's commands. The `cogs` folder contains the source code for each command module if you want to explore further.
