import json
import datetime
import io
import discord
import os
import random
import validators
import yt_dlp as youtube_dl

from core.database import DB_PATH
import logging
import asyncio

from PIL import Image, ImageDraw
from discord.ext import commands, tasks
from discord import app_commands

from core.utils import check_permissions, log_command_usage

# ---------------------------------------------------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------------------------------------------------
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------------------------------------------------
ytdl_format_options = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_stream_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin -re',
    'options': '-vn',
    'executable': 'ffmpeg'
}

ffmpeg_file_options = {
    'options': '-vn',
    'executable': 'ffmpeg'
}


ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

#  ---------------------------------------------------------------------------------------------------------------------
#  Confirm/Cancel View
#  ---------------------------------------------------------------------------------------------------------------------
class ConfirmView(discord.ui.View):
    def __init__(self, music_player):
        super().__init__()
        self.music_player = music_player

    @discord.ui.button(label='Yes', style=discord.ButtonStyle.red)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Clear the queue and stop the player
        self.music_player.song_queue.clear()
        self.music_player.currently_playing = None

        bot_voice_state = interaction.guild.voice_client
        if bot_voice_state:
            await bot_voice_state.disconnect()

        self.music_player.player_message = None

        await interaction.response.edit_message(content="Bot has left the voice channel.", view=None)

    @discord.ui.button(label='No', style=discord.ButtonStyle.green)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Action canceled.", view=None)


#  ---------------------------------------------------------------------------------------------------------------------
#  PlayerControl View
#  ---------------------------------------------------------------------------------------------------------------------
class PlayerControls(discord.ui.View):
    def __init__(self, bot, music_player):
        super().__init__()
        self.bot = bot
        self.music_player = music_player

    @discord.ui.button(label='⏮️', style=discord.ButtonStyle.grey)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_voice_state = interaction.user.voice
        bot_voice_state = interaction.guild.voice_client

        if not user_voice_state or user_voice_state.channel != bot_voice_state.channel:
            await interaction.followup.send("`Error: You must be in the same voice channel to control the music`",
                                            ephemeral=True)
            return

        if not self.music_player.song_history:
            await interaction.response.send_message("No previous song in history.", ephemeral=True)
            return

        self.music_player.currently_playing = self.music_player.song_history.pop()
        self.music_player.song_queue.insert(0, self.music_player.currently_playing)

        if bot_voice_state:
            bot_voice_state.stop()

        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"Playing Previous Song!", ephemeral=True)
        await self.music_player.update_player(interaction)

    @discord.ui.button(label='⏯️', style=discord.ButtonStyle.grey)
    async def play_pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        bot_voice_state = interaction.guild.voice_client

        try:
            if bot_voice_state.is_playing():
                bot_voice_state.pause()
                await interaction.followup.send(f"Song has been Paused!", ephemeral=True)
                self.music_player._pause()
                if self.music_player.update_progress_loop.is_running():
                    self.music_player.update_progress_loop.stop()
            elif bot_voice_state.is_paused():
                bot_voice_state.resume()
                await interaction.followup.send(f"Song has been Resumed!", ephemeral=True)
                self.music_player.resume()
                if not self.music_player.update_progress_loop.is_running():
                    self.music_player.update_progress_loop.start()

            await self.music_player.update_player(interaction)
        except Exception as e:
            await interaction.followup.send(f"`Error: {str(e)}`", ephemeral=True)
            print(f"Error in play_pause_button: {e}")

    @discord.ui.button(label='⏭️', style=discord.ButtonStyle.grey)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        user_voice_state = interaction.user.voice
        bot_voice_state = interaction.guild.voice_client

        if not user_voice_state or user_voice_state.channel != bot_voice_state.channel:
            await interaction.followup.send("`Error: You must be in the same voice channel to control the music`",
                                            ephemeral=True)
            return

        if not self.music_player.song_queue:
            await interaction.followup.send("The Queue is Empty!", ephemeral=True)
            return

        try:
            if bot_voice_state:
                bot_voice_state.stop()
            await interaction.followup.send(f"Playing Next Song!", ephemeral=True)
            await self.music_player.update_player(interaction)
        except Exception as e:
            print(f"Error processing next button: {e}")
            await interaction.followup.send("`Error: Something went wrong while skipping the song`", ephemeral=True)

    @discord.ui.button(label='🔁', style=discord.ButtonStyle.grey)
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        user_voice_state = interaction.user.voice
        bot_voice_state = interaction.guild.voice_client

        if not user_voice_state or user_voice_state.channel != bot_voice_state.channel:
            await interaction.followup.send("`Error: You must be in the same voice channel to control the music`",
                                            ephemeral=True)
            return

        try:
            self.music_player.loop = not self.music_player.loop
            loop_status = "enabled" if self.music_player.loop else "disabled"

            await interaction.followup.send(f"Loop has been {loop_status}.", ephemeral=True)
            await self.music_player.update_player(interaction)
        except Exception as e:
            await interaction.followup.send("`Error: Something went wrong while trying to toggle the loop`",
                                            ephemeral=True)
            print(f"Error in loop_button: {e}")

    @discord.ui.button(label='🔀', style=discord.ButtonStyle.grey)
    async def shuffle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        user_voice_state = interaction.user.voice
        bot_voice_state = interaction.guild.voice_client

        if not user_voice_state or user_voice_state.channel != bot_voice_state.channel:
            await interaction.followup.send("`Error: You must be in the same voice channel to control the music`",
                                            ephemeral=True)
            return

        try:
            if len(self.music_player.song_queue) > 1:
                random.shuffle(self.music_player.song_queue)

            await self.music_player.update_player(interaction)
        except Exception as e:
            await interaction.followup.send("`Error: Something went wrong while trying to shuffle the queue`",
                                            ephemeral=True)
            print(f"Error in shuffle_button: {e}")

#  ---------------------------------------------------------------------------------------------------------------------
#  Queue View
#  ---------------------------------------------------------------------------------------------------------------------
class QueueView(discord.ui.View):
    def __init__(self, songs, music_player):
        super().__init__()
        self.music_player = music_player
        self.add_item(QueueDropdown(songs))

class QueueDropdown(discord.ui.Select):
    def __init__(self, songs):
        options = [
            discord.SelectOption(label=song['title'], description=f"URL: {song['url'][:75]}...", value=str(index))
            for index, song in enumerate(songs) if index < 25
        ]
        super().__init__(placeholder='Choose a song to remove...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        index = int(self.values[0])
        removed_song = self.view.music_player.song_queue.pop(index)
        await interaction.followup.send(f"Removed {removed_song['title']} from the queue.", ephemeral=True)
        await self.view.music_player.update_player(interaction)


#  ---------------------------------------------------------------------------------------------------------------------
#  MusicPlayer Cog
#  ---------------------------------------------------------------------------------------------------------------------
class MusicPlayer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.player_message = None
        self.currently_playing = None
        self.song_queue = []
        self.song_history = []
        self.loop = False
        self.download_path = './data/downloads/music/'
        self.song_start_time = None
        self.paused_time_start = None
        self.total_paused_time = 0
        self.progress_bar_images = {}

        # Start the tasks
        self.update_progress_loop.start()
        self.check_idle_loop.start()
        self.update_lock = asyncio.Lock()
    def format_duration(self, seconds):
        """Convert seconds into a human-readable duration format."""
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours}:{minutes:02}:{seconds:02}"
        else:
            return f"{minutes:02}:{seconds:02}"

    async def autocomplete_playlists(self, interaction: discord.Interaction, current: str):
        user_id = str(interaction.user.id)
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT name FROM playlists WHERE user_id = ? AND name LIKE ?",
                (user_id, f'%{current}%')
            )
            playlists = await cursor.fetchall()
            return [
                app_commands.Choice(name=playlist[0], value=playlist[0])
                for playlist in playlists
            ]

    @commands.Cog.listener()
    async def on_ready(self):
        await self.load_progress_images()

    async def load_progress_images(self):
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute('SELECT percentage, url FROM progress_bars')
            rows = await cursor.fetchall()
            self.progress_bar_images = {str(row[0]): row[1] for row in rows}
            if not self.progress_bar_images:
                print("No progress bar images found in the database.")

#  ---------------------------------------------------------------------------------------------------------------------
#  Loops
#  ---------------------------------------------------------------------------------------------------------------------

    @tasks.loop(seconds=10)
    async def update_progress_loop(self):
        if self.currently_playing and self.player_message:
            await self.update_player(self.player_message.interaction_metadata)

    @tasks.loop(seconds=120)
    async def check_idle_loop(self):
        if not self.currently_playing and not self.song_queue:
            await self.handle_idle_disconnect()

    async def handle_idle_disconnect(self):
        try:
            guild_id = None
            if self.player_message:
                guild_id = self.player_message.guild.id
                controls = PlayerControls(self.bot, self)
                controls.disable_all_buttons()
                await self.player_message.edit(view=controls)
                self.player_message = None

            if guild_id is None:
                for voice_client in self.bot.voice_clients:
                    if voice_client.guild:
                        guild_id = voice_client.guild.id
                        break

            if guild_id:
                guild = self.bot.get_guild(guild_id)
                if guild:
                    voice_client = discord.utils.get(self.bot.voice_clients, guild=guild)
                    if voice_client and voice_client.is_connected():
                        await voice_client.disconnect()
        except discord.NotFound:
            pass

    def generate_progress_bar(self, current, total, width, height, bg_color="black", fg_color='#8e4cd0'):
        percentage = current / total
        image = Image.new("RGB", (width, height), bg_color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, int(percentage * width), height), fill=fg_color)
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        return img_byte_arr

    async def upload_image(self, image_bytes, channel_id=1359480363725885470):
        channel = self.bot.get_channel(channel_id)
        file = discord.File(fp=image_bytes, filename="progress.png")
        message = await channel.send(file=file)
        return message.attachments[0].url

    async def generate_and_upload_progress_images(self):
        channel = self.bot.get_channel(1359480363725885470)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM progress_bars')

            for i in range(101):  # Loop through percentages 0 to 100
                image_bytes = self.generate_progress_bar(i, 100, 400, 20)
                file = discord.File(fp=image_bytes, filename=f"progress_{i}.png")
                message = await channel.send(file=file)
                image_url = message.attachments[0].url

                await db.execute(
                    'INSERT INTO progress_bars (percentage, url) VALUES (?, ?)',
                    (i, image_url)
                )
                # Commit after each insert
                await db.commit()

        await self.load_progress_images()

    def _pause(self):
        if self.song_start_time and not self.paused_time_start:
            self.paused_time_start = datetime.datetime.utcnow()

    def resume(self):
        if self.paused_time_start:
            self.total_paused_time += (datetime.datetime.utcnow() - self.paused_time_start).total_seconds()
            self.paused_time_start = None

    async def update_player(self, interaction=None, force_completion=False):
        async with self.update_lock:
            try:
                guild = interaction.guild if interaction else self.bot.get_guild(self.player_message.guild.id)
                voice_client = guild.voice_client

                if self.currently_playing:
                    song_url = self.currently_playing['url']
                    song_title = self.currently_playing['title']
                    song_length = self.currently_playing.get('duration', 0)
                    song_webpage = self.currently_playing.get('webpage_url', song_url)

                    if self.song_start_time:
                        current_time = datetime.datetime.utcnow()
                        elapsed_time = (current_time - self.song_start_time).total_seconds() - self.total_paused_time
                    else:
                        elapsed_time = 0

                    progress_percentage = 100 if force_completion else int(
                        (elapsed_time / song_length) * 100) if song_length else 0
                    image_url = self.progress_bar_images.get(str(progress_percentage))
                    formatted_song_length = self.format_duration(song_length)

                    embed = discord.Embed(title="Now Playing", description=song_title,
                                          url=song_webpage, color=discord.Color.from_str("#8e4cd0"))

                    if image_url:
                        embed.set_image(url=image_url)

                    queue_preview = ''
                    for index, song in enumerate(self.song_queue[:5], start=1):
                        queue_preview += f"{index}. {song['title']}\n"

                    if len(self.song_queue) > 5:
                        queue_preview += f"...and {len(self.song_queue) - 5} more!"

                    embed.add_field(name="Queue", value=queue_preview or "Use `/play` to add a Song!", inline=False)
                    embed.add_field(name="Duration", value=f"{formatted_song_length}", inline=False)
                    embed.set_thumbnail(url=self.bot.user.avatar)
                    embed.set_footer(text="Untz Untz Untz Untz", icon_url=self.bot.user.avatar)

                    controls = PlayerControls(self.bot, self)
                    if not self.player_message:
                        target_channel = guild.text_channels[0] if not interaction else interaction.channel
                        self.player_message = await target_channel.send(embed=embed, view=controls)
                    else:
                        await self.player_message.edit(embed=embed, view=controls)

                elif force_completion and self.player_message:
                    embed = discord.Embed(title="Now Playing", description="No song currently playing.",
                                          color=discord.Color.from_str("#8e4cd0"))
                    image_url = self.progress_bar_images.get("100")
                    if image_url:
                        embed.set_image(url=image_url)
                    await self.player_message.edit(embed=embed)

            except Exception as e:
                logger.exception(f"Error updating player: {e}")

    async def ensure_voice(self, interaction: discord.Interaction):
        user = interaction.user
        if user.voice is None:
            if not interaction.response.is_done():
                await interaction.response.send_message("`Error: You must be in a voice channel to use this command`",
                                                        ephemeral=True)
            else:
                await interaction.followup.send("`Error: You must be in a voice channel to use this command`",
                                                ephemeral=True)
            return None
        channel = user.voice.channel
        if interaction.guild.voice_client is not None:
            await interaction.guild.voice_client.move_to(channel)
            return interaction.guild.voice_client
        else:
            return await channel.connect()

    async def play_next(self, interaction, voice_client):
        if voice_client.is_playing():
            return

        if self.loop and self.currently_playing:
            self.song_queue.insert(0, self.currently_playing)
        elif self.currently_playing:
            self.song_history.append(self.currently_playing)

        if self.song_queue:
            self.currently_playing = self.song_queue.pop(0)
            self.song_start_time = datetime.datetime.utcnow()

            next_url = self.currently_playing['url']
            local_filename = await self.download_song(next_url)

            if os.path.exists(local_filename):
                source = discord.FFmpegPCMAudio(local_filename, **ffmpeg_file_options)
                voice_client.play(source, after=lambda e: self.bot.loop.create_task(
                    self.after_playing(e, interaction.guild.id, voice_client))
                                  )

                await self.update_player(interaction)
            else:
                print(f"File {local_filename} not found.")
        else:
            self.currently_playing = None
            self.player_message = None

    async def download_song(self, url):
        info = ytdl.extract_info(url, download=False)
        local_filename = os.path.join(self.download_path, f"{info['id']}.mp3")

        if not os.path.exists(local_filename):
            download_options = ytdl_format_options.copy()
            download_options['outtmpl'] = local_filename
            local_ytdl = youtube_dl.YoutubeDL(download_options)
            await self.bot.loop.run_in_executor(None, local_ytdl.download, [url])

        return local_filename

    async def after_playing(self, error, guild_id, voice_client):
        try:
            if error:
                logger.error(f"Playback error in after_playing: {error}")

            guild = self.bot.get_guild(guild_id)
            if guild is None:
                logger.warning(f"Guild with ID {guild_id} not found. Skipping after_playing.")
                return

            interaction_channel = None
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    interaction_channel = channel
                    break

            if interaction_channel:
                await self.update_player(interaction_channel, force_completion=True)

            # Clean up old file
            if self.currently_playing:
                info = ytdl.extract_info(self.currently_playing['url'], download=False)
                local_filename = os.path.join(self.download_path, f"{info['id']}.mp3")
                if os.path.exists(local_filename):
                    os.remove(local_filename)

            # Move to the next song
            if not voice_client.is_playing() and not voice_client.is_paused():
                if interaction_channel:
                    await self.play_next(interaction_channel, voice_client)

        except Exception as e:
            logger.exception(f"Unexpected error in after_playing: {e}")

    #  ---------------------------------------------------------------------------------------------------------------------
#  Commands
#  ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name='setup_music', description="Owner: Setup Progress Bars.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_music(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.generate_and_upload_progress_images()
        await interaction.followup.send("Progress bar images have been successfully created and stored.",
                                        ephemeral=True)

        await log_command_usage(self.bot, interaction)

    #  ---------------------------------------------------------------------------------------------------------------------

    @app_commands.command(name='play', description='User: Plays a song from a URL or by song name.')
    async def play(self, interaction: discord.Interaction, song: str):
        await interaction.response.defer()

        voice_client = await self.ensure_voice(interaction)
        if voice_client is None:
            return

        if not validators.url(song):
            song = f"ytsearch:{song}"

        info = ytdl.extract_info(song, download=False)
        if 'entries' in info:
            info = info['entries'][0]

        song_data = {
            'url': info['webpage_url'],
            'title': info.get('title', 'Unknown Title'),
            'duration': info.get('duration', 0),
            'webpage_url': info.get('webpage_url', info['url'])
        }

        self.song_queue.append(song_data)
        # Start download in background so it's ready when we need it
        asyncio.create_task(self.download_song(song_data['url']))

        if not voice_client.is_playing() and not voice_client.is_paused():
            await self.play_next(interaction, voice_client)

        await self.update_player(interaction)
        await interaction.followup.send(f"`Success: Added {info['title']} to the queue.`", ephemeral=True)

        await log_command_usage(self.bot, interaction)

    #  ---------------------------------------------------------------------------------------------------------------------


    @app_commands.command(name='previous', description='User: Plays the previous song in the queue.')
    async def previous(self, interaction: discord.Interaction):
        voice_client = await self.ensure_voice(interaction)
        if voice_client is None:
            return

        await self._previous_song(interaction)


    async def _previous_song(self, interaction):
        user_voice_state = interaction.user.voice
        bot_voice_state = interaction.guild.voice_client

        if not user_voice_state or user_voice_state.channel != bot_voice_state.channel:
            await interaction.response.send_message("You must be in the same voice channel to control the music.",
                                                    ephemeral=True)
            return

        if not self.song_history:
            await interaction.response.send_message("No previous song in history.", ephemeral=True)
            return

        self.currently_playing = self.song_history.pop()
        self.song_queue.insert(0, self.currently_playing)

        if bot_voice_state:
            bot_voice_state.stop()

        await interaction.response.send_message("Playing the previous song...", ephemeral=True)
        await self.update_player(interaction)
        await log_command_usage(self.bot, interaction)

    #  ---------------------------------------------------------------------------------------------------------------------

    @app_commands.command(name='next', description='User: Skips to the next song in the queue.')
    async def next(self, interaction: discord.Interaction):
        voice_client = await self.ensure_voice(interaction)
        if voice_client is None:
            return

        await self._next_song(interaction)

    async def _next_song(self, interaction):
        user_voice_state = interaction.user.voice
        bot_voice_state = interaction.guild.voice_client

        if not user_voice_state or user_voice_state.channel != bot_voice_state.channel:
            await interaction.response.send_message("You must be in the same voice channel to control the music.",
                                                    ephemeral=True)
            return

        if not self.song_queue:
            await interaction.response.send_message("The queue is empty.", ephemeral=True)
            return

        if bot_voice_state:
            bot_voice_state.stop()

        await interaction.response.send_message("Skipping to the next song...", ephemeral=True)
        await self.update_player(interaction)
        await log_command_usage(self.bot, interaction)

    #  ---------------------------------------------------------------------------------------------------------------------

    @app_commands.command(name='pause', description='User: Pauses or resumes the current song.')
    async def pause(self, interaction: discord.Interaction):
        voice_client = await self.ensure_voice(interaction)
        if voice_client is None:
            return

        await self._pause_song(interaction)
        await log_command_usage(self.bot, interaction)

    async def _pause_song(self, interaction):
        bot_voice_state = interaction.guild.voice_client

        if not bot_voice_state:
            await interaction.response.send_message("Bot is not connected to a voice channel.", ephemeral=True)
            return

        try:
            if bot_voice_state.is_playing():
                bot_voice_state._pause()
                await interaction.response.send_message("Paused the song.", ephemeral=True)
                if self.update_progress_loop.is_running():
                    self.update_progress_loop.stop()
            elif bot_voice_state.is_paused():
                bot_voice_state.resume()
                await interaction.response.send_message("Resumed the song.", ephemeral=True)
                if not self.update_progress_loop.is_running():
                    self.update_progress_loop.start()

        except Exception as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)
            print(f"Error in _pause_song: {e}")

#  ---------------------------------------------------------------------------------------------------------------------

    @app_commands.command(name='loop', description='User: Toggles loop mode.')
    async def loop(self, interaction: discord.Interaction):
        voice_client = await self.ensure_voice(interaction)
        if voice_client is None:
            return

        await self._toggle_loop(interaction)
        await log_command_usage(self.bot, interaction)

    async def _toggle_loop(self, interaction):
        self.loop = not self.loop
        loop_status = "enabled" if self.loop else "disabled"
        await interaction.response.send_message(f"Loop has been {loop_status}.", ephemeral=True)


#  ---------------------------------------------------------------------------------------------------------------------

    @app_commands.command(name='shuffle', description='User: Shuffles the song queue.')
    async def shuffle(self, interaction: discord.Interaction):
        voice_client = await self.ensure_voice(interaction)
        if voice_client is None:
            return

        await self._shuffle_queue(interaction)
        await log_command_usage(self.bot, interaction)

    async def _shuffle_queue(self, interaction):
        if len(self.song_queue) > 1:
            random.shuffle(self.song_queue)
            await interaction.response.send_message("Shuffled the queue.", ephemeral=True)
        else:
            await interaction.response.send_message("Queue has less than 2 songs, cannot shuffle.", ephemeral=True)


#  ---------------------------------------------------------------------------------------------------------------------

    @app_commands.command(name='stop', description='User: Stops the music and leaves the channel with confirmation.')
    async def stop(self, interaction: discord.Interaction):
        voice_client = await self.ensure_voice(interaction)
        if voice_client is None:
            return

        await self._stop_music(interaction)
        await log_command_usage(self.bot, interaction)

    async def _stop_music(self, interaction):
        view = ConfirmView(self)
        await interaction.response.send_message("Are you sure you want to stop the music and leave the channel?",
                                                view=view, ephemeral=True)

#  ---------------------------------------------------------------------------------------------------------------------

    @app_commands.command(name='load_playlist', description='User: Loads a playlist into the music player.')
    @app_commands.autocomplete(playlist_name=autocomplete_playlists)
    @app_commands.describe(playlist_name='The name of the playlist you want to load')
    async def load_playlist(self, interaction: discord.Interaction, playlist_name: str):
        voice_client = await self.ensure_voice(interaction)
        if voice_client is None:
            return

        user_id = str(interaction.user.id)
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT title, url FROM songs WHERE user_id = ? AND playlist_name = ?",
                (user_id, playlist_name)
            )
            songs = await cursor.fetchall()

        if not songs:
            await interaction.response.send_message(f"No playlist named '{playlist_name}' found or it is empty.",
                                                    ephemeral=True)
            return

        self.song_queue = [{'url': song[1], 'title': song[0]} for song in songs]
        await interaction.response.send_message(f"Loaded {len(songs)} songs from playlist '{playlist_name}'.",
                                                ephemeral=True)

        if not self.currently_playing and self.song_queue:
            await self.play_next(interaction, voice_client)
        await self.update_player(interaction)

        await log_command_usage(self.bot, interaction)

    #  ---------------------------------------------------------------------------------------------------------------------


    @app_commands.command(name='clear_queue', description='User: Clears the current song queue.')
    async def clear_queue(self, interaction: discord.Interaction):
        voice_client = await self.ensure_voice(interaction)
        if voice_client is None:
            return

        self.song_queue.clear()
        await interaction.response.send_message("The song queue has been cleared.", ephemeral=True)
        await log_command_usage(self.bot, interaction)

    #  ---------------------------------------------------------------------------------------------------------------------

    @app_commands.command(name='remove_song_from_queue', description='User: Remove a specific song from the queue.')
    async def remove_song_from_queue(self, interaction: discord.Interaction):
        if not self.song_queue:
            await interaction.response.send_message("The song queue is currently empty.", ephemeral=True)
            return

        view = QueueView(songs=self.song_queue, music_player=self)
        await interaction.response.send_message("Select a song to remove from the queue:", view=view, ephemeral=True)
        await log_command_usage(self.bot, interaction)


#  ---------------------------------------------------------------------------------------------------------------------
#  Setup Function
#  ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS playlists (
                user_id TEXT,
                name TEXT,
                PRIMARY KEY (user_id, name)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS songs (
                user_id TEXT,
                playlist_name TEXT,
                title TEXT,
                url TEXT,
                PRIMARY KEY (user_id, playlist_name, url),
                FOREIGN KEY (user_id, playlist_name) REFERENCES playlists (user_id, name) ON DELETE CASCADE
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS progress_bars (
                percentage INTEGER PRIMARY KEY,
                url TEXT
            )
        ''')
        await db.commit()
    await bot.add_cog(MusicPlayer(bot))
