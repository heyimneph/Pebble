import discord
import validators
import yt_dlp as youtube_dl
import aiosqlite
import logging

from discord import app_commands
from discord.ext import commands

from core.utils import check_permissions, log_command_usage

# ---------------------------------------------------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------------------------------------------------
db_path = './data/databases/pebble.db'

# ---------------------------------------------------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------------------------------------------------

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------------------------------------------------
ytdl_format_options = {
    'format': 'bestaudio/best',
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
ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

#  ---------------------------------------------------------------------------------------------------------------------
#  Playlist Management View
#  ---------------------------------------------------------------------------------------------------------------------
class SongSelect(discord.ui.Select):
    def __init__(self, songs, playlist_name, user_id):
        super().__init__(placeholder='Choose a song to remove...', min_values=1, max_values=1)
        self.songs = songs
        self.playlist_name = playlist_name
        self.user_id = user_id
        self.options = [discord.SelectOption(label=song['title'], value=song['url']) for song in songs]

    async def callback(self, interaction: discord.Interaction):
        selected_song = next((song for song in self.songs if song['url'] == self.values[0]), None)
        if selected_song:
            view = ConfirmView(self.user_id, self.playlist_name, selected_song['url'], selected_song['title'])
            await interaction.response.send_message(f"Are you sure you want to remove '{selected_song['title']}' from '{self.playlist_name}'?", view=view, ephemeral=True)
        else:
            await interaction.response.send_message("Song not found.", ephemeral=True)

class RemoveSongView(discord.ui.View):
    def __init__(self, songs, playlist_name, user_id):
        super().__init__()
        self.add_item(SongSelect(songs, playlist_name, user_id))

#  ---------------------------------------------------------------------------------------------------------------------
#  Confirm/Cancel View
#  ---------------------------------------------------------------------------------------------------------------------
class ConfirmView(discord.ui.View):
    def __init__(self, user_id, playlist_name, song_url, song_title):
        super().__init__()
        self.user_id = user_id
        self.playlist_name = playlist_name
        self.song_url = song_url
        self.song_title = song_title

    @discord.ui.button(label='Yes', style=discord.ButtonStyle.red)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "DELETE FROM songs WHERE user_id = ? AND playlist_name = ? AND url = ?",
                (self.user_id, self.playlist_name, self.song_url)
            )
            await db.commit()
            await interaction.response.edit_message(content=f"Song '{self.song_title}' has been removed from '{self.playlist_name}'.", view=None)

    @discord.ui.button(label='No', style=discord.ButtonStyle.green)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Song removal canceled.", view=None)

#  ---------------------------------------------------------------------------------------------------------------------
#  Playlist Management Class
#  ---------------------------------------------------------------------------------------------------------------------
class PlaylistManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def create_playlist(self, user_id: str, playlist_name: str):
        async with aiosqlite.connect(db_path) as db:
            # Check if the playlist already exists
            cursor = await db.execute(
                "SELECT 1 FROM playlists WHERE user_id = ? AND name = ?",
                (user_id, playlist_name)
            )
            if await cursor.fetchone():
                return False  # Playlist already exists

            # Create the playlist
            await db.execute(
                "INSERT INTO playlists (user_id, name) VALUES (?, ?)",
                (user_id, playlist_name)
            )
            await db.commit()
        return True

    async def get_playlist_songs(self, user_id: str, playlist_name: str):
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT title, url FROM songs WHERE user_id = ? AND playlist_name = ?",
                (user_id, playlist_name)
            )
            songs = await cursor.fetchall()
        return [{"title": song[0], "url": song[1]} for song in songs] if songs else None

    async def autocomplete_playlists(self, interaction: discord.Interaction, current: str):
        user_id = str(interaction.user.id)
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT name FROM playlists WHERE user_id = ?",
                (user_id,)
            )
            playlists = await cursor.fetchall()
        return [app_commands.Choice(name=playlist[0], value=playlist[0]) for playlist in playlists if
                current.lower() in playlist[0].lower()]

    async def autocomplete_songs(self, interaction: discord.Interaction, current: str):
        user_id = str(interaction.user.id)
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT title, url FROM songs WHERE user_id = ?",
                (user_id,)
            )
            songs = await cursor.fetchall()
        return [
            app_commands.Choice(name=song[0], value=song[1])
            for song in songs if current.lower() in song[0].lower()
        ]


#  ---------------------------------------------------------------------------------------------------------------------
#  Playlist Commands
#  ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="create_playlist", description="User: Create a new music playlist.")
    @app_commands.describe(name="Name of the playlist you want to create")
    async def create_playlist_command(self, interaction: discord.Interaction, name: str):
        user_id = str(interaction.user.id)
        success = await self.create_playlist(user_id, name)
        if success:
            await interaction.response.send_message(f"`Success: Playlist Created`", ephemeral=True)
        else:
            await interaction.response.send_message(f"`Error: Playlist already exists`", ephemeral=True)
        await log_command_usage(self.bot, interaction)

    #  ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name='delete_playlist', description="User: Delete one of your playlists.")
    @app_commands.autocomplete(playlist=autocomplete_playlists)
    @app_commands.describe(playlist="The playlist you want to delete")
    async def delete_playlist(self, interaction: discord.Interaction, playlist: str):
        user_id = str(interaction.user.id)
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "DELETE FROM playlists WHERE user_id = ? AND name = ?",
                (user_id, playlist)
            )
            await db.execute(
                "DELETE FROM songs WHERE user_id = ? AND playlist_name = ?",
                (user_id, playlist)
            )
            await db.commit()
        await interaction.response.send_message(f"Playlist '{playlist}' has been deleted.", ephemeral=True)
        await log_command_usage(self.bot, interaction)

    #  ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name='add_to_playlist', description='User: Add a song to a specific playlist.')
    @app_commands.autocomplete(playlist=autocomplete_playlists)
    @app_commands.describe(song='Name of the song to add', playlist='The playlist to add the song to')
    async def add_to_playlist(self, interaction: discord.Interaction, song: str, playlist: str):
        user_id = str(interaction.user.id)
        song_info = ytdl.extract_info(f"ytsearch:{song}", download=False)
        if 'entries' in song_info and song_info['entries']:
            song_url = song_info['entries'][0]['webpage_url']
            song_title = song_info['entries'][0]['title']

            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "INSERT INTO songs (user_id, playlist_name, title, url) VALUES (?, ?, ?, ?)",
                    (user_id, playlist, song_title, song_url)
                )
                await db.commit()
            await interaction.response.send_message(f"'{song_title}' added to playlist '{playlist}'.", ephemeral=True)
        else:
            await interaction.response.send_message("`Error: No results found for the song`", ephemeral=True)
        await log_command_usage(self.bot, interaction)

    #  ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name='remove_song', description='User: Remove a song from a playlist.')
    @app_commands.autocomplete(playlist=autocomplete_playlists)
    async def remove_song(self, interaction: discord.Interaction, playlist: str):
        user_id = str(interaction.user.id)
        songs = await self.get_playlist_songs(user_id, playlist)
        if songs:
            view = RemoveSongView(songs, playlist, user_id)
            await interaction.response.send_message("Select a song to remove:", view=view, ephemeral=True)
        else:
            await interaction.response.send_message("No songs found in this playlist.", ephemeral=True)
        await log_command_usage(self.bot, interaction)

#  ---------------------------------------------------------------------------------------------------------------------
#  Setup Function
#  ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS playlists (
                user_id TEXT,
                name TEXT,
                PRIMARY KEY (user_id, name)
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS songs (
                user_id TEXT,
                playlist_name TEXT,
                title TEXT,
                url TEXT,
                PRIMARY KEY (user_id, playlist_name, url),
                FOREIGN KEY (user_id, playlist_name) REFERENCES playlists (user_id, name) ON DELETE CASCADE
            )
        ''')
        await conn.commit()
    await bot.add_cog(PlaylistManager(bot))
