import discord
import logging
import aiosqlite
import os
import psutil
import inspect

from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button
from datetime import datetime

from core.utils import log_command_usage, check_permissions, get_embed_colour

# ---------------------------------------------------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------------------------------------------------
os.makedirs('./data/databases', exist_ok=True)
db_path = './data/databases/pebble.db'

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------------------------------------------------
# Help View
# ---------------------------------------------------------------------------------------------------------------------
class HelpPaginator(View):
    def __init__(self, bot, pages, updates_page):
        super().__init__(timeout=180)
        self.bot = bot
        self.pages = pages
        self.current_page = 0
        self.updates_page = updates_page

        self.prev_button = Button(label="Prev", style=discord.ButtonStyle.primary)
        self.prev_button.callback = self.prev_page
        self.add_item(self.prev_button)

        self.home_button = Button(label="Home", style=discord.ButtonStyle.green)
        self.home_button.callback = self.go_home
        self.add_item(self.home_button)

        self.next_button = Button(label="Next", style=discord.ButtonStyle.primary)
        self.next_button.callback = self.next_page
        self.add_item(self.next_button)

        self.updates_button = Button(label="Updates", style=discord.ButtonStyle.secondary)
        self.updates_button.callback = self.go_to_updates
        self.add_item(self.updates_button)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        if self.current_page >= len(self.pages):
            self.current_page = 0
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        if self.current_page < 0:
            self.current_page = len(self.pages) - 1
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    async def go_home(self, interaction: discord.Interaction):
        self.current_page = 0
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    async def go_to_updates(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.updates_page, view=self)

    async def start(self, interaction: discord.Interaction):
        for page in self.pages:
            page.set_thumbnail(url=self.bot.user.display_avatar.url)
            page.set_footer(text="Created by heyimneph")
            page.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=self.pages[self.current_page], view=self, ephemeral=True)

# ---------------------------------------------------------------------------------------------------------------------
# Utility Cog Class
# ---------------------------------------------------------------------------------------------------------------------
class UtilityCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot_start_time = datetime.utcnow()

    async def has_required_permissions(self, interaction, command):
        if interaction.user.guild_permissions.administrator:
            return True

        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute('''
                SELECT can_use_commands FROM permissions WHERE guild_id = ? AND user_id = ?
            ''', (interaction.guild.id, interaction.user.id))
            permission = await cursor.fetchone()
            if permission and permission[0]:
                return True

        if "Admin" in command.description or "Owner" in command.description:
            return False

        for check in command.checks:
            try:
                if inspect.iscoroutinefunction(check):
                    result = await check(interaction)
                else:
                    result = check(interaction)
                if not result:
                    return False
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                return False

        return True

    async def owner_check(self, interaction: discord.Interaction):
        owner_id = 111941993629806592
        return interaction.user.id == owner_id


    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="help", description="User: Display help information for all commands.")
    async def help(self, interaction: discord.Interaction):
        try:
            pages = []
            colour = await get_embed_colour(interaction.guild.id)

            # Main help intro page
            help_intro = discord.Embed(
                title="About Pebble",
                description=(
                    "*Hey there! I'm **Pebble** – your cozy digital companion designed to help couples bond, "
                    "grow, and connect even when you're apart.*\n\n"
                    "I offer thoughtful prompts, countdowns to special moments, shared goals, and fun games "
                    "to spark joy in your relationship. 💞\n\n"
                    "*Use the buttons below to browse all commands and features.*"
                ),
                color=colour
            )

            help_intro.add_field(name="",value="",inline=False)
            help_intro.add_field(
                name="Getting Started",
                value=(
                    "1. Run `/set_prompt_channel`\n"
                    "*Start your mornings with daily conversation starters.*\n"
                    "2. Try `/countdown`\n"
                    "*Set a timer for your next date, trip, or anniversary.*\n"
                    "3. Play a game together: `/wyr`, `/ttt`, `/rps`\n"
                    "*Because love should be fun too!*\n"
                    "4. Listen to music together with `/play`\n"
                    "*Background music while you game or talk!*\n"
                )
            )
            help_intro.add_field(name="",value="",inline=False)
            pages.append(help_intro)

            # Generating command pages
            for cog_name, cog in self.bot.cogs.items():
                if cog_name in {"Core", "TheMachineBotCore", "AdminCog"}:
                    continue
                embed = discord.Embed(title=f"{cog_name.replace('Cog', '')} Commands", description="", color=colour)

                for cmd in cog.get_app_commands():
                    if "Owner" in cmd.description and not await self.owner_check(interaction):
                        continue
                    if not await self.has_required_permissions(interaction, cmd):
                        continue
                    embed.add_field(name=f"/{cmd.name}", value=f"```{cmd.description}```", inline=False)

                if embed.fields:
                    pages.append(embed)

            # Updates page
            updates_page = discord.Embed(
                title="Latest Updates",
                description=(
                    "08/04/2025\n"
                    "- Pebble is live \n\n"
                ),
                color=colour
            )
            updates_page.set_footer(text="Created by heyimneph")
            updates_page.timestamp = discord.utils.utcnow()

            paginator = HelpPaginator(self.bot, pages=pages, updates_page=updates_page)
            await paginator.start(interaction)

        except Exception as e:
            logger.error(f"Error with Help command: {e}")
            await interaction.response.send_message("Failed to fetch help information.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(description="Admin: Authorize a user to use Woof Admin commands.")
    @app_commands.describe(user="The user to authorize")
    @app_commands.checks.has_permissions(administrator=True)
    async def authorise(self, interaction: discord.Interaction, user: discord.User):
        try:
            async with aiosqlite.connect(db_path) as conn:
                await conn.execute('''
                    INSERT INTO permissions (guild_id, user_id, can_use_commands) VALUES (?, ?, 1)
                    ON CONFLICT(guild_id, user_id) DO UPDATE SET can_use_commands = 1
                ''', (interaction.guild.id, user.id))
                await conn.commit()
            await interaction.response.send_message(f"{user.display_name} has been authorized.", ephemeral=True)

        except Exception as e:
            logger.error(f"Failed to authorise user: {e}")
            await interaction.response.send_message(f"Failed to authorise user: {e}",
                                                    ephemeral=True)


        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="Admin: Revoke a user's authorization to use Woof's Admin commands.")
    @app_commands.describe(user="The user to unauthorize")
    @app_commands.checks.has_permissions(administrator=True)
    async def unauthorise(self, interaction: discord.Interaction, user: discord.User):
        try:
            async with aiosqlite.connect(db_path) as conn:
                await conn.execute('''
                    UPDATE permissions SET can_use_commands = 0 WHERE guild_id = ? AND user_id = ?
                ''', (interaction.guild.id, user.id))
                await conn.commit()
            await interaction.response.send_message(f"{user.display_name} has been unauthorized.", ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to unauthorise user: {e}")
            await interaction.response.send_message(f"Failed to unauthorise user: {e}",
                                                    ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)


# ---------------------------------------------------------------------------------------------------------------------
# Setup Function
# ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS blacklist (
                user_id INTEGER PRIMARY KEY
            )
        ''')
        await conn.execute('''
                CREATE TABLE IF NOT EXISTS permissions (
                    guild_id INTEGER,
                    user_id INTEGER,
                    can_use_commands BOOLEAN DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            ''')

        await conn.commit()
    await bot.add_cog(UtilityCog(bot))



