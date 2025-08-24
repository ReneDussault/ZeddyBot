#!/usr/bin/env python3

from datetime import datetime, timezone
import json
import requests
import discord
from discord.ext import commands
from discord.ext.tasks import loop
import socket
import asyncio
import logging
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import threading
import sys
import os
import time
import select
from collections import deque

# Add parent directory to path to import from tools
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import our shared token utility
from tools.token_utils import refresh_twitch_bot_token, validate_bot_token, get_current_bot_token

# OBS WebSocket v5 (obsws-python)
try:
    from obsws_python import ReqClient
except ImportError:
    ReqClient = None

# Configure logging
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger('werkzeug').setLevel(logging.ERROR)  # Disable Flask request logging


def now():
    return datetime.now().strftime('%d-%m-%Y %H:%M:%S')


class Config:
    def __init__(self, config_path=None):
        if config_path is None:
            config_path = "./config.json"

        with open(config_path) as config_file:
            self.data = json.load(config_file)

    def save(self):
        with open("./config.json", "w") as f:
            json.dump(self.data, f)

    @property
    def discord_token(self):
        return self.data["disc_token"]

    @property
    def discord_channel_id(self):
        return int(self.data["discord_channel_id"])

    @property
    def twitch_chat_token(self):
        return self.data["twitch_bot_access_token"]

    @property
    def twitch_bot_username(self):
        return self.data["twitch_bot_username"]

    @property
    def twitch_bot_access_token(self):
        return self.data["twitch_bot_access_token"]

    @property
    def twitch_bot_refresh_token(self):
        return self.data.get("twitch_bot_refresh_token", "")

    @twitch_bot_refresh_token.setter
    def twitch_bot_refresh_token(self, value):
        self.data["twitch_bot_refresh_token"] = value

    @property
    def twitch_bot_client_id(self):
        return self.data["twitch_bot_client_id"]

    @property
    def twitch_bot_client_secret(self):
        return self.data["twitch_bot_secret"]

    @property
    def twitch_user_id(self):
        return self.data["twitch_user_id"]

    @property
    def target_channel(self):
        return self.data["target_channel"]

    @property
    def twitch_client_id(self):
        return self.data.get("twitch_client_id", "")

    @property
    def twitch_secret(self):
        return self.data.get("twitch_secret", "")

    @property
    def access_token(self):
        return self.data.get("access_token", "")

    @access_token.setter
    def access_token(self, value):
        self.data["access_token"] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


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
        success, message, new_token = refresh_twitch_bot_token("config.json")
        if success:
            # Reload the config with new token
            with open("config.json") as config_file:
                self.config.data = json.load(config_file)
            # Message already printed by refresh_twitch_bot_token utility
            return True
        else:
            print(message)
            return False


class TwitchChatBot:
    def __init__(self, config, twitch_api, dashboard_data=None):
        self.config = config
        self.twitch_api = twitch_api
        self.dashboard_data = dashboard_data
        self.server = "irc.chat.twitch.tv"
        self.port = 6667
        self.socket = None
        self.connected = False
        self.channel = f"#{config.target_channel}"
        
    def connect(self):
        try:
            # Clean up any existing socket
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                    
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10)  # 10 second timeout for connection
            self.socket.connect((self.server, self.port))
            
            # Authenticate
            self.socket.send(f"PASS oauth:{self.config.twitch_chat_token}\r\n".encode('utf-8'))
            self.socket.send(f"NICK {self.config.twitch_bot_username}\r\n".encode('utf-8'))
            self.socket.send(f"JOIN {self.channel}\r\n".encode('utf-8'))
            
            # Wait for successful connection
            response = self.socket.recv(2048).decode('utf-8')
            if "Welcome, GLHF!" in response or "End of /NAMES list" in response:
                self.connected = True
                self.socket.settimeout(None)  # Remove timeout for normal operation
                print(f"[{now()}] Connected to Twitch chat as {self.config.twitch_bot_username}")
                print(f"[{now()}] Sending Twitch chat messages...")
                self.send_message("ZeddyBot connected!")
                return True
            else:
                print(f"[{now()}] Unexpected response during connection: {response}")
                return False
                
        except socket.timeout:
            print(f"[{now()}] Timeout connecting to Twitch chat")
            return False
        except Exception as e:
            print(f"[{now()}] Error connecting to Twitch chat: {e}")
            return False

    def is_connected(self):
        """Check if the connection is still alive by testing socket"""
        if not self.connected or not self.socket:
            return False
        
        try:
            # Try to send a simple ping to test connection
            self.socket.send("PING :tmi.twitch.tv\r\n".encode('utf-8'))
            return True
        except (BrokenPipeError, socket.error, OSError) as e:
            print(f"[{now()}] Connection test failed, marking as disconnected")
            self.connected = False
            return False

    def disconnect(self):
        try:
            if self.connected and self.socket:
                self.socket.send("QUIT\r\n".encode('utf-8'))
                self.socket.close()
        except Exception as e:
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
            print(f"[{now()}] Error disconnecting from Twitch chat: {e}")
        finally:
            self.connected = False
            self.socket = None

    def send_message(self, message):
        if not self.connected:
            print(f"[{now()}] Twitch chat not connected, attempting to connect...")
            if not self.connect():
                print(f"[{now()}] Failed to connect to Twitch chat")
                return False

        try:
            # Test connection before sending
            if not self.is_connected():
                raise BrokenPipeError("Connection lost")
                
            # Send the actual message
            if self.socket is not None:
                message_to_send = f"PRIVMSG {self.channel} :{message}\r\n"
                self.socket.send(message_to_send.encode('utf-8'))
                print(f"[{now()}] Sending to Twitch chat: {message}")
                
                # Add sent message to chat display (since Twitch doesn't echo it back)
                if self.dashboard_data is not None:
                    self.dashboard_data.chat_messages.append({
                        'username': self.config.twitch_bot_username,
                        'message': message,
                        'timestamp': datetime.now().strftime('%d-%m-%Y %H:%M:%S')
                    })
            
            return True
            
        except (BrokenPipeError, socket.error, OSError) as e:
            print(f"[{now()}] Twitch chat connection error ({e}), marking as disconnected")
            self.connected = False
            
            # Try to reconnect and resend once
            print(f"[{now()}] Attempting to reconnect and resend message...")
            if self.connect():
                try:
                    if self.socket is not None:
                        message_to_send = f"PRIVMSG {self.channel} :{message}\r\n"
                        self.socket.send(message_to_send.encode('utf-8'))
                        print(f"[{now()}] Message sent after reconnection: {message}")
                        return True
                    else:
                        return False
                except Exception as retry_e:
                    print(f"[{now()}] Failed to send message after reconnection: {retry_e}")
                    return False
            else:
                print(f"[{now()}] Failed to reconnect to Twitch chat")
                return False
                
        except Exception as e:
            print(f"[{now()}] Unexpected error sending message to Twitch chat: {e}")
            return False

    def listen_for_chat(self):
        """Listen for chat messages and handle them"""
        if not self.connected or not self.dashboard_data or not self.socket:
            return
            
        try:
            # Set socket to non-blocking for select
            self.socket.setblocking(False)
            
            ready = select.select([self.socket], [], [], 0.1)  # 0.1 second timeout
            if ready[0]:
                try:
                    data = self.socket.recv(2048).decode('utf-8')
                    for line in data.split('\r\n'):
                        if line:
                            self.dashboard_data.parse_chat_message(line)
                except socket.error:
                    # Connection lost
                    self.connected = False
                    
        except Exception as e:
            if "timed out" not in str(e).lower():
                print(f"[{now()}] Twitch chat connection lost during ping check: {e}")
                self.connected = False
        finally:
            # Reset to blocking mode
            if self.socket:
                self.socket.setblocking(True)


class DashboardData:
    def __init__(self, config_path="./config.json"):
        self.config_path = config_path
        self.load_config()
        self.stream_history = []
        self.discord_stats = {"online_members": 0, "total_members": 0}
        self.bot_status = {"discord_connected": False, "twitch_connected": False}
        self.chat_messages = deque(maxlen=100)
        self.current_question = {}
        self.qna_theme = "default"
        self.obs_client = None
        self.last_obs_attempt = 0
        self.obs_connection_cooldown = 30
        
        # Stream status caching
        self.cached_stream_status = None
        self.last_stream_check = 0
        self.stream_cache_duration = 30  # Cache for 30 seconds

    def test_chat_connection(self):
        """Test if chat connection credentials are working without sending a message"""
        try:
            if not self.config.get('target_channel'):
                return False, "Missing target_channel in config"
            
            # Test connection to Twitch IRC
            sock = socket.socket()
            sock.settimeout(5)
            sock.connect(("irc.chat.twitch.tv", 6667))
            
            # Try with bot token if available, otherwise use anonymous
            if 'twitch_bot_access_token' in self.config and self.config['twitch_bot_access_token']:
                sock.send(f"PASS oauth:{self.config['twitch_bot_access_token']}\r\n".encode('utf-8'))
                sock.send(f"NICK {self.config.get('twitch_bot_username', 'Zeddy_bot')}\r\n".encode('utf-8'))
            else:
                # Anonymous connection (read-only)
                sock.send(f"NICK justinfan12345\r\n".encode('utf-8'))
            
            # Read response to check if authentication was successful
            response = sock.recv(1024).decode('utf-8', errors='ignore')
            # Only print non-verbose IRC messages for debugging
            if not any(code in response for code in ["001", "002", "003", "004", "375", "372", "376"]):
                print(f"[CHAT_TEST] IRC Response: {response}")  # Debug output
            sock.close()
            
            if ":tmi.twitch.tv 001" in response:  # Welcome message indicates success
                if 'twitch_bot_access_token' in self.config and self.config['twitch_bot_access_token']:
                    return True, "Chat connection test successful (authenticated bot)"
                else:
                    return True, "Chat connection test successful (anonymous - read only)"
            elif "Login authentication failed" in response or ":tmi.twitch.tv NOTICE * :Login authentication failed" in response:
                # Try to automatically refresh the token
                print(f"[{self._log_timestamp()}] [CHAT_TEST] Authentication failed, attempting automatic token refresh...")
                success, refresh_msg, new_token = refresh_twitch_bot_token("config.json")
                if success:
                    self.load_config()  # Reload config with new token
                    return True, f"Authentication failed but token auto-refreshed successfully: {refresh_msg}"
                else:
                    return False, f"Authentication failed and auto-refresh failed: {refresh_msg}"
            elif ":tmi.twitch.tv NOTICE * :Improperly formatted auth" in response:
                return False, "Improperly formatted auth - check token format"
            else:
                return False, f"Unexpected response: {response}"
                
        except socket.timeout:
            return False, "Connection timeout - check network connection"
        except Exception as e:
            return False, f"Connection test failed: {str(e)}"

    def _log_timestamp(self):
        """Get formatted timestamp for logging"""
        return datetime.now().strftime('%d-%m-%Y %H:%M:%S')

    def load_config(self):
        with open(self.config_path) as f:
            self.config = json.load(f)

    def connect_obs(self, host="10.0.0.228", port=4455, password=None):
        """Connect to OBS WebSocket v5 using ReqClient - gracefully handle OBS being offline"""
        if ReqClient is None:
            print(f"[{self._log_timestamp()}] [OBS] obsws-python not installed - OBS features disabled")
            self.obs_client = None
            return

        # Rate limiting: don't attempt connection too frequently
        current_time = time.time()
        if current_time - self.last_obs_attempt < self.obs_connection_cooldown:
            return  # Skip connection attempt, too soon
            
        self.last_obs_attempt = current_time
        
        # Use config values if not provided
        if host == "10.0.0.228":  # Default value
            obs_config = dashboard_data.config.get('obs', {})
            host = obs_config.get('host', 'localhost')
            port = obs_config.get('port', 4455)
            password = obs_config.get('password', '')
        
        print(f"[{self._log_timestamp()}] [OBS] Attempting to connect to OBS WebSocket at {host}:{port}...")
        
        # Temporarily suppress stderr to hide the obsws-python traceback
        import sys
        import io
        
        old_stderr = sys.stderr
        try:
            # Redirect stderr to suppress obsws-python error output
            sys.stderr = io.StringIO()
            
            # Clean up any existing client
            if self.obs_client:
                try:
                    self.obs_client.disconnect()
                except:
                    pass
                    
            # Attempt connection
            self.obs_client = ReqClient(host=host, port=port, password=password, timeout=5)
            # Test the connection immediately
            self.obs_client.get_version()
            
            # Restore stderr and print success
            sys.stderr = old_stderr
            print(f"[{self._log_timestamp()}] [OBS] ✅ Connected to OBS successfully at {host}:{port}")
            return
            
        except Exception:
            # Restore stderr first
            sys.stderr = old_stderr
            # Any exception from ReqClient creation or version check
            self.obs_client = None
            print(f"[{self._log_timestamp()}] [OBS] ⚠️  OBS not running or unreachable at {host}:{port}")
            print(f"[{self._log_timestamp()}] [OBS] Dashboard will continue without OBS integration (retry in {self.obs_connection_cooldown}s)")

    def obs_reconnect(self):
        """Retry connecting to OBS - useful when OBS starts after dashboard"""
        # Check if we're in cooldown period
        current_time = time.time()
        if current_time - self.last_obs_attempt < self.obs_connection_cooldown:
            time_remaining = int(self.obs_connection_cooldown - (current_time - self.last_obs_attempt))
            print(f"[{self._log_timestamp()}] [OBS] Connection attempt too recent, retry in {time_remaining}s")
            return False
            
        print(f"[{self._log_timestamp()}] [OBS] Manual reconnection attempt...")
        self.connect_obs()
        return self.obs_client is not None

    def parse_chat_message(self, line):
        """Parse incoming IRC chat messages using the same method as original dashboardqa.py"""
        try:
            if 'PRIVMSG' in line:
                # Parse IRC message format using colon splitting (original method)
                parts = line.split(':', 2)
                if len(parts) >= 3:
                    user_part = parts[1].split('!')[0]
                    message = parts[2]
                    
                    self.chat_messages.append({
                        'username': user_part,
                        'message': message,
                        'timestamp': datetime.now().strftime('%d-%m-%Y %H:%M:%S')
                    })
        except Exception as e:
            print(f"[{self._log_timestamp()}] Error parsing message: {e}")
            
        # Handle PING to keep connection alive
        if 'PING' in line:
            return 'PONG :tmi.twitch.tv\r\n'

    def display_question_on_obs(self, username, message):
        """Display Q&A using browser source (primary method)"""
        if not self.obs_client:
            return False, "OBS not connected - use reconnect button"
        
        try:
            # Store the question data for browser source to fetch via API
            self.current_question = {
                'username': username,
                'message': message,
                'timestamp': datetime.now().isoformat()
            }
            
            # Enable the Q&A nested scene (ID 73) which contains the browser source
            try:
                self.obs_client.set_scene_item_enabled(
                    scene_name="Scene - In Game",
                    item_id=73,
                    enabled=True
                )
                return True, "Question displayed on stream via browser source"
            except Exception as scene_error:
                print(f"[{self._log_timestamp()}] [OBS] Scene item ID 73 not found: {scene_error}")
                return False, f"Failed to show Q&A scene: {scene_error}"

        except Exception as e:
            return False, f"OBS error: {str(e)}"

    def hide_question_on_obs(self):
        """Hide Q&A browser source"""
        if not self.obs_client:
            return False, "OBS not connected - use reconnect button"
        
        try:
            # Clear the question data
            self.current_question = {}
            
            # Hide the Q&A nested scene (ID 73)
            try:
                self.obs_client.set_scene_item_enabled(
                    scene_name="Scene - In Game",
                    item_id=73,
                    enabled=False
                )
                return True, "Question hidden from stream"
            except Exception as scene_error:
                print(f"[{self._log_timestamp()}] [OBS] Scene item ID 73 not found: {scene_error}")
                return False, f"Failed to hide Q&A scene: {scene_error}"

        except Exception as e:
            return False, f"OBS error: {str(e)}"

    def get_twitch_stream_status(self):
        """Get current stream status with caching"""
        current_time = time.time()
        
        # Return cached data if still fresh
        if (self.cached_stream_status is not None and 
            current_time - self.last_stream_check < self.stream_cache_duration):
            return self.cached_stream_status
        
        try:
            # Get user info first
            user_url = f"https://api.twitch.tv/helix/users?login={self.config.get('target_channel', '')}"
            user_headers = {
                'Client-ID': self.config.get('twitch_bot_client_id', ''),
                'Authorization': f'Bearer {self.config.get("twitch_bot_access_token", "")}'
            }
            
            user_response = requests.get(user_url, headers=user_headers, timeout=10)
            
            if user_response.status_code != 200:
                print(f"[{self._log_timestamp()}] Failed to get user info: {user_response.status_code}")
                # Update cache timestamp even on failure to prevent spam
                self.last_stream_check = current_time
                return self.cached_stream_status
                
            user_data = user_response.json()
            if not user_data.get('data'):
                print(f"[{self._log_timestamp()}] No user data found for channel: {self.config.get('target_channel', '')}")
                self.last_stream_check = current_time
                return self.cached_stream_status
                
            user_id = user_data['data'][0]['id']
            
            # Get stream info
            stream_url = f"https://api.twitch.tv/helix/streams?user_id={user_id}"
            stream_response = requests.get(stream_url, headers=user_headers, timeout=10)
            
            if stream_response.status_code != 200:
                print(f"[{self._log_timestamp()}] Failed to get stream info: {stream_response.status_code}")
                self.last_stream_check = current_time
                return self.cached_stream_status
                
            stream_data = stream_response.json()
            
            if stream_data['data']:
                # Stream is live
                stream_info = stream_data['data'][0]
                result = {
                    'is_live': True,
                    'title': stream_info.get('title', ''),
                    'game_name': stream_info.get('game_name', ''),
                    'viewer_count': stream_info.get('viewer_count', 0),
                    'started_at': stream_info.get('started_at', ''),
                    'thumbnail_url': stream_info.get('thumbnail_url', '').replace('{width}', '1920').replace('{height}', '1080')
                }
            else:
                # Stream is offline
                result = {
                    'is_live': False,
                    'title': '',
                    'game_name': '',
                    'viewer_count': 0,
                    'started_at': '',
                    'thumbnail_url': ''
                }
            
            # Update cache
            self.cached_stream_status = result
            self.last_stream_check = current_time
            return result
                
        except requests.exceptions.Timeout:
            print(f"[{self._log_timestamp()}] Twitch API timeout")
            # Return cached data if available, otherwise None
            return self.cached_stream_status
        except requests.exceptions.RequestException as e:
            print(f"[{self._log_timestamp()}] Twitch API request error: {e}")
            # Return cached data if available, otherwise None
            return self.cached_stream_status
        except Exception as e:
            print(f"[{self._log_timestamp()}] Error getting stream status: {e}")
            # Don't update cache on unexpected errors, return existing cache if available
            return self.cached_stream_status

    def update_data(self):
        stream_status = self.get_twitch_stream_status()
        if stream_status:
            if not self.stream_history or self.stream_history[-1]["started_at"] != stream_status["started_at"]:
                self.stream_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "is_live": stream_status["is_live"],
                    "title": stream_status["title"],
                    "game_name": stream_status["game_name"],
                    "viewer_count": stream_status["viewer_count"],
                    "started_at": stream_status["started_at"]
                })


class ZeddyBot(commands.Bot):
    def __init__(self, config, dashboard_data):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True
        super().__init__(command_prefix='!', intents=intents)
        
        self.config = config
        self.dashboard_data = dashboard_data
        self.twitch_api = TwitchAPI(config)
        self.twitch_chat_bot = TwitchChatBot(config, self.twitch_api, dashboard_data)
        
        # User tracking for stream notifications
        self.online_users = {}
        self.sent_notifications = set()
        
        # Role upgrade tracking
        self.user_join_timestamps = {}

    async def on_ready(self):
        print(f"[{now()}] ZeddyBot is connected to Discord ")
        self.dashboard_data.bot_status["discord_connected"] = True
        
        # Connect to Twitch chat
        if self.twitch_chat_bot.connect():
            self.dashboard_data.bot_status["twitch_connected"] = True
        
        # Start background tasks
        self.update_discord_stats.start()
        self.check_streams.start()
        self.chat_listener.start()
        self.update_token_task.start()
        self.update_bot_token_task.start()
        self.check_twitch_ping.start()

    @loop(seconds=30)
    async def update_discord_stats(self):
        """Update Discord member statistics"""
        try:
            guild = self.get_guild(self.config.discord_channel_id)
            if guild:
                online_members = sum(1 for member in guild.members if not member.bot and member.status != discord.Status.offline)
                total_humans = sum(1 for member in guild.members if not member.bot)
                
                self.dashboard_data.discord_stats = {
                    "online_members": online_members,
                    "total_members": total_humans
                }
                
                print(f"[{now()}] Discord stats updated: {total_humans} humans, {online_members} online")
        except Exception as e:
            print(f"[{now()}] Error updating Discord stats: {e}")

    @loop(seconds=60)
    async def check_streams(self):
        """Check for new streams and send notifications"""
        try:
            # Update dashboard data
            self.dashboard_data.update_data()
            
            # Get current stream status
            stream_status = self.dashboard_data.get_twitch_stream_status()
            if not stream_status:
                return
                
            # Check if stream just went live
            if stream_status["is_live"]:
                stream_key = stream_status["started_at"]
                if stream_key and stream_key not in self.sent_notifications:
                    await self.send_stream_notification(stream_status)
                    self.sent_notifications.add(stream_key)
            
        except Exception as e:
            print(f"[{now()}] Error in stream check: {e}")

    @loop(seconds=5)
    async def chat_listener(self):
        """Listen for Twitch chat messages"""
        try:
            if self.twitch_chat_bot.connected:
                self.twitch_chat_bot.listen_for_chat()
            elif not self.twitch_chat_bot.connected:
                # Try to reconnect periodically
                if self.twitch_chat_bot.connect():
                    self.dashboard_data.bot_status["twitch_connected"] = True
                else:
                    self.dashboard_data.bot_status["twitch_connected"] = False
        except Exception as e:
            print(f"[{now()}] Error in chat listener: {e}")

    @loop(hours=24 * 5)
    async def update_token_task(self):
        """Update app access token every 5 days"""
        try:
            acc_tok = self.twitch_api.get_app_access_token()
            print(f"[{now()}] Changing access token ")
            
            self.config.access_token = acc_tok
            self.config.save()
            await self.change_presence(status=discord.Status.online)
        except Exception as e:
            print(f"[{now()}] Error updating app access token: {e}")

    @loop(hours=24)
    async def update_bot_token_task(self):
        """Update bot access token every 24 hours"""
        try:
            self.twitch_api.refresh_bot_token()
        except Exception as e:
            print(f"[{now()}] Error updating bot token: {e}")

    @loop(minutes=2)
    async def check_twitch_ping(self):
        """Check Twitch chat connection every 2 minutes"""
        try:
            # Check if chat bot is connected, reconnect if needed
            if not self.twitch_chat_bot.is_connected():
                print(f"[{now()}] Twitch chat disconnected, attempting reconnection...")
                if self.twitch_chat_bot.connect():
                    self.dashboard_data.bot_status["twitch_connected"] = True
                    print(f"[{now()}] Twitch chat reconnected successfully")
                else:
                    self.dashboard_data.bot_status["twitch_connected"] = False
                    print(f"[{now()}] Failed to reconnect to Twitch chat")
        except Exception as e:
            print(f"[{now()}] Error in Twitch ping check: {e}")

    async def send_stream_notification(self, stream_info):
        """Send Discord notification when stream goes live"""
        try:
            channel = self.get_channel(self.config.discord_channel_id)
            # Only send to text-based channels that support sending messages
            if isinstance(channel, (discord.TextChannel, discord.DMChannel, discord.Thread)):
                embed = discord.Embed(
                    title=f"🔴 {self.config.target_channel} is now live!",
                    description=stream_info["title"],
                    color=0x9146FF,
                    url=f"https://twitch.tv/{self.config.target_channel}",
                    timestamp=datetime.now()
                )
                
                if stream_info["game_name"]:
                    embed.add_field(name="Game", value=stream_info["game_name"], inline=True)
                
                if stream_info["thumbnail_url"]:
                    embed.set_image(url=stream_info["thumbnail_url"])
                
                await channel.send(embed=embed)
                
                # Also send to Twitch chat
                chat_message = f"🔴 {self.config.target_channel} just went live! Check it out at https://twitch.tv/{self.config.target_channel}"
                self.twitch_chat_bot.send_message(chat_message)
                
        except Exception as e:
            print(f"[{now()}] Error sending stream notification: {e}")


# Global instances
config = Config("config.json")
dashboard_data = DashboardData("config.json")
bot = ZeddyBot(config, dashboard_data)

# Flask app setup
app = Flask(__name__, template_folder='../templates')
CORS(app)

# Connect to OBS on startup (gracefully)
dashboard_data.connect_obs()

# Flask Routes
@app.route('/')
def dashboard():
    return render_template('dashboardqa.html')

@app.route('/qna')
def qna_display():
    return render_template('qna_display.html')

@app.route('/api/status')
def api_status():
    """Get comprehensive status information in the format expected by the dashboard"""
    stream_status = dashboard_data.get_twitch_stream_status()
    
    # Fallback data if stream status fails
    if stream_status is None:
        stream_status = {
            'is_live': False,
            'title': 'Unable to fetch stream data',
            'game_name': '',
            'viewer_count': 0,
            'started_at': '',
            'thumbnail_url': ''
        }
    
    # Convert to expected format for the dashboard template
    return jsonify({
        'stream': {
            'live': stream_status['is_live'],
            'title': stream_status['title'],
            'game': stream_status['game_name'], 
            'viewers': stream_status['viewer_count']
        },
        'discord': dashboard_data.discord_stats,
        'bot_status': dashboard_data.bot_status,
        'obs_connected': dashboard_data.obs_client is not None
    })



@app.route('/api/history')
def get_history():
    return jsonify(dashboard_data.stream_history)

@app.route('/api/send_chat', methods=['POST'])
def send_chat():
    try:
        data = request.get_json()
        message = data.get('message', '')
        
        if not message:
            return jsonify({'success': False, 'error': 'No message provided'}), 400
        
        if bot.twitch_chat_bot.send_message(message):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Failed to send message'}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/quick_messages', methods=['GET'])
def get_quick_messages():
    quick_messages = dashboard_data.config.get('quick_messages', [
        "Thanks for watching!",
        "Don't forget to follow!",
        "Join our Discord!",
        "What game should we play next?",
        "Thanks for the follow!",
        "Welcome to the stream!"
    ])
    return jsonify(quick_messages)

@app.route('/api/quick_messages', methods=['POST'])
def send_quick_message():
    try:
        data = request.get_json()
        message_index = data.get('index')
        message_type = data.get('type')
        
        # Define message mapping for the template's message types
        message_map = {
            'welcome': "Thanks for watching! Welcome to the stream!",
            'follow': "Thanks for the follow! Don't forget to hit that notification bell!",
            'brb': "Be right back! Thanks for your patience!",
            'ending': "Thanks for watching! Stream ending soon!",
            'lurk': "Thanks for the lurk! Enjoy the stream!"
        }
        
        # Handle both new format (type) and old format (index)
        if message_type:
            message = message_map.get(message_type, f"Unknown message type: {message_type}")
        elif message_index is not None:
            quick_messages = dashboard_data.config.get('quick_messages', [])
            if message_index < 0 or message_index >= len(quick_messages):
                return jsonify({'success': False, 'error': 'Invalid message index'}), 400
            message = quick_messages[message_index]
        else:
            return jsonify({'success': False, 'error': 'No message type or index provided'}), 400
        
        if bot.twitch_chat_bot.send_message(message):
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': 'Failed to send message'}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/chat')
def get_chat():
    return jsonify(list(dashboard_data.chat_messages))

@app.route('/api/discord_stats', methods=['GET'])
def get_discord_stats():
    """Get Discord server stats from the integrated Discord bot"""
    try:
        if bot and bot.is_ready():
            total_members = 0
            online_members = 0
            total_humans = 0
            
            # Get stats from all guilds
            for guild in bot.guilds:
                total_members += guild.member_count or 0
                for member in guild.members:
                    if not member.bot:
                        total_humans += 1
                        if member.status != discord.Status.offline:
                            online_members += 1
            
            return jsonify({
                "success": True,
                "stats": {
                    "online_members": online_members,
                    "total_members": total_members,
                    "total_humans": total_humans,
                    "bot_connected": True
                }
            })
        else:
            return jsonify({
                "success": False,
                "stats": {
                    "online_members": 0,
                    "total_members": 0,
                    "total_humans": 0,
                    "bot_connected": False
                },
                "error": "Discord bot not connected"
            })
    except Exception as e:
        return jsonify({
            "success": False,
            "stats": {
                "online_members": 0,
                "total_members": 0,
                "total_humans": 0,
                "bot_connected": False
            },
            "error": f"Error getting Discord stats: {str(e)}"
        })

@app.route('/api/test_chat_messages', methods=['POST'])
def add_test_chat_messages():
    """Add some test messages to verify chat display is working"""
    test_messages = [
        {'username': 'TestUser1', 'message': 'Hello world!', 'timestamp': datetime.now().strftime('%d-%m-%Y %H:%M:%S')},
        {'username': 'TestUser2', 'message': 'How is everyone doing?', 'timestamp': datetime.now().strftime('%d-%m-%Y %H:%M:%S')},
        {'username': 'TestUser3', 'message': 'Great stream!', 'timestamp': datetime.now().strftime('%d-%m-%Y %H:%M:%S')}
    ]
    
    for msg in test_messages:
        dashboard_data.chat_messages.append(msg)
    
    return jsonify({'success': True, 'message': f'Added {len(test_messages)} test messages'})

@app.route('/api/test_chat', methods=['GET'])
def test_chat():
    success, message = dashboard_data.test_chat_connection()
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 500

@app.route('/api/refresh_token', methods=['POST'])
def refresh_token():
    try:
        success, message, new_token = refresh_twitch_bot_token("config.json")
        if success:
            # Reload config to get updated token
            dashboard_data.load_config()
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/obs_scene_items/<scene_name>')
def get_obs_scene_items(scene_name):
    if not dashboard_data.obs_client:
        return jsonify({'error': 'OBS not connected'}), 503
    
    try:
        scene_items_response = dashboard_data.obs_client.get_scene_item_list(scene_name)
        if scene_items_response is not None:
            # Try accessing as object attribute first
            scene_items = getattr(scene_items_response, 'scene_items', None)
            if scene_items is not None:
                return jsonify(scene_items)
            # Try accessing as dict
            elif isinstance(scene_items_response, dict) and 'scene_items' in scene_items_response:
                return jsonify(scene_items_response['scene_items'])
        
        # Return empty list if no scene items found
        return jsonify([])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/obs_toggle_item', methods=['POST'])
def toggle_obs_item():
    if not dashboard_data.obs_client:
        return jsonify({'error': 'OBS not connected'}), 503
    
    try:
        data = request.get_json()
        scene_name = data.get('scene_name')
        item_id = data.get('item_id')
        enabled = data.get('enabled')
        
        if scene_name is None or item_id is None or enabled is None:
            return jsonify({'error': 'Missing required parameters'}), 400
        
        try:
            dashboard_data.obs_client.set_scene_item_enabled(scene_name, item_id, enabled)
            return jsonify({'success': True})
        except Exception as scene_error:
            if "scene item ID 73 not found" in str(scene_error):
                print(f"[{dashboard_data._log_timestamp()}] [OBS] Scene item ID 73 not found: {scene_error}")
                return jsonify({'error': 'Scene item not found - may have been deleted or recreated in OBS'}), 404
            else:
                raise scene_error
                
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ping', methods=['GET'])
def ping():
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'bot_connected': dashboard_data.bot_status["discord_connected"],
        'twitch_connected': dashboard_data.bot_status["twitch_connected"]
    })

@app.route('/api/obs_reconnect', methods=['POST'])
def obs_reconnect():
    try:
        success = dashboard_data.obs_reconnect()
        if success:
            return jsonify({'success': True, 'message': 'OBS reconnected successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to reconnect to OBS'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/obs_status', methods=['GET'])
def obs_status():
    """Get OBS connection status without attempting reconnection"""
    try:
        if dashboard_data.obs_client:
            # Quick test to see if connection is still valid
            try:
                version_info = dashboard_data.obs_client.get_version()
                current_scene = dashboard_data.obs_client.get_current_program_scene()
                
                # Safely extract scene name with multiple fallback methods
                scene_name = "Unknown"
                if current_scene is not None:
                    try:
                        # Try accessing as object attribute
                        if hasattr(current_scene, 'scene_name'):
                            scene_name = getattr(current_scene, 'scene_name', "Unknown")
                        # Try accessing as dict
                        elif isinstance(current_scene, dict) and 'scene_name' in current_scene:
                            scene_name = current_scene['scene_name']
                        # Try other possible attribute names
                        elif hasattr(current_scene, 'sceneName'):
                            scene_name = getattr(current_scene, 'sceneName', "Unknown")
                    except (AttributeError, KeyError, TypeError):
                        scene_name = "Unknown"
                
                return jsonify({
                    "success": True,
                    "connected": True,
                    "current_scene": scene_name,
                    "message": f"OBS Connected - Current: {scene_name}"
                })
            except Exception:
                # Connection lost
                dashboard_data.obs_client = None
                return jsonify({
                    "success": True,
                    "connected": False,
                    "message": "OBS connection lost"
                })
        else:
            # Check cooldown status
            current_time = time.time()
            time_since_attempt = current_time - dashboard_data.last_obs_attempt
            
            if time_since_attempt < dashboard_data.obs_connection_cooldown:
                time_remaining = int(dashboard_data.obs_connection_cooldown - time_since_attempt)
                return jsonify({
                    "success": True,
                    "connected": False,
                    "message": f"OBS not connected (retry in {time_remaining}s)"
                })
            else:
                return jsonify({
                    "success": True,
                    "connected": False,
                    "message": "OBS not connected - use reconnect button"
                })
    except Exception as e:
        return jsonify({
            "success": False,
            "connected": False,
            "message": f"Error checking OBS status: {str(e)}"
        })

@app.route('/api/display_question', methods=['POST'])
def display_question():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No JSON data provided"})
        
        username = data.get('username', '')
        message = data.get('message', '')
        
        if not username or not message:
            return jsonify({"success": False, "error": "Missing username or message"})
        
        # Use the OBS browser source method (primary)
        ok, msg = dashboard_data.display_question_on_obs(username, message)
        
        return jsonify({"success": ok, "message": msg})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/hide_question', methods=['POST'])
def hide_question():
    try:
        # Use the OBS browser source method
        ok, msg = dashboard_data.hide_question_on_obs()
        return jsonify({"success": ok, "message": msg})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/current_question')
def get_current_question():
    try:
        # Include the current theme with the question data
        question_data = dashboard_data.current_question.copy() if dashboard_data.current_question else {}
        question_data['theme'] = getattr(dashboard_data, 'qna_theme', 'dark')
        return jsonify(question_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/qna_theme', methods=['POST'])
def set_qna_theme():
    try:
        data = request.get_json()
        theme = data.get('theme', 'default')
        
        # Validate theme
        valid_themes = ['default', 'dark', 'colorful', 'minimal']
        if theme not in valid_themes:
            return jsonify({'success': False, 'error': 'Invalid theme'}), 400
        
        dashboard_data.qna_theme = theme
        return jsonify({'success': True, 'theme': theme})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bot_status', methods=['GET'])
def get_bot_status():
    return jsonify({
        'discord_connected': dashboard_data.bot_status["discord_connected"],
        'twitch_connected': dashboard_data.bot_status["twitch_connected"],
        'obs_connected': dashboard_data.obs_client is not None
    })

@app.route('/api/force_notification', methods=['POST'])
def force_notification():
    try:
        # Get current stream status and force a notification
        stream_status = dashboard_data.get_twitch_stream_status()
        if stream_status and stream_status["is_live"]:
            # Force send notification by temporarily clearing the sent notifications
            original_notifications = bot.sent_notifications.copy()
            bot.sent_notifications.clear()
            
            # Send notification
            asyncio.create_task(bot.send_stream_notification(stream_status))
            
            # Restore notifications set but add current stream
            bot.sent_notifications = original_notifications
            bot.sent_notifications.add(stream_status["started_at"])
            
            return jsonify({'success': True, 'message': 'Notification sent'})
        else:
            return jsonify({'success': False, 'message': 'Stream is not live'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/test_notification', methods=['POST'])
def test_notification():
    try:
        # Send a test notification regardless of stream status
        test_stream_info = {
            "title": "🧪 This is a test notification",
            "game_name": "Testing",
            "thumbnail_url": ""
        }
        
        asyncio.create_task(bot.send_stream_notification(test_stream_info))
        return jsonify({'success': True, 'message': 'Test notification sent'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/obs_scene', methods=['POST'])
def change_obs_scene():
    """Change OBS scene"""
    try:
        data = request.json if request.json else {}
        scene_name = data.get('scene_name', '')
        
        if not dashboard_data.obs_client:
            return jsonify({"success": False, "error": "OBS not connected"})
        
        dashboard_data.obs_client.set_current_program_scene(scene_name)
        return jsonify({
            "success": True,
            "message": f"Scene changed to: {scene_name}"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/obs_scenes', methods=['GET'])
def get_obs_scenes():
    """Get list of available OBS scenes"""
    try:
        if not dashboard_data.obs_client:
            return jsonify({"success": False, "error": "OBS not connected - use reconnect button"})
        
        # Test the connection first
        try:
            scenes_response = dashboard_data.obs_client.get_scene_list()
            scene_list = []
            current_scene = None
            
            if scenes_response is not None:
                # Handle both object and dict return types for scenes
                if hasattr(scenes_response, 'scenes'):
                    scene_items = getattr(scenes_response, 'scenes', [])
                    scene_list = [scene['sceneName'] if isinstance(scene, dict) else getattr(scene, 'sceneName', None) for scene in scene_items]
                    current_scene = getattr(scenes_response, 'current_program_scene_name', None)
                elif isinstance(scenes_response, dict) and 'scenes' in scenes_response:
                    scene_items = scenes_response['scenes']
                    scene_list = [scene['sceneName'] for scene in scene_items]
                    current_scene = scenes_response.get('current_program_scene_name')
            
            return jsonify({
                'success': True,
                'scenes': scene_list,
                'current_scene': current_scene
            })
        except Exception as e:
            # Connection lost
            dashboard_data.obs_client = None
            return jsonify({"success": False, "error": f"OBS connection lost: {str(e)}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    print(f"[{now()}] Starting ZeddyBot...")
    print(f"[{now()}] HTTP server starting on http://0.0.0.0:5000 (Dashboard + Discord stats API)")
    
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Start Discord bot
    try:
        bot.run(config.discord_token)
    except KeyboardInterrupt:
        print(f"[{now()}] Shutting down...")
    except Exception as e:
        print(f"[{now()}] Error running bot: {e}")
