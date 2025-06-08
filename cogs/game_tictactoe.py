import random
import discord
import aiosqlite
import logging

from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View

from core.utils import check_permissions, log_command_usage

# ---------------------------------------------------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------------------------------------------------
db_path = './data/databases/pebble.db'

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
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
            game_view = GameView(self.opponent, self.challenger, interaction)
            game_view.create_board()
            await interaction.response.edit_message(
                content=f"Game started! It's {game_view.current_player.mention}'s turn",
                embed=None,
                view=game_view
            )

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
# Rematch View
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

        view = GameView(self.opponent, self.challenger, interaction)
        view.create_board()

        followup_msg = await interaction.followup.send(
            content=f"Game started! It's {view.current_player.mention}'s turn"
        )
        await followup_msg.edit(view=view)
        view.response_target = followup_msg


class RematchView(View):
    def __init__(self, opponent, challenger):
        super().__init__(timeout=None)
        self.add_item(RematchButton(opponent, challenger))

# ---------------------------------------------------------------------------------------------------------------------
# Game View
# ---------------------------------------------------------------------------------------------------------------------
class GameView(View):
    def __init__(self, opponent: discord.Member, challenger: discord.User, response_target):
        super().__init__()
        self.opponent = opponent
        self.challenger = challenger
        self.response_target = response_target  # Can be Interaction or WebhookMessage
        self.board = [[" " for _ in range(3)] for _ in range(3)]
        self.game_over = False

        players = [self.challenger, self.opponent]
        random.shuffle(players)
        self.current_player = players[0]

    def add_rematch_button(self):
        # Left blank spacer
        self.add_item(Button(label="\u200b", style=discord.ButtonStyle.secondary, disabled=True, row=3))

        # Rematch button
        rematch = RematchButton(self.opponent, self.challenger)
        rematch.row = 3
        self.add_item(rematch)

        # Right blank spacer
        self.add_item(Button(label="\u200b", style=discord.ButtonStyle.secondary, disabled=True, row=3))

    async def edit_response(self, **kwargs):
        if isinstance(self.response_target, discord.Interaction):
            await self.response_target.edit_original_response(**kwargs)
        else:
            await self.response_target.edit(**kwargs)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user == self.opponent or interaction.user == self.challenger

    async def update_leaderboard(self, guild_id, winner_id, loser_id, draw=False):
        game_name = "TicTacToe"
        async with aiosqlite.connect(db_path) as db:
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

    def create_board(self):
        self.clear_items()
        for i in range(3):
            for j in range(3):
                button = Button(label="\u200b", style=discord.ButtonStyle.secondary, custom_id=f"cell_{i}_{j}", row=i)
                button.callback = self.make_move
                self.add_item(button)

    async def make_move(self, interaction: discord.Interaction):
        if interaction.user != self.current_player or self.game_over:
            await interaction.response.defer()
            return

        custom_id = interaction.data['custom_id']
        row, col = map(int, custom_id.split('_')[1:])

        if self.board[row][col] != " ":
            await interaction.response.defer()
            return

        self.board[row][col] = "X" if self.current_player == self.challenger else "O"

        button = discord.utils.get(self.children, custom_id=custom_id)
        button.label = self.board[row][col]
        button.disabled = True
        button.style = discord.ButtonStyle.primary if self.board[row][col] == "X" else discord.ButtonStyle.danger

        winner, winning_line = self.check_winner()
        if winner:
            for win_button_custom_id in winning_line:
                win_button = discord.utils.get(self.children, custom_id='_'.join(map(str, win_button_custom_id)))
                win_button.style = discord.ButtonStyle.success
            self.game_over = True
            self.disable_all_buttons()
            content = f"{self.current_player.mention} wins!"

            await self.update_leaderboard(
                interaction.guild_id,
                self.current_player.id,
                self.opponent.id if self.current_player == self.challenger else self.challenger.id
            )

            await interaction.response.edit_message(content=content, view=self)

            self.add_rematch_button()
            await self.edit_response(view=self)


        elif all(self.board[i][j] != " " for i in range(3) for j in range(3)):
            self.game_over = True
            self.disable_all_buttons()
            content = "It's a draw!"

            await self.update_leaderboard(interaction.guild_id, self.challenger.id, self.opponent.id, draw=True)
            await interaction.response.edit_message(content=content, view=self)

            rematch_view = RematchView(self.opponent, self.challenger)
            await self.edit_response(view=rematch_view)

        else:
            self.current_player = self.opponent if self.current_player == self.challenger else self.challenger
            content = f"It's {self.current_player.mention}'s turn"
            await interaction.response.edit_message(content=content, view=self)

    def check_winner(self):
        for i in range(3):
            if self.board[i][0] == self.board[i][1] == self.board[i][2] != " ":
                return True, [('cell', i, j) for j in range(3)]
            if self.board[0][i] == self.board[1][i] == self.board[2][i] != " ":
                return True, [('cell', j, i) for j in range(3)]

        if self.board[0][0] == self.board[1][1] == self.board[2][2] != " ":
            return True, [('cell', i, i) for i in range(3)]
        if self.board[0][2] == self.board[1][1] == self.board[2][0] != " ":
            return True, [('cell', i, 2 - i) for i in range(3)]

        return False, None

    def disable_all_buttons(self):
        for item in self.children:
            if isinstance(item, Button):
                item.disabled = True

# ---------------------------------------------------------------------------------------------------------------------
# TicTacToe Cog
# ---------------------------------------------------------------------------------------------------------------------
class TicTacToe(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(description="User: Play a game of TicTacToe.")
    async def ttt(self, interaction: discord.Interaction, opponent: discord.Member):
        await interaction.response.defer()

        try:
            embed = discord.Embed(
                title="᲼᲼᲼᲼᲼᲼᲼᲼᲼᲼᲼᲼TicTacToe Challenge!",
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
            logger.error(f"Error in /ttt: {e}")
            await interaction.followup.send("Error: Could not start the TicTacToe challenge.", ephemeral=True)

        finally:
            await log_command_usage(self.bot, interaction)


# ---------------------------------------------------------------------------------------------------------------------
# Setup Function
# ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    async with aiosqlite.connect(db_path) as conn:
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
    await bot.add_cog(TicTacToe(bot))
