import discord
import logging
import asyncio
import random
import pytz
import aiosqlite
import json
import os

from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime
from core.utils import get_embed_colour, log_command_usage

# ---------------------------------------------------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------------------------------------------------
os.makedirs('./data/databases', exist_ok=True)
db_path = './data/databases/pebble.db'
prompt_file = './prompt_bank/prompts.json'
BST_TIMEZONE = pytz.timezone("Europe/London")

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------------------------------
# Conversation Starters Cog
# ---------------------------------------------------------------------------------------------------------------------
class ConversationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.task_started = False

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.task_started:
            self.daily_prompt_task.start()
            self.task_started = True

    @tasks.loop(minutes=1)
    async def daily_prompt_task(self):
        await self.bot.wait_until_ready()

        now_bst = datetime.now(BST_TIMEZONE)
        if now_bst.hour != 2 or now_bst.minute != 0:
            return

        if not os.path.exists(prompt_file):
            logger.warning("Prompt JSON file not found.")
            return

        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompts = json.load(f)

        if not prompts:
            logger.warning("Prompt JSON is empty.")
            return

        prompt_text = random.choice(prompts)

        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute('''
                SELECT guild_id, prompt_channel_id
                FROM config
                WHERE prompt_channel_id IS NOT NULL
            ''')
            guilds = await cursor.fetchall()

        for guild_id, channel_id in guilds:
            try:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    await channel.send(f"**Daily Conversation Starter:** {prompt_text}")
                else:
                    logger.warning(f"Prompt channel {channel_id} not found for guild {guild_id}")
            except Exception as e:
                logger.error(f"Failed to send prompt for guild {guild_id}: {e}")

# ---------------------------------------------------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name='set_prompt_channel', description='Admin: Set the channel for daily prompts.')
    async def set_prompt_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        try:
            await log_command_usage(self.bot, interaction)

            if not channel.permissions_for(interaction.user).send_messages:
                await interaction.response.send_message("Error: You don't have permission to set that channel.", ephemeral=True)
                return

            async with aiosqlite.connect(db_path) as conn:
                await conn.execute('''
                    INSERT INTO config (guild_id, prompt_channel_id)
                    VALUES (?, ?)
                    ON CONFLICT(guild_id) DO UPDATE SET prompt_channel_id = excluded.prompt_channel_id
                ''', (interaction.guild.id, channel.id))
                await conn.commit()

            await interaction.response.send_message(f"Success: Daily prompts will be sent to {channel.mention}.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in set_prompt_channel: {e}")
            await interaction.response.send_message("Error: Something went wrong.", ephemeral=True)

    @app_commands.command(name='list_prompts', description='User: View all available conversation prompts.')
    async def list_prompts(self, interaction: discord.Interaction):
        colour = await get_embed_colour(interaction.guild.id)

        try:
            await log_command_usage(self.bot, interaction)

            if not os.path.exists(prompt_file):
                await interaction.response.send_message("Error: Prompt file not found.", ephemeral=True)
                return

            with open(prompt_file, 'r', encoding='utf-8') as f:
                prompts = json.load(f)

            if not prompts:
                await interaction.response.send_message("Error: No prompts available.", ephemeral=True)
                return

            embeds = []
            desc = ''
            for i, text in enumerate(prompts, start=1):
                new_line = f"{i}. {text}\n"
                if len(desc) + len(new_line) > 1800:
                    embeds.append(discord.Embed(
                        title="Conversation Starters",
                        description=desc,
                        color=colour
                    ))
                    desc = ''
                desc += new_line

            if desc:
                embeds.append(discord.Embed(
                    title="Conversation Starters",
                    description=desc,
                    color=colour
                ))

            await interaction.response.send_message(embed=embeds[0], ephemeral=True)
            for embed in embeds[1:]:
                await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in list_prompts: {e}")
            await interaction.response.send_message("Error: Could not list prompts.", ephemeral=True)

    @app_commands.command(name='add_prompt', description='Admin: Add a new conversation starter.')
    @app_commands.default_permissions(administrator=True)
    async def add_prompt(self, interaction: discord.Interaction, *, prompt: str):
        try:
            await log_command_usage(self.bot, interaction)

            if os.path.exists(prompt_file):
                with open(prompt_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = []

            data.append(prompt)

            with open(prompt_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            await interaction.response.send_message("Success: Prompt added.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in add_prompt: {e}")
            await interaction.response.send_message("Error: Failed to add prompt.", ephemeral=True)

    @app_commands.command(name='remove_prompt', description='Admin: Remove a prompt by number (not ID).')
    @app_commands.default_permissions(administrator=True)
    async def remove_prompt(self, interaction: discord.Interaction, prompt_number: int):
        try:
            await log_command_usage(self.bot, interaction)

            if not os.path.exists(prompt_file):
                await interaction.response.send_message("Error: Prompt file not found.", ephemeral=True)
                return

            with open(prompt_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            index = prompt_number - 1
            if index < 0 or index >= len(data):
                await interaction.response.send_message("Error: Prompt number is out of range.", ephemeral=True)
                return

            removed = data.pop(index)

            with open(prompt_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            await interaction.response.send_message(f"Success: Removed prompt: `{removed}`", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in remove_prompt: {e}")
            await interaction.response.send_message("Error: Could not remove prompt.", ephemeral=True)

    @app_commands.command(name='export_prompts', description='Admin: Export prompts.json as a file.')
    @app_commands.default_permissions(administrator=True)
    async def export_prompts(self, interaction: discord.Interaction):
        try:
            await log_command_usage(self.bot, interaction)

            if not os.path.exists(prompt_file):
                await interaction.response.send_message("Error: Prompt file not found.", ephemeral=True)
                return

            await interaction.response.send_message(
                content="Success: Here is the current `prompts.json`.",
                file=discord.File(prompt_file),
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error in export_prompts: {e}")
            await interaction.response.send_message("Error: Could not export prompts.", ephemeral=True)

# ---------------------------------------------------------------------------------------------------------------------
# Setup Function
# ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    await bot.add_cog(ConversationCog(bot))
