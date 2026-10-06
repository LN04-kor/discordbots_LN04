from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from math import isqrt
from pathlib import Path
import sqlite3
import threading

import discord
import uvicorn
from discord.ext import commands
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field


DATABASE_PATH = Path(__file__).with_name("klukai.db")
API_HOST = "127.0.0.1"
API_PORT = 8000
NOTIFICATION_TYPES = {"join", "left"}
RANKING_TIMEZONE = timezone(timedelta(hours=9), name="KST")
LEVEL_EXP_BASE = 250

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS guild_notification_channels (
                guild_id INTEGER NOT NULL,
                notification_type TEXT NOT NULL,
                channel_id INTEGER,
                PRIMARY KEY (guild_id, notification_type)
            );

            CREATE TABLE IF NOT EXISTS guild_experience_settings (
                guild_id INTEGER PRIMARY KEY,
                experience_enabled INTEGER NOT NULL DEFAULT 1,
                levels_enabled INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS member_experience (
                guild_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                total_exp INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, member_id)
            );

            CREATE TABLE IF NOT EXISTS daily_member_experience (
                guild_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                experience_date TEXT NOT NULL,
                exp INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, member_id, experience_date)
            );

            CREATE TABLE IF NOT EXISTS experience_events (
                message_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                exp INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_member_experience_ranking
                ON member_experience (guild_id, total_exp DESC);
            CREATE INDEX IF NOT EXISTS idx_daily_experience_ranking
                ON daily_member_experience (guild_id, experience_date, exp DESC);
            """
        )


def validate_notification_type(notification_type: str):
    if notification_type not in NOTIFICATION_TYPES:
        raise HTTPException(404, "Notification type must be either 'join' or 'left'.")


def get_settings(connection, guild_id: int):
    row = connection.execute(
        "SELECT experience_enabled, levels_enabled FROM guild_experience_settings WHERE guild_id = ?",
        (guild_id,),
    ).fetchone()
    if row is None:
        return {"experience_enabled": True, "levels_enabled": True}
    return {"experience_enabled": bool(row["experience_enabled"]), "levels_enabled": bool(row["levels_enabled"])}


def get_level(total_exp: int):
    return isqrt(total_exp // LEVEL_EXP_BASE) + 1


def level_details(total_exp: int):
    level = get_level(total_exp)
    level_start_exp = (level - 1) ** 2 * LEVEL_EXP_BASE
    next_level_exp = level**2 * LEVEL_EXP_BASE
    return {
        "level": level,
        "level_start_exp": level_start_exp,
        "next_level_exp": next_level_exp,
        "exp_to_next_level": next_level_exp - total_exp,
    }


def period_start(period: str):
    now = datetime.now(RANKING_TIMEZONE)
    if period == "daily":
        return now.date()
    if period == "weekly":
        return (now - timedelta(days=now.weekday())).date()
    return None


def member_period_exp(connection, guild_id: int, member_id: int, period: str):
    if period == "all":
        row = connection.execute(
            "SELECT total_exp AS exp FROM member_experience WHERE guild_id = ? AND member_id = ?",
            (guild_id, member_id),
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT COALESCE(SUM(exp), 0) AS exp FROM daily_member_experience "
            "WHERE guild_id = ? AND member_id = ? AND experience_date >= ?",
            (guild_id, member_id, period_start(period).isoformat()),
        ).fetchone()
    return 0 if row is None else row["exp"]


class NotificationChannelRequest(BaseModel):
    channel_id: int | None = None


class GuildExperienceSettingsRequest(BaseModel):
    enabled: bool


class ExperienceAwardRequest(BaseModel):
    message_id: int
    exp: int = Field(ge=1, le=1000)
    occurred_at: datetime | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Klukai API", description="Server data management API for Discord bots.", lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.put("/guilds/{guild_id}/channels/{notification_type}")
async def set_notification_channel(guild_id: int, notification_type: str, request: NotificationChannelRequest):
    validate_notification_type(notification_type)
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO guild_notification_channels (guild_id, notification_type, channel_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, notification_type) DO UPDATE SET channel_id = excluded.channel_id",
            (guild_id, notification_type, request.channel_id),
        )
    return {"guild_id": guild_id, "notification_type": notification_type, "channel_id": request.channel_id}


@app.get("/guilds/{guild_id}/channels/{notification_type}")
async def get_notification_channel(guild_id: int, notification_type: str):
    validate_notification_type(notification_type)
    with get_connection() as connection:
        row = connection.execute(
            "SELECT channel_id FROM guild_notification_channels WHERE guild_id = ? AND notification_type = ?",
            (guild_id, notification_type),
        ).fetchone()
    if row is None or row["channel_id"] is None:
        raise HTTPException(404, "No notification channel setting was found for this guild.")
    return {"guild_id": guild_id, "notification_type": notification_type, "channel_id": row["channel_id"]}


@app.get("/guilds/{guild_id}/settings")
async def get_guild_settings(guild_id: int):
    with get_connection() as connection:
        settings = get_settings(connection, guild_id)
        channels = connection.execute(
            "SELECT notification_type, channel_id FROM guild_notification_channels WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
    notification_channels = {"join": None, "left": None}
    for channel in channels:
        notification_channels[channel["notification_type"]] = channel["channel_id"]
    return {
        "guild_id": guild_id,
        **settings,
        "notification_channels": notification_channels,
    }


@app.get("/guilds/{guild_id}/experience-settings")
async def get_experience_settings(guild_id: int):
    with get_connection() as connection:
        return {"guild_id": guild_id, **get_settings(connection, guild_id)}


@app.put("/guilds/{guild_id}/experience-settings")
async def set_experience_enabled(guild_id: int, request: GuildExperienceSettingsRequest):
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO guild_experience_settings (guild_id, experience_enabled) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET experience_enabled = excluded.experience_enabled",
            (guild_id, request.enabled),
        )
        return {"guild_id": guild_id, **get_settings(connection, guild_id)}


@app.put("/guilds/{guild_id}/level-settings")
async def set_levels_enabled(guild_id: int, request: GuildExperienceSettingsRequest):
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO guild_experience_settings (guild_id, levels_enabled) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET levels_enabled = excluded.levels_enabled",
            (guild_id, request.enabled),
        )
        return {"guild_id": guild_id, **get_settings(connection, guild_id)}


@app.post("/guilds/{guild_id}/members/{member_id}/experience")
async def award_experience(guild_id: int, member_id: int, request: ExperienceAwardRequest):
    created_at = (request.occurred_at or datetime.now(RANKING_TIMEZONE)).astimezone(RANKING_TIMEZONE)
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        settings = get_settings(connection, guild_id)
        existing = connection.execute("SELECT exp FROM experience_events WHERE message_id = ?", (request.message_id,)).fetchone()
        if existing is not None:
            return {"awarded": False, "reason": "duplicate_message", "exp": existing["exp"]}
        if not settings["experience_enabled"]:
            return {"awarded": False, "reason": "experience_disabled", "exp": 0}
        connection.execute(
            "INSERT INTO experience_events (message_id, guild_id, member_id, exp, created_at) VALUES (?, ?, ?, ?, ?)",
            (request.message_id, guild_id, member_id, request.exp, created_at.isoformat()),
        )
        connection.execute(
            "INSERT INTO member_experience (guild_id, member_id, total_exp, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, member_id) DO UPDATE SET total_exp = total_exp + excluded.total_exp, updated_at = excluded.updated_at",
            (guild_id, member_id, request.exp, created_at.isoformat()),
        )
        connection.execute(
            "INSERT INTO daily_member_experience (guild_id, member_id, experience_date, exp) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, member_id, experience_date) DO UPDATE SET exp = exp + excluded.exp",
            (guild_id, member_id, created_at.date().isoformat(), request.exp),
        )
        total_exp = connection.execute(
            "SELECT total_exp FROM member_experience WHERE guild_id = ? AND member_id = ?", (guild_id, member_id)
        ).fetchone()["total_exp"]
    return {"awarded": True, "exp": request.exp, "total_exp": total_exp, **level_details(total_exp)}


@app.get("/guilds/{guild_id}/members/{member_id}/profile")
async def get_member_profile(guild_id: int, member_id: int):
    with get_connection() as connection:
        total_exp = member_period_exp(connection, guild_id, member_id, "all")
        total_rank = connection.execute(
            "SELECT COUNT(*) + 1 AS rank FROM member_experience WHERE guild_id = ? AND total_exp > ?",
            (guild_id, total_exp),
        ).fetchone()["rank"]
        settings = get_settings(connection, guild_id)
        return {
            "guild_id": guild_id,
            "member_id": member_id,
            "total_exp": total_exp,
            "daily_exp": member_period_exp(connection, guild_id, member_id, "daily"),
            "weekly_exp": member_period_exp(connection, guild_id, member_id, "weekly"),
            "rank": total_rank,
            "levels_enabled": settings["levels_enabled"],
            **level_details(total_exp),
        }


@app.get("/guilds/{guild_id}/rankings")
async def get_rankings(guild_id: int, period: str = Query("all", pattern="^(all|daily|weekly)$"), limit: int = Query(10, ge=1, le=50)):
    with get_connection() as connection:
        if period == "all":
            rows = connection.execute(
                "SELECT member_id, total_exp AS exp FROM member_experience WHERE guild_id = ? "
                "ORDER BY total_exp DESC, member_id ASC LIMIT ?", (guild_id, limit)
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT member_id, SUM(exp) AS exp FROM daily_member_experience "
                "WHERE guild_id = ? AND experience_date >= ? GROUP BY member_id "
                "ORDER BY exp DESC, member_id ASC LIMIT ?", (guild_id, period_start(period).isoformat(), limit)
            ).fetchall()
    return {"guild_id": guild_id, "period": period, "rankings": [{"rank": index, "member_id": row["member_id"], "exp": row["exp"]} for index, row in enumerate(rows, start=1)]}


@bot.event
async def on_ready():
    print(f"{bot.user} logged")


def run_api():
    uvicorn.run(app, host=API_HOST, port=API_PORT)


def main():
    initialize_database()
    threading.Thread(target=run_api, daemon=True).start()
    bot.run("YOUR_BOT_TOKEN")


if __name__ == "__main__":
    main()

