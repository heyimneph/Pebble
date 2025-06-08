import discord

from core.database import DB_PATH
import asyncio
import aiohttp
import logging
import pytz
import re

from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord import app_commands

from core.utils import log_command_usage, get_embed_colour

# ---------------------------------------------------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

BST = pytz.timezone("Europe/London")

def parse_time_string(time_str: str):
    pattern = r'(\d+)([dhm])'
    matches = re.findall(pattern, time_str.lower())
    if not matches:
        return None
    delta = timedelta()
    for value, unit in matches:
        value = int(value)
        if unit == 'd':
            delta += timedelta(days=value)
        elif unit == 'h':
            delta += timedelta(hours=value)
        elif unit == 'm':
            delta += timedelta(minutes=value)
    return datetime.now(BST) + delta if delta.total_seconds() > 0 else None

# ---------------------------------------------------------------------------------------------------------------------
# Countdown Views
# ---------------------------------------------------------------------------------------------------------------------
class CancelCountdownButton(discord.ui.View):
    def __init__(self, bot, guild_id, user_id, name):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        self.name = name

    @discord.ui.button(label="Cancel Countdown", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Only admins can cancel countdowns.", ephemeral=True)
            return
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM countdowns WHERE guild_id = ? AND user_id = ? AND name = ?",
                             (self.guild_id, self.user_id, self.name))
            await db.commit()
        try:
            await interaction.message.delete()
        except discord.NotFound:
            pass
        await interaction.response.send_message("Countdown cancelled.", ephemeral=True)

# ---------------------------------------------------------------------------------------------------------------------
# Countdown Class
# ---------------------------------------------------------------------------------------------------------------------
class CountdownCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.countdown_check.start()

    def cog_unload(self):
        self.countdown_check.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if not hasattr(self.bot, '_countdown_started'):
            self.bot._countdown_started = True
            await self.resume_active_countdowns()


# ---------------------------------------------------------------------------------------------------------------------
# Countdown Commands
# ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="countdown_add", description="User: Start a countdown to a specific time or delay.")
    @app_commands.describe(
        name="Name of the countdown",
        date="Date (DD/MM/YYYY), or leave blank if using a delay",
        time="Time (HH:MM) in 24h format, optional",
        delay="Delay instead, e.g. 2d3h10m"
    )
    async def countdown_add(self, interaction: discord.Interaction, name: str, date: str = None, time: str = None,
                            delay: str = None):
        try:
            if date:
                try:
                    date_obj = datetime.strptime(date, "%d/%m/%Y")
                except ValueError:
                    await interaction.response.send_message("Error: Invalid date format. Use `DD/MM/YYYY`.",
                                                            ephemeral=True)
                    return

                if time:
                    try:
                        time_obj = datetime.strptime(time, "%H:%M").time()
                    except ValueError:
                        await interaction.response.send_message("Error: Invalid time format. Use `HH:MM` (24h).",
                                                                ephemeral=True)
                        return
                    dt = datetime.combine(date_obj, time_obj)
                else:
                    dt = datetime.combine(date_obj, datetime.min.time())

                dt = BST.localize(dt)
            elif delay:
                dt = parse_time_string(delay)
                if not dt:
                    await interaction.response.send_message("Error: Invalid delay format. Try `2d3h` or `5m`.",
                                                            ephemeral=True)
                    return
            else:
                await interaction.response.send_message("Error: You must provide either a `date` or a `delay`.",
                                                        ephemeral=True)
                return

            utc_dt = dt.astimezone(pytz.utc)
            colour = await get_embed_colour(interaction.guild.id)
            embed = discord.Embed(
                title=f"⏳ {name}",
                description="Preparing countdown...",
                color=colour
            )

            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute("SELECT countdown_channel_id FROM config WHERE guild_id = ?",
                                          (interaction.guild.id,))
                row = await cursor.fetchone()
                countdown_channel_id = row[0] if row and row[0] else None

            channel = self.bot.get_channel(countdown_channel_id) or discord.utils.get(interaction.guild.text_channels,
                                                                                      name='countdowns')

            if not channel:
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    interaction.guild.me: discord.PermissionOverwrite(read_messages=True)
                }
                channel = await interaction.guild.create_text_channel('countdowns', overwrites=overwrites)

                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute('''
                        INSERT INTO config (guild_id, countdown_channel_id)
                        VALUES (?, ?)
                        ON CONFLICT(guild_id) DO UPDATE SET countdown_channel_id = excluded.countdown_channel_id
                    ''', (interaction.guild.id, channel.id))
                    await db.commit()

            view = CancelCountdownButton(self.bot, interaction.guild.id, interaction.user.id, name)
            message = await channel.send(embed=embed, view=view)

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('''
                    INSERT OR REPLACE INTO countdowns (guild_id, user_id, name, date, warned, channel_id, message_id)
                    VALUES (?, ?, ?, ?, 0, ?, ?)
                ''', (interaction.guild.id, interaction.user.id, name, utc_dt.isoformat(), channel.id, message.id))
                await db.commit()

            await interaction.response.send_message(
                f"Countdown **{name}** created for {dt.strftime('%d/%m/%Y %H:%M')} BST!", ephemeral=True)
            self.bot.loop.create_task(self.update_countdown_embed(channel, message, name, dt, colour))

        except Exception as e:
            logger.error(f"Error in countdown_add: {e}")
            await interaction.response.send_message("Error: Failed to create countdown.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="set_countdown_channel", description="Admin: Set the channel to post countdowns.")
    async def set_countdown_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        try:
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("Only admins can set the countdown channel.", ephemeral=True)
                return

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('''
                    INSERT INTO config (guild_id, countdown_channel_id)
                    VALUES (?, ?)
                    ON CONFLICT(guild_id) DO UPDATE SET countdown_channel_id = excluded.countdown_channel_id
                ''', (interaction.guild.id, channel.id))
                await db.commit()

            await interaction.response.send_message(f"Countdowns will now be posted in {channel.mention}.",
                                                    ephemeral=True)

        except Exception as e:
            logger.error(f"Error in set_countdown_channel: {e}")
            await interaction.response.send_message("Error: Could not set countdown channel.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="countdown_list", description="User: See your active countdowns.")
    async def countdown_list(self, interaction: discord.Interaction):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                rows = await db.execute_fetchall('''
                    SELECT name, date FROM countdowns
                    WHERE guild_id = ? AND user_id = ?
                    ORDER BY date ASC
                ''', (interaction.guild.id, interaction.user.id))

            if not rows:
                await interaction.response.send_message("You don't have any active countdowns.", ephemeral=True)
                return

            embed = discord.Embed(title="📅 Your Countdown Timers", color=discord.Color.green())
            now = datetime.now(pytz.utc)

            for name, date in rows:
                dt = datetime.fromisoformat(date).astimezone(BST)
                diff = dt - now.astimezone(BST)
                if diff.total_seconds() < 0:
                    continue
                days, seconds = diff.days, diff.seconds
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                embed.add_field(name=name,
                                value=f"{days}d {hours}h {minutes}m left ({dt.strftime('%d/%m/%Y %H:%M BST')})",
                                inline=False)

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in countdown_list: {e}")
            await interaction.response.send_message("Error: Could not list countdowns.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    async def resume_active_countdowns(self):
        await self.bot.wait_until_ready()
        async with aiosqlite.connect(DB_PATH) as db:
            rows = await db.execute_fetchall('''
                SELECT guild_id, user_id, name, date, channel_id, message_id
                FROM countdowns
            ''')

        for guild_id, user_id, name, date, channel_id, message_id in rows:
            guild = self.bot.get_guild(guild_id)
            channel = guild.get_channel(channel_id) if guild else None
            if not channel:
                continue
            try:
                message = await channel.fetch_message(message_id)
                target_time = datetime.fromisoformat(date).astimezone(BST)
                colour = await get_embed_colour(guild_id)
                self.bot.loop.create_task(self.update_countdown_embed(channel, message, name, target_time, colour))
            except Exception:
                continue

    # ---------------------------------------------------------------------------------------------------------------------
    async def update_countdown_embed(self, channel, message, name, target_time, colour):
        first_update = True
        while True:
            now = datetime.now(BST)
            remaining = target_time - now

            # Final “time’s up” update
            if remaining.total_seconds() <= 0:
                embed = discord.Embed(
                    title=f"⏳ {name}",
                    description="🎉 The time has arrived!",
                    color=discord.Color.gold()
                )
                embed.set_thumbnail(url=self.bot.user.display_avatar.url)
                embed.set_footer(text=f"Last Updated at {now.strftime('%H:%M on %d/%m/%Y')}")
                try:
                    await message.edit(embed=embed, view=None)
                except discord.NotFound:
                    return  # message deleted, bail out
                except (aiohttp.ClientConnectorDNSError, aiohttp.ClientConnectionError) as e:
                    logger.error(f"Network error finishing countdown '{name}': {e}")
                    return
                break

            # Format remaining time
            days = remaining.days
            hours, rem = divmod(remaining.seconds, 3600)
            minutes, seconds = divmod(rem, 60)
            if days >= 1:
                time_text = f"{days} day(s), {hours} hour(s) and {minutes} minute(s)"
            elif hours >= 1:
                time_text = f"{hours} hour(s) and {minutes} minute(s)"
            elif minutes >= 1:
                time_text = f"{minutes} minute(s) and {seconds} second(s)"
            else:
                time_text = f"{seconds} second(s)"

            embed = discord.Embed(title=f"⏳ {name}", color=colour)
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            embed.add_field(name="Time Remaining:", value=f"\n {time_text}", inline=False)
            embed.set_footer(text=f"Last Updated at {now.strftime('%H:%M on %d/%m/%Y')}")

            view = CancelCountdownButton(self.bot, channel.guild.id, message.author.id, name)

            try:
                await message.edit(embed=embed, view=view)
            except discord.NotFound:
                return  # stop if message was deleted
            except (aiohttp.ClientConnectorDNSError, aiohttp.ClientConnectionError) as e:
                logger.error(f"Network error updating countdown '{name}': {e}")
                return  # exit loop on DNS/connection failure

            # if less than a minute left, update every second; otherwise every minute
            await asyncio.sleep(1 if remaining.total_seconds() <= 60 else 60)

    # ---------------------------------------------------------------------------------------------------------------------
    @tasks.loop(minutes=10)
    async def countdown_check(self):
        now = datetime.utcnow()
        warning_threshold = now + timedelta(hours=24)
        async with aiosqlite.connect(DB_PATH) as db:
            rows = await db.execute_fetchall('''
                SELECT guild_id, user_id, name, date FROM countdowns
                WHERE warned = 0 AND date <= ?
            ''', (warning_threshold.isoformat(),))
            for guild_id, user_id, name, date in rows:
                user = self.bot.get_user(user_id)
                if user:
                    local_dt = datetime.fromisoformat(date).replace(tzinfo=pytz.utc).astimezone(BST)
                    try:
                        await user.send(f"⏳ Heads up! Countdown to **{name}** ends at {local_dt.strftime('%Y-%m-%d %H:%M BST')}!")
                    except Exception:
                        pass
                await db.execute('''
                    UPDATE countdowns SET warned = 1
                    WHERE guild_id = ? AND user_id = ? AND name = ?
                ''', (guild_id, user_id, name))
            await db.commit()

    @countdown_check.before_loop
    async def before_countdown_check(self):
        await self.bot.wait_until_ready()

# ---------------------------------------------------------------------------------------------------------------------
# SETUP FUNCTION
# ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS countdowns (
                guild_id INTEGER,
                user_id INTEGER,
                name TEXT,
                date TEXT,
                warned INTEGER DEFAULT 0,
                channel_id INTEGER,
                message_id INTEGER,
                PRIMARY KEY (guild_id, user_id, name)
            )
        ''')
        await db.commit()
    await bot.add_cog(CountdownCog(bot))
