
import logging
import discord
import aiosqlite
import re

from discord.ext import commands
from discord import app_commands
from core.utils import log_command_usage, DB_PATH

# ---------------------------------------------------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logger = logging.getLogger(__name__)



# ---------------------------------------------------------------------------------------------------------------------
# Setup Class
# ---------------------------------------------------------------------------------------------------------------------
class SetupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def owner_check(self, interaction: discord.Interaction):
        return interaction.user.id == 111941993629806592


# ---------------------------------------------------------------------------------------------------------------------
# Setup Commands
# ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(description="Owner: Run the setup for Pebble.")
    async def setup(self, interaction: discord.Interaction):
        if not await self.owner_check(interaction):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        try:
            guild = interaction.guild

            overwrites = {}

            for role in guild.roles:
                if role.permissions.administrator:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True)

            log_channel = discord.utils.get(guild.text_channels, name='pebble_logs')
            if not log_channel:
                log_channel = await guild.create_text_channel('pebble_logs', overwrites=overwrites)
                await log_channel.send("Welcome to the Pebble Logs Channel!")

            categories = {
                "Living Room": ["general", "calendar", "love-notes", "journal"],
                "Bedroom": ["to-do-list", "topic-list", "fuck-it-list", "watch-list"],
                "Kitchen": ["recipes", "food-pics"],
                "Garden": ["adventures", "gallery"]
            }

            async with aiosqlite.connect(DB_PATH) as conn:
                for cat_name, channels in categories.items():
                    category = discord.utils.get(guild.categories, name=cat_name)
                    if not category:
                        category = await guild.create_category(cat_name, overwrites=overwrites)

                    for name in channels:
                        channel = discord.utils.get(guild.text_channels, name=name)
                        if not channel:
                            channel = await guild.create_text_channel(name, category=category, overwrites=overwrites)

                        if cat_name == "Bedroom":
                            title_map = {
                                "topic-list": "Topics",
                                "watch-list": "Watch List",
                                "fuck-it-list": "Fuckit List",
                                "to-do-list": "To-Do List"
                            }

                            embed = discord.Embed(
                                title=title_map.get(name, "📋 Your List"),
                                description="",
                                color=discord.Color.purple()
                            )
                            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
                            msg = await channel.send(embed=embed)

                            await conn.execute('''
                                INSERT INTO bedroom_lists (guild_id, channel_name, channel_id, message_id)
                                VALUES (?, ?, ?, ?)
                                ON CONFLICT(guild_id, channel_name) DO UPDATE SET
                                    channel_id = excluded.channel_id,
                                    message_id = excluded.message_id
                            ''', (guild.id, name, channel.id, msg.id))
                await conn.commit()
            await interaction.response.send_message('Setup completed!')

        except Exception as e:
            logger.error(f"Error with setup command: {e}")
            logger.error(f"An error occurred: {e}")
            try:
                await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)
            except:
                pass
        finally:
            await log_command_usage(self.bot, interaction)


# ---------------------------------------------------------------------------------------------------------------------
# Setup Function
# ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    async with aiosqlite.connect(DB_PATH) as conn:
        # Config table
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS config (
                guild_id INTEGER PRIMARY KEY,
                log_channel_id INTEGER,
                countdown_channel_id INTEGER,
                prompt_channel_id INTEGER
            )
        ''')

        # Bedroom items table
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS bedroom_items (
                guild_id INTEGER,
                channel_name TEXT,
                item_index INTEGER,
                content TEXT,
                checked BOOLEAN DEFAULT 0,
                PRIMARY KEY (guild_id, channel_name, item_index)
            )
        ''')

        # Updated bedroom_lists table with channel_id
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS bedroom_lists (
                guild_id INTEGER,
                channel_name TEXT,
                channel_id INTEGER,
                message_id INTEGER,
                PRIMARY KEY (guild_id, channel_name)
            )
        ''')

        await conn.commit()

    await bot.add_cog(SetupCog(bot))
