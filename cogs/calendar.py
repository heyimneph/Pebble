import logging
import discord
import aiosqlite
import calendar
import os
import io
import pytz
import textwrap

from datetime import datetime, timedelta, time
from discord.ext import commands, tasks
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont

from core.utils import get_embed_colour, log_command_usage

BST = pytz.timezone("Europe/London")

# ---------------------------------------------------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------------------------------------------------
os.makedirs('./data/databases', exist_ok=True)
db_path = './data/databases/pebble.db'

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------------------------------
# Calendar View
# ---------------------------------------------------------------------------------------------------------------------
class CalendarNavigationView(discord.ui.View):
    def __init__(self, cog, guild_id, month, year):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        now = datetime.now()
        self.month = month if month > 0 else now.month
        self.year = year if year > 0 else now.year

    async def update(self, interaction):
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    async def update_message(self, interaction):
        # Fetch fresh event data directly from the DB
        image = await self.cog.generate_calendar_image(self.guild_id, self.month, self.year)
        file = discord.File(fp=image, filename="calendar.png")  # 'image' is now a buffer

        # Now the embed and image should reflect the actual events from the table
        embed = discord.Embed(
            title=f"📆 {datetime(self.year, self.month, 1).strftime('%B')} Calendar",
            description="Here's this month's page with today's events!",
            color=await get_embed_colour(self.guild_id)
        )
        embed.set_image(url="attachment://calendar.png")
        await interaction.message.edit(embed=embed, attachments=[file], view=self)

    @discord.ui.button(label="⬅️ Prev.", style=discord.ButtonStyle.secondary, custom_id="calendar_prev")
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.month -= 1
        if self.month == 0:
            self.month = 12
        await self.update_message(interaction)
        await interaction.response.defer()

    @discord.ui.button(label="🗓️ Current", style=discord.ButtonStyle.primary, custom_id="calendar_current")
    async def current(self, interaction: discord.Interaction, button: discord.ui.Button):
        now = datetime.now()
        self.month = now.month
        self.year = now.year
        await self.update_message(interaction)
        await interaction.response.defer()

    @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.secondary, custom_id="calendar_next")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.month += 1
        if self.month == 13:
            self.month = 1
        await self.update_message(interaction)
        await interaction.response.defer()

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.success, custom_id="calendar_refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_message(interaction)
        await interaction.response.defer()

# ---------------------------------------------------------------------------------------------------------------------
# Calendar Class
# ---------------------------------------------------------------------------------------------------------------------
class CalendarCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @commands.Cog.listener()
    async def on_ready(self):
        await self.restore_calendar_views()

        if not self.cleanup_calendar_images.is_running():
            self.cleanup_calendar_images.start()

        if not self.calendar_loop.is_running():
            self.calendar_loop.start()



    def cog_unload(self):
        self.calendar_loop.cancel()

# ---------------------------------------------------------------------------------------------------------------------
# Calendar Loops
# ---------------------------------------------------------------------------------------------------------------------
    @tasks.loop(hours=1)
    async def cleanup_calendar_images(self):
        folder = "./data"
        now = datetime.now().timestamp()

        for filename in os.listdir(folder):
            if filename.startswith("calendar_") and filename.endswith(".png"):
                full_path = os.path.join(folder, filename)
                try:
                    # Delete if older than 2 hours
                    if os.path.getmtime(full_path) < now - 60 * 60 * 2:
                        os.remove(full_path)
                except Exception as e:
                    logger.warning(f"Failed to delete {filename}: {e}")

    @tasks.loop(minutes=1)
    async def calendar_loop(self):
        now_bst = datetime.now(BST)
        if not (now_bst.hour == 0 and now_bst.minute == 0):
            return
        async with aiosqlite.connect(db_path) as db:
            rows = await db.execute_fetchall("""
                    SELECT guild_id, channel_id, message_id, month, year
                    FROM calendar_views
                """)

        for guild_id, channel_id, message_id, month, year in rows:
            guild = self.bot.get_guild(guild_id)
            channel = guild and guild.get_channel(channel_id)
            if not channel:
                continue

            try:
                message = await channel.fetch_message(message_id)
                buf = await self.generate_calendar_image(guild_id, month, year)
                file = discord.File(fp=buf, filename="calendar.png")

                embed = discord.Embed(
                    title=f"📆 {datetime(year, month, 1).strftime('%B')} Calendar",
                    description="Here's this month's page with today's events!",
                    color=await get_embed_colour(guild_id)
                )
                embed.set_image(url="attachment://calendar.png")

                view = CalendarNavigationView(self, guild_id, month, year)
                await message.edit(embed=embed, attachments=[file], view=view)
            except Exception as e:
                logger.warning(f"[CalendarCog.calendar_loop] guild={guild_id} failed: {e}")

    @calendar_loop.before_loop
    async def before_calendar_loop(self):
        await self.bot.wait_until_ready()
    # ---------------------------------------------------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------------------------------------------------
    async def restore_calendar_views(self):
        try:
            async with aiosqlite.connect(db_path) as db:
                cursor = await db.execute("SELECT guild_id, channel_id, message_id, month, year FROM calendar_views")
                rows = await cursor.fetchall()

            for guild_id, channel_id, message_id, month, year in rows:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue
                channel = guild.get_channel(channel_id)
                if not channel:
                    continue
                try:
                    message = await channel.fetch_message(message_id)
                    # Generate a fresh calendar image using current entries
                    image = await self.generate_calendar_image(guild_id, month, year)
                    file = discord.File(fp=image, filename="calendar.png")  # 'image' is now a buffer

                    embed = discord.Embed(
                        title=f"📆 {datetime(year, month, 1).strftime('%B')} Calendar",
                        description="Here's this month's page with today's events!",
                        color=await get_embed_colour(guild_id)
                    )
                    embed.set_image(url="attachment://calendar.png")

                    await message.edit(embed=embed, attachments=[file],
                                       view=CalendarNavigationView(self, guild_id, month, year))

                except Exception as e:
                    logger.warning(f"Failed to restore calendar view for {guild_id}: {e}")

        except Exception as e:
            logger.error(f"Error in restoring calendar views: {e}")

    async def autocomplete_calendar_title(self, interaction: discord.Interaction, current: str):
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("""
                SELECT DISTINCT title FROM calendar_entries
                WHERE guild_id = ? AND title LIKE ?
                LIMIT 25
            """, (interaction.guild.id, f"%{current}%"))
            rows = await cursor.fetchall()

        return [
            app_commands.Choice(name=title[0], value=title[0])
            for title in rows
        ]

    async def generate_calendar_image(self, guild_id, month, year):
        # ─── Configuration ────────────────────────────────────────────────────────
        TITLE_FONT_SIZE = 56
        WEEKDAY_FONT_SIZE = 20
        DATE_FONT_SIZE = 13
        EVENT_FONT_SIZE = 16
        CHALK_FONT_SIZE = 28
        FOOTER_FONT_SIZE = 24
        HEADER_HEIGHT = 120
        FOOTER_HEIGHT = 60
        GUTTER = 10
        PADDING_X = 40
        CHALKBOARD_WIDTH = 230

        width, height = 1000, 600
        image = Image.new('RGB', (width, height), '#fefefe')
        draw = ImageDraw.Draw(image)

        # ─── Load fonts ─────────────────────────────────────────────────────────
        base = os.path.dirname(os.path.abspath(__file__))
        fp = os.path.join(base, "..", "fonts", "PatrickHand-Regular.ttf")
        try:
            title_fnt = ImageFont.truetype(fp, TITLE_FONT_SIZE)
            weekday_fnt = ImageFont.truetype(fp, WEEKDAY_FONT_SIZE)
            date_fnt = ImageFont.truetype(fp, DATE_FONT_SIZE)
            event_fnt = ImageFont.truetype(fp, EVENT_FONT_SIZE)
            chalk_fnt = ImageFont.truetype(fp, CHALK_FONT_SIZE)
            footer_fnt = ImageFont.truetype(fp, FOOTER_FONT_SIZE)
        except OSError:
            title_fnt = weekday_fnt = date_fnt = event_fnt = chalk_fnt = footer_fnt = ImageFont.load_default()

        # ─── Header ─────────────────────────────────────────────────────────────
        draw.rectangle([0, 0, width, HEADER_HEIGHT], fill="#fef3c7")
        title = datetime(year, month, 1).strftime('%B %Y')
        tw = draw.textlength(title, font=title_fnt)
        draw.text((width // 2 - tw // 2, 20), title, fill="black", font=title_fnt)
        tb = draw.textbbox((0, 0), title, font=title_fnt)
        th = tb[3] - tb[1]
        draw.text((width // 2 - 10, 20 + th + 5), "💖", font=weekday_fnt, fill="black")

        # ─── Load events ─────────────────────────────────────────────────────────
        async with aiosqlite.connect(db_path) as db:
            c = await db.execute("""
                SELECT title, date, emoji FROM calendar_entries
                WHERE guild_id = ? AND title IS NOT NULL AND date IS NOT NULL
            """, (guild_id,))
            rows = await c.fetchall()
        events = []
        for t, ds, e in rows:
            try:
                dt = datetime.strptime(ds, "%d/%m/%Y")
                if dt.month == month and dt.year == year:
                    events.append((dt, t, e))
            except ValueError:
                continue
        today = datetime.now().date()
        today_events = [(d, t, e) for d, t, e in events if d.date() == today]

        # ─── Geometry ────────────────────────────────────────────────────────────
        cols = 7
        avail_w = width - PADDING_X - CHALKBOARD_WIDTH - 20
        box_w = (avail_w - GUTTER * (cols - 1)) // cols

        lb = draw.textbbox((0, 0), calendar.day_name[0], font=weekday_fnt)
        lh = lb[3] - lb[1]

        LABEL_Y = HEADER_HEIGHT + 5
        pad_y = LABEL_Y + lh + 10
        rows_cnt = 6
        box_h = (height - pad_y - FOOTER_HEIGHT - GUTTER * (rows_cnt - 1)) // rows_cnt

        sx, sy = PADDING_X, pad_y

        # ─── Weekday labels ───────────────────────────────────────────────────────
        for i, wd in enumerate(calendar.day_name):
            lw = draw.textlength(wd, font=weekday_fnt)
            x = sx + i * (box_w + GUTTER) + (box_w - lw) / 2
            draw.text((x, LABEL_Y), wd, fill="black", font=weekday_fnt)

        # ─── Previous‐month fill ──────────────────────────────────────────────────
        first_wd = datetime(year, month, 1).weekday()
        pm = month - 1 or 12
        py = year - (1 if month == 1 else 0)
        _, pdays = calendar.monthrange(py, pm)
        for i in range(first_wd):
            x = sx + i * (box_w + GUTTER)
            y = sy
            draw.rounded_rectangle([x, y, x + box_w, y + box_h],
                                   radius=12, fill="#f0f0f0", outline="lightgray", width=1)
            dn = pdays - (first_wd - 1 - i)
            draw.text((x + 5, y + 5), str(dn), font=date_fnt, fill="darkgray")

        # ─── Helper for wrapping/truncation ───────────────────────────────────────
        def fit_and_truncate(text, fnt, max_w):
            # wrap into at most 2 lines
            lines = textwrap.wrap(text, width=40)[:2]
            fitted = []
            for ln in lines:
                if draw.textlength(ln, font=fnt) <= max_w:
                    fitted.append(ln)
                else:
                    while draw.textlength(ln + "…", font=fnt) > max_w:
                        ln = ln[:-1]
                    fitted.append(ln + "…")
            return fitted

        # ─── Current‐month days ───────────────────────────────────────────────────
        for day in range(1, 32):
            try:
                dobj = datetime(year, month, day)
            except:
                break

            idx = (day - 1) + first_wd
            x = sx + (idx % cols) * (box_w + GUTTER)
            y = sy + (idx // cols) * (box_h + GUTTER)
            rect = [x, y, x + box_w, y + box_h]

            # determine background
            if dobj.date() < today:
                fill = "#e5e5e5"
            elif dobj.date() == today:
                fill = "#ffe4e1"
            else:
                fill = "#f9fafb"

            draw.rounded_rectangle(rect, radius=12, fill=fill, outline="gray", width=1)
            if dobj.date() == today:
                draw.rounded_rectangle(rect, radius=12, outline="black", width=1)

            # —— 1) draw the day number + event‐count if >1
            events_for_day = [ev for ev in events if ev[0].day == day]
            count = len(events_for_day)

            # day text
            day_txt = str(day)
            draw.text((x + 5, y + 5), day_txt, font=date_fnt, fill="black")
            if count > 1:
                cnt_txt = f"- {count} events"
                day_w = draw.textlength(day_txt, font=date_fnt)
                draw.text((x + 5 + day_w + 4, y + 5), cnt_txt, font=date_fnt, fill="black")

            # —— 2) draw at most one event description underneath
            if events_for_day:
                _, etitle, eemoji = events_for_day[0]
                raw = f"{eemoji or ''} {etitle}".strip()
                lines = fit_and_truncate(raw, event_fnt, box_w - 10)
                for i, ln in enumerate(lines):
                    dy = y + 5 + (DATE_FONT_SIZE + 2) + i * (EVENT_FONT_SIZE + 2)
                    draw.text((x + 5, dy), ln, font=event_fnt, fill="black")

        # ─── Chalkboard ───────────────────────────────────────────────────────────
        cx0 = width - CHALKBOARD_WIDTH - 20
        cbox = [cx0, pad_y, width - 20, height - FOOTER_HEIGHT]
        draw.rectangle(cbox, fill="#1e3d2f", outline="black")
        hdr = "Today's Events"
        hw = draw.textlength(hdr, font=chalk_fnt)
        cx = (cbox[0] + cbox[2]) // 2
        draw.text((cx - hw // 2, pad_y + 10), hdr, font=chalk_fnt, fill="white")
        cb = draw.textbbox((0, 0), hdr, font=chalk_fnt)
        chh = cb[3] - cb[1]
        y0 = pad_y + 10 + chh + 10

        for idx, (d, t, e) in enumerate(today_events, start=1):
            txt = f"{idx}. {e or ''} {t}".strip()
            lines = textwrap.wrap(txt, width=40)
            for ln in lines:
                draw.text((cx0 + 10, y0), ln, font=event_fnt, fill="white")
                lb = draw.textbbox((0, 0), ln, font=event_fnt)
                y0 += (lb[3] - lb[1]) + 5

        # ─── Footer quote ─────────────────────────────────────────────────────────
        quote = "Every day with you is my favourite."
        qw = draw.textlength(quote, font=footer_fnt)
        draw.text((width // 2 - qw // 2, height - 40), quote, font=footer_fnt, fill="gray")
        # ──────────────────────────────────────────────────────────────────────────

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        buf.seek(0)
        return buf

# ---------------------------------------------------------------------------------------------------------------------
# Calendar Commands
# ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="set_calendar_channel", description="Admin: Set the channel for calendar posts.")
    async def set_calendar_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        try:
            async with aiosqlite.connect(db_path) as db:
                # Insert or update config row
                await db.execute("""
                    INSERT OR REPLACE INTO calendar (guild_id, calendar_channel_id)
                    VALUES (?, ?)
                """, (interaction.guild.id, channel.id))
                await db.commit()

                now = datetime.now()
                image = await self.generate_calendar_image(interaction.guild.id, now.month, now.year)
                file = discord.File(fp=image, filename="calendar.png")  # 'image' is now a buffer
                embed = discord.Embed(
                    title=f"📆 {now.strftime('%B %Y')} Calendar",
                    description="Here's this month's page with today's events!",
                    color=await get_embed_colour(interaction.guild.id)
                )
                embed.set_image(url="attachment://calendar.png")

                view = CalendarNavigationView(self, interaction.guild.id, now.month, now.year)
                sent_message = await channel.send(embed=embed, file=file, view=view)

                # ✅ Move this inside the context
                await db.execute("""
                    INSERT OR REPLACE INTO calendar_views (guild_id, channel_id, message_id, month, year)
                    VALUES (?, ?, ?, ?, ?)
                """, (interaction.guild.id, channel.id, sent_message.id, now.month, now.year))
                await db.commit()

            await interaction.response.send_message(
                f"Success: Calendar posts will go to {channel.mention}.", ephemeral=True)

        except Exception as e:
            logger.error(f"Failed to set calendar channel: {e}")
            await interaction.response.send_message("Error: Could not set calendar channel.", ephemeral=True)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(
        name="calendar_events",
        description="User: List all calendar events on a specific date (DD/MM/YYYY)."
    )
    async def calendar_events(
        self,
        interaction: discord.Interaction,
        date: str
    ):
        """
        Show all events logged on the given date.
        Date must be in DD/MM/YYYY format.
        """
        await log_command_usage(self.bot, interaction)

        # parse the date
        try:
            target = datetime.strptime(date, "%d/%m/%Y").date()
        except ValueError:
            await interaction.response.send_message(
                "❌ Please provide a valid date in `DD/MM/YYYY` format.",
                ephemeral=True
            )
            return

        # fetch matching entries
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT emoji, title FROM calendar_entries "
                "WHERE guild_id = ? AND date = ? "
                "ORDER BY title",
                (interaction.guild.id, target.strftime("%d/%m/%Y"))
            )
            rows = await cursor.fetchall()

        if not rows:
            await interaction.response.send_message(
                f"📅 No events found on **{target.strftime('%d %b %Y')}**.",
                ephemeral=True
            )
            return

        # build a nice list
        lines = []
        for idx, (emoji, title) in enumerate(rows, start=1):
            prefix = f"{emoji} " if emoji else ""
            lines.append(f"**{idx}.** {prefix}{title}")

        # send as embed for readability
        embed = discord.Embed(
            title=f"Events on {target.strftime('%d %b %Y')}",
            description="\n".join(lines),
            color=await get_embed_colour(interaction.guild.id)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="calendar_add", description="User: Log a special event for this month.")
    async def calendar_add(self, interaction: discord.Interaction, title: str, date: str, emoji: str = None):
        """
        Accepts:
        - A single date: "25/12/2025"
        - A range: "01/06/2025 - 07/06/2025"
        """
        try:
            await log_command_usage(self.bot, interaction)

            # Parse date or range
            date_parts = date.split('-')
            try:
                if len(date_parts) == 1:
                    start_date = end_date = datetime.strptime(date.strip(), "%d/%m/%Y")
                elif len(date_parts) == 2:
                    start_date = datetime.strptime(date_parts[0].strip(), "%d/%m/%Y")
                    end_date = datetime.strptime(date_parts[1].strip(), "%d/%m/%Y")
                    if end_date < start_date:
                        raise ValueError("End date must be after start date.")
                else:
                    raise ValueError("Invalid format")
            except ValueError:
                await interaction.response.send_message(
                    "Error: Date must be in `DD/MM/YYYY` format, or `DD/MM/YYYY - DD/MM/YYYY` for a range.",
                    ephemeral=True)
                return

            # Add all dates to the calendar_entries table
            days = (end_date - start_date).days + 1
            async with aiosqlite.connect(db_path) as db:
                for i in range(days):
                    day = start_date + timedelta(days=i)
                    await db.execute("""
                        INSERT OR IGNORE INTO calendar_entries (guild_id, channel_name, title, date, emoji)
                        VALUES (?, ?, ?, ?, ?)
                    """, (interaction.guild.id, interaction.channel.name, title, day.strftime("%d/%m/%Y"), emoji))
                await db.commit()

            if days == 1:
                msg = f"Success: Event '{title}' on {start_date.strftime('%d/%m/%Y')} logged!"
            else:
                msg = f"Success: Event '{title}' from {start_date.strftime('%d/%m/%Y')} to {end_date.strftime('%d/%m/%Y')} logged!"

            await interaction.response.send_message(msg, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in calendar_add: {e}")
            await interaction.response.send_message("Error: Failed to log the event.", ephemeral=True)

    # ------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="calendar_remove", description="Admin: Remove a calendar event by title.")
    @app_commands.autocomplete(title=autocomplete_calendar_title)
    async def calendar_remove(self, interaction: discord.Interaction, title: str):

        try:
            await log_command_usage(self.bot, interaction)

            async with aiosqlite.connect(db_path) as db:
                result = await db.execute("""
                    DELETE FROM calendar_entries
                    WHERE guild_id = ? AND title = ?
                """, (interaction.guild.id, title))
                await db.commit()

            if result.rowcount == 0:
                await interaction.response.send_message("Error: No matching event found.", ephemeral=True)
            else:
                await interaction.response.send_message(f"Success: Event '{title}' removed!", ephemeral=True)

        except Exception as e:
            logger.error(f"Error in calendar_remove: {e}")
            await interaction.response.send_message("Error: Failed to remove the event.", ephemeral=True)

    # ------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="calendar_edit", description="Admin: Modify a calendar event.")
    @app_commands.autocomplete(title=autocomplete_calendar_title)
    async def calendar_edit(self, interaction: discord.Interaction, title: str, new_title: str = None,
                            new_date: str = None, new_emoji: str = None):
        try:
            await log_command_usage(self.bot, interaction)

            if new_date:
                try:
                    datetime.strptime(new_date, "%d/%m/%Y")
                except ValueError:
                    await interaction.response.send_message("Error: New date must be in DD/MM/YYYY format.",
                                                            ephemeral=True)
                    return

            async with aiosqlite.connect(db_path) as db:
                # Get existing entry
                cursor = await db.execute("""
                    SELECT date, emoji FROM calendar_entries
                    WHERE guild_id = ? AND title = ?
                    LIMIT 1
                """, (interaction.guild.id, title))
                row = await cursor.fetchone()

                if not row:
                    await interaction.response.send_message("Error: Event not found.", ephemeral=True)
                    return

                original_date = row[0]
                updated_title = new_title or title
                updated_date = new_date or original_date
                updated_emoji = new_emoji if new_emoji is not None else row[1]

                await db.execute("""
                    UPDATE calendar_entries SET title = ?, date = ?, emoji = ?
                    WHERE guild_id = ? AND title = ?
                """, (updated_title, updated_date, updated_emoji, interaction.guild.id, title))
                await db.commit()

            await interaction.response.send_message(
                f"Success: Event updated to '{updated_title}' on {updated_date}.",
                ephemeral=True)

        except Exception as e:
            logger.error(f"Error in calendar_edit: {e}")
            await interaction.response.send_message("Error: Failed to update the event.", ephemeral=True)

# ------------------------------------------------------------------------------------------------------------------
# Setup Function
# ------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    async with aiosqlite.connect(db_path) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS calendar (
                guild_id INTEGER,
                calendar_channel_id INTEGER,
                message_id INTEGER,
                month INTEGER,
                year INTEGER,
                PRIMARY KEY (guild_id)
            )
        ''')

        await db.execute('''
            CREATE TABLE IF NOT EXISTS calendar_entries (
                guild_id INTEGER,
                channel_name TEXT,
                title TEXT,
                date TEXT,
                emoji TEXT,
                PRIMARY KEY (guild_id, title, date)
            )
        ''')

        await db.execute('''
            CREATE TABLE IF NOT EXISTS calendar_views (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                message_id INTEGER,
                month INTEGER,
                year INTEGER
            )
        ''')

        await db.commit()
    await bot.add_cog(CalendarCog(bot))
