import os
import discord
import logging

from datetime import datetime
from discord.ext import commands
from dotenv import load_dotenv

from discord.ext.commands import is_owner, Context
from core.database import DB_PATH

# Loads the .env file that resides on the same level as the script
load_dotenv("config.env.txt")

# Grab API tokens from the .env file and other things
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_PREFIX = "%"

# Other External Keys
LAUNCH_TIME = datetime.utcnow()

# Login Clients
intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

# Ensure the necessary directories exist
os.makedirs('data', exist_ok=True)
os.makedirs('data/logs', exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs('data/prompt_bank', exist_ok=True)
os.makedirs('data/fonts', exist_ok=True)

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger('discord')
handler = logging.FileHandler(filename='data/logs/discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

client = commands.Bot(command_prefix=DISCORD_PREFIX,
                      intents=intents,
                      help_command=None,
                      activity=discord.Activity(type=discord.ActivityType.watching, name=" love -- /help"))

async def perform_sync():
    synced = await client.tree.sync()
    return len(synced)

@client.command()
@is_owner()
async def sync(ctx: Context) -> None:
    synced = await client.tree.sync()
    await ctx.reply("{} commands synced".format(len(synced)))

if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
