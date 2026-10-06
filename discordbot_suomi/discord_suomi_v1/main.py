import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import discord
from discord.ext import commands
from discord import app_commands


KLUKAI_API_URL = "http://127.0.0.1:8000"

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)




# Klukai API helpers

def send_klukai_request(method, path, payload=None):
    data = None
    headers = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(f"{KLUKAI_API_URL}{path}", data=data, headers=headers, method=method, )

    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))




# send serverdata to Klukai

async def save_notification_channel(guild_id, notification_type, channel_id):
    try:
        await asyncio.to_thread(send_klukai_request, "PUT", f"/guilds/{guild_id}/channels/{notification_type}", {"channel_id": channel_id},)
        return True
    except (HTTPError, URLError, TimeoutError) as error:
        print(f"Could not save the notification channel in Klukai: {error}")
        return False




# get serverdata from Klukai

async def get_notification_channel(guild, notification_type):
    try:
        setting = await asyncio.to_thread(send_klukai_request, "GET", f"/guilds/{guild.id}/channels/{notification_type}",)
    except HTTPError as error:
        if error.code != 404:
            print(f"Could not load the notification channel from Klukai: {error}")
        return None
    except (URLError, TimeoutError) as error:
        print(f"Could not load the notification channel from Klukai: {error}")
        return None

    channel_id = setting["channel_id"]
    channel = bot.get_channel(channel_id)

    if channel is None:
        return None

    return channel


# Ordinal number

def get_ordinal(number):

    if 10 <= number % 100 <= 20:
        return f"{number}th"

    match number % 10:
        case 1:
            return f"{number}st"
        case 2:
            return f"{number}nd"
        case 3:
            return f"{number}rd"
        case _:
            return f"{number}th"


# Server visit period

def get_stay_time(joined_at, left_at):

    total_days = (left_at - joined_at).days

    months = total_days // 31
    days = total_days % 31

    if months == 0:
        return f"{days} days"

    if days == 0:
        return f"{months} months"

    return f"{months} months, {days} days"


# Member join event

@bot.event
async def on_member_join(member):
    channel = await get_notification_channel(member.guild, "join")

    if channel is None:
        return

    print(f"{member} has joined the server.  |  Server : {member.guild.name}-{member.guild.id}, Channel : {channel.name}-{channel.id}")

    servermembercount = member.guild.member_count
    embed = discord.Embed(title=f"{get_ordinal(servermembercount)} member has entered", color=discord.Color.blue())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name=member.display_name, value=member.mention, inline=False)
    embed.add_field(name="Account Sign-up Date", value=f"{discord.utils.format_dt(member.created_at, style='F')}({discord.utils.format_dt(member.created_at, style='R')})", inline=False)
    embed.add_field(name="Server Join Date", value=f"{discord.utils.format_dt(member.joined_at, style='F')}({discord.utils.format_dt(member.joined_at, style='R')})", inline=False)

    await channel.send(embed=embed)


# Member left event

@bot.event
async def on_member_remove(member):
    channel = await get_notification_channel(member.guild, "left")

    if channel is None:
        return

    print(f"{member} has left the server.  |  Server : {member.guild.name}-{member.guild.id}, Channel : {channel.name}-{channel.id}")

    left_at = discord.utils.utcnow()
    stay_time = get_stay_time(member.joined_at, left_at)
    embed = discord.Embed(title=f"{member.display_name} has left the server", color=discord.Color.blue())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name=member.display_name, value=member.mention, inline=False)
    embed.add_field(name="Server Leave Date", value=f"{discord.utils.format_dt(left_at, style='F')}({discord.utils.format_dt(left_at, style='R')})", inline=False)
    embed.add_field(name="Time On Server", value=stay_time, inline=False)

    await channel.send(embed=embed)


# /notificationchannel

@bot.tree.command(name="notificationchannel", description="Set or disable all system notification channels.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(channel="The channel for both join and leave notifications. Leave empty to disable both.")
async def setting_channel(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    saved_join = await save_notification_channel(interaction.guild.id, "join", channel.id if channel is not None else None)
    saved_left = await save_notification_channel(interaction.guild.id, "left", channel.id if channel is not None else None)

    if not saved_join or not saved_left:
        await interaction.response.send_message("Klukai is unavailable. The notification channel was not changed.", ephemeral=True)
        return

    if channel is None:
        print(f"All Notification Channels have been disabled  |  server : {interaction.guild.name}-{interaction.guild.id}")
        await interaction.response.send_message("Join and leave notifications have been disabled.", ephemeral=True)
        return

    print(f"All Notification Channels have been changed  |  server : {interaction.guild.name}-{interaction.guild.id}, Channel : {channel.name}-{channel.id}")
    await interaction.response.send_message(f"Join and leave notification channels have been changed  |  Channel : {channel.name}", ephemeral=True)


# /joinnotificationchannel

@bot.tree.command(name="joinnotificationchannel", description="Set or disable the channel for member join notifications.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(channel="The channel for join notifications. Leave empty to disable join notifications.")
async def setting_join_channel(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    saved = await save_notification_channel(interaction.guild.id, "join", channel.id if channel is not None else None)

    if not saved:
        await interaction.response.send_message("Klukai is unavailable. The join notification channel was not changed.", ephemeral=True)
        return

    if channel is None:
        print(f"Join Notification Channel has been disabled  |  server : {interaction.guild.name}-{interaction.guild.id}")
        await interaction.response.send_message("Join notifications have been disabled.", ephemeral=True)
        return

    print(f"Join Notification Channel has been changed  |  server : {interaction.guild.name}-{interaction.guild.id}, Channel : {channel.name}-{channel.id}")
    await interaction.response.send_message(f"Join Notification Channel has been changed  |  Channel : {channel.name}", ephemeral=True)


# /leftnotificationchannel

@bot.tree.command(name="leftnotificationchannel", description="Set or disable the channel for member leave notifications.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(channel="The channel for leave notifications. Leave empty to disable leave notifications.")
async def setting_left_channel(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    saved = await save_notification_channel(interaction.guild.id, "left", channel.id if channel is not None else None)

    if not saved:
        await interaction.response.send_message("Klukai is unavailable. The leave notification channel was not changed.", ephemeral=True)
        return

    if channel is None:
        print(f"Leave Notification Channel has been disabled  |  server : {interaction.guild.name}-{interaction.guild.id}")
        await interaction.response.send_message("Leave notifications have been disabled.", ephemeral=True)
        return

    print(f"Leave Notification Channel has been changed  |  server : {interaction.guild.name}-{interaction.guild.id}, Channel : {channel.name}-{channel.id}")
    await interaction.response.send_message(f"Leave Notification Channel has been changed  |  Channel : {channel.name}", ephemeral=True)


# Bot ready

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} logged")


bot.run("YOUR_BOT_TOKEN")
