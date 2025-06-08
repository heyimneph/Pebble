import asyncio
import aiosqlite

from core import utils

class DummyPermissions:
    def __init__(self, administrator: bool):
        self.administrator = administrator

class DummyUser:
    def __init__(self, user_id: int, administrator: bool = False):
        self.id = user_id
        self.guild_permissions = DummyPermissions(administrator)

class DummyInteraction:
    def __init__(self, user: DummyUser, guild_id: int):
        self.user = user
        self.guild_id = guild_id

def test_get_embed_colour(monkeypatch, tmp_path):
    db = tmp_path / "test.db"
    monkeypatch.setattr(utils, "DB_PATH", str(db))

    async def setup_db():
        async with aiosqlite.connect(db) as conn:
            await conn.execute(
                """
                CREATE TABLE customisation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    UNIQUE(guild_id, type)
                )
                """
            )
            await conn.execute(
                "INSERT INTO customisation (guild_id, type, value) VALUES (?, ?, ?)",
                (123, "embed_color", "FF0000"),
            )
            await conn.commit()

    asyncio.run(setup_db())
    colour = asyncio.run(utils.get_embed_colour(123))
    assert colour == int("FF0000", 16)

def test_get_embed_colour_default(monkeypatch, tmp_path):
    db = tmp_path / "test.db"
    monkeypatch.setattr(utils, "DB_PATH", str(db))

    async def setup_db():
        async with aiosqlite.connect(db) as conn:
            await conn.execute(
                """
                CREATE TABLE customisation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    UNIQUE(guild_id, type)
                )
                """
            )
            await conn.commit()

    asyncio.run(setup_db())
    colour = asyncio.run(utils.get_embed_colour(123))
    assert colour == 0xC4A7EC

def test_check_permissions_admin(monkeypatch, tmp_path):
    db = tmp_path / "test.db"
    monkeypatch.setattr(utils, "DB_PATH", str(db))

    async def setup_db():
        async with aiosqlite.connect(db) as conn:
            await conn.execute(
                """
                CREATE TABLE permissions (
                    guild_id INTEGER,
                    user_id INTEGER,
                    can_use_commands BOOLEAN DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            await conn.commit()

    asyncio.run(setup_db())
    interaction = DummyInteraction(DummyUser(1, administrator=True), 123)
    result = asyncio.run(utils.check_permissions(interaction))
    assert result is True

def test_check_permissions_allowed(monkeypatch, tmp_path):
    db = tmp_path / "test.db"
    monkeypatch.setattr(utils, "DB_PATH", str(db))

    async def setup_db():
        async with aiosqlite.connect(db) as conn:
            await conn.execute(
                """
                CREATE TABLE permissions (
                    guild_id INTEGER,
                    user_id INTEGER,
                    can_use_commands BOOLEAN DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            await conn.execute(
                "INSERT INTO permissions (guild_id, user_id, can_use_commands) VALUES (?, ?, ?)",
                (123, 1, 1),
            )
            await conn.commit()

    asyncio.run(setup_db())
    interaction = DummyInteraction(DummyUser(1), 123)
    result = asyncio.run(utils.check_permissions(interaction))
    assert result == 1

def test_check_permissions_denied(monkeypatch, tmp_path):
    db = tmp_path / "test.db"
    monkeypatch.setattr(utils, "DB_PATH", str(db))

    async def setup_db():
        async with aiosqlite.connect(db) as conn:
            await conn.execute(
                """
                CREATE TABLE permissions (
                    guild_id INTEGER,
                    user_id INTEGER,
                    can_use_commands BOOLEAN DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            await conn.commit()

    asyncio.run(setup_db())
    interaction = DummyInteraction(DummyUser(2), 123)
    result = asyncio.run(utils.check_permissions(interaction))
    assert result is None
