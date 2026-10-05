import discord
from discord.ext import commands
from discord import app_commands

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

notification_channels = {}




# event handler

async def get_notification_channel(guild):
    channel_id = notification_channels.get(guild.id)

    if channel_id is None:
        return None

    channel = bot.get_channel(channel_id)

    if channel is None:
        return None

    return channel




# ordinal number

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




# server visit period

def get_stay_time(joined_at, left_at):

    total_days = (left_at - joined_at).days

    months = total_days // 31
    days = total_days % 31

    if months == 0:
        return f"{days} days"

    if days == 0:
        return f"{months} months"

    return f"{months} months, {days} days"




# member join event

@bot.event
async def on_member_join(member):
    channel = await get_notification_channel(member.guild)

    if channel is None:
        return

    print(f"{member} has joined the server.  |  Server : {member.guild.name}-{member.guild.id}, Channel : {channel.name}-{channel.id}")

    servermembercount = member.guild.member_count
    embed = discord.Embed( title = f"{get_ordinal(servermembercount)} member has entered", color = discord.Color.blue())
    embed.set_thumbnail(url = member.display_avatar.url)
    embed.add_field(name = member.display_name, value = member.mention,inline = False)
    embed.add_field(name = "Account Sign-up Date", value = f"{discord.utils.format_dt(member.created_at, style = 'F')}({discord.utils.format_dt(member.created_at, style='R')})", inline = False)
    embed.add_field(name = "Server Join Date", value = f"{discord.utils.format_dt(member.joined_at, style = 'F')}({discord.utils.format_dt(member.joined_at, style='R')})", inline = False)

    await channel.send(embed = embed)




# member left event

@bot.event
async def on_member_remove(member):
    channel = await get_notification_channel(member.guild)

    if channel is None:
        return

    print(f"{member} has left the server.  |  Server : {member.guild.name}-{member.guild.id}, Channel : {channel.name}-{channel.id}")

    left_at = discord.utils.utcnow()
    stay_time = get_stay_time(member.joined_at, left_at)
    embed = discord.Embed( title = f"{member.display_name} has left the server", color = discord.Color.blue())
    embed.set_thumbnail(url = member.display_avatar.url)
    embed.add_field(name = member.display_name, value = member.mention, inline = False)
    embed.add_field(name = "Server Leave Date", value = f"{discord.utils.format_dt(left_at, style='F')}({discord.utils.format_dt(left_at, style='R')})", inline = False)
    embed.add_field(name = "Time On Server", value = stay_time, inline = False)

    await channel.send(embed = embed)




# /notificationchannel

@bot.tree.command(name = "notificationchannel", description = "Set the channel for sending system notifications.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(channel = "The channel where notifications will be sent.")

async def setting_channel(interaction : discord.Interaction, channel : discord.TextChannel):
    notification_channels[interaction.guild.id] = channel.id
    print(f"Notification Channel has been changed  |  server : {interaction.guild.name}-{interaction.guild.id}, Channel : {channel.name}-{channel.id}")
    await interaction.response.send_message(f"Notification Channel has been changed  |  Channel : {channel.name}", ephemeral = True)




# bot ready

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} logged")
 



bot.run("YOUR_BOT_TOKEN")
