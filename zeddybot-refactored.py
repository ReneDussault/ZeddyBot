from datetime import datetime
import json
import requests
import discord
from discord.ext import commands
from discord.ext.tasks import loop

class Config:
    def __init__(self, config_path="config.json"):
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
    
    def get_users(self, login_names):
        params = {"login": login_names}
        headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Client-Id": self.config.twitch_client_id,
        }
        response = requests.get(
            "https://api.twitch.tv/helix/users", 
            params=params, 
            headers=headers
        )
        return {entry["login"]: entry["id"] for entry in response.json()["data"]}
    
    def get_streams(self, users):
        params = {"user_id": users.values()}
        headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Client-Id": self.config.twitch_client_id,
        }
        response = requests.get(
            "https://api.twitch.tv/helix/streams", 
            params=params, 
            headers=headers
        )
        return {entry["user_login"]: entry for entry in response.json()["data"]}

class StreamNotificationManager:
    def __init__(self, twitch_api: TwitchAPI, config: Config):
        self.twitch_api = twitch_api
        self.config = config
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
                started_at = datetime.strptime(
                    streams[user_name]["started_at"], 
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                if (self.online_users[user_name] is None or 
                    started_at > self.online_users[user_name]):
                    notifications.append(streams[user_name])
                    self.online_users[user_name] = started_at
                    
        return notifications

class ZeddyBot(commands.Bot):
    def __init__(self, config: Config):
        intents = discord.Intents.all()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        
        self.config = config
        self.twitch_api = TwitchAPI(config)
        self.notification_manager = StreamNotificationManager(self.twitch_api, config)
        
        self.CHANNEL_ID = 966493808869138442
        self.LIVE_ROLE_ID = 983061320133922846
        
        # Register commands and listeners
        self.setup()
        
    def setup(self):
        # Commands
        @self.command()
        async def ping(ctx):
            await ctx.send("Pong!")
            
        @self.command()
        async def hello(ctx):
            await ctx.send(f"Hello {ctx.author.name}!")
            
        # Events
        @self.event
        async def on_ready():
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------ZeddyBot is connected to Discord----------")
            self.update_token_task.start()
            self.check_twitch_online_streamers.start()
            
        @self.listen("on_member_update")
        @self.listen("on_presence_update")
        async def update_live_role(before, after):
            await self._handle_live_role_update(before, after)
            
    async def _handle_live_role_update(self, before, after):
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------ZeddyBot is checking for roles----------")
        
        is_streaming = any(a for a in after.activities if a.type == discord.ActivityType.streaming)
        has_live_role = self.LIVE_ROLE_ID in after._roles
        
        if is_streaming and not has_live_role:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------ZeddyBot is Giving LIVE role to {after.name}----------")
            await after.add_roles(after.guild.get_role(self.LIVE_ROLE_ID))
        elif not is_streaming and has_live_role:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------ZeddyBot is Removing LIVE role from {after.name}----------")
            await after.remove_roles(after.guild.get_role(self.LIVE_ROLE_ID))
            
    @loop(hours=24 * 5)
    async def update_token_task(self):
        acc_tok = self.twitch_api.get_app_access_token()
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}----------Changing access token----------")
        self.config.access_token = acc_tok
        self.config.save()
        await self.change_presence(status=discord.Status.online)
        
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
        
        embed.set_thumbnail(
            url=f"https://avatar-resolver.vercel.app/twitch-boxart/{notification['game_name']}"
        )
        
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
