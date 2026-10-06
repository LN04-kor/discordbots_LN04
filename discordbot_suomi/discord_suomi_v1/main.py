import asyncio
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import discord
from discord import app_commands
from discord.ext import commands


KLUKAI_API_URL = "http://127.0.0.1:8000"
MAX_MESSAGE_EXP = 1000
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
CUSTOM_EMOJI_PATTERN = re.compile(r"<a?:\w+:\d+>")
UNICODE_EMOJI_PATTERN = re.compile(
    "[\U0001F000-\U0001FAFF\U0001FC00-\U0001FFFD\u2600-\u27BF\uFE0F\u200D]"
)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)


def send_klukai_request(method, path, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{KLUKAI_API_URL}{path}", data=data, headers=headers, method=method)
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


async def klukai_request(method, path, payload=None):
    return await asyncio.to_thread(send_klukai_request, method, path, payload)


async def save_notification_channel(guild_id, notification_type, channel_id):
    try:
        await klukai_request("PUT", f"/guilds/{guild_id}/channels/{notification_type}", {"channel_id": channel_id})
        return True
    except (HTTPError, URLError, TimeoutError) as error:
        print(f"Could not save the notification channel in Klukai: {error}")
        return False


async def get_notification_channel(guild, notification_type):
    try:
        setting = await klukai_request("GET", f"/guilds/{guild.id}/channels/{notification_type}")
    except HTTPError as error:
        if error.code != 404:
            print(f"Could not load the notification channel from Klukai: {error}")
        return None
    except (URLError, TimeoutError) as error:
        print(f"Could not load the notification channel from Klukai: {error}")
        return None
    return bot.get_channel(setting["channel_id"])


def calculate_message_exp(message):
    content = URL_PATTERN.sub("", message.content)
    content = CUSTOM_EMOJI_PATTERN.sub("", content)
    content = UNICODE_EMOJI_PATTERN.sub("", content)
    text_length = len("".join(content.split()))
    if text_length:
        return min(text_length, MAX_MESSAGE_EXP)
    has_non_text_content = bool(
        message.attachments or message.stickers or URL_PATTERN.search(message.content)
        or CUSTOM_EMOJI_PATTERN.search(message.content) or UNICODE_EMOJI_PATTERN.search(message.content)
    )
    return 1 if has_non_text_content else 0


def get_ordinal(number):
    if 10 <= number % 100 <= 20:
        return f"{number}th"
    return f"{number}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th') }"


def get_stay_time(joined_at, left_at):
    total_days = (left_at - joined_at).days
    months, days = divmod(total_days, 31)
    if months == 0:
        return f"{days} days"
    if days == 0:
        return f"{months} months"
    return f"{months} months, {days} days"


@bot.event
async def on_member_join(member):
    channel = await get_notification_channel(member.guild, "join")
    if channel is None:
        return
    member_count = member.guild.member_count
    embed = discord.Embed(title=f"{get_ordinal(member_count)} member has entered", color=discord.Color.blue())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name=member.display_name, value=member.mention, inline=False)
    embed.add_field(name="Account Sign-up Date", value=f"{discord.utils.format_dt(member.created_at, style='F')} ({discord.utils.format_dt(member.created_at, style='R')})", inline=False)
    embed.add_field(name="Server Join Date", value=f"{discord.utils.format_dt(member.joined_at, style='F')} ({discord.utils.format_dt(member.joined_at, style='R')})", inline=False)
    await channel.send(embed=embed)


@bot.event
async def on_member_remove(member):
    channel = await get_notification_channel(member.guild, "left")
    if channel is None:
        return
    left_at = discord.utils.utcnow()
    embed = discord.Embed(title=f"{member.display_name} has left the server", color=discord.Color.blue())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name=member.display_name, value=member.mention, inline=False)
    embed.add_field(name="Server Leave Date", value=f"{discord.utils.format_dt(left_at, style='F')} ({discord.utils.format_dt(left_at, style='R')})", inline=False)
    embed.add_field(name="Time On Server", value=get_stay_time(member.joined_at, left_at), inline=False)
    await channel.send(embed=embed)


@bot.event
async def on_message(message):
    if message.guild is None or message.author.bot or message.content.startswith("/"):
        return
    exp = calculate_message_exp(message)
    if exp == 0:
        return
    try:
        await klukai_request(
            "POST",
            f"/guilds/{message.guild.id}/members/{message.author.id}/experience",
            {"message_id": message.id, "exp": exp, "occurred_at": message.created_at.isoformat()},
        )
    except (HTTPError, URLError, TimeoutError) as error:
        print(f"Could not award experience through Klukai: {error}")


async def update_guild_setting(interaction, path, enabled, label):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    try:
        await klukai_request("PUT", f"/guilds/{interaction.guild.id}/{path}", {"enabled": enabled})
    except (HTTPError, URLError, TimeoutError):
        await interaction.response.send_message("Klukai is unavailable. The setting was not changed.", ephemeral=True)
        return
    state = "enabled" if enabled else "disabled"
    await interaction.response.send_message(f"{label} has been {state}.", ephemeral=True)


@bot.tree.command(name="experience", description="Enable or disable this server's experience system.")
@app_commands.default_permissions(manage_guild=True)
async def set_experience(interaction: discord.Interaction, enabled: bool):
    await update_guild_setting(interaction, "experience-settings", enabled, "Experience system")


@bot.tree.command(name="levels", description="Enable or disable level display for this server.")
@app_commands.default_permissions(manage_guild=True)
async def set_levels(interaction: discord.Interaction, enabled: bool):
    await update_guild_setting(interaction, "level-settings", enabled, "Level display")


@bot.tree.command(name="status", description="Show this server's current bot settings.")
async def status(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    try:
        data = await klukai_request("GET", f"/guilds/{interaction.guild.id}/settings")
    except (HTTPError, URLError, TimeoutError):
        await interaction.response.send_message("Klukai is unavailable.", ephemeral=True)
        return

    channels = data["notification_channels"]
    join_channel = f"<#{channels['join']}>" if channels["join"] else "Disabled"
    left_channel = f"<#{channels['left']}>" if channels["left"] else "Disabled"
    experience_state = "Enabled" if data["experience_enabled"] else "Disabled"
    levels_state = "Enabled" if data["levels_enabled"] else "Disabled"

    embed = discord.Embed(title="Server bot status", color=discord.Color.blue())
    embed.add_field(name="Experience system", value=experience_state, inline=False)
    embed.add_field(name="Level display", value=levels_state, inline=False)
    embed.add_field(name="Join notifications", value=join_channel, inline=False)
    embed.add_field(name="Leave notifications", value=left_channel, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="help", description="Show available bot commands.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Suomi help",
        description="Experience requirements increase by level. Use /status to check this server's current settings.",
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="General commands",
        value="/profile [member] — Show an experience profile.\n"
        "/ranking [period] — Show all-time, daily, or weekly rankings.\n"
        "/status — Show experience, level, and notification settings.",
        inline=False,
    )
    embed.add_field(
        name="Server management",
        value="/experience <enabled> — Enable or disable experience gain.\n"
        "/levels <enabled> — Enable or disable level display.\n"
        "/notificationchannel [channel] — Set or disable both notification channels.\n"
        "/joinnotificationchannel [channel] — Set or disable join notifications.\n"
        "/leftnotificationchannel [channel] — Set or disable leave notifications.",
        inline=False,
    )
    embed.set_footer(text="Server management commands require Manage Server permission.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="profile", description="Show a member's experience profile.")
async def profile(interaction: discord.Interaction, member: discord.Member | None = None):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    member = member or interaction.user
    try:
        data = await klukai_request("GET", f"/guilds/{interaction.guild.id}/members/{member.id}/profile")
    except (HTTPError, URLError, TimeoutError):
        await interaction.response.send_message("Klukai is unavailable.", ephemeral=True)
        return
    description = f"Total EXP: **{data['total_exp']}**\nRank: **#{data['rank']}**\nToday: **{data['daily_exp']}**\nThis week: **{data['weekly_exp']}**"
    if data["levels_enabled"]:
        description += f"\nLevel: **{data['level']}** ({data['exp_to_next_level']} EXP to next level)"
    await interaction.response.send_message(embed=discord.Embed(title=f"{member.display_name}'s profile", description=description, color=discord.Color.blue()))


@bot.tree.command(name="ranking", description="Show experience rankings.")
@app_commands.choices(period=[
    app_commands.Choice(name="All time", value="all"),
    app_commands.Choice(name="Daily", value="daily"),
    app_commands.Choice(name="Weekly", value="weekly"),
])
async def ranking(interaction: discord.Interaction, period: app_commands.Choice[str] | None = None):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    selected_period = period.value if period else "all"
    try:
        data = await klukai_request("GET", f"/guilds/{interaction.guild.id}/rankings?period={selected_period}")
    except (HTTPError, URLError, TimeoutError):
        await interaction.response.send_message("Klukai is unavailable.", ephemeral=True)
        return
    lines = []
    for row in data["rankings"]:
        member = interaction.guild.get_member(row["member_id"])
        name = member.display_name if member else f"Member {row['member_id']}"
        lines.append(f"**#{row['rank']}** {name} — {row['exp']} EXP")
    title = {"all": "All-time", "daily": "Daily", "weekly": "Weekly"}[selected_period]
    await interaction.response.send_message(embed=discord.Embed(title=f"{title} ranking", description="\n".join(lines) or "No experience has been earned yet.", color=discord.Color.blue()))


@bot.tree.command(name="notificationchannel", description="Set or disable all system notification channels.")
@app_commands.default_permissions(manage_guild=True)
async def setting_channel(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    saved_join = await save_notification_channel(interaction.guild.id, "join", channel.id if channel else None)
    saved_left = await save_notification_channel(interaction.guild.id, "left", channel.id if channel else None)
    if not saved_join or not saved_left:
        await interaction.response.send_message("Klukai is unavailable. The notification channel was not changed.", ephemeral=True)
    elif channel is None:
        await interaction.response.send_message("Join and leave notifications have been disabled.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Join and leave notifications now use {channel.mention}.", ephemeral=True)


@bot.tree.command(name="joinnotificationchannel", description="Set or disable the channel for member join notifications.")
@app_commands.default_permissions(manage_guild=True)
async def setting_join_channel(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    saved = await save_notification_channel(interaction.guild.id, "join", channel.id if channel else None)
    await interaction.response.send_message("Join notification channel updated." if saved else "Klukai is unavailable. The channel was not changed.", ephemeral=True)


@bot.tree.command(name="leftnotificationchannel", description="Set or disable the channel for member leave notifications.")
@app_commands.default_permissions(manage_guild=True)
async def setting_left_channel(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    saved = await save_notification_channel(interaction.guild.id, "left", channel.id if channel else None)
    await interaction.response.send_message("Leave notification channel updated." if saved else "Klukai is unavailable. The channel was not changed.", ephemeral=True)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} logged")


bot.run("YOUR_BOT_TOKEN")

