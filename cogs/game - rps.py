import discord

from core.database import DB_PATH
import logging

from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View

from core.utils import check_permissions, log_command_usage

# ---------------------------------------------------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------------------------------
# Challenge View
# ---------------------------------------------------------------------------------------------------------------------
class ChallengeView(View):
    def __init__(self, opponent: discord.Member, challenger: discord.User, challenge_interaction: discord.Interaction):
        super().__init__()
        self.opponent = opponent
        self.challenger = challenger
        self.challenge_interaction = challenge_interaction

    @discord.ui.button(label="\u200b", style=discord.ButtonStyle.secondary, disabled=True)
    async def blank1(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.opponent:
            await interaction.response.send_message("You are not the one being challenged!", ephemeral=True)
        else:
            await interaction.response.defer()

            game_view = GameView(self.opponent, self.challenger, self.challenge_interaction)
            embed = discord.Embed(
                title="᲼᲼᲼᲼᲼᲼᲼Game On!",
                description="Choose rock, paper, or scissors!",
                color=discord.Color.from_str("#8e4cd0")
            )

            await self.challenge_interaction.edit_original_response(content="", embed=embed, view=game_view)

    @discord.ui.button(label="\u200b", style=discord.ButtonStyle.secondary, disabled=True)
    async def blank2(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.opponent:
            await interaction.response.send_message("You are not the one being challenged!", ephemeral=True)
        else:
            embed = discord.Embed(
                title="᲼᲼᲼Challenge Rejected!",
                description=f"{interaction.user.display_name} has rejected the challenge",
                color=discord.Color.from_str("#8e4cd0")
            )
            await self.challenge_interaction.edit_original_response(content="", embed=embed, view=None)
            await interaction.response.send_message("You have rejected the challenge.", ephemeral=True)

    @discord.ui.button(label="\u200b", style=discord.ButtonStyle.secondary, disabled=True)
    async def blank3(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

# ---------------------------------------------------------------------------------------------------------------------
# Game View
# ---------------------------------------------------------------------------------------------------------------------
class GameView(View):
    def __init__(self, opponent, challenger, response_target):
        super().__init__()
        self.opponent = opponent
        self.challenger = challenger
        self.response_target = response_target  # can be either Interaction or WebhookMessage
        self.choices = {}

    async def edit_response(self, **kwargs):
        if isinstance(self.response_target, discord.Interaction):
            await self.response_target.edit_original_response(**kwargs)
        else:
            await self.response_target.edit(**kwargs)


    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user == self.opponent or interaction.user == self.challenger

    async def update_leaderboard(self, guild_id, winner_id, loser_id, draw=False):
        game_name = "RPS"
        async with aiosqlite.connect(DB_PATH) as db:
            if draw:
                await db.execute(
                    "INSERT INTO leaderboards (guild_id, game, user_id, draws) VALUES (?, ?, ?, 1) "
                    "ON CONFLICT(guild_id, game, user_id) DO UPDATE SET draws = draws + 1",
                    (guild_id, game_name, winner_id)
                )
                await db.execute(
                    "INSERT INTO leaderboards (guild_id, game, user_id, draws) VALUES (?, ?, ?, 1) "
                    "ON CONFLICT(guild_id, game, user_id) DO UPDATE SET draws = draws + 1",
                    (guild_id, game_name, loser_id)
                )
            else:
                await db.execute(
                    "INSERT INTO leaderboards (guild_id, game, user_id, wins) VALUES (?, ?, ?, 1) "
                    "ON CONFLICT(guild_id, game, user_id) DO UPDATE SET wins = wins + 1",
                    (guild_id, game_name, winner_id)
                )
                await db.execute(
                    "INSERT INTO leaderboards (guild_id, game, user_id, losses) VALUES (?, ?, ?, 1) "
                    "ON CONFLICT(guild_id, game, user_id) DO UPDATE SET losses = losses + 1",
                    (guild_id, game_name, loser_id)
                )
            await db.commit()

    @discord.ui.button(label="🪨", style=discord.ButtonStyle.primary)
    async def select_rock(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choices[interaction.user.id] = '🪨'
        await interaction.response.send_message(f"You chose 🪨", ephemeral=True)
        await self.check_winner(interaction)

    @discord.ui.button(label="📜", style=discord.ButtonStyle.primary)
    async def select_paper(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choices[interaction.user.id] = '📜'
        await interaction.response.send_message(f"You chose 📜", ephemeral=True)
        await self.check_winner(interaction)

    @discord.ui.button(label="✂️", style=discord.ButtonStyle.primary)
    async def select_scissors(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choices[interaction.user.id] = '✂️'
        await interaction.response.send_message(f"You chose ✂️", ephemeral=True)
        await self.check_winner(interaction)

    async def check_winner(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        if len(self.choices) == 2:
            user_ids = list(self.choices.keys())
            user_choices = [self.choices[user_id] for user_id in user_ids]

            result, winner, loser = self.determine_winner(user_ids, user_choices)

            if result == "It's a tie!":
                await self.update_leaderboard(guild_id, user_ids[0], user_ids[1], draw=True)
                embed = discord.Embed(
                    title="᲼Game Over",
                    description="᲼᲼᲼It's a tie!",
                    color=discord.Color.from_str("#8e4cd0")
                )
                embed.set_footer(text="Thanks for playing!")
            else:
                await self.update_leaderboard(guild_id, winner, loser)
                winner_user = interaction.guild.get_member(winner)
                loser_user = interaction.guild.get_member(loser)
                embed = discord.Embed(
                    title="Game Over!",
                    description=f"{winner_user.mention} wins!",
                    color=discord.Color.from_str("#8e4cd0")
                )
                embed.add_field(name="", value=f"{self.choices[winner]} beats {self.choices[loser]}")
                embed.add_field(name="", value=f"\n")
                embed.set_footer(text="Thanks for playing!")

            # Show rematch button
            rematch_view = RematchView(self.opponent, self.challenger)
            await self.edit_response(content="", embed=embed, view=rematch_view)
            self.stop()

    def determine_winner(self, user_ids, user_choices):
        outcomes = {
            ('🪨', '✂️'),
            ('📜', '🪨'),
            ('✂️', '📜'),
        }

        user1, user2 = user_ids
        choice1, choice2 = user_choices

        if choice1 == choice2:
            return "It's a tie!", None, None
        elif (choice1, choice2) in outcomes:
            return "Winner determined", user1, user2
        else:
            return "Winner determined", user2, user1

# ---------------------------------------------------------------------------------------------------------------------
# Rematch Button + View
# ---------------------------------------------------------------------------------------------------------------------
class RematchButton(discord.ui.Button):
    def __init__(self, opponent, challenger):
        super().__init__(label="🔁 Rematch", style=discord.ButtonStyle.success)
        self.opponent = opponent
        self.challenger = challenger

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.opponent and interaction.user != self.challenger:
            await interaction.response.send_message("You're not one of the players!", ephemeral=True)
            return

        await interaction.response.defer()

        embed = discord.Embed(
            title="᲼᲼᲼᲼᲼᲼᲼Game On!",
            description="Choose rock, paper, or scissors!",
            color=discord.Color.from_str("#8e4cd0")
        )

        followup_msg = await interaction.followup.send(embed=embed)
        view = GameView(self.opponent, self.challenger, followup_msg)
        await followup_msg.edit(embed=embed, view=view)


class RematchView(View):
    def __init__(self, opponent, challenger):
        super().__init__(timeout=None)
        self.add_item(RematchButton(opponent, challenger))

# ---------------------------------------------------------------------------------------------------------------------
# RPS Cog
# ---------------------------------------------------------------------------------------------------------------------
class RPSCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(description="User: Play a game of rock, paper, scissors.")
    async def rps(self, interaction: discord.Interaction, opponent: discord.Member):
        await interaction.response.defer()

        try:
            embed = discord.Embed(
                title=f"᲼᲼᲼᲼᲼᲼Rock, Paper, Scissors Challenge!",
                description=f"{opponent.mention}, you have been challenged by {interaction.user.mention}.",
                color=discord.Color.from_str("#8e4cd0")
            )
            embed.set_footer(text="᲼᲼᲼᲼Click a button below to accept or reject the challenge")

            view = ChallengeView(opponent, interaction.user, interaction)

            await interaction.followup.send(
                content=f"{interaction.user.mention} has challenged {opponent.mention}!",
                embed=embed,
                view=view
            )

        except Exception as e:
            logger.error(f"Error in /rps: {e}")
            await interaction.followup.send("Error: Could not initiate RPS challenge.", ephemeral=True)

        finally:
            await log_command_usage(self.bot, interaction)


# ---------------------------------------------------------------------------------------------------------------------
# Setup Function
# ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS leaderboards (
                guild_id INTEGER,
                game TEXT,
                user_id INTEGER,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                draws INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, game, user_id)
            )
        ''')
        await conn.commit()
    await bot.add_cog(RPSCog(bot))