import discord
import aiosqlite
import logging
import os

from discord import app_commands
from discord.ext import commands
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


class ImportantDatesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def build_date_description(self, entries):
        special_entries = []
        general_entries = []

        for d, t in entries:
            label = t.lower()
            if "birthday" in label or "anniversary" in label:
                special_entries.append((d, t))
            else:
                general_entries.append((d, t))

        desc = ""
        if special_entries:
            desc += "**🎉 Birthdays & Anniversary**\n"
            desc += "\n".join(f"**{t}** – {d.strftime('%d/%m/%Y')}" for d, t in special_entries)
            desc += "\n\n"

        if general_entries:
            desc += "**📅 Other Special Dates**\n"
            desc += "\n".join(f"**{t}** – {d.strftime('%d/%m/%Y')}" for d, t in general_entries)

        return desc

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="set_dates_channel", description="Admin: Set the channel for important date posts.")
    async def set_dates_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        try:
            if not await check_permissions(interaction):
                await interaction.response.send_message("Error: You don’t have permission to do that.", ephemeral=True)
                return

            colour = await get_embed_colour(interaction.guild.id)
            embed = discord.Embed(title="Our Special Dates :heart: ", description="", color=colour)
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

            embed.set_footer(text="Use `/add_date` to add new entries.")

            message = await channel.send(embed=embed)

            async with aiosqlite.connect(db_path) as conn:
                await conn.execute('''
                    INSERT INTO dates (guild_id, type, value)
                    VALUES (?, 'channel', ?)
                    ON CONFLICT(guild_id, type) DO UPDATE SET value=excluded.value
                ''', (interaction.guild.id, channel.id))
                await conn.execute('''
                    INSERT INTO dates (guild_id, type, value)
                    VALUES (?, 'message_id', ?)
                    ON CONFLICT(guild_id, type) DO UPDATE SET value=excluded.value
                ''', (interaction.guild.id, message.id))
                await conn.commit()

            await interaction.response.send_message(f"Success: Dates will now be shown in {channel.mention}.", ephemeral=True)

        except Exception as e:
            logger.error(f"Failed to set dates channel: {e}")
            await interaction.response.send_message("Error: Failed to configure date channel.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="add_date", description="User: Add a new important date with a title and date.")
    async def add_date(self, interaction: discord.Interaction, title: str, date: str):
        try:
            try:
                parsed_date = datetime.strptime(date, "%d/%m/%Y")
                formatted = parsed_date.strftime("%d/%m/%Y")
            except ValueError:
                await interaction.response.send_message("Error: Please provide a valid date in DD/MM/YYYY format.",
                                                        ephemeral=True)
                return

            async with aiosqlite.connect(db_path) as conn:
                cursor = await conn.execute('SELECT value FROM dates WHERE guild_id = ? AND type = ?',
                                            (interaction.guild.id, 'channel'))
                channel_row = await cursor.fetchone()
                cursor = await conn.execute('SELECT value FROM dates WHERE guild_id = ? AND type = ?',
                                            (interaction.guild.id, 'message_id'))
                message_row = await cursor.fetchone()

                if not channel_row or not message_row:
                    await interaction.response.send_message(
                        "Error: Dates channel not configured. Use `/set_dates_channel`.", ephemeral=True)
                    return

                channel = self.bot.get_channel(int(channel_row[0]))
                message = await channel.fetch_message(int(message_row[0]))
                embed = message.embeds[0] if message.embeds else discord.Embed(title="Our Special Dates ❤️")

                # Parse existing entries
                entries = []
                if embed.description and embed.description != "No dates added yet.":
                    for line in embed.description.strip().split("\n"):
                        if "–" in line:
                            title_part, date_part = line.strip().split("–")
                            title_part = title_part.strip(" *")
                            date_part = date_part.strip()
                            try:
                                dt = datetime.strptime(date_part, "%d/%m/%Y")
                                entries.append((dt, title_part))
                            except Exception as e:
                                logger.warning(f"Skipping malformed date line: {line} – {e}")

                # Add new entry and sort
                entries.append((parsed_date, title))
                entries.sort(key=lambda x: x[0])  # Earliest first

                embed.description = self.build_date_description(entries)
                embed.set_thumbnail(url=self.bot.user.display_avatar.url)

                await message.edit(embed=embed)
                await interaction.response.send_message(f"Success: `{title}` on {formatted} added.", ephemeral=True)

        except Exception as e:
            logger.error(f"Failed to add date: {e}")
            await interaction.response.send_message("Error: Failed to add the date.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="remove_date", description="User: Remove a date manually by editing the embed.")
    async def remove_date(self, interaction: discord.Interaction, index: int):
        try:
            async with aiosqlite.connect(db_path) as conn:
                cursor = await conn.execute('SELECT value FROM dates WHERE guild_id = ? AND type = ?', (interaction.guild.id, 'channel'))
                channel_row = await cursor.fetchone()
                cursor = await conn.execute('SELECT value FROM dates WHERE guild_id = ? AND type = ?', (interaction.guild.id, 'message_id'))
                message_row = await cursor.fetchone()

                if not channel_row or not message_row:
                    await interaction.response.send_message("Error: Dates channel not configured.", ephemeral=True)
                    return

                channel = self.bot.get_channel(int(channel_row[0]))
                message = await channel.fetch_message(int(message_row[0]))

                embed = message.embeds[0]
                entries = embed.description.strip().split('\n')

                if index < 1 or index > len(entries):
                    await interaction.response.send_message("Error: Invalid index.", ephemeral=True)
                    return

                removed = entries.pop(index - 1)
                embed.description = '\n'.join(entries) if entries else "No dates added yet."
                await message.edit(embed=embed)

                await interaction.response.send_message(f"Success: Removed entry:\n{removed}", ephemeral=True)

        except Exception as e:
            logger.error(f"Failed to remove date: {e}")
            await interaction.response.send_message("Error: Failed to remove the date.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)
# ------------------------------------------------------------------------------------------------------------------

    @app_commands.command(name="edit_date", description="User: Edit a previously added date entry.")
    @app_commands.describe(index="The position number of the entry (starting at 1)",
                           new_title="Optional new title for the entry",
                           new_date="Optional new date in DD/MM/YYYY")
    async def edit_date(self, interaction: discord.Interaction, index: int, new_title: str = None, new_date: str = None):
        try:
            if not new_title and not new_date:
                await interaction.response.send_message("Error: You must provide at least a new title or a new date.",
                                                        ephemeral=True)
                return

            if new_date:
                try:
                    parsed_new_date = datetime.strptime(new_date, "%d/%m/%Y")
                except ValueError:
                    await interaction.response.send_message("Error: Invalid date format. Use DD/MM/YYYY.", ephemeral=True)
                    return

            async with aiosqlite.connect(db_path) as conn:
                cursor = await conn.execute('SELECT value FROM dates WHERE guild_id = ? AND type = ?', (interaction.guild.id, 'channel'))
                channel_row = await cursor.fetchone()
                cursor = await conn.execute('SELECT value FROM dates WHERE guild_id = ? AND type = ?', (interaction.guild.id, 'message_id'))
                message_row = await cursor.fetchone()

                if not channel_row or not message_row:
                    await interaction.response.send_message("Error: Dates channel not configured.", ephemeral=True)
                    return

                channel = self.bot.get_channel(int(channel_row[0]))
                message = await channel.fetch_message(int(message_row[0]))

                embed = message.embeds[0]
                lines = embed.description.strip().split("\n")

                # Extract valid entries
                raw_entries = []
                for line in lines:
                    if "–" in line:
                        try:
                            title_part, date_part = line.strip().split("–")
                            title_part = title_part.strip(" *")
                            date_part = date_part.strip()
                            dt = datetime.strptime(date_part, "%d/%m/%Y")
                            raw_entries.append((dt, title_part))
                        except Exception as e:
                            logger.warning(f"Skipping line during edit parse: {line} – {e}")

                if index < 1 or index > len(raw_entries):
                    await interaction.response.send_message("Error: Invalid index.", ephemeral=True)
                    return

                # Update the entry
                old_date, old_title = raw_entries[index - 1]
                updated_date = parsed_new_date if new_date else old_date
                updated_title = new_title if new_title else old_title
                raw_entries[index - 1] = (updated_date, updated_title)

                # Sort and rebuild
                raw_entries.sort(key=lambda x: x[0])
                embed.description = self.build_date_description(raw_entries)
                await message.edit(embed=embed)

                await interaction.response.send_message(f"Success: Entry {index} has been updated.", ephemeral=True)

        except Exception as e:
            logger.error(f"Failed to edit date: {e}")
            await interaction.response.send_message("Error: Failed to update the date.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

# ------------------------------------------------------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS dates (
                guild_id INTEGER,
                type TEXT,
                value TEXT,
                PRIMARY KEY (guild_id, type)
            )
        ''')
        await conn.commit()
    await bot.add_cog(ImportantDatesCog(bot))
