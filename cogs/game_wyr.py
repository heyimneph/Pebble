import discord
import logging
import random
import json
import os

from discord import app_commands
from discord.ext import commands
from core.utils import log_command_usage, get_embed_colour

# ---------------------------------------------------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------------------------------------------------
wyr_file = './prompt_bank/would_you_rather.json'

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------------------------------------------------
# Buttons and Views
# ---------------------------------------------------------------------------------------------------------------------
class WYRVoteButton(discord.ui.Button):
    def __init__(self, label, choice, style):
        super().__init__(label=label, style=style)
        self.choice = choice

    async def callback(self, interaction: discord.Interaction):
        parent: WYRVoteView = self.view
        await parent.register_vote(interaction, self.choice)


class WYRNextButton(discord.ui.Button):
    def __init__(self, bot, category):
        super().__init__(label="Next", style=discord.ButtonStyle.secondary)
        self.bot = bot
        self.category = category

    async def callback(self, interaction: discord.Interaction):
        try:
            if not os.path.exists(wyr_file):
                await interaction.response.send_message("Error: WYR file not found.", ephemeral=True)
                return

            with open(wyr_file, 'r', encoding='utf-8') as f:
                questions = json.load(f)

            if self.category:
                questions = [q for q in questions if q.get("category", "").lower() == self.category.lower()]

            if not questions:
                await interaction.response.send_message("Error: No questions found in this category.", ephemeral=True)
                return

            # 🎲 Get new question and embed
            question = random.choice(questions)
            colour = await get_embed_colour(interaction.guild.id)
            bot_avatar = self.bot.user.display_avatar.url

            embed = discord.Embed(
                title="💭 Would You Rather...",
                description=f"🇦 {question['a']}\n\n 🇧 {question['b']}",
                color=colour,
                timestamp=discord.utils.utcnow()
            )

            embed.set_thumbnail(url=bot_avatar)
            if "category" in question and question["category"]:
                embed.set_footer(text=f"Category: {question['category']}")
            else:
                embed.set_footer(text="Would You Rather • Choose wisely!")

            await interaction.response.send_message(embed=embed, view=new_view)
            new_view.message = await interaction.original_response()


        except Exception as e:
            logger.error(f"Error posting new WYR from Next: {e}")
            await interaction.response.send_message("Error: Something went wrong.", ephemeral=True)

class WYRVoteView(discord.ui.View):
    def __init__(self, bot, question, category=None, message=None):
        super().__init__(timeout=None)
        self.bot = bot
        self.question = question
        self.category = category
        self.message = message
        self.votes = {}

        self.add_item(WYRVoteButton("🇦", "A", discord.ButtonStyle.primary))
        self.add_item(WYRNextButton(bot, category))
        self.add_item(WYRVoteButton("🇧", "B", discord.ButtonStyle.primary))

    def disable_all_items(self):
        for item in self.children:
            if isinstance(item, WYRVoteButton):
                item.disabled = True

    async def register_vote(self, interaction: discord.Interaction, choice: str):
        user_id = interaction.user.id
        if user_id in self.votes:
            await interaction.response.send_message("You've already voted!", ephemeral=True)
            return

        self.votes[user_id] = choice
        await interaction.response.send_message(f"Vote registered for option {choice}!", ephemeral=True)

        if len(self.votes) >= 2:
            await self.reveal_results(interaction)

    async def reveal_results(self, interaction: discord.Interaction):
        self.disable_all_items()

        counts = {"A": 0, "B": 0}
        user_mentions = {"A": [], "B": []}

        for user_id, choice in self.votes.items():
            try:
                user = interaction.guild.get_member(user_id) or interaction.client.get_user(user_id)
                if not user:
                    user = await interaction.client.fetch_user(user_id)
                user_mentions[choice].append(user.mention)
                counts[choice] += 1
            except Exception as e:
                logger.warning(f"Failed to resolve user ID {user_id}: {e}")

        embed = discord.Embed(
            title="💭 Would You Rather...",
            description=f"🇦 {self.question['a']}\n 🇧 {self.question['b']}",
            color=discord.Color.green()
        )

        embed.add_field(name="", value="", inline=False)
        embed.add_field(name="🇦 Votes", value="\n".join(user_mentions["A"]) or "*None*", inline=True)
        embed.add_field(name="🇧 Votes", value="\n".join(user_mentions["B"]) or "*None*", inline=True)

        if self.category:
            embed.set_footer(text=f"Category: {self.category}")
        else:
            embed.set_footer(text="Would You Rather • Results")

        await self.message.edit(embed=embed, view=self)


# ---------------------------------------------------------------------------------------------------------------------
# Would You Rather Cog
# ---------------------------------------------------------------------------------------------------------------------
class WouldYouRatherCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

# ------------------------------------------------------------------------------------------------------------------
# Commands
# ------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="wyr", description="User: Get a fun 'Would You Rather' question.")
    @app_commands.describe(category="Optionally choose a category")
    async def wyr(self, interaction: discord.Interaction, category: str = None):
        try:
            if not os.path.exists(wyr_file):
                await interaction.response.send_message("Error: WYR file not found.", ephemeral=True)
                return

            with open(wyr_file, 'r', encoding='utf-8') as f:
                questions = json.load(f)

            if category:
                questions = [q for q in questions if q.get("category", "").lower() == category.lower()]

            if not questions:
                await interaction.response.send_message("Error: No questions found in this category.", ephemeral=True)
                return

            question = random.choice(questions)
            colour = await get_embed_colour(interaction.guild.id)
            bot_avatar = self.bot.user.display_avatar.url

            embed = discord.Embed(
                title="💭 Would You Rather...",
                description=f"🇦 {question['a']}\n\n 🇧 {question['b']}",
                color=colour,
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=bot_avatar)
            embed.set_footer(
                text=f"Category: {question['category']}" if question.get(
                    "category") else "Would You Rather • Choose wisely!"
            )

            view = WYRVoteView(self.bot, question, category)
            await interaction.response.send_message(embed=embed, view=view)
            view.message = await interaction.original_response()

        except Exception as e:
            logger.error(f"Error in /wyr: {e}")
            await interaction.followup.send("Error: Something went wrong.", ephemeral=True)
        finally:
            await log_command_usage("wyr", interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="add_wyr", description="Admin: Add a new 'Would You Rather' question.")
    @app_commands.default_permissions(administrator=True)
    async def add_wyr(self, interaction: discord.Interaction, a: str, b: str, category: str = None):
        try:
            if os.path.exists(wyr_file):
                with open(wyr_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = []

            data.append({
                "a": a,
                "b": b,
                "category": category if category else ""
            })

            with open(wyr_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            await interaction.response.send_message("Success: Question added!", ephemeral=True)

        except Exception as e:
            logger.error(f"Error in add_wyr: {e}")
            await interaction.response.send_message("Error: Could not add question.", ephemeral=True)
        finally:
            await log_command_usage("add_wyr", interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="remove_wyr", description="Admin: Remove a 'Would You Rather' question by number.")
    @app_commands.default_permissions(administrator=True)
    async def remove_wyr(self, interaction: discord.Interaction, index: int):
        try:
            if not os.path.exists(wyr_file):
                await interaction.response.send_message("Error: File not found.", ephemeral=True)
                return

            with open(wyr_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if index < 1 or index > len(data):
                await interaction.response.send_message("Error: Index out of range.", ephemeral=True)
                return

            removed = data.pop(index - 1)

            with open(wyr_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            await interaction.response.send_message(
                f"Success: Removed question:\n**A:** {removed['a']}\n**B:** {removed['b']}",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error in remove_wyr: {e}")
            await interaction.response.send_message("Error: Could not remove question.", ephemeral=True)
        finally:
            await log_command_usage("remove_wyr", interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="import_wyr", description="Admin: Import a new WYR set from a JSON file.")
    @app_commands.default_permissions(administrator=True)
    async def import_wyr(self, interaction: discord.Interaction, attachment: discord.Attachment):
        try:
            if not attachment.filename.endswith(".json"):
                await interaction.response.send_message("Error: Please upload a valid `.json` file.", ephemeral=True)
                return

            content = await attachment.read()
            questions = json.loads(content)

            if not isinstance(questions, list) or not all("a" in q and "b" in q for q in questions):
                await interaction.response.send_message("Error: Invalid WYR format. Each item must have 'a' and 'b'.",
                                                        ephemeral=True)
                return

            with open(wyr_file, 'w', encoding='utf-8') as f:
                json.dump(questions, f, indent=2)

            await interaction.response.send_message(f"Success: Imported {len(questions)} questions from file.",
                                                    ephemeral=True)

        except Exception as e:
            logger.error(f"Error in import_wyr: {e}")
            await interaction.response.send_message("Error: Failed to import WYR questions.", ephemeral=True)
        finally:
            await log_command_usage("import_wyr", interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="export_wyr", description="Admin: Export all WYR questions.")
    @app_commands.default_permissions(administrator=True)
    async def export_wyr(self, interaction: discord.Interaction):
        try:
            if not os.path.exists(wyr_file):
                await interaction.response.send_message("Error: File not found.", ephemeral=True)
                return

            await interaction.response.send_message(
                content="Success: Here's the `would_you_rather.json` file.",
                file=discord.File(wyr_file),
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error in export_wyr: {e}")
            await interaction.response.send_message("Error: Could not export file.", ephemeral=True)
        finally:
            await log_command_usage("export_wyr", interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name='list_wyr', description='User: View all available "Would You Rather" questions.')
    async def list_wyr(self, interaction: discord.Interaction):
        try:
            if not os.path.exists(self.prompt_file):
                await interaction.response.send_message("Error: WYR file not found.", ephemeral=True)
                return

            with open(self.prompt_file, 'r', encoding='utf-8') as f:
                questions = json.load(f)

            if not questions:
                await interaction.response.send_message("Error: No WYR questions found.", ephemeral=True)
                return

            embeds = []
            buffer = ""
            for i, q in enumerate(questions, start=1):
                line = f"**{i}.** Would you rather **{q['a']}** or **{q['b']}**? *(Category: {q['category']})*\n\n"
                if len(buffer) + len(line) > 1800:
                    embeds.append(discord.Embed(
                        title="Would You Rather Questions",
                        description=buffer,
                        color=discord.Color.pink()
                    ))
                    buffer = line
                else:
                    buffer += line

            if buffer:
                embeds.append(discord.Embed(
                    title="Would You Rather Questions",
                    description=buffer,
                    color=discord.Color.pink()
                ))

            await interaction.response.send_message(embed=embeds[0], ephemeral=True)
            for embed in embeds[1:]:
                await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in list_wyr: {e}")
            await interaction.response.send_message("Error: Could not list WYR questions.", ephemeral=True)
        finally:
            await log_command_usage("list_wyr", interaction)

# ---------------------------------------------------------------------------------------------------------------------
# Autocompletes
# ---------------------------------------------------------------------------------------------------------------------
    @wyr.autocomplete('category')
    async def category_autocomplete(self, interaction: discord.Interaction, current: str):
        if not os.path.exists(wyr_file):
            return []

        with open(wyr_file, 'r', encoding='utf-8') as f:
            questions = json.load(f)

        categories = sorted({q["category"] for q in questions if "category" in q})
        return [
            app_commands.Choice(name=cat, value=cat)
            for cat in categories if current.lower() in cat.lower()
        ][:25]


# ---------------------------------------------------------------------------------------------------------------------
# Setup Function
# ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    await bot.add_cog(WouldYouRatherCog(bot))
