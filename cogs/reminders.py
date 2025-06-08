import discord
import aiosqlite
import asyncio
import logging
import pytz
import os

from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord import app_commands
from core.utils import log_command_usage, get_embed_colour

# ---------------------------------------------------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------------------------------------------------
os.makedirs('./data/databases', exist_ok=True)
db_path = './data/databases/pebble.db'

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

BST = pytz.timezone("Europe/London")

# ---------------------------------------------------------------------------------------------------------------------
class ReminderCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    # ---------------------------------------------------------------------------------------------------------------------
    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="remind", description="User: Set a reminder for yourself or your partner.")
    @app_commands.describe(
        message="What should the reminder say?",
        time="When should I remind you? (e.g., 'in 1 hour', '2025-04-09 17:00')",
        repeat="Repeat how often? (daily, weekly, monthly)",
        channel="Optional: Channel to send the reminder in",
        tag_partner="Tag your partner too?"
    )
    async def remind(self, interaction: discord.Interaction, message: str, time: str, repeat: str = None,
                     channel: discord.TextChannel = None, tag_partner: bool = False):
        await interaction.response.defer(ephemeral=True)
        try:
            user_id = interaction.user.id
            guild_id = interaction.guild.id

            async with aiosqlite.connect(db_path) as db:
                cur = await db.execute("SELECT partner_id FROM user_info WHERE guild_id = ? AND user_id = ?",
                                       (guild_id, user_id))
                result = await cur.fetchone()

            partner_id = result[0] if result else None

            # Parse time
            if time.lower().startswith("in "):
                delta_parts = time[3:].split()
                amount = int(delta_parts[0])
                unit = delta_parts[1].lower()
                if "min" in unit:
                    remind_time = datetime.now(BST) + timedelta(minutes=amount)
                elif "hour" in unit:
                    remind_time = datetime.now(BST) + timedelta(hours=amount)
                elif "day" in unit:
                    remind_time = datetime.now(BST) + timedelta(days=amount)
                else:
                    await interaction.followup.send("Error: Invalid time unit.", ephemeral=True)
                    return
            else:
                local_time = BST.localize(datetime.fromisoformat(time))
                remind_time = local_time

            if remind_time < datetime.now(BST):
                await interaction.followup.send("Error: That time is in the past.", ephemeral=True)
                return

            # Convert to UTC before storing
            remind_time_utc = remind_time.astimezone(pytz.utc)

            await self.save_reminder(guild_id, user_id, partner_id if tag_partner else None,
                                     channel.id if channel else None, message, remind_time_utc.isoformat(), repeat)

            await interaction.followup.send("Success: Reminder created.", ephemeral=True)

        except Exception as e:
            logger.error(f"Failed to set reminder: {e}")
            await interaction.followup.send("Error: Could not create reminder.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="remind_list", description="User: List your upcoming reminders.")
    async def remind_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            user_id = interaction.user.id
            guild_id = interaction.guild.id

            async with aiosqlite.connect(db_path) as db:
                cur = await db.execute("""
                    SELECT id, message, remind_time, repeat FROM reminders
                    WHERE guild_id = ? AND user_id = ?
                    ORDER BY remind_time ASC
                """, (guild_id, user_id))
                rows = await cur.fetchall()

            if not rows:
                await interaction.followup.send("You have no upcoming reminders.", ephemeral=True)
                return

            colour = await get_embed_colour(guild_id)
            embed = discord.Embed(title="⏰ Your Reminders", color=colour)

            for r in rows:
                rid, msg, remind_time, repeat = r
                utc_time = datetime.fromisoformat(remind_time).replace(tzinfo=pytz.utc)
                local_time = utc_time.astimezone(BST).strftime("%d %b %Y • %H:%M BST")
                repeat_text = f" (Repeats {repeat})" if repeat else ""
                embed.add_field(name=f"ID: {rid}", value=f"**{msg}**\n{local_time}{repeat_text}", inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Failed to list reminders: {e}")
            await interaction.followup.send("Error: Could not list reminders.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="remind_cancel", description="User: Cancel one of your reminders by ID.")
    @app_commands.describe(reminder_id="The ID of the reminder to cancel.")
    async def remind_cancel(self, interaction: discord.Interaction, reminder_id: int):
        await interaction.response.defer(ephemeral=True)
        try:
            user_id = interaction.user.id
            guild_id = interaction.guild.id

            async with aiosqlite.connect(db_path) as db:
                cur = await db.execute("""
                    SELECT id FROM reminders WHERE id = ? AND guild_id = ? AND user_id = ?
                """, (reminder_id, guild_id, user_id))
                row = await cur.fetchone()
                if not row:
                    await interaction.followup.send("Error: No reminder found with that ID.", ephemeral=True)
                    return

                await db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
                await db.commit()

            await interaction.followup.send("Success: Reminder cancelled.", ephemeral=True)

        except Exception as e:
            logger.error(f"Failed to cancel reminder: {e}")
            await interaction.followup.send("Error: Could not cancel reminder.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    async def save_reminder(self, guild_id, user_id, partner_id, channel_id, message, remind_time, repeat):
        async with aiosqlite.connect(db_path) as db:
            await db.execute('''
                INSERT INTO reminders (guild_id, user_id, partner_id, channel_id, message, remind_time, repeat, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (guild_id, user_id, partner_id, channel_id, message, remind_time, repeat, datetime.utcnow().isoformat()))
            await db.commit()

    # ---------------------------------------------------------------------------------------------------------------------
    @tasks.loop(minutes=1)
    async def check_reminders(self):
        now = datetime.utcnow().isoformat()
        try:
            async with aiosqlite.connect(db_path) as db:
                cur = await db.execute("SELECT * FROM reminders WHERE remind_time <= ?", (now,))
                reminders = await cur.fetchall()

                for r in reminders:
                    reminder_id, guild_id, user_id, partner_id, channel_id, message, remind_time, repeat, _ = r

                    channel = self.bot.get_channel(channel_id) if channel_id else None
                    user = self.bot.get_user(user_id)
                    partner = self.bot.get_user(partner_id) if partner_id else None

                    if not channel:
                        try:
                            channel = await user.create_dm()
                        except:
                            continue

                    msg = f"🔔 **Reminder:** {message}"
                    if partner:
                        msg = f"🔔 <@{user_id}> & <@{partner_id}>: {message}"

                    await channel.send(msg)

                    if repeat == "daily":
                        next_time = datetime.fromisoformat(remind_time) + timedelta(days=1)
                    elif repeat == "weekly":
                        next_time = datetime.fromisoformat(remind_time) + timedelta(weeks=1)
                    elif repeat == "monthly":
                        next_time = datetime.fromisoformat(remind_time) + timedelta(days=30)
                    else:
                        next_time = None

                    if next_time:
                        await db.execute("UPDATE reminders SET remind_time = ? WHERE id = ?",
                                         (next_time.isoformat(), reminder_id))
                    else:
                        await db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))

                await db.commit()
        except Exception as e:
            logger.error(f"Reminder loop error: {e}")

    # ---------------------------------------------------------------------------------------------------------------------
    @check_reminders.before_loop
    async def before_reminders(self):
        await self.bot.wait_until_ready()


# ---------------------------------------------------------------------------------------------------------------------
# SETUP FUNCTION
# ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    async with aiosqlite.connect(db_path) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                user_id INTEGER,
                partner_id INTEGER,
                channel_id INTEGER,
                message TEXT,
                remind_time TEXT,
                repeat TEXT,
                created_at TEXT
            )
        ''')
        await db.commit()
    await bot.add_cog(ReminderCog(bot))
