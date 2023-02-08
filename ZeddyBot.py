import json
from datetime import datetime, timezone

import discord
import requests as rq
from discord.ext import commands
from discord.ext.tasks import loop


# config.json import
with open("config.json") as config_file:
    config_data = json.load(config_file)


"""

discord stuff below

"""


# discord bot token
disc_token = config_data["disc_token"]

# proper intent privileges for bot
intents = discord.Intents.all()
intents.members = True

# instance of (bot) client
bot = commands.Bot(command_prefix="!", intents=intents)


# checks if discord activity is streaming, if true, assign LIVE role, if False, remove LIVE role
LIVE_ROLE_ID = 983061320133922846


@bot.event
async def on_member_update(before, after):
    print(
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------ZeddyBot is checking for roles----------"
    )
    if any(a for a in after.activities if a.type == discord.ActivityType.streaming):
        if LIVE_ROLE_ID in after._roles:
            return
        print(
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------ZeddyBot is Giving LIVE role to {after.name}----------"
        )
        await after.add_roles(after.guild.get_role(LIVE_ROLE_ID))

    elif LIVE_ROLE_ID in after._roles:
        print(
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------ZeddyBot is Removing LIVE role from {after.name}----------"
        )
        await after.remove_roles(after.guild.get_role(LIVE_ROLE_ID))


# print that we logged in once the bot is ready
@bot.event
async def on_ready():
    print(
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------ZeddyBot is connected to Discord----------"
    )


# ping command
@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")


# hello command
@bot.command()
async def hello(ctx):
    await ctx.send(f"Hello {ctx.author.name}!")


# post in discord if streamer is live
@loop(seconds=30)
async def check_twitch_online_streamers():
    channel = bot.get_channel(966493808869138442)

    if not channel:
        return

    notifications = get_notifications()
    for notification in notifications:
        print("----------Sending discord notification----------")
        await channel.send(
            f"We are now live! {notification['title']}.\nStreaming: {notification['game_name']} at https://www.twitch.tv/renegadezed\n"
        )


"""

twitch stuff below

"""


# oath access token
def get_app_access_token():
    params = {
        "client_id": config_data["twitch_client_id"],
        "client_secret": config_data["twitch_secret"],
        "grant_type": "client_credentials",
    }

    response = rq.post("https://id.twitch.tv/oauth2/token", params=params)
    return response.json()["access_token"]


# access_token = get_app_access_token()
# print(access_token)


# convert config.json watchlist names to appropriate twitch login names and IDs
def get_users(login_names):
    params = {"login": login_names}

    headers = {
        "Authorization": f"Bearer {config_data['access_token']}",
        "Client-Id": config_data["twitch_client_id"],
    }

    response = rq.get(
        "https://api.twitch.tv/helix/users", params=params, headers=headers
    )
    return {entry["login"]: entry["id"] for entry in response.json()["data"]}


# get stream info when live and reformat to a dictionary
def get_streams(users):
    params = {"user_id": users.values()}

    headers = {
        "Authorization": f"Bearer {config_data['access_token']}",
        "Client-Id": config_data["twitch_client_id"],
    }

    response = rq.get(
        "https://api.twitch.tv/helix/streams", params=params, headers=headers
    )
    return {entry["user_login"]: entry for entry in response.json()["data"]}


online_users = {}


# add streamer to online_users
def get_notifications():
    users = get_users(config_data["watchlist"])
    streams = get_streams(users)

    notifications = []
    for user_name in config_data["watchlist"]:
        if user_name not in online_users:
            online_users[user_name] = datetime.now(timezone.utc)

        if user_name not in streams:
            online_users[user_name] = None
        else:
            started_at = datetime.strptime(
                streams[user_name]["started_at"], "%Y-%m-%dT%H:%M:%SZ"
            )
            if online_users[user_name] is None or started_at > online_users[user_name]:
                notifications.append(streams[user_name])
                online_users[user_name] = started_at

    return notifications


if __name__ == "__main__":
    check_twitch_online_streamers.start()
    bot.run(disc_token)
