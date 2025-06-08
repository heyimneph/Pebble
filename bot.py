import discord
import aiosqlite
import asyncio
import os
import logging

from datetime import datetime, timezone
from config import client, DISCORD_TOKEN, perform_sync
from core.utils import DB_PATH

# ---------------------------------------------------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------------------------------------------
# Customisation Functions
# ---------------------------------------------------------------------------------------------------------------------

async def get_embed_colour():
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute('SELECT value FROM customisation WHERE type = ?', ("embed_color",)) as cursor:
            row = await cursor.fetchone()
            if row:
                return int(row[0], 16)
            return 0x3498db

async def get_bio_settings():
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute('SELECT value FROM customisation WHERE type = ?', ("activity_type",)) as cursor:
            activity_type_doc = await cursor.fetchone()
        async with conn.execute('SELECT value FROM customisation WHERE type = ?', ("bio",)) as cursor:
            bio_doc = await cursor.fetchone()
        if activity_type_doc and bio_doc:
            return activity_type_doc[0], bio_doc[0]
        return None, None

# ---------------------------------------------------------------------------------------------------------------------
# Event Handlers
# ---------------------------------------------------------------------------------------------------------------------

@client.event
async def on_ready():
    print(f'Bot is logged in as {client.user.name} ({client.user.id})')
    synced_count = await perform_sync()
    print(f"{synced_count} commands synced")

# ---------------------------------------------------------------------------------------------------------------------
# Main Function
# ---------------------------------------------------------------------------------------------------------------------

async def main():
    await client.load_extension("core.initialisation")

    for filename in os.listdir('cogs'):
        if not filename.endswith('.py'):
            continue

        module_name = filename[:-3]

        # Skip files that start with an underscore or are not valid module names
        if module_name.startswith('_') or not module_name.isidentifier():
            continue

        await client.load_extension(f'cogs.{module_name}')
        print(f"Loading {module_name}...")

    print("Starting Bot...")

    await client.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
