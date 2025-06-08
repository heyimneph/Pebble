import discord
import random
import logging

from discord import app_commands
from discord.ext import commands
from core.utils import log_command_usage, get_embed_colour

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


ALLOWED_USER_IDS = {270248357501337600, 111941993629806592}

battle_outcomes = [
    "A meteor fell on {loser}, {winner} is left standing and has been declared the victor!",
    "{loser} got a little...heated during the battle and ended up getting set on fire. {winner} wins by remaining cool",
    "Princess Celestia came in and banished {loser} to the moon.",
    "{loser} tripped down some stairs on their way to the battle with {winner}",
    "{winner} and {loser} engage in a dance off; {winner} wiped the floor with {loser}",
    "{loser} didn't press x enough to not die",
    "{winner} threw a sick meme and {loser} totally got PRANK'D",
]

hugs = [
    "*hugs {user}.*",
    "*tackles {user} for a hug.*",
    "*cuddles {user} tightly*",
    "*goes out to buy a big enough blanket to embrace {user}*",
    "*hires mercenaries to take {user} out....to a nice dinner*",
    "*glomps {user}*",
    "*approaches {user} after gym time and almost crushes them in a hug.*",
]

class InteractionsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def validate_users(self, user_id: int, target_id: int):
        return user_id in ALLOWED_USER_IDS and target_id in ALLOWED_USER_IDS

    async def handle_interaction(self, interaction: discord.Interaction, action: str, emoji: str = "", use_random: bool = False):
        await log_command_usage(self.bot, interaction)

        user = interaction.user
        other_id = next(uid for uid in ALLOWED_USER_IDS if uid != user.id)
        other_user = await self.bot.fetch_user(other_id)

        if not self.validate_users(user.id, other_user.id):
            await interaction.response.send_message("You are not allowed to use this command.", ephemeral=True)
            return

        colour = await get_embed_colour(interaction.guild.id)

        if action == "fight":
            winner = random.choice([user, other_user])
            loser = other_user if winner == user else user
            description = random.choice(battle_outcomes).format(winner=winner.mention, loser=loser.mention)
        elif action == "hug":
            description = f"{user.mention} {random.choice(hugs).format(user=other_user.mention)}"
        else:
            description = f"{user.mention} {action}s {other_user.mention}! {emoji}"

        embed = discord.Embed(description=description, color=colour)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="User: Give a hug.")
    async def hug(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "hug")
        except Exception as e:
            logger.error(f"Error in /hug: {e}")
            await interaction.response.send_message("Error: Could not send hug.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: Start a fight.")
    async def fight(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "fight")
        except Exception as e:
            logger.error(f"Error in /fight: {e}")
            await interaction.response.send_message("Error: Could not start fight.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: Cuddle the other user.")
    async def cuddle(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "cuddle", "🥰")
        except Exception as e:
            logger.error(f"Error in /cuddle: {e}")
            await interaction.response.send_message("Error: Could not cuddle.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: Smooch the other user.")
    async def smooch(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "smooch", "😘")
        except Exception as e:
            logger.error(f"Error in /smooch: {e}")
            await interaction.response.send_message("Error: Could not smooch.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: Boop the other user.")
    async def boop(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "boop")
        except Exception as e:
            logger.error(f"Error in /boop: {e}")
            await interaction.response.send_message("Error: Could not boop.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: Bonk the other user.")
    async def bonk(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "bonk", "🥖")
        except Exception as e:
            logger.error(f"Error in /bonk: {e}")
            await interaction.response.send_message("Error: Could not bonk.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: Slap the other user.")
    async def slap(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "slap", "✋")
        except Exception as e:
            logger.error(f"Error in /slap: {e}")
            await interaction.response.send_message("Error: Could not slap.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: Give the other user flowers.")
    async def flowers(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "gives flowers to", "🌹")
        except Exception as e:
            logger.error(f"Error in /flowers: {e}")
            await interaction.response.send_message("Error: Could not give flowers.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: Give the other user a cookie.")
    async def cookie(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "gives a cookie to", "🍪")
        except Exception as e:
            logger.error(f"Error in /cookie: {e}")
            await interaction.response.send_message("Error: Could not give cookie.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: Poke the other user.")
    async def poke(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "poke", "👉")
        except Exception as e:
            logger.error(f"Error in /poke: {e}")
            await interaction.response.send_message("Error: Could not poke.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: Pat the other user's head.")
    async def pat(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "pats", "🪚")
        except Exception as e:
            logger.error(f"Error in /pat: {e}")
            await interaction.response.send_message("Error: Could not pat.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: Snuggle with the other user.")
    async def snuggle(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "snuggle", "🐻")
        except Exception as e:
            logger.error(f"Error in /snuggle: {e}")
            await interaction.response.send_message("Error: Could not snuggle.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: High five the other user.")
    async def highfive(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "high fives", "✋")
        except Exception as e:
            logger.error(f"Error in /highfive: {e}")
            await interaction.response.send_message("Error: Could not high five.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: Tickle the other user.")
    async def tickle(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "tickle", "🤣")
        except Exception as e:
            logger.error(f"Error in /tickle: {e}")
            await interaction.response.send_message("Error: Could not tickle.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: Wink at the other user.")
    async def wink(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "winks at", "😉")
        except Exception as e:
            logger.error(f"Error in /wink: {e}")
            await interaction.response.send_message("Error: Could not wink.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: Nuzzle the other user.")
    async def nuzzle(self, interaction: discord.Interaction):
        try:
            await self.handle_interaction(interaction, "nuzzles", "🐾")
        except Exception as e:
            logger.error(f"Error in /nuzzle: {e}")
            await interaction.response.send_message("Error: Could not nuzzle.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)


async def setup(bot):
    await bot.add_cog(InteractionsCog(bot))
