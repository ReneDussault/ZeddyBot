#!/usr/bin/env python3

from datetime import datetime, timezone
import json
import requests
import discord
from discord.ext import commands
from discord.ext.tasks import loop
import socket
import asyncio
from typing import Optional
import logging

logging.getLogger("discord").setLevel(logging.WARNING)


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


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
    def discord_outlaws_role_id(self):
        return self.data.get("discord_outlaws_role_id", "")

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
                print(f"[{now()}] Refreshed bot access token ")
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
            # self.twitch_api.refresh_bot_token()

            self.socket = socket.socket()
            self.socket.connect((self.server, self.port))

            # pass Twitch IRC credentials
            self.socket.send(f"PASS oauth:{self.config.twitch_bot_access_token}\r\n".encode("utf-8"))
            self.socket.send(f"NICK {self.config.twitch_bot_username}\r\n".encode("utf-8"))
            self.socket.send(f"JOIN #{self.config.target_channel}\r\n".encode("utf-8"))

            # set socket to non-blocking
            self.socket.setblocking(False)
            self.connected = True
            print(f"[{now()}] Connected to Twitch chat as {self.config.twitch_bot_username} ")

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
        if not self.connected or self.socket is None:
            if not self.connect():
                return False

        try:
            if not self.connected or self.socket is None:
                return
            self.socket.send(f"PRIVMSG #{self.config.target_channel} :{message}\r\n".encode("utf-8"))
            print(f"[{now()}] Sending to Twitch chat: {message}")
            return True
        except Exception as e:
            print(f"Error sending message to Twitch chat: {e}")
            self.connected = False
            return False


    def check_for_ping(self):
        if not self.connected or self.socket is None:
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
    def __init__(self, twitch_api: TwitchAPI, config: Config, chat_bot: Optional[TwitchChatBot] = None):
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
                self.online_users[user_name] = datetime.now(timezone.utc)

            if user_name not in streams:
                self.online_users[user_name] = None
            else:
                started_at = datetime.strptime(streams[user_name]["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
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

        self._last_log_line = None
        self.config = config
        self.twitch_api = TwitchAPI(config)
        self.twitch_chat_bot = TwitchChatBot(config, self.twitch_api)
        self.notification_manager = StreamNotificationManager(self.twitch_api, config, self.twitch_chat_bot)

        self.CHANNEL_ID = int(config.discord_channel_id) if config.discord_channel_id else None
        self.LIVE_ROLE_ID = config.discord_live_role_id
        self.DRIFTERS_ROLE_ID = config.discord_drifters_role_id
        self.OUTLAWS_ROLE_ID = config.discord_outlaws_role_id

        # timestamps for tracking role upgrades
        self.user_join_timestamps = {}

        self.setup()


    def log_once(self, message):
        if getattr(self, "_last_log_line", None) != message:
            print(message)
            self._last_log_line = message


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

        @self.command()
        async def test_stream_check(ctx):
            """Debug command to manually test stream detection"""
            try:
                users = self.twitch_api.get_users(self.config.watchlist)
                streams = self.twitch_api.get_streams(users)
                
                await ctx.send(f"Watchlist: {self.config.watchlist}")
                await ctx.send(f"Users found: {users}")
                await ctx.send(f"Streams found: {list(streams.keys())}")
                
                if streams:
                    for user, stream in streams.items():
                        await ctx.send(f"Stream: {user} - {stream['title']} - {stream['game_name']}")
                else:
                    await ctx.send("No active streams detected")
                    
            except Exception as e:
                await ctx.send(f"Error testing stream check: {e}")

        @self.command()
        async def force_notification(ctx):
            """Force send a notification for the current stream"""
            try:
                if not self.CHANNEL_ID:
                    await ctx.send("Discord channel ID not configured")
                    return
                    
                channel = self.get_channel(self.CHANNEL_ID)
                if not channel:
                    await ctx.send(f"Could not find Discord channel with ID {self.CHANNEL_ID}")
                    return
                
                # Get actual current stream data
                users = self.twitch_api.get_users(self.config.watchlist)
                streams = self.twitch_api.get_streams(users)
                
                # Find your stream specifically
                your_stream = None
                for user_name in self.config.watchlist:
                    if user_name.lower() == self.config.target_channel.lower() and user_name in streams:
                        your_stream = streams[user_name]
                        break
                
                if your_stream:
                    await self._send_stream_notification(channel, your_stream)
                    # Only send confirmation if command was used in a different channel
                    if ctx.channel.id != self.CHANNEL_ID:
                        await ctx.send("Live stream notification sent!")
                else:
                    await ctx.send("You are not currently live on Twitch, so no notification was sent.")
                
            except Exception as e:
                await ctx.send(f"Error sending notification: {e}")

        @self.command()
        async def test_notification(ctx):
            """Send a test notification (fake data)"""
            try:
                if not self.CHANNEL_ID:
                    await ctx.send("Discord channel ID not configured")
                    return
                    
                channel = self.get_channel(self.CHANNEL_ID)
                if not channel:
                    await ctx.send(f"Could not find Discord channel with ID {self.CHANNEL_ID}")
                    return
                
                # Create a fake notification for testing
                fake_notification = {
                    'user_name': 'RenegadeZed',
                    'user_login': 'renegadezed',
                    'title': 'Test Stream Notification',
                    'game_name': 'Test Game',
                }
                
                await self._send_stream_notification(channel, fake_notification)
                # Only send confirmation if command was used in a different channel
                if ctx.channel.id != self.CHANNEL_ID:
                    await ctx.send("Test notification sent!")
                
            except Exception as e:
                await ctx.send(f"Error sending test notification: {e}")


        @self.event
        async def on_ready():

            print(f"[{now()}] ZeddyBot is connected to Discord ")
            
            self.update_token_task.start()
            self.update_bot_token_task.start()
            self.check_twitch_online_streamers.start()
            self.check_twitch_ping.start()

            self.twitch_chat_bot.connect()


        @self.listen("on_member_update")
        async def update_live_role_member(before, after):
            await self.log_activity_changes(before, after)
            await self._handle_live_role_update(before, after)


        @self.listen("on_presence_update")
        async def update_live_role_presence(before, after):
            await self.log_activity_changes(before, after)
            await self._handle_live_role_update(before, after)


        @self.event
        async def on_member_join(self, member):
            print(f"[{now()}] {member} has joined the server")
            
            # drifters role - convert to int and validate
            drifters_role = member.guild.get_role(int(self.DRIFTERS_ROLE_ID))
            if drifters_role:
                has_drifter_role = drifters_role in member.roles
                
                if not has_drifter_role:
                    await member.add_roles(drifters_role)
                    print(f"[{now()}] Added Drifters role to {member}")
                    
                    # role upgrade after 30 days
                    self.loop.create_task(self._upgrade_role_after_delay(member))
            else:
                print(f"[{now()}] ERROR: Drifters role with ID {self.DRIFTERS_ROLE_ID} not found!")


    async def log_activity_changes(self, before, after):
        before_activities = set((a.type, getattr(a, 'name', None)) for a in before.activities)
        after_activities = set((a.type, getattr(a, 'name', None)) for a in after.activities)

        started = after_activities - before_activities
        stopped = before_activities - after_activities

        for act_type, act_name in started:
            self.log_once(f"[{now()}] User '{after.name}' started activity: {act_type.name} ({act_name})")
        for act_type, act_name in stopped:
            self.log_once(f"[{now()}] User '{after.name}' stopped activity: {act_type.name} ({act_name})")

        if before.status == discord.Status.offline and after.status != discord.Status.offline:
            self.log_once(f"[{now()}] User '{after.name}' has come online.")
        elif before.status != discord.Status.offline and after.status == discord.Status.offline:
            self.log_once(f"[{now()}] User '{after.name}' has gone offline.")

        
    async def _handle_live_role_update(self, before, after):
        is_streaming = any(a for a in after.activities if a.type == discord.ActivityType.streaming)
        has_live_role = int(self.LIVE_ROLE_ID) in after._roles

        if is_streaming and not has_live_role:
            print(f"[{now()}] Giving LIVE role to {after.name}")
            
            # Convert to int and validate role exists
            live_role = after.guild.get_role(int(self.LIVE_ROLE_ID))
            if live_role:
                await after.add_roles(live_role)
                
                # send message to Twitch chat that stream is starting
                if hasattr(after, "name") and after.name.lower() == self.config.target_channel.lower():
                    self.twitch_chat_bot.send_message(f"Discord status updated to streaming! Welcome everyone!")
            else:
                print(f"[{now()}] ERROR: Live role with ID {self.LIVE_ROLE_ID} not found!")

        elif not is_streaming and has_live_role:
            print(f"[{now()}] Removing LIVE role from {after.name}")
            
            # Convert to int and validate role exists
            live_role = after.guild.get_role(int(self.LIVE_ROLE_ID))
            if live_role:
                await after.remove_roles(live_role)
                
                # send message to Twitch chat that stream is ending
                if hasattr(after, "name") and after.name.lower() == self.config.target_channel.lower():
                    self.twitch_chat_bot.send_message("Stream appears to be ending. Thanks for watching!")
            else:
                print(f"[{now()}] ERROR: Live role with ID {self.LIVE_ROLE_ID} not found!")


    async def _upgrade_role_after_delay(self, member, days=30):
        """promote member to Outlaws role after 30 days"""
        await asyncio.sleep(days * 24 * 60 * 60)
        
        guild = member.guild
        updated_member = guild.get_member(member.id)
        if not updated_member:
            return
        
        # Convert to int and validate roles exist
        outlaws_role = guild.get_role(int(self.OUTLAWS_ROLE_ID))
        drifters_role = guild.get_role(int(self.DRIFTERS_ROLE_ID))
        
        if outlaws_role and drifters_role:
            has_outlaw_role = outlaws_role in updated_member.roles
            if not has_outlaw_role:
                await updated_member.add_roles(outlaws_role)
                await updated_member.remove_roles(drifters_role)
                print(f"[{now()}] Upgraded {updated_member.name} to Outlaws after {days} days")
        else:
            print(f"[{now()}] ERROR: Required roles not found - Outlaws: {self.OUTLAWS_ROLE_ID}, Drifters: {self.DRIFTERS_ROLE_ID}")

    @loop(hours=24 * 5)
    async def update_token_task(self):
        acc_tok = self.twitch_api.get_app_access_token()

        print(f"[{now()}] Changing access token ")
        
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
        if not self.CHANNEL_ID:
            print(f"[{now()}] Discord channel ID not configured")
            return
            
        channel = self.get_channel(self.CHANNEL_ID)
        if not channel:
            print(f"[{now()}] Could not find Discord channel with ID {self.CHANNEL_ID}")
            return

        notifications = self.notification_manager.get_notifications()
        for notification in notifications:
            await self._send_stream_notification(channel, notification)


    async def _send_stream_notification(self, channel, notification):

        print(f"[{now()}] Sending discord notification ")

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

        # Only set thumbnail if game_name exists and is not empty
        if notification.get('game_name') and notification['game_name'].strip():
            try:
                # URL encode the game name to handle special characters
                import urllib.parse
                encoded_game = urllib.parse.quote(notification['game_name'])
                embed.set_thumbnail(url=f"https://avatar-resolver.vercel.app/twitch-boxart/{encoded_game}")
            except Exception as e:
                print(f"[{now()}] Warning: Could not set thumbnail for game {notification.get('game_name')}: {e}")

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
