
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
# Bedroom View
# ---------------------------------------------------------------------------------------------------------------------
class BedroomListView(discord.ui.View):
    def __init__(self, pages, bot=None):
        super().__init__(timeout=None)
        self.pages = pages
        self.current_page = 0
        self.bot = bot

    async def update(self, interaction):
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update(interaction)

    @discord.ui.button(label="Home", style=discord.ButtonStyle.primary)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        await self.update(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            await self.update(interaction)

    @discord.ui.button(label="Complete", style=discord.ButtonStyle.success)
    async def complete(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Get the current channel from the message
        channel = interaction.channel

        # Create a dropdown with incomplete items
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute('''
                SELECT item_index, content
                FROM bedroom_items
                WHERE guild_id = ? AND channel_name = ? AND checked = 0
                ORDER BY item_index
            ''', (interaction.guild.id, channel.name))
            rows = await cursor.fetchall()

        if not rows:
            await interaction.response.send_message("No incomplete items found!", ephemeral=True)
            return

        # Create the dropdown options
        options = [
            discord.SelectOption(
                label=f"{index + 1}. {content[:95]}",
                value=str(index),
                description=content[:100] if len(content) > 100 else None
            )
            for index, content in rows
        ]

        # Create the dropdown view
        class CompleteDropdown(discord.ui.View):
            def __init__(self, parent_view, channel):
                super().__init__()
                self.parent_view = parent_view
                self.channel = channel

                # Add the dropdown
                self.dropdown = discord.ui.Select(
                    placeholder="Select an item to mark as complete",
                    options=options[:25]  # Discord limits to 25 options
                )
                self.dropdown.callback = self.on_dropdown_select
                self.add_item(self.dropdown)

            async def on_dropdown_select(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True)  # Acknowledge the interaction first
                selected_index = int(self.dropdown.values[0])

                try:
                    # Update the database
                    async with aiosqlite.connect(DB_PATH) as conn:
                        await conn.execute('''
                            UPDATE bedroom_items
                            SET checked = 1
                            WHERE guild_id = ? AND channel_name = ? AND item_index = ?
                        ''', (interaction.guild.id, self.channel.name, selected_index))
                        await conn.commit()

                    # Refresh the embed
                    await self.parent_view.refresh_embed(interaction, self.channel)

                    await interaction.followup.send(
                        f"Marked item {selected_index + 1} as complete!",
                        ephemeral=True
                    )

                except Exception as e:
                    logger.error(f"Error in dropdown select: {e}")
                    await interaction.followup.send("An error occurred while marking the item as complete.",
                                                    ephemeral=True)

        # Send the dropdown
        await interaction.response.send_message(
            "Select an item to mark as complete:",
            view=CompleteDropdown(self, channel),
            ephemeral=True
        )

    async def refresh_embed(self, interaction: discord.Interaction, channel: discord.TextChannel):
        try:
            # Recreate the embed with updated items
            async with aiosqlite.connect(DB_PATH) as conn:
                cursor = await conn.execute('''
                    SELECT content, checked FROM bedroom_items
                    WHERE guild_id = ? AND channel_name = ?
                    ORDER BY item_index
                ''', (interaction.guild.id, channel.name))
                rows = await cursor.fetchall()

            lines = [f"{'✅' if checked else '⬜'} {content}" for content, checked in rows]
            title_map = {
                "topic-list": "Topics",
                "watch-list": "Watch List",
                "fuck-it-list": "Fuckit List",
                "to-do-list": "To-Do List"
            }
            title = title_map.get(channel.name, "📋 Your List")

            pages = []
            buffer = ""
            for line in lines:
                if len(buffer) + len(line) + 1 > 1024:
                    embed_page = discord.Embed(title=title, description=buffer.strip(), color=discord.Color.purple())
                    embed_page.set_thumbnail(url=self.bot.user.display_avatar.url)
                    pages.append(embed_page)
                    buffer = line + "\n"
                else:
                    buffer += line + "\n"

            if buffer:
                embed_page = discord.Embed(title=title, description=buffer.strip(), color=discord.Color.purple())
                embed_page.set_thumbnail(url=self.bot.user.display_avatar.url)
                pages.append(embed_page)

            # Update the view's pages
            self.pages = pages
            self.current_page = min(self.current_page, len(pages) - 1)

            # Get the original message ID from the database
            async with aiosqlite.connect(DB_PATH) as conn:
                cursor = await conn.execute('''
                    SELECT message_id FROM bedroom_lists
                    WHERE guild_id = ? AND channel_name = ?
                ''', (interaction.guild.id, channel.name))
                row = await cursor.fetchone()

            if not row:
                await interaction.followup.send("Error: Could not find list message in database.", ephemeral=True)
                return

            try:
                # Edit the original message
                message = await channel.fetch_message(int(row[0]))
                await message.edit(embed=pages[self.current_page], view=self)
            except discord.NotFound:
                await interaction.followup.send("Error: The list message could not be found.", ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send("Error: I don't have permission to edit the list message.",
                                                ephemeral=True)

        except Exception as e:
            logger.error(f"Error in refresh_embed: {e}")
            await interaction.followup.send("An error occurred while updating the list.", ephemeral=True)


# ---------------------------------------------------------------------------------------------------------------------
# List Class
# ---------------------------------------------------------------------------------------------------------------------
class ListsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        await self.restore_views()

    async def owner_check(self, interaction: discord.Interaction):
        return interaction.user.id == 111941993629806592

    async def refresh_bedroom_embed(self, interaction: discord.Interaction, channel_obj: discord.TextChannel):
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute('''
                SELECT message_id FROM bedroom_lists
                WHERE guild_id = ? AND channel_name = ?
            ''', (interaction.guild.id, channel_obj.name))
            row = await cursor.fetchone()

            if not row:
                return

            cursor = await conn.execute('''
                SELECT content, checked FROM bedroom_items
                WHERE guild_id = ? AND channel_name = ?
                ORDER BY item_index
            ''', (interaction.guild.id, channel_obj.name))
            rows = await cursor.fetchall()

        lines = [f"{'✅' if checked else '⬜'} {content}" for content, checked in rows]

        title_map = {
            "topic-list": "Topics",
            "watch-list": "Watch List",
            "fuck-it-list": "Fuckit List",
            "to-do-list": "To-Do List"
        }

        title = title_map.get(channel_obj.name, "📋 Your List")

        pages = []
        buffer = ""
        for line in lines:
            if len(buffer) + len(line) + 1 > 1024:
                embed_page = discord.Embed(title=title, description=buffer.strip(), color=discord.Color.purple())
                embed_page.set_thumbnail(url=self.bot.user.display_avatar.url)
                pages.append(embed_page)
                buffer = line + "\n"
            else:
                buffer += line + "\n"

        if buffer:
            embed_page = discord.Embed(title=title, description=buffer.strip(), color=discord.Color.purple())
            embed_page.set_thumbnail(url=self.bot.user.display_avatar.url)
            pages.append(embed_page)

        embed_msg = await channel_obj.fetch_message(int(row[0]))
        await embed_msg.edit(embed=pages[0], view=BedroomListView(pages))

    async def restore_views(self):
        await self.bot.wait_until_ready()  # Wait until the bot is fully loaded
        logger.info("Restoring list views...")

        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute('''
                SELECT guild_id, channel_name, message_id FROM bedroom_lists
            ''')
            rows = await cursor.fetchall()

        for guild_id, channel_name, message_id in rows:
            try:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue

                channel = discord.utils.get(guild.text_channels, name=channel_name)
                if not channel:
                    continue

                try:
                    message = await channel.fetch_message(message_id)
                except discord.NotFound:
                    logger.warning(f"Message {message_id} not found in channel {channel_name} (guild {guild_id})")
                    continue

                # Recreate the view with current data
                async with aiosqlite.connect(DB_PATH) as conn:
                    cursor = await conn.execute('''
                        SELECT content, checked FROM bedroom_items
                        WHERE guild_id = ? AND channel_name = ?
                        ORDER BY item_index
                    ''', (guild_id, channel_name))
                    rows = await cursor.fetchall()

                lines = [f"{'✅' if checked else '⬜'} {content}" for content, checked in rows]
                title_map = {
                    "topic-list": "Topics",
                    "watch-list": "Watch List",
                    "fuck-it-list": "Fuckit List",
                    "to-do-list": "To-Do List"
                }
                title = title_map.get(channel_name, "📋 Your List")

                pages = []
                buffer = ""
                for line in lines:
                    if len(buffer) + len(line) + 1 > 1024:
                        embed_page = discord.Embed(title=title, description=buffer.strip(),
                                                   color=discord.Color.purple())
                        embed_page.set_thumbnail(url=self.bot.user.display_avatar.url)
                        pages.append(embed_page)
                        buffer = line + "\n"
                    else:
                        buffer += line + "\n"

                if buffer:
                    embed_page = discord.Embed(title=title, description=buffer.strip(), color=discord.Color.purple())
                    embed_page.set_thumbnail(url=self.bot.user.display_avatar.url)
                    pages.append(embed_page)

                # Handle empty lists
                if not pages:
                    empty_embed = discord.Embed(
                        title=title,
                        description="No items in this list yet!",
                        color=discord.Color.purple()
                    )
                    empty_embed.set_thumbnail(url=self.bot.user.display_avatar.url)
                    pages.append(empty_embed)

                view = BedroomListView(pages, self.bot)
                await message.edit(embed=pages[0], view=view)
                logger.info(f"Restored view for message {message_id} in channel {channel_name} (guild {guild_id})")

            except Exception as e:
                logger.error(f"Error restoring view for message {message_id} in channel {channel_name}: {e}")
    # ---------------------------------------------------------------------------------------------------------------------
    async def autocomplete_channel(self, interaction: discord.Interaction, current: str):
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute('''
                SELECT DISTINCT channel_id FROM bedroom_lists
                WHERE guild_id = ?
            ''', (interaction.guild.id,))
            rows = await cursor.fetchall()

        valid_ids = [int(r[0]) for r in rows if r[0]]

        channels = [
            c for c in interaction.guild.text_channels
            if c.id in valid_ids and current.lower() in c.name.lower()
        ]

        return [
                   app_commands.Choice(name=c.name, value=str(c.id))
                   for c in channels
               ][:25]

    # ---------------------------------------------------------------------------------------------------------------------
    async def autocomplete_item(self, interaction: discord.Interaction, current: str):
        # Get the selected channel from the form (stringified channel ID)
        channel_id = interaction.namespace.channel
        if not channel_id:
            return []

        channel = interaction.guild.get_channel(int(channel_id))
        if not channel:
            return []

        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute('''
                SELECT item_index, content
                FROM bedroom_items
                WHERE guild_id = ? AND channel_name = ? AND checked = 0
                ORDER BY item_index
            ''', (interaction.guild.id, channel.name))
            rows = await cursor.fetchall()

        return [
                   app_commands.Choice(
                       name=f"{index + 1}. ⬜ {content[:80]}",
                       value=f"{index + 1}. ⬜ {content[:100]}"
                   )
                   for index, content in rows
                   if current.lower() in content.lower()
               ][:25]

    # ---------------------------------------------------------------------------------------------------------------------
    async def autocomplete_checked_item(self, interaction: discord.Interaction, current: str):
        channel_id = interaction.namespace.channel
        if not channel_id:
            return []

        channel = interaction.guild.get_channel(int(channel_id))
        if not channel:
            return []

        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute('''
                SELECT item_index, content
                FROM bedroom_items
                WHERE guild_id = ? AND channel_name = ? AND checked = 1
                ORDER BY item_index
            ''', (interaction.guild.id, channel.name))
            rows = await cursor.fetchall()

        return [
                   app_commands.Choice(
                       name=f"{index + 1}. ✅ {content[:80]}",
                       value=f"{index + 1}. ✅ {content[:100]}"
                   )
                   for index, content in rows
                   if current.lower() in content.lower()
               ][:25]

    # ---------------------------------------------------------------------------------------------------------------------
    # Listeners
    # ---------------------------------------------------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute('''
                SELECT message_id FROM bedroom_lists
                WHERE guild_id = ? AND channel_name = ?
            ''', (message.guild.id, message.channel.name))
            row = await cursor.fetchone()

            if not row:
                return

            clean = message.content.strip()
            if not clean:
                return

            # Store in DB
            await conn.execute('''
                INSERT INTO bedroom_items (guild_id, channel_name, item_index, content)
                VALUES (?, ?, (SELECT COUNT(*) FROM bedroom_items WHERE guild_id = ? AND channel_name = ?), ?)
            ''', (message.guild.id, message.channel.name, message.guild.id, message.channel.name, clean))
            await conn.commit()

            # Fetch all items
            cursor = await conn.execute('''
                SELECT content, checked FROM bedroom_items
                WHERE guild_id = ? AND channel_name = ?
                ORDER BY item_index
            ''', (message.guild.id, message.channel.name))
            rows = await cursor.fetchall()

            lines = [f"{'✅' if checked else '⬜'} {content}" for content, checked in rows]

            title_map = {
                "topic-list": "Topics",
                "watch-list": "Watch List",
                "fuck-it-list": "Fuckit List",
                "to-do-list": "To-Do List"
            }

            title = title_map.get(message.channel.name, "📋 Your List")

            pages = []
            buffer = ""
            for line in lines:
                if len(buffer) + len(line) + 1 > 1024:
                    embed_page = discord.Embed(title=title, description=buffer.strip(), color=discord.Color.purple())
                    embed_page.set_thumbnail(url=self.bot.user.display_avatar.url)
                    pages.append(embed_page)
                    buffer = line + "\n"
                else:
                    buffer += line + "\n"

            if buffer:
                embed_page = discord.Embed(title=title, description=buffer.strip(), color=discord.Color.purple())
                embed_page.set_thumbnail(url=self.bot.user.display_avatar.url)
                pages.append(embed_page)

            embed_msg = await message.channel.fetch_message(int(row[0]))
            view = BedroomListView(pages, self.bot)
            await embed_msg.edit(embed=pages[0], view=view)

            try:
                await message.delete()
            except discord.Forbidden:
                pass


    # ---------------------------------------------------------------------------------------------------------------------
    # List Commands
    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="check_item", description="Mark an item as completed in a bedroom list.")
    @app_commands.autocomplete(channel=autocomplete_channel, item=autocomplete_item)
    @app_commands.describe(channel="The bedroom channel", item="Pick an item to check off")
    async def check_item(self, interaction: discord.Interaction, channel: str, item: str):
        try:
            channel_obj = interaction.guild.get_channel(int(channel))
            if not channel_obj:
                await interaction.response.send_message("Error: Channel not found.", ephemeral=True)
                return

            async with aiosqlite.connect(DB_PATH) as conn:
                index_match = re.match(r'^(\d+)\.', item)
                if not index_match:
                    await interaction.response.send_message("Error: Could not extract index from selection.",
                                                            ephemeral=True)
                    return
                item_index = int(index_match.group(1)) - 1

                await conn.execute('''
                    UPDATE bedroom_items
                    SET checked = 1
                    WHERE guild_id = ? AND channel_name = ? AND item_index = ?
                ''', (interaction.guild.id, channel_obj.name, item_index))
                await conn.commit()

                cursor = await conn.execute('''
                    SELECT message_id FROM bedroom_lists
                    WHERE guild_id = ? AND channel_name = ?
                ''', (interaction.guild.id, channel_obj.name))
                row = await cursor.fetchone()
                if not row:
                    await interaction.response.send_message("Error: Embed not found.", ephemeral=True)
                    return

                cursor = await conn.execute('''
                    SELECT content, checked FROM bedroom_items
                    WHERE guild_id = ? AND channel_name = ?
                    ORDER BY item_index
                ''', (interaction.guild.id, channel_obj.name))
                rows = await cursor.fetchall()

            lines = [f"{'✅' if checked else '⬜'} {content}" for content, checked in rows]
            title_map = {"topic-list": "Topics", "watch-list": "Watch List", "fuck-it-list": "Fuckit List"}
            title = title_map.get(channel_obj.name, "📋 Your List")

            pages = []
            buffer = ""
            for line in lines:
                if len(buffer) + len(line) + 1 > 1024:
                    embed_page = discord.Embed(title=title, description=buffer.strip(), color=discord.Color.purple())
                    embed_page.set_thumbnail(url=self.bot.user.display_avatar.url)
                    pages.append(embed_page)
                    buffer = line + "\n"
                else:
                    buffer += line + "\n"

            if buffer:
                embed_page = discord.Embed(title=title, description=buffer.strip(), color=discord.Color.purple())
                embed_page.set_thumbnail(url=self.bot.user.display_avatar.url)
                pages.append(embed_page)

            embed_msg = await channel_obj.fetch_message(int(row[0]))
            view = BedroomListView(pages, self.bot)
            await embed_msg.edit(embed=pages[0], view=view)

            await interaction.response.send_message(
                f"Marked item {item_index + 1} as complete in {channel_obj.mention}.", ephemeral=True)

        except Exception as e:
            logger.error(f"Error in /check_item: {e}")
            await interaction.response.send_message("Error: Could not check item.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="uncheck_item", description="Mark a completed item as incomplete.")
    @app_commands.autocomplete(channel=autocomplete_channel, item=autocomplete_checked_item)
    @app_commands.describe(channel="The bedroom channel", item="Pick a completed item to uncheck")
    async def uncheck_item(self, interaction: discord.Interaction, channel: str, item: str):
        try:
            channel_obj = interaction.guild.get_channel(int(channel))
            if not channel_obj:
                await interaction.response.send_message("Error: Channel not found.", ephemeral=True)
                return

            async with aiosqlite.connect(DB_PATH) as conn:
                index_match = re.match(r'^(\d+)\.', item)
                if not index_match:
                    await interaction.response.send_message("Error: Could not extract index from selection.",
                                                            ephemeral=True)
                    return

                item_index = int(index_match.group(1)) - 1

                await conn.execute('''
                    UPDATE bedroom_items
                    SET checked = 0
                    WHERE guild_id = ? AND channel_name = ? AND item_index = ?
                ''', (interaction.guild.id, channel_obj.name, item_index))
                await conn.commit()

            await self.refresh_bedroom_embed(interaction, channel_obj)
            await interaction.response.send_message(f"Unchecked item {item_index + 1} in {channel_obj.mention}.",
                                                    ephemeral=True)

        except Exception as e:
            logger.error(f"Error in /uncheck_item: {e}")
            await interaction.response.send_message("Error: Could not uncheck item.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="remove_item", description="Remove an item from the bedroom list.")
    @app_commands.autocomplete(channel=autocomplete_channel, item=autocomplete_item)
    @app_commands.describe(channel="The bedroom channel", item="Pick an item to remove")
    async def remove_item(self, interaction: discord.Interaction, channel: str, item: str):
        try:
            channel_obj = interaction.guild.get_channel(int(channel))
            if not channel_obj:
                await interaction.response.send_message("Error: Channel not found.", ephemeral=True)
                return

            async with aiosqlite.connect(DB_PATH) as conn:
                index_match = re.match(r'^(\d+)\.', item)
                if not index_match:
                    await interaction.response.send_message("Error: Could not extract index from selection.",
                                                            ephemeral=True)
                    return

                item_index = int(index_match.group(1)) - 1

                await conn.execute('''
                    DELETE FROM bedroom_items
                    WHERE guild_id = ? AND channel_name = ? AND item_index = ?
                ''', (interaction.guild.id, channel_obj.name, item_index))

                await conn.execute('''
                    UPDATE bedroom_items
                    SET item_index = item_index - 1
                    WHERE guild_id = ? AND channel_name = ? AND item_index > ?
                ''', (interaction.guild.id, channel_obj.name, item_index))

                await conn.commit()

            await self.refresh_bedroom_embed(interaction, channel_obj)
            await interaction.response.send_message(f"Removed item {item_index + 1} from {channel_obj.mention}.",
                                                    ephemeral=True)

        except Exception as e:
            logger.error(f"Error in /remove_item: {e}")
            await interaction.response.send_message("Error: Could not remove item.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="edit_item", description="Edit the content of an item in the bedroom list.")
    @app_commands.autocomplete(channel=autocomplete_channel, item=autocomplete_item)
    @app_commands.describe(channel="The bedroom channel", item="Item to edit", new_text="The new content")
    async def edit_item(self, interaction: discord.Interaction, channel: str, item: str, new_text: str):
        try:
            channel_obj = interaction.guild.get_channel(int(channel))
            if not channel_obj:
                await interaction.response.send_message("Error: Channel not found.", ephemeral=True)
                return

            async with aiosqlite.connect(DB_PATH) as conn:
                index_match = re.match(r'^(\d+)\.', item)
                if not index_match:
                    await interaction.response.send_message("Error: Could not extract index from selection.",
                                                            ephemeral=True)
                    return

                item_index = int(index_match.group(1)) - 1

                await conn.execute('''
                    UPDATE bedroom_items
                    SET content = ?
                    WHERE guild_id = ? AND channel_name = ? AND item_index = ?
                ''', (new_text.strip(), interaction.guild.id, channel_obj.name, item_index))
                await conn.commit()

            await self.refresh_bedroom_embed(interaction, channel_obj)
            await interaction.response.send_message(f"Updated item {item_index + 1} in {channel_obj.mention}.",
                                                    ephemeral=True)

        except Exception as e:
            logger.error(f"Error in /edit_item: {e}")
            await interaction.response.send_message("Error: Could not edit item.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)


# ---------------------------------------------------------------------------------------------------------------------
# Setup Function
# ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    await bot.add_cog(ListsCog(bot))
