#!/usr/bin/env python3

from datetime import datetime
import json
import requests
import discord
from discord.ext import commands
from discord.ext.tasks import loop
import socket
import asyncio


class Config:
    def __init__(self, config_path=None):
        if config_path is None:
            config_path = "config.json"

        with open(config_path) as config_file:
            self.data = json.load(config_file)

    def save(self):
        with open("config.json", "w") as f:
            json.dump(self.data, f)

    @property
    def discord_token(self):
        return self.data["disc_token"]

    @property
    def twitch_client_id(self):
        return self.data["twitch_client_id"]

    @property
    def twitch_secret(self):
        return self.data["twitch_secret"]

    @property
    def access_token(self):
        return self.data["access_token"]

    @access_token.setter
    def access_token(self, value):
        self.data["access_token"] = value

    @property
    def watchlist(self):
        return self.data["watchlist"]

    @property
    def twitch_bot_username(self):
        return self.data.get("twitch_bot_username", "Zeddy_bot")

    @property
    def twitch_bot_access_token(self):
        return self.data.get("twitch_bot_access_token", "")

    @twitch_bot_access_token.setter
    def twitch_bot_access_token(self, value):
        self.data["twitch_bot_access_token"] = value

    @property
    def twitch_bot_refresh_token(self):
        return self.data.get("twitch_bot_refresh_token", "")

    @twitch_bot_refresh_token.setter
    def twitch_bot_refresh_token(self, value):
        self.data["twitch_bot_refresh_token"] = value

    @property
    def target_channel(self):
        return self.data.get("target_channel", "")

    @property
    def twitch_bot_client_id(self):
        return self.data.get("twitch_bot_client_id", "")

    @property
    def twitch_bot_secret(self):
        return self.data.get("twitch_bot_secret", "")

    @property
    def discord_channel_id(self):
        return self.data.get("discord_channel_id", "")

    @property
    def discord_live_role_id(self):
        return self.data.get("discord_live_role_id", "")

    @property
    def discord_drifters_role_id(self): 
        return self.data.get("discord_drifters_role_id", "")

    @property
    def discord_outlaw_role_id(self):
        return self.data.get("discord_outlaw_role_id", "")

class TwitchAPI:
    def __init__(self, config: Config):
        self.config = config

    def get_app_access_token(self):
        params = {
            "client_id": self.config.twitch_client_id,
            "client_secret": self.config.twitch_secret,
            "grant_type": "client_credentials",
        }
        response = requests.post("https://id.twitch.tv/oauth2/token", params=params)
        return response.json()["access_token"]

    def refresh_bot_token(self):
        if not self.config.twitch_bot_refresh_token:
            print("No refresh token available for bot account")
            return False

        params = {
            "client_id": self.config.twitch_bot_client_id,
            "client_secret": self.config.twitch_bot_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.config.twitch_bot_refresh_token,
        }

        try:
            response = requests.post("https://id.twitch.tv/oauth2/token", params=params)
            if response.status_code == 200:
                data = response.json()
                self.config.twitch_bot_access_token = data["access_token"]
                self.config.twitch_bot_refresh_token = data["refresh_token"]
                self.config.save()
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------Refreshed bot access token----------")
                return True
            else:
                print(f"Failed to refresh bot token: {response.text}")
                return False
        except Exception as e:
            print(f"Error refreshing bot token: {e}")
            return False

    def get_users(self, login_names):
        params = {"login": login_names}
        headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Client-Id": self.config.twitch_client_id,
        }
        response = requests.get("https://api.twitch.tv/helix/users", params=params, headers=headers)
        return {entry["login"]: entry["id"] for entry in response.json()["data"]}

    def get_streams(self, users):
        params = {"user_id": users.values()}
        headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Client-Id": self.config.twitch_client_id,
        }
        response = requests.get("https://api.twitch.tv/helix/streams", params=params, headers=headers)
        return {entry["user_login"]: entry for entry in response.json()["data"]}


class TwitchChatBot:
    def __init__(self, config: Config, twitch_api: TwitchAPI):
        self.config = config
        self.twitch_api = twitch_api
        self.server = "irc.chat.twitch.tv"
        self.port = 6667
        self.socket = None
        self.connected = False

    def connect(self):
        try:
            # try to refresh the token first
            self.twitch_api.refresh_bot_token()

            self.socket = socket.socket()
            self.socket.connect((self.server, self.port))

            # pass Twitch IRC credentials
            self.socket.send(f"PASS oauth:{self.config.twitch_bot_access_token}\r\n".encode("utf-8"))
            self.socket.send(f"NICK {self.config.twitch_bot_username}\r\n".encode("utf-8"))
            self.socket.send(f"JOIN #{self.config.target_channel}\r\n".encode("utf-8"))

            # set socket to non-blocking
            self.socket.setblocking(0)
            self.connected = True
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------Connected to Twitch chat as {self.config.twitch_bot_username}----------")

            # send initial message to confirm bot is working
            self.send_message("ZeddyBot is now active in chat!")

            return True
        except Exception as e:
            print(f"Error connecting to Twitch chat: {e}")
            self.connected = False
            return False

    def disconnect(self):
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                print(f"Error disconnecting to Twitch chat: {e}")
                pass
        self.connected = False

    def send_message(self, message):
        if not self.connected:
            if not self.connect():
                return False

        try:
            self.socket.send(f"PRIVMSG #{self.config.target_channel} :{message}\r\n".encode("utf-8"))
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------Sent message to Twitch chat: {message}----------")
            return True
        except Exception as e:
            print(f"Error sending message to Twitch chat: {e}")
            self.connected = False
            return False

    def check_for_ping(self):
        if not self.connected:
            return

        try:
            data = self.socket.recv(2048).decode("utf-8")
            if data.startswith("PING"):
                self.socket.send("PONG\r\n".encode("utf-8"))
        except Exception as e:
            print(f"Error checking for ping: {e}")
            # no data to read
            pass


class StreamNotificationManager:
    def __init__(self, twitch_api: TwitchAPI, config: Config, chat_bot: TwitchChatBot = None):
        self.twitch_api = twitch_api
        self.config = config
        self.chat_bot = chat_bot
        self.online_users = {}

    def get_notifications(self):
        users = self.twitch_api.get_users(self.config.watchlist)
        streams = self.twitch_api.get_streams(users)

        notifications = []
        for user_name in self.config.watchlist:
            if user_name not in self.online_users:
                self.online_users[user_name] = datetime.utcnow()

            if user_name not in streams:
                self.online_users[user_name] = None
            else:
                started_at = datetime.strptime(streams[user_name]["started_at"], "%Y-%m-%dT%H:%M:%SZ")
                if self.online_users[user_name] is None or started_at > self.online_users[user_name]:
                    notifications.append(streams[user_name])
                    self.online_users[user_name] = started_at

                    # send notification to Twitch chat if this is the target channel
                    if self.chat_bot and user_name.lower() == self.config.target_channel.lower():
                        self.chat_bot.send_message(f"Stream is now live: {streams[user_name]['title']} - playing {streams[user_name]['game_name']}")

        return notifications


class ZeddyBot(commands.Bot):
    def __init__(self, config: Config):
        intents = discord.Intents.all()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

        self.config = config
        self.twitch_api = TwitchAPI(config)
        self.twitch_chat_bot = TwitchChatBot(config, self.twitch_api)
        self.notification_manager = StreamNotificationManager(self.twitch_api, config, self.twitch_chat_bot)

        self.CHANNEL_ID = config.discord_channel_id
        self.LIVE_ROLE_ID =  config.discord_live_role_id
        self.DRIFTERS_ROLE_ID = config.discord_drifters_role_id
        self.OUTLAW_ROLE_ID = config.discord_outlaw_role_id

        # timestamps for tracking role upgrades
        self.user_join_timestamps = {}

        self.setup()

    def setup(self):
        """
        Some boilerplate commands and events
        """

        @self.command()
        async def ping(ctx):
            await ctx.send("Pong!")

        @self.command()
        async def hello(ctx):
            await ctx.send(f"Hello {ctx.author.name}!")

        @self.command()
        async def twitch_chat(ctx, *, message):
            if self.twitch_chat_bot.send_message(message):
                await ctx.send(f"Message sent to Twitch chat: {message}")
            else:
                await ctx.send("Failed to send message to Twitch chat.")

        @self.command()
        async def refresh_bot_token(ctx):
            if self.twitch_api.refresh_bot_token():
                await ctx.send("Successfully refreshed the bot's Twitch token.")
            else:
                await ctx.send("Failed to refresh the bot's Twitch token.")

        @self.event
        async def on_ready():
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------ZeddyBot is connected to Discord----------")
            self.update_token_task.start()
            self.update_bot_token_task.start()
            self.check_twitch_online_streamers.start()
            self.check_twitch_ping.start()

            self.twitch_chat_bot.connect()

        @self.listen("on_member_update")
        @self.listen("on_presence_update")
        async def update_live_role(before, after):
            await self._handle_live_role_update(before, after)

        @self.event
        async def on_member_join(member):
            # drifters role
            drifter_role = member.guild.get_role(self.DRIFTERS_ROLE_ID)
            if drifter_role:
                await member.add_roles(drifter_role)
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------Added Drifters role to {member.name}----------")

                # role upgrade after 30 days
                self.loop.create_task(self._upgrade_role_after_delay(member))

    async def _upgrade_role_after_delay(self, member, days=30):
        """
        promote member to Outlaws role after 30 days
        """
        await asyncio.sleep(days * 24 * 60 * 60)  # Convert days to seconds

        # check if member is still in the server
        guild = member.guild
        updated_member = guild.get_member(member.id)
        if not updated_member:
            return

        # upgrade to Outlaws role
        outlaw_role = guild.get_role(self.OUTLAW_ROLE_ID)
        if outlaw_role:
            await updated_member.add_roles(outlaw_role)
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------Upgraded {updated_member.name} to Outlaws after {days} days----------")

    async def _handle_live_role_update(self, before, after):
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------ZeddyBot is checking for roles----------")

        is_streaming = any(a for a in after.activities if a.type == discord.ActivityType.streaming)
        has_live_role = self.LIVE_ROLE_ID in after._roles

        if is_streaming and not has_live_role:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------ZeddyBot is Giving LIVE role to {after.name}----------")
            await after.add_roles(after.guild.get_role(self.LIVE_ROLE_ID))

            # send message to Twitch chat that stream is starting
            if hasattr(after, "name") and after.name.lower() == self.config.target_channel.lower():
                self.twitch_chat_bot.send_message(f"Discord status updated to streaming! Welcome everyone!")

        elif not is_streaming and has_live_role:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------ZeddyBot is Removing LIVE role from {after.name}----------")
            await after.remove_roles(after.guild.get_role(self.LIVE_ROLE_ID))

            # send message to Twitch chat that stream is ending
            if hasattr(after, "name") and after.name.lower() == self.config.target_channel.lower():
                self.twitch_chat_bot.send_message("Stream appears to be ending. Thanks for watching!")

    @loop(hours=24 * 5)
    async def update_token_task(self):
        acc_tok = self.twitch_api.get_app_access_token()
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------Changing access token----------")
        self.config.access_token = acc_tok
        self.config.save()
        await self.change_presence(status=discord.Status.online)

    @loop(hours=24)
    async def update_bot_token_task(self):
        self.twitch_api.refresh_bot_token()

    @loop(minutes=5)
    async def check_twitch_ping(self):
        self.twitch_chat_bot.check_for_ping()

    @loop(seconds=60)
    async def check_twitch_online_streamers(self):
        channel = self.get_channel(self.CHANNEL_ID)
        if not channel:
            return

        notifications = self.notification_manager.get_notifications()
        for notification in notifications:
            await self._send_stream_notification(channel, notification)

    async def _send_stream_notification(self, channel, notification):
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------Sending discord notification----------")

        embed = discord.Embed(
            title=f"{notification['user_name']} is live on Twitch",
            url=f"https://www.twitch.tv/{notification['user_login']}",
            color=0x9146FF,
            timestamp=datetime.now(),
        )

        embed.set_author(
            name=f"{notification['user_name']}",
            url=f"https://www.twitch.tv/{notification['user_login']}",
            icon_url=f"https://avatar.glue-bot.xyz/twitch/{notification['user_login']}",
        )

        embed.set_thumbnail(url=f"https://avatar-resolver.vercel.app/twitch-boxart/{notification['game_name']}")

        embed.add_field(
            name="",
            value=notification["title"] or "No Title",
            inline=False,
        )

        embed.add_field(
            name=":joystick: Game",
            value=notification["game_name"] or "No Game",
            inline=True,
        )

        await channel.send(embed=embed)


def main():
    config = Config()
    bot = ZeddyBot(config)
    bot.run(config.discord_token)


if __name__ == "__main__":
    main()
