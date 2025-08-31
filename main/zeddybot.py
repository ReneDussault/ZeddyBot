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
from flask import Flask, render_template, jsonify, request, Response
from flask_cors import CORS
import threading
import sys
import os
import time
import select
from collections import deque
from typing import Optional
import queue

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

    @property
    def watchlist(self):
        return self.data.get("watchlist", [])

    @property
    def discord_live_role_id(self):
        return self.data.get("discord_live_role_id", "")

    @property
    def discord_drifters_role_id(self):
        return self.data.get("discord_drifters_role_id", "")

    @property
    def discord_outlaws_role_id(self):
        return self.data.get("discord_outlaws_role_id", "")

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
            print(f"[{now()}] [TWITCH] {message}")
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
                message = "Operational status: Online."
                self.connected = True
                self.socket.settimeout(None)  # Remove timeout for normal operation
                print(f"[{now()}] [TWITCH] Connected to chat as {self.config.twitch_bot_username}")
                print(f"[{now()}] [TWITCH] Sending to chat: {message}")
                self.send_message(message)
                return True
            else:
                print(f"[{now()}] [TWITCH] Unexpected response during connection: {response}")
                return False
                
        except socket.timeout:
            print(f"[{now()}] [TWITCH] Timeout connecting to chat")
            return False
        except Exception as e:
            print(f"[{now()}] [TWITCH] Error connecting to chat: {e}")
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
            print(f"[{now()}] [TWITCH] Connection test failed, marking as disconnected")
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
            print(f"[{now()}] [TWITCH] Error disconnecting from chat: {e}")
        finally:
            self.connected = False
            self.socket = None

    def send_message(self, message):
        if not self.connected:
            print(f"[{now()}] [TWITCH] Chat not connected, attempting to connect...")
            if not self.connect():
                print(f"[{now()}] [TWITCH] Failed to connect to chat")
                return False

        try:
            # Test connection before sending
            if not self.is_connected():
                raise BrokenPipeError("Connection lost")
                
            # Send the actual message
            if self.socket is not None:
                message_to_send = f"PRIVMSG {self.channel} :{message}\r\n"
                self.socket.send(message_to_send.encode('utf-8'))
                
                # Add sent message to chat display (since Twitch doesn't echo it back)
                message_data = {
                    'username': self.config.twitch_bot_username,
                    'message': message,
                    'timestamp': datetime.now().strftime('%d-%m-%Y %H:%M:%S')
                }
                
                if self.dashboard_data is not None:
                    self.dashboard_data.chat_messages.append(message_data)
                
                # Don't broadcast here - let parse_chat_messages handle it when we see our own message
                # This prevents duplicate broadcasting
            
            return True
            
        except (BrokenPipeError, socket.error, OSError) as e:
            print(f"[{now()}] [TWITCH] Chat connection error ({e}), marking as disconnected")
            self.connected = False
            
            # Try to reconnect and resend once
            print(f"[{now()}] [TWITCH] Attempting to reconnect and resend message...")
            if self.connect():
                try:
                    if self.socket is not None:
                        message_to_send = f"PRIVMSG {self.channel} :{message}\r\n"
                        self.socket.send(message_to_send.encode('utf-8'))
                        print(f"[{now()}] [TWITCH] Message sent after reconnection: {message}")
                        
                        # Also broadcast reconnection message to SSE clients
                        message_data = {
                            'username': self.config.twitch_bot_username,
                            'message': message,
                            'timestamp': datetime.now().strftime('%d-%m-%Y %H:%M:%S')
                        }
                        if self.dashboard_data is not None:
                            self.dashboard_data.chat_messages.append(message_data)
                        # Don't broadcast here either - let parse_chat_messages handle it
                        
                        return True
                    else:
                        return False
                except Exception as retry_e:
                    print(f"[{now()}] [TWITCH] Failed to send message after reconnection: {retry_e}")
                    return False
            else:
                print(f"[{now()}] [TWITCH] Failed to reconnect to chat")
                return False
                
        except Exception as e:
            print(f"[{now()}] [TWITCH] Unexpected error sending message to chat: {e}")
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
                    # Only handle PING/PONG, chat reading is handled by DashboardData thread
                    for line in data.split('\r\n'):
                        if line.startswith("PING"):
                            if self.socket is not None:
                                self.socket.send("PONG\r\n".encode("utf-8"))
                except socket.error:
                    # Connection lost
                    self.connected = False
                    
        except Exception as e:
            if "timed out" not in str(e).lower():
                print(f"[{now()}] [TWITCH] Chat connection lost during ping check: {e}")
                self.connected = False
        finally:
            # Reset to blocking mode
            if self.socket:
                self.socket.setblocking(True)

    def check_for_ping(self):
        """Check for PING from Twitch and respond with PONG"""
        if not self.connected or self.socket is None:
            return

        try:
            # Set socket to non-blocking to prevent blocking the Discord event loop
            self.socket.setblocking(False)
            
            try:
                data = self.socket.recv(2048).decode("utf-8")
                lines = data.strip().split('\r\n')
                
                for line in lines:
                    if line.startswith("PING"):
                        if self.socket is not None:
                            self.socket.send("PONG :tmi.twitch.tv\r\n".encode("utf-8"))
                    # Chat message parsing is now handled by DashboardData thread
            except BlockingIOError:
                # No data available, this is normal for non-blocking sockets
                pass
            except socket.error:
                # Connection lost
                self.connected = False
        except Exception as e:
            if "timed out" not in str(e).lower():
                print(f"[{now()}] [TWITCH] Error in check_for_ping: {e}")
        finally:
            # Always restore blocking mode for other operations
            if self.socket:
                self.socket.setblocking(True)


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
        
        # Chat reading functionality
        self.chat_sock = None
        # Don't start chat reader automatically - will be started manually during startup

    def start_chat_reader(self):
        """Start background thread to read chat messages"""
        def chat_reader():
            while True:
                try:
                    self.connect_to_chat()
                    while self.chat_sock:
                        ready = select.select([self.chat_sock], [], [], 1)
                        if ready[0]:
                            data = self.chat_sock.recv(1024).decode('utf-8', errors='ignore')
                            self.parse_chat_messages(data)
                except Exception as e:
                    print(f"[{now()}] [TWITCH] Chat reader error: {e}")
                    time.sleep(5)
        chat_thread = threading.Thread(target=chat_reader, daemon=True)
        chat_thread.start()

    def connect_to_chat(self):
        """Connect to Twitch IRC for reading chat"""
        try:
            if self.chat_sock:
                self.chat_sock.close()
            self.chat_sock = socket.socket()
            self.chat_sock.connect(("irc.chat.twitch.tv", 6667))
            
            # Use bot token if available, otherwise anonymous
            if 'twitch_bot_access_token' in self.config and self.config['twitch_bot_access_token']:
                self.chat_sock.send(f"PASS oauth:{self.config['twitch_bot_access_token']}\r\n".encode('utf-8'))
                self.chat_sock.send(f"NICK {self.config.get('twitch_bot_username', 'Zeddy_bot')}\r\n".encode('utf-8'))
            else:
                # Anonymous connection for reading only
                self.chat_sock.send(f"NICK justinfan12345\r\n".encode('utf-8'))
            
            self.chat_sock.send(f"JOIN #{self.config.get('target_channel', '')}\r\n".encode('utf-8'))
            print(f"[{now()}] [TWITCH] ✓ Chat connected: #{self.config.get('target_channel', '')}")
        except Exception as e:
            print(f"[{now()}] [TWITCH] Failed to connect to chat: {e}")
            self.chat_sock = None

    def parse_chat_messages(self, data):
        """Parse incoming chat messages from IRC"""
        lines = data.strip().split('\r\n')
        for line in lines:
            if 'PRIVMSG' in line:
                try:
                    parts = line.split(':', 2)
                    if len(parts) >= 3:
                        user_part = parts[1].split('!')[0]
                        message = parts[2]
                        if user_part == "zeddy_bot" and message == "Operational status: Online.":
                            print(f"[{now()}] [TWITCH] ZeddyBot connected to Twitch chat") 
                        
                        # Create message data
                        message_data = {
                            'username': user_part,
                            'message': message,
                            'timestamp': datetime.now().strftime('%d-%m-%Y %H:%M:%S')
                        }
                        
                        # Add to local storage
                        self.chat_messages.append(message_data)
                        
                        # Always broadcast all messages to SSE clients
                        broadcast_chat_message(message_data)
                            
                except Exception as e:
                    print(f"[{self._log_timestamp()}] [TWITCH] Error parsing message: {e}")
            elif 'PING' in line:
                if self.chat_sock:
                    self.chat_sock.send("PONG :tmi.twitch.tv\r\n".encode('utf-8'))

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
                print(f"[{now()}] [TWITCH] IRC Response: {response}")  # Debug output
            sock.close()
            
            if ":tmi.twitch.tv 001" in response:  # Welcome message indicates success
                if 'twitch_bot_access_token' in self.config and self.config['twitch_bot_access_token']:
                    return True, "Chat connection test successful (authenticated bot)"
                else:
                    return True, "Chat connection test successful (anonymous - read only)"
            elif "Login authentication failed" in response or ":tmi.twitch.tv NOTICE * :Login authentication failed" in response:
                # Try to automatically refresh the token
                print(f"[{now()}] [TWITCH] Authentication failed, attempting automatic token refresh...")
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
            print(f"[{now()}] [OBS] obsws-python not installed - OBS features disabled")
            self.obs_client = None
            return

        # Rate limiting: don't attempt connection too frequently
        current_time = time.time()
        if current_time - self.last_obs_attempt < self.obs_connection_cooldown:
            return  # Skip connection attempt, too soon
            
        self.last_obs_attempt = current_time
        
        # Use config values if not provided
        if host == "10.0.0.228":  # Default value
            obs_config = self.config.get('obs', {})
            host = obs_config.get('host', 'localhost')
            port = obs_config.get('port', 4455)
            password = obs_config.get('password', '')
        
        print(f"[{now()}] [OBS] Attempting to connect to OBS WebSocket")
        
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
            print(f"[{now()}] [OBS] ✅ Connected to OBS successfully at {host}:{port}")
            return
            
        except Exception:
            # Restore stderr first
            sys.stderr = old_stderr
            # Any exception from ReqClient creation or version check
            self.obs_client = None
            print(f"[{now()}] [OBS] ⚠️ OBS not running or unreachable")
            print(f"[{now()}] [OBS] Continue without OBS integration")

    def obs_reconnect(self):
        """Retry connecting to OBS - useful when OBS starts after dashboard"""
        # Check if we're in cooldown period
        current_time = time.time()
        if current_time - self.last_obs_attempt < self.obs_connection_cooldown:
            time_remaining = int(self.obs_connection_cooldown - (current_time - self.last_obs_attempt))
            print(f"[{now()}] [OBS] Connection attempt too recent, retry in {time_remaining}s")
            return False

        print(f"[{now()}] [OBS] Manual reconnection attempt...")
        self.connect_obs()
        return self.obs_client is not None

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
                print(f"[{now()}] [OBS] Scene item ID 73 not found: {scene_error}")
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
                print(f"[{now()}] [OBS] Scene item ID 73 not found: {scene_error}")
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
            headers = {
                "Authorization": f"Bearer {self.config['access_token']}",
                "Client-Id": self.config['twitch_client_id']
            }
            
            # Get user ID first
            user_response = requests.get(
                "https://api.twitch.tv/helix/users",
                params={"login": self.config.get("target_channel", "")},
                headers=headers,
                timeout=10  # Add timeout to prevent hanging
            )
            
            if user_response.status_code != 200:
                print(f"[{now()}] [TWITCH] Failed to get user info: {user_response.status_code}")
                self.cached_stream_status = None
                self.last_stream_check = current_time
                return None
                
            user_data = user_response.json()["data"]
            if not user_data:
                print(f"[{now()}] [TWITCH] No user data found for channel: {self.config.get('target_channel', '')}")
                self.cached_stream_status = None
                self.last_stream_check = current_time
                return None
                
            user_id = user_data[0]["id"]
            
            # Get stream status
            stream_response = requests.get(
                "https://api.twitch.tv/helix/streams",
                params={"user_id": user_id},
                headers=headers,
                timeout=10  # Add timeout to prevent hanging
            )
            
            if stream_response.status_code == 200:
                streams = stream_response.json()["data"]
                stream_data = streams[0] if streams else None
                
                # Cache the result
                self.cached_stream_status = stream_data
                self.last_stream_check = current_time
                
                return stream_data
            else:
                print(f"[{now()}] [TWITCH] Failed to get stream info: {stream_response.status_code}")
                self.cached_stream_status = None
                self.last_stream_check = current_time
                return None
                
        except requests.exceptions.Timeout:
            print(f"[{now()}] [TWITCH] API timeout")
            # Return cached data if available, otherwise None
            return self.cached_stream_status
        except requests.exceptions.RequestException as e:
            print(f"[{now()}] [TWITCH] API request error: {e}")
            # Return cached data if available, otherwise None
            return self.cached_stream_status
        except Exception as e:
            print(f"[{now()}] [TWITCH] Error getting stream status: {e}")
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
        
        # For tracking sent notifications (used by Flask routes)
        self.sent_notifications = set()

        # Bot moderation functionality removed due to TwitchInsights being discontinued

        self.setup()


    def log_once(self, message):
        if getattr(self, "_last_log_line", None) != message:
            print(f"[{now()}] {message}")
            self._last_log_line = message

    def setup(self):
        """
        Some boilerplate commands and events
        """

        @self.event
        async def on_command_error(ctx, error):
            """Handle command errors gracefully"""
            if isinstance(error, commands.CommandNotFound):
                # Silently ignore unknown commands - don't spam logs or send error messages
                return
            elif isinstance(error, commands.MissingRequiredArgument):
                await ctx.send(f"❌ Missing required argument. Use `!help {ctx.command}` for usage info.")
            elif isinstance(error, commands.BadArgument):
                await ctx.send(f"❌ Invalid argument. Use `!help {ctx.command}` for usage info.")
            elif isinstance(error, commands.MissingPermissions):
                await ctx.send("❌ You don't have permission to use this command.")
            else:
                # Log other errors but don't spam the user
                print(f"[{now()}] [DISCORD] Command error:\n    ╰› {error}")

        @self.command()
        async def ping(ctx):
            await ctx.send("Pong!")


        @self.command()
        async def hello(ctx):
            await ctx.send(f"Hello {ctx.author.name}!")


        @self.command()
        async def twitch_chat(ctx, *, message):
            # Include Discord username in the message
            formatted_message = f"[{ctx.author.display_name}]: {message}"
            if self.twitch_chat_bot.send_message(formatted_message):
                await ctx.send(f"Message sent to Twitch chat: {formatted_message}")
            else:
                await ctx.send("Failed to send message to Twitch chat.")


        @self.command()
        async def refresh_bot_token(ctx):
            if self.twitch_api.refresh_bot_token():
                await ctx.send("Successfully refreshed the bot's Twitch token.")
            else:
                await ctx.send("Failed to refresh the bot's Twitch token.")

        # Bot moderation commands
        # Bot moderation Discord commands removed due to TwitchInsights being discontinued

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

            print(f"[{now()}] [DISCORD] ✓ ZeddyBot connected to Discord")
            
            # Initialize Discord stats cache
            await self.update_discord_stats()
            
            self.update_token_task.start()
            self.update_bot_token_task.start()
            self.check_twitch_online_streamers.start()
            self.check_twitch_ping.start()

            self.twitch_chat_bot.connect()


        @self.listen("on_member_update")
        async def update_live_role_member(before, after):
            await self.log_activity_changes(before, after)
            await self._handle_live_role_update(before, after)
            
            # Update Discord stats if online status changed
            if before.status != after.status:
                await self.update_discord_stats()


        @self.listen("on_presence_update")
        async def update_live_role_presence(before, after):
            await self.log_activity_changes(before, after)
            await self._handle_live_role_update(before, after)
            
            # Update Discord stats if online status changed
            if before.status != after.status:
                await self.update_discord_stats()


        @self.event
        async def on_member_join(self, member):
            print(f"[{now()}] [DISCORD] {member} has joined the server")

            # drifters role - convert to int and validate
            drifters_role = member.guild.get_role(int(self.DRIFTERS_ROLE_ID))
            if drifters_role:
                has_drifter_role = drifters_role in member.roles
                
                if not has_drifter_role:
                    await member.add_roles(drifters_role)
                    print(f"[{now()}] [DISCORD] Added Drifters role to {member}")

                    # role upgrade after 30 days
                    self.loop.create_task(self._upgrade_role_after_delay(member))
            else:
                print(f"[{now()}] [DISCORD] ERROR: Drifters role with ID {self.DRIFTERS_ROLE_ID} not found!")
            
            # Update Discord stats in real-time
            await self.update_discord_stats()

        @self.event
        async def on_member_remove(self, member):
            print(f"[{now()}] [DISCORD] {member} has left the server")

            # Update Discord stats in real-time
            await self.update_discord_stats()


    async def update_discord_stats(self):
        """Update Discord stats in real-time and notify dashboard"""
        try:
            if not self.guilds:
                return
            
            guild = self.guilds[0]  # Assuming first guild
            
            # Count members and filter out bots
            total_members = guild.member_count
            human_members = len([m for m in guild.members if not m.bot])
            online_members = len([m for m in guild.members if m.status != discord.Status.offline and not m.bot])
            
            # Store stats for API endpoint
            self._discord_stats = {
                'total_members': total_members,
                'total_humans': human_members,
                'online_members': online_members,
                'bot_connected': self.is_ready(),
                'guild_name': guild.name,
                'last_updated': datetime.now().isoformat()
            }
            
            print(f"[{now()}] [DISCORD] Discord stats updated: {human_members} humans, {online_members} online")
            
        except Exception as e:
            print(f"[{now()}] [DISCORD] Error updating Discord stats: {e}")

    async def log_activity_changes(self, before, after):
        before_activities = set((a.type, getattr(a, 'name', None)) for a in before.activities)
        after_activities = set((a.type, getattr(a, 'name', None)) for a in after.activities)

        started = after_activities - before_activities
        stopped = before_activities - after_activities

        # Handle started activities with detailed information
        for act_type, act_name in started:
            # Find the actual activity object to get detailed info
            activity = None
            for a in after.activities:
                if a.type == act_type and getattr(a, 'name', None) == act_name:
                    activity = a
                    break
            
            if activity and isinstance(activity, discord.Spotify):
                # Special handling for Spotify activities
                print(f"[{now()}] [DISCORD] User '{after.name}' started activity:")
                print(f"    ╰› 🎵 {act_type.name} ({act_name})")
                print(f"    ╰› 🎵 {activity.artist} - {activity.title}")

            else:
                print(f"[{now()}] [DISCORD] User '{after.name}' started activity:")
                print(f"    ╰› {act_type.name} ({act_name})")

        for act_type, act_name in stopped:
            # Find the actual activity object for stopped activities too
            activity = None
            for a in before.activities:
                if a.type == act_type and getattr(a, 'name', None) == act_name:
                    activity = a
                    break

            if activity and isinstance(activity, discord.Spotify):
                print(f"[{now()}] [DISCORD] User '{after.name}' stopped activity:")
                print(f"    ╰› {act_type.name} ({act_name})")

            else:
                print(f"[{now()}] [DISCORD] User '{after.name}' stopped activity:")
                print(f"    ╰› {act_type.name} ({act_name})")


        if before.status == discord.Status.offline and after.status != discord.Status.offline:
            print(f"[{now()}] [DISCORD] User '{after.name}' has come online.")
        elif before.status != discord.Status.offline and after.status == discord.Status.offline:
            print(f"[{now()}] [DISCORD] User '{after.name}' has gone offline.")

        
    async def _handle_live_role_update(self, before, after):
        is_streaming = any(a for a in after.activities if a.type == discord.ActivityType.streaming)
        has_live_role = int(self.LIVE_ROLE_ID) in after._roles

        if is_streaming and not has_live_role:
            print(f"[{now()}] [DISCORD] Giving LIVE role to {after.name}")

            # Convert to int and validate role exists
            live_role = after.guild.get_role(int(self.LIVE_ROLE_ID))
            if live_role:
                await after.add_roles(live_role)
                
                # send message to Twitch chat that stream is starting
                if hasattr(after, "name") and after.name.lower() == self.config.target_channel.lower():
                    self.twitch_chat_bot.send_message(f"Discord status updated to streaming! Welcome everyone!")
            else:
                print(f"[{now()}] [DISCORD] ERROR: Live role with ID {self.LIVE_ROLE_ID} not found!")

        elif not is_streaming and has_live_role:
            print(f"[{now()}] [DISCORD] Removing LIVE role from {after.name}")

            # Convert to int and validate role exists
            live_role = after.guild.get_role(int(self.LIVE_ROLE_ID))
            if live_role:
                await after.remove_roles(live_role)
                
                # send message to Twitch chat that stream is ending
                if hasattr(after, "name") and after.name.lower() == self.config.target_channel.lower():
                    self.twitch_chat_bot.send_message("Stream appears to be ending. Thanks for watching!")
            else:
                print(f"[{now()}] [DISCORD] ERROR: Live role with ID {self.LIVE_ROLE_ID} not found!")


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
                print(f"[{now()}] [DISCORD] Upgraded {updated_member.name} to Outlaws after {days} days")
        else:
            print(f"[{now()}] [DISCORD] ERROR: Required roles not found - Outlaws: {self.OUTLAWS_ROLE_ID}, Drifters: {self.DRIFTERS_ROLE_ID}")

    @loop(hours=24 * 5)
    async def update_token_task(self):
        acc_tok = self.twitch_api.get_app_access_token()

        print(f"[{now()}] [TWITCH] Changing access token ")

        self.config.access_token = acc_tok
        self.config.save()
        await self.change_presence(status=discord.Status.online)


    @loop(hours=24)
    async def update_bot_token_task(self):
        self.twitch_api.refresh_bot_token()


    @loop(minutes=2)
    async def check_twitch_ping(self):
        # Check if chat bot is connected, reconnect if needed
        if not self.twitch_chat_bot.is_connected():
            print(f"[{now()}] [TWITCH] Twitch chat bot disconnected, attempting reconnection...")
            if self.twitch_chat_bot.connect():
                print(f"[{now()}] [TWITCH] Twitch chat bot reconnected successfully")
            else:
                print(f"[{now()}] [TWITCH] Failed to reconnect Twitch chat bot")
        else:
            self.twitch_chat_bot.check_for_ping()


    @loop(seconds=60)
    async def check_twitch_online_streamers(self):
        if not self.CHANNEL_ID:
            print(f"[{now()}] [DISCORD] Discord channel ID not configured")
            return
            
        channel = self.get_channel(self.CHANNEL_ID)
        if not channel:
            print(f"[{now()}] [DISCORD] Could not find Discord channel with ID {self.CHANNEL_ID}")
            return

        notifications = self.notification_manager.get_notifications()
        for notification in notifications:
            await self._send_stream_notification(channel, notification)


    async def _send_stream_notification(self, channel, notification):

        print(f"[{now()}] [DISCORD] Sending discord notification ")

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
                print(f"[{now()}] [DISCORD] Warning: Could not set thumbnail for game {notification.get('game_name')}: {e}")

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

    async def send_stream_notification(self, stream_info):
        """Public method for sending stream notifications (used by Flask routes)"""
        if not self.CHANNEL_ID:
            print(f"[{now()}] [DISCORD] No Discord channel configured")
            return
            
        channel = self.get_channel(self.CHANNEL_ID)
        if not channel:
            print(f"[{now()}] [DISCORD] Could not find Discord channel with ID {self.CHANNEL_ID}")
            return
        
        # Convert stream_info format to notification format expected by _send_stream_notification
        notification = {
            'user_name': stream_info.get('user_name', 'Unknown'),
            'user_login': stream_info.get('user_login', 'unknown'),
            'title': stream_info.get('title', 'No Title'),
            'game_name': stream_info.get('game_name', 'No Game')
        }
        
        await self._send_stream_notification(channel, notification)

        

# Global variables - will be initialized in main
config = None
dashboard_data = None
bot = None


def create_flask_app():
    """Create and configure Flask app"""
    flask_app = Flask(__name__, template_folder='../templates')
    CORS(flask_app)
    return flask_app

# Create Flask app
app = create_flask_app()

# Global list to track Server-Sent Events clients for real-time chat updates
chat_sse_clients = []

def broadcast_chat_message(message_data):
    """Broadcast new chat message to all connected SSE clients"""
    if len(chat_sse_clients) > 0:
        print(f"[{now()}] [SSE] Broadcasting message to {len(chat_sse_clients)} clients: \n    ╰› {message_data['username']}: {message_data['message']}")

    if not chat_sse_clients:
        return

    # Format as SSE data
    sse_data = f"data: {json.dumps(message_data)}\n\n"
    
    # Send to all connected clients (remove disconnected ones)
    clients_to_remove = []
    for client_queue in chat_sse_clients:
        try:
            client_queue.put(sse_data)
        except Exception as e:
            print(f"[{now()}] [SSE] Error sending to client: {e}")
            clients_to_remove.append(client_queue)
    
    # Clean up disconnected clients
    for client in clients_to_remove:
        chat_sse_clients.remove(client)

# Connect to OBS on startup will be called manually during startup

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
    if not dashboard_data:
        return jsonify({"success": False, "error": "Dashboard not initialized"}), 500
        
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
    if not dashboard_data:
        return jsonify([])
    return jsonify(dashboard_data.stream_history)


@app.route('/api/send_chat', methods=['POST'])
def send_chat():
    try:
        if not bot:
            return jsonify({'success': False, 'error': 'Bot not initialized'}), 500
            
        data = request.get_json()
        message = data.get('message', '')
        
        if not message:
            return jsonify({'success': False, 'error': 'No message provided'}), 400
        
        if bot.twitch_chat_bot.send_message(message):
            print(f"[{now()}] [TWITCH] Chat message sent: {message}")
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Failed to send message'}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/quick_messages', methods=['GET'])
def get_quick_messages():
    if not dashboard_data:
        return jsonify([])
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
        if not bot or not dashboard_data:
            return jsonify({'success': False, 'error': 'Components not initialized'}), 500
            
        data = request.get_json()
        message_index = data.get('index')
        message_type = data.get('type')
        
        # Define message mapping for the template's message types
        message_map = {
            'welcome': "Welcome to the stream!",
            'follow': "Thanks for the follow!",
            'brb': "Be right back! Thanks for your patience!",
            'ending': "Stream ending soon! Thanks for watching!",
            'lurk': "Thanks for the lurk!"
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
    if not dashboard_data:
        return jsonify([])
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
    if not dashboard_data:
        return jsonify({'success': False, 'error': 'Dashboard not initialized'}), 500
        
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
    if not dashboard_data:
        return jsonify({'success': False, 'error': 'Dashboard not initialized'}), 500
    success, message = dashboard_data.test_chat_connection()
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 500

@app.route('/api/chat/stream')
def chat_stream():
    """Server-Sent Events endpoint for real-time chat updates"""
    
    def event_stream():
        client_queue = queue.Queue()
        chat_sse_clients.append(client_queue)
        print(f"[{now()}] [SSE] Client connected, total clients: {len(chat_sse_clients)}")
        
        # Send initial connection confirmation
        connection_msg = {
            'type': 'system',
            'username': 'System',
            'message': 'Real-time chat connected',
            'timestamp': datetime.now().strftime('%d-%m-%Y %H:%M:%S')
        }
        yield f"data: {json.dumps(connection_msg)}\n\n"
        
        try:
            while True:
                try:
                    # Wait for new message with timeout
                    message = client_queue.get(timeout=30)
                    yield message
                except queue.Empty:
                    # Send heartbeat to keep connection alive
                    yield "data: {\"type\": \"heartbeat\"}\n\n"
        except GeneratorExit:
            # Client disconnected
            if client_queue in chat_sse_clients:
                chat_sse_clients.remove(client_queue)
                print(f"[{now()}] [SSE] Client disconnected, remaining: {len(chat_sse_clients)}")

    response = Response(event_stream(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Cache-Control'
    response.headers['X-Accel-Buffering'] = 'no'  # Disable nginx buffering
    return response

@app.route('/api/refresh_token', methods=['POST'])
def refresh_token():
    try:
        if not dashboard_data:
            return jsonify({'success': False, 'error': 'Dashboard not initialized'}), 500
            
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
    if not dashboard_data or not dashboard_data.obs_client:
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
    if not dashboard_data or not dashboard_data.obs_client:
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
                print(f"[{now()}] [OBS] Scene item ID 73 not found: {scene_error}")
                return jsonify({'error': 'Scene item not found - may have been deleted or recreated in OBS'}), 404
            else:
                raise scene_error
                
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ping', methods=['GET'])
def ping():
    if not dashboard_data:
        return jsonify({'status': 'error', 'error': 'Dashboard not initialized'}), 500
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'bot_connected': dashboard_data.bot_status["discord_connected"],
        'twitch_connected': dashboard_data.bot_status["twitch_connected"]
    })

@app.route('/api/obs_reconnect', methods=['POST'])
def obs_reconnect():
    try:
        if not dashboard_data:
            return jsonify({'success': False, 'error': 'Dashboard not initialized'}), 500
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
        if not dashboard_data:
            return jsonify({"success": False, "connected": False, "message": "Dashboard not initialized"})
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
        if not dashboard_data:
            return jsonify({"success": False, "error": "Dashboard not initialized"})
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
        if not dashboard_data:
            return jsonify({"success": False, "error": "Dashboard not initialized"})
        # Use the OBS browser source method
        ok, msg = dashboard_data.hide_question_on_obs()
        return jsonify({"success": ok, "message": msg})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/current_question')
def get_current_question():
    try:
        if not dashboard_data:
            return jsonify({"question": {}, "theme": "default"})
        # Include the current theme with the question data
        question_data = dashboard_data.current_question.copy() if dashboard_data.current_question else {}
        question_data['theme'] = getattr(dashboard_data, 'qna_theme', 'dark')
        return jsonify(question_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/qna_theme', methods=['POST'])
def set_qna_theme():
    try:
        if not dashboard_data:
            return jsonify({'success': False, 'error': 'Dashboard not initialized'}), 500
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
    if not dashboard_data:
        return jsonify({'success': False, 'error': 'Dashboard not initialized'}), 500
    
    return jsonify({
        'discord_connected': dashboard_data.bot_status["discord_connected"],
        'twitch_connected': dashboard_data.bot_status["twitch_connected"],
        'obs_connected': dashboard_data.obs_client is not None
    })

@app.route('/api/force_notification', methods=['POST'])
def force_notification():
    try:
        if not dashboard_data or not bot:
            return jsonify({'success': False, 'error': 'Bot not initialized'}), 500
        
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
        if not bot:
            return jsonify({'success': False, 'error': 'Bot not initialized'}), 500
            
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
        if not dashboard_data:
            return jsonify({'success': False, 'error': 'Dashboard not initialized'}), 500
            
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
        if not dashboard_data:
            return jsonify({'success': False, 'error': 'Dashboard not initialized'}), 500
            
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


def initialize_components():
    """Initialize all components in the correct order"""
    global config, dashboard_data, bot
    
    print(f"[{now()}] [SYSTEM] Starting ZeddyBot...")
    
    # Step 1: Load configuration
    print(f"[{now()}] [CONFIG] Loading configuration...")
    config = Config("config.json")
    
    # Step 2: Initialize Discord bot
    print(f"[{now()}] [DISCORD] Initializing Discord bot...")
    bot = ZeddyBot(config)
    
    # Step 3: Initialize dashboard data (but don't start chat reader yet)
    print(f"[{now()}] [DASHBOARD] Initializing dashboard...")
    dashboard_data = DashboardData("config.json")
    
    # Step 4: Start Twitch chat reader
    print(f"[{now()}] [TWITCH] Starting Twitch chat reader...")
    dashboard_data.start_chat_reader()
    
    # Give chat connection a moment to establish
    time.sleep(2)
    
    # Step 5: Connect to OBS
    dashboard_data.connect_obs()
    
    # Check OBS status and print appropriate completion message
    if dashboard_data.obs_client is not None:
        print(f"[{now()}] [SYSTEM] All components initialized!")
    else:
        print(f"[{now()}] [SYSTEM] Core components initialized:\n    ╰› (OBS integration disabled)")


if __name__ == "__main__":
    def run_flask():
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
        
    # Initialize all components
    initialize_components()
    
    # Start Flask server
    print(f"[{now()}] [FLASK] Starting HTTP server on http://0.0.0.0:5000")
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Start Discord bot (this will block until the bot shuts down)
    try:
        if not bot or not config:
            print(f"[{now()}] [SYSTEM] Error: Bot or config not initialized properly")
            exit(1)
            
        print(f"[{now()}] [DISCORD] Starting Discord bot connection...")
        bot.run(config.discord_token)
    except KeyboardInterrupt:
        print(f"[{now()}] [SYSTEM] Shutting down...")
    except Exception as e:
        print(f"[{now()}] [SYSTEM] Error running bot: {e}")
