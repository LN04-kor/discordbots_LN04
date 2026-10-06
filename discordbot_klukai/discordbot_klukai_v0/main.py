import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import discord
import uvicorn
from discord.ext import commands
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


DATABASE_PATH = Path(__file__).with_name("klukai.db")
API_HOST = "127.0.0.1"
API_PORT = 8000

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)


# Database helpers

def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                notification_channel_id INTEGER
            )
            """
        )


# HTTP API

class NotificationChannelRequest(BaseModel):
    channel_id: int | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Klukai API",
    description="Server data management API for Discord bots.",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.put("/guilds/{guild_id}/channels/notification")
async def set_notification_channel(
    guild_id: int,
    request: NotificationChannelRequest,
):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO guild_settings (guild_id, notification_channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                notification_channel_id = excluded.notification_channel_id
            """,
            (guild_id, request.channel_id),
        )

    return {
        "guild_id": guild_id,
        "notification_channel_id": request.channel_id,
    }


@app.get("/guilds/{guild_id}/channels/notification")
async def get_notification_channel(guild_id: int):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT notification_channel_id
            FROM guild_settings
            WHERE guild_id = ?
            """,
            (guild_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No notification channel setting was found for this guild.",
        )

    return {
        "guild_id": guild_id,
        "notification_channel_id": row["notification_channel_id"],
    }


# Discord bot

@bot.event
async def on_ready():
    print(f"{bot.user} logged")


# Application entry point

def run_api():
    uvicorn.run(app, host=API_HOST, port=API_PORT)


def main():
    initialize_database()

    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()

    bot.run("YOUR_BOT_TOKEN")


if __name__ == "__main__":
    main()
