#!/usr/bin/env python3

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import json
import requests
from datetime import datetime
import threading
import time
import socket
import select
from collections import deque
import sys
import os

# Add parent directory to path to import from tools
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import our shared token utility
from tools.token_utils import refresh_twitch_bot_token, validate_bot_token, get_current_bot_token

# OBS WebSocket v5 (obsws-python)
try:
    from obsws_python import ReqClient
except ImportError:
    ReqClient = None

app = Flask(__name__, template_folder='../templates')
CORS(app)  # Enable CORS for all routes

# Disable Flask request logging for successful requests
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

class DashboardData:
    def __init__(self, config_path="./config.json"):
        self.config_path = config_path
        self.load_config()
        self.stream_history = []
        self.discord_stats = {"online_members": 0, "total_members": 0}
        self.bot_status = {"discord_connected": False, "twitch_connected": False}
        self.chat_messages = deque(maxlen=100)
        self.chat_sock = None
        self.current_question = {}
        self.qna_theme = "default"  # Store current Q&A theme
        self.obs_client = None
        self.last_obs_attempt = 0  # Rate limiting for OBS connections
        self.obs_connection_cooldown = 30  # Wait 30 seconds between connection attempts
        self.connect_obs()
        self.start_chat_reader()

    def _log_timestamp(self):
        """Get formatted timestamp for logging"""
        return datetime.now().strftime('%H:%M:%S')

    def load_config(self):
        with open(self.config_path) as f:
            self.config = json.load(f)

    def save_config(self):
        """Save config back to file"""
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)

    def refresh_bot_token(self):
        """Refresh the Twitch bot access token using shared utility"""
        success, message, new_token = refresh_twitch_bot_token(self.config_path)
        if success:
            # Reload config to get the updated token
            self.load_config()
            print(f"[{self._log_timestamp()}] [DASHBOARD] {message}")
        else:
            print(f"[{self._log_timestamp()}] [DASHBOARD] {message}")
        return success

    def connect_obs(self):
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
        
        obs_config = self.config.get('obs', {})
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

    def retry_obs_connection(self):
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

    def start_chat_reader(self):
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
                    print(f"[{self._log_timestamp()}] Chat reader error: {e}")
                    time.sleep(5)
        chat_thread = threading.Thread(target=chat_reader, daemon=True)
        chat_thread.start()

    def connect_to_chat(self):
        try:
            if self.chat_sock:
                self.chat_sock.close()
            self.chat_sock = socket.socket()
            self.chat_sock.connect(("irc.chat.twitch.tv", 6667))
            self.chat_sock.send(f"PASS oauth:{self.config['access_token']}\r\n".encode('utf-8'))
            self.chat_sock.send(f"NICK justinfan12345\r\n".encode('utf-8'))
            self.chat_sock.send(f"JOIN #{self.config.get('target_channel', '')}\r\n".encode('utf-8'))
            print(f"[{self._log_timestamp()}] Connected to chat: #{self.config.get('target_channel', '')}")
        except Exception as e:
            print(f"[{self._log_timestamp()}] Failed to connect to chat: {e}")
            self.chat_sock = None

    def parse_chat_messages(self, data):
        lines = data.strip().split('\r\n')
        for line in lines:
            if 'PRIVMSG' in line:
                try:
                    parts = line.split(':', 2)
                    if len(parts) >= 3:
                        user_part = parts[1].split('!')[0]
                        message = parts[2]
                        self.chat_messages.append({
                            'username': user_part,
                            'message': message,
                            'timestamp': datetime.now().strftime('%H:%M:%S')
                        })
                except Exception as e:
                    print(f"[{self._log_timestamp()}] Error parsing message: {e}")
            elif 'PING' in line:
                if self.chat_sock:
                    self.chat_sock.send("PONG :tmi.twitch.tv\r\n".encode('utf-8'))

    def get_twitch_stream_status(self):
        try:
            headers = {
                "Authorization": f"Bearer {self.config['access_token']}",
                "Client-Id": self.config['twitch_client_id']
            }
            user_response = requests.get(
                "https://api.twitch.tv/helix/users",
                params={"login": self.config.get("target_channel", "")},
                headers=headers
            )
            if user_response.status_code != 200:
                return None
            user_data = user_response.json()["data"]
            if not user_data:
                return None
            user_id = user_data[0]["id"]
            stream_response = requests.get(
                "https://api.twitch.tv/helix/streams",
                params={"user_id": user_id},
                headers=headers
            )
            if stream_response.status_code == 200:
                streams = stream_response.json()["data"]
                return streams[0] if streams else None
        except Exception as e:
            print(f"[{self._log_timestamp()}] Error getting stream status: {e}")
            return None

    def update_data(self):
        stream_status = self.get_twitch_stream_status()
        if stream_status:
            if not self.stream_history or self.stream_history[-1]["started_at"] != stream_status["started_at"]:
                self.stream_history.append({
                    "title": stream_status["title"],
                    "game": stream_status["game_name"],
                    "started_at": stream_status["started_at"],
                    "viewer_count": stream_status["viewer_count"]
                })
                self.stream_history = self.stream_history[-10:]

    def test_chat_connection(self):
        """Test if chat connection credentials are working"""
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
                success, refresh_msg, new_token = refresh_twitch_bot_token(self.config_path)
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

    # Q&A/OBS methods using obsws-python ReqClient
    def display_question_on_obs(self, username, message):
        """Display Q&A using browser source (primary method)"""
        if not self.obs_client:
            # Don't automatically retry - let user manually reconnect
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

    def hide_question_on_obs(self):  # Note the proper indentation
        """Hide Q&A browser source"""
        if not self.obs_client:
            # Don't automatically retry - let user manually reconnect
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

    # Enhanced Q&A methods for Browser Source (styled)
    def display_question_on_obs_browser(self, username, message):
        """Display Q&A using browser source (recommended for better styling)"""
        if not self.obs_client:
            return False, "OBS not connected"
        try:
            # Store the question data (browser source will fetch it via API)
            self.current_question = {
                'username': username,
                'message': message,
                'timestamp': datetime.now().isoformat()
            }
            
            # Enable the browser source scene item
            self.obs_client.set_scene_item_enabled(
                scene_name="Scene - In Game",  # Your OBS scene name
                item_id=73,                     # Your QnA browser source item ID (different from text source)
                enabled=True                   # Enable the item
            )

            return True, "Styled question displayed on stream"
        except Exception as e:
            return False, f"OBS browser source error: {str(e)}"

    def hide_question_on_obs_browser(self):
        """Hide Q&A browser source"""
        if not self.obs_client:
            return False, "OBS not connected"
        try:
            # Clear the question data
            self.current_question = {}
            
            # Browser source will auto-hide when no question is available
            # But we can also disable the source entirely if preferred
            # self.obs_client.set_scene_item_enabled(
            #     scene_name="Scene - In Game",
            #     item_id=73,  # Your QnA browser source item ID
            #     enabled=False
            # )

            return True, "Styled question hidden"
        except Exception as e:
            return False, f"OBS browser source error: {str(e)}"

    def set_qna_theme(self, theme="default"):
        """Set the Q&A display theme (default, green, blue, red, orange)"""
        valid_themes = ['default', 'green', 'blue', 'red', 'orange']
        if theme not in valid_themes:
            return False, f"Invalid theme. Valid options: {valid_themes}"
        
        self.qna_theme = theme
        print(f"Q&A theme changed to: {theme}")
        return True, f"Theme set to {theme}"

dashboard_data = DashboardData()

@app.route('/')
def index():
    return render_template('dashboardqa.html')

@app.route('/qna')
def qna_display():
    return render_template('qna_display.html')

@app.route('/api/status')
def api_status():
    stream_status = dashboard_data.get_twitch_stream_status()
    return jsonify({
        "stream": {
            "live": stream_status is not None,
            "title": stream_status["title"] if stream_status else "",
            "game": stream_status["game_name"] if stream_status else "",
            "viewers": stream_status["viewer_count"] if stream_status else 0,
            "started_at": stream_status["started_at"] if stream_status else ""
        },
        "discord": dashboard_data.discord_stats,
        "bot": dashboard_data.bot_status,
        "watchlist": dashboard_data.config["watchlist"] if dashboard_data.config and "watchlist" in dashboard_data.config else []
    })

@app.route('/api/history')
def api_history():
    return jsonify(dashboard_data.stream_history)

@app.route('/api/send_chat', methods=['POST'])
def send_chat():
    print(f"[CHAT] Received request from {request.remote_addr}")
    data = request.json
    message = data.get('message', '') if data else ''
    print(f"[CHAT] Message: {message}")
    
    if not message:
        return jsonify({"success": False, "error": "No message provided"})
    
    if not dashboard_data.config.get('target_channel'):
        print("[CHAT] Missing target_channel")
        return jsonify({"success": False, "error": "Missing target_channel in config"})
    
    # Get current bot token and validate it
    current_token = get_current_bot_token(dashboard_data.config_path)
    if not current_token:
        print("[CHAT] No bot access token found, attempting to refresh...")
        success, msg, new_token = refresh_twitch_bot_token(dashboard_data.config_path)
        if not success:
            return jsonify({"success": False, "error": f"No valid bot access token: {msg}"})
        current_token = new_token
        dashboard_data.load_config()  # Reload config with new token
    
    # Validate the token before using it
    is_valid, validation_msg = validate_bot_token(current_token, dashboard_data.config_path)
    if not is_valid:
        print(f"[CHAT] Token validation failed: {validation_msg}, attempting refresh...")
        success, msg, new_token = refresh_twitch_bot_token(dashboard_data.config_path)
        if not success:
            return jsonify({"success": False, "error": f"Token refresh failed: {msg}"})
        current_token = new_token
        dashboard_data.load_config()  # Reload config with new token
    
    print(f"[CHAT] Attempting to send to channel: {dashboard_data.config.get('target_channel')}")
    
    try:
        server = "irc.chat.twitch.tv"
        port = 6667
        sock = socket.socket()
        sock.settimeout(10)  # Set timeout to prevent hanging
        print(f"[CHAT] Connecting to {server}:{port}")
        sock.connect((server, port))
        
        # IRC authentication flow with validated bot token
        sock.send(f"PASS oauth:{current_token}\r\n".encode('utf-8'))
        sock.send(f"NICK {dashboard_data.config.get('twitch_bot_username', 'Zeddy_bot')}\r\n".encode('utf-8'))
        print("[CHAT] Sent authentication")
        
        # Wait for server response and check for authentication errors
        time.sleep(1)
        
        # Check for authentication response (optional - can help debug)
        try:
            sock.settimeout(2)  # Short timeout for auth check
            response = sock.recv(1024).decode('utf-8', errors='ignore')
            if "Login authentication failed" in response:
                sock.close()
                print("[CHAT] Authentication failed, attempting token refresh...")
                success, msg, new_token = refresh_twitch_bot_token(dashboard_data.config_path)
                if success:
                    dashboard_data.load_config()
                    return jsonify({"success": False, "error": "Token was expired and refreshed, please try again"})
                else:
                    return jsonify({"success": False, "error": f"Authentication failed and refresh failed: {msg}"})
        except socket.timeout:
            pass  # No response yet, continue
        
        sock.settimeout(10)  # Reset timeout
        
        # Request capabilities for better IRC support
        sock.send("CAP REQ :twitch.tv/membership twitch.tv/tags twitch.tv/commands\r\n".encode('utf-8'))
        
        # Join channel
        target_channel = dashboard_data.config.get('target_channel', '')
        sock.send(f"JOIN #{target_channel}\r\n".encode('utf-8'))
        print(f"[CHAT] Joined channel #{target_channel}")
        
        # Wait a bit more before sending message
        time.sleep(0.5)
        
        # Send the actual message
        sock.send(f"PRIVMSG #{target_channel} :{message}\r\n".encode('utf-8'))
        print(f"[CHAT] Sent message: {message}")
        
        # Wait a moment for the message to be sent before closing
        time.sleep(0.5)
        
        sock.close()
        print("[CHAT] Connection closed successfully")
        return jsonify({"success": True, "message": f"Sent to Twitch: {message}"})
        
    except socket.timeout:
        print("[CHAT] Connection timeout")
        return jsonify({"success": False, "error": "Connection timeout - check your network connection"})
    except ConnectionRefusedError:
        print("[CHAT] Connection refused")
        return jsonify({"success": False, "error": "Connection refused - check if Twitch IRC server is accessible"})
    except Exception as e:
        print(f"[CHAT] Error: {str(e)}")
        return jsonify({"success": False, "error": f"Failed to send: {str(e)}"})

@app.route('/api/chat')
def api_chat():
    return jsonify(list(dashboard_data.chat_messages))

@app.route('/api/test_chat', methods=['GET'])
def test_chat():
    """Test chat connection and credentials"""
    success, message = dashboard_data.test_chat_connection()
    return jsonify({"success": success, "message": message})

@app.route('/api/refresh_token', methods=['POST'])
def refresh_token():
    """Manually refresh the bot access token"""
    success = dashboard_data.refresh_bot_token()
    if success:
        return jsonify({"success": True, "message": "Bot token refreshed successfully"})
    else:
        return jsonify({"success": False, "message": "Failed to refresh bot token"})

@app.route('/api/obs_scene_items/<scene_name>')
def get_scene_items(scene_name):
    """Get all scene items in a specific scene for debugging"""
    if not dashboard_data.obs_client:
        return jsonify({"success": False, "error": "OBS not connected"})
    
    try:
        scene_items = dashboard_data.obs_client.get_scene_item_list(name=scene_name)
        items_info = []
        items = []
        if scene_items is not None:
            if hasattr(scene_items, 'sceneItems'):
                items = getattr(scene_items, 'sceneItems', [])
            elif hasattr(scene_items, 'scene_items'):
                items = getattr(scene_items, 'scene_items', [])
            elif isinstance(scene_items, dict) and 'sceneItems' in scene_items:
                items = scene_items['sceneItems']
            elif isinstance(scene_items, dict) and 'scene_items' in scene_items:
                items = scene_items['scene_items']
        for item in items:
            # Handle both dict and object item types
            scene_item_id = item['sceneItemId'] if isinstance(item, dict) else getattr(item, 'sceneItemId', None)
            source_name = item['sourceName'] if isinstance(item, dict) else getattr(item, 'sourceName', None)
            input_kind = item['inputKind'] if isinstance(item, dict) and 'inputKind' in item else getattr(item, 'inputKind', 'Unknown') if hasattr(item, 'inputKind') else 'Unknown'
            enabled = item['sceneItemEnabled'] if isinstance(item, dict) else getattr(item, 'sceneItemEnabled', None)
            items_info.append({
                "id": scene_item_id,
                "name": source_name,
                "type": input_kind,
                "enabled": enabled
            })
        return jsonify({"success": True, "scene": scene_name, "items": items_info})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/ping', methods=['GET'])
def ping():
    """Simple connectivity test"""
    return jsonify({
        "status": "ok", 
        "message": "Dashboard server is reachable",
        "server_time": datetime.now().isoformat()
    })

@app.route('/api/obs_reconnect', methods=['POST'])
def obs_reconnect():
    """Retry OBS connection"""
    try:
        success = dashboard_data.retry_obs_connection()
        if success:
            return jsonify({
                "success": True,
                "message": "Successfully connected to OBS"
            })
        else:
            return jsonify({
                "success": False,
                "message": "Failed to connect to OBS - make sure OBS is running with WebSocket enabled"
            })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/obs_status', methods=['GET'])
def obs_status():
    """Get OBS connection status without attempting reconnection"""
    try:
        if dashboard_data.obs_client:
            # Quick test to see if connection is still valid
            try:
                dashboard_data.obs_client.get_version()
                return jsonify({
                    "success": True,
                    "connected": True,
                    "message": "OBS connected and responding"
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
                cooldown_remaining = int(dashboard_data.obs_connection_cooldown - time_since_attempt)
                return jsonify({
                    "success": True,
                    "connected": False,
                    "message": f"OBS not connected (retry available in {cooldown_remaining}s)"
                })
            else:
                return jsonify({
                    "success": True,
                    "connected": False,
                    "message": "OBS not connected (retry available)"
                })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# Q&A API endpoints
@app.route('/api/display_question', methods=['POST'])
def display_question():
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "No JSON data provided"})
    username = data.get('username', '')
    message = data.get('message', '')
    if not username or not message:
        return jsonify({"success": False, "error": "Missing username or message"})
    
    # Use the browser source method (primary)
    ok, msg = dashboard_data.display_question_on_obs(username, message)
    
    return jsonify({"success": ok, "message": msg})

@app.route('/api/hide_question', methods=['POST'])
def hide_question():
    # Use the browser source method
    ok, msg = dashboard_data.hide_question_on_obs()
    
    return jsonify({"success": ok, "message": msg})

@app.route('/api/current_question')
def get_current_question():
    # Include the current theme with the question data
    question_data = dashboard_data.current_question.copy() if dashboard_data.current_question else {}
    question_data['theme'] = dashboard_data.qna_theme
    return jsonify(question_data)

@app.route('/api/qna_theme', methods=['POST'])
def set_qna_theme():
    data = request.json
    theme = data.get('theme', 'default') if data else 'default'
    valid_themes = ['default', 'green', 'blue', 'red', 'orange']
    
    if theme not in valid_themes:
        return jsonify({"success": False, "error": f"Invalid theme. Valid options: {valid_themes}"})
    
    ok, msg = dashboard_data.set_qna_theme(theme)
    return jsonify({"success": ok, "message": msg, "theme": theme})

# Bot moderation functionality removed due to TwitchInsights being discontinued

@app.route('/api/bot_status', methods=['GET'])
def api_bot_status():
    return jsonify({
        "success": True,
        "bot_connected": True,  # Assume dashboard is running means bot is running
        "message": "ZeddyBot Dashboard is running"
    })

# New API endpoints for comprehensive dashboard control
@app.route('/api/force_notification', methods=['POST'])
def force_notification():
    """Force send a Discord notification for current stream"""
    try:
        # This would need to integrate with the Discord bot
        # For now, return a placeholder response
        return jsonify({
            "success": True,
            "message": "Force notification triggered (requires Discord bot integration)"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/test_notification', methods=['POST'])
def test_notification():
    """Send a test Discord notification"""
    try:
        return jsonify({
            "success": True,
            "message": "Test notification sent (requires Discord bot integration)"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

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
            # Don't try to reconnect here - let the user manually reconnect if needed
            return jsonify({"success": False, "error": "OBS not connected - use reconnect button"})
        
        # Test the connection first
        try:
            scenes = dashboard_data.obs_client.get_scene_list()
            scene_list = []
            current_scene = None
            if scenes is not None:
                # Handle both object and dict return types for scenes
                if hasattr(scenes, 'scenes'):
                    scene_items = getattr(scenes, 'scenes', [])
                    scene_list = [scene['sceneName'] if isinstance(scene, dict) else getattr(scene, 'sceneName', None) for scene in scene_items]
                    current_scene = getattr(scenes, 'currentProgramSceneName', None)
                elif isinstance(scenes, dict) and 'scenes' in scenes:
                    scene_items = scenes['scenes']
                    scene_list = [scene['sceneName'] for scene in scene_items]
                    current_scene = scenes.get('currentProgramSceneName')
                else:
                    scene_list = []
                    current_scene = None
            return jsonify({
                "success": True,
                "scenes": scene_list,
                "current_scene": current_scene
            })
        except Exception as obs_error:
            # OBS connection failed - don't automatically reconnect
            dashboard_data.obs_client = None  # Mark as disconnected
            return jsonify({"success": False, "error": f"OBS connection lost: {str(obs_error)}"})
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/obs_toggle_source', methods=['POST'])
def toggle_obs_source():
    """Toggle visibility of an OBS source"""
    try:
        data = request.json if request.json else {}
        scene_name = data.get('scene_name', 'Scene - In Game')
        source_name = data.get('source_name', '')
        enabled = data.get('enabled', True)
        
        if not dashboard_data.obs_client:
            return jsonify({"success": False, "error": "OBS not connected"})
        
        # Get scene item ID for the source
        scene_items = dashboard_data.obs_client.get_scene_item_list(scene_name)
        item_id = None
        # Handle both dict and object return types
        items = []
        if scene_items is not None:
            if hasattr(scene_items, 'sceneItems'):
                items = getattr(scene_items, 'sceneItems', [])
            elif hasattr(scene_items, 'scene_items'):
                items = getattr(scene_items, 'scene_items', [])
            elif isinstance(scene_items, dict) and 'sceneItems' in scene_items:
                items = scene_items['sceneItems']
            elif isinstance(scene_items, dict) and 'scene_items' in scene_items:
                items = scene_items['scene_items']
        for item in items:
            # Handle both dict and object item types
            source_name_val = item['sourceName'] if isinstance(item, dict) else getattr(item, 'sourceName', None)
            scene_item_id_val = item['sceneItemId'] if isinstance(item, dict) else getattr(item, 'sceneItemId', None)
            if source_name_val == source_name:
                item_id = scene_item_id_val
                break
        
        if item_id is None:
            return jsonify({"success": False, "error": f"Source '{source_name}' not found in scene '{scene_name}'"})
        
        dashboard_data.obs_client.set_scene_item_enabled(
            scene_name=scene_name,
            item_id=item_id,
            enabled=enabled
        )
        
        return jsonify({
            "success": True,
            "message": f"Source '{source_name}' {'enabled' if enabled else 'disabled'}"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/stream_status', methods=['GET'])
def get_stream_status():
    """Get current stream status"""
    try:
        # Get real stream info from Twitch API
        stream_status = dashboard_data.get_twitch_stream_status()
        
        if stream_status:
            return jsonify({
                "success": True,
                "is_live": True,
                "title": stream_status.get("title", "Live Stream"),
                "game": stream_status.get("game_name", "Unknown Game"),
                "viewer_count": stream_status.get("viewer_count", 0),
                "started_at": stream_status.get("started_at", ""),
                "thumbnail_url": stream_status.get("thumbnail_url", "")
            })
        else:
            return jsonify({
                "success": True,
                "is_live": False,
                "title": "Stream Offline",
                "game": "N/A",
                "viewer_count": 0,
                "started_at": "",
                "thumbnail_url": ""
            })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/discord_stats', methods=['GET'])
def get_discord_stats():
    """Get Discord server stats from the Discord bot"""
    try:
        # Try to get real Discord stats from the Discord bot's API
        try:
            response = requests.get("http://127.0.0.1:5001/api/discord_stats", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return jsonify(data)
        except requests.exceptions.RequestException:
            # Discord bot API not available, return fallback data
            pass
        
        # Fallback when Discord bot is not running or API is unavailable
        return jsonify({
            "success": False,
            "stats": {
                "online_members": 0,
                "total_members": 0,
                "total_humans": 0,
                "bot_connected": False
            },
            "error": "Discord bot not connected (start zeddybot.py)"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/quick_messages', methods=['POST'])
def send_quick_message():
    """Send predefined quick messages to Twitch chat"""
    try:
        data = request.json if request.json else {}
        message_type = data.get('type', '')
        
        quick_messages = {
            "welcome": "Welcome everyone! Thanks for stopping by! 🎮",
            "follow": "Thanks for the follow! Really appreciate the support! ❤️",
            "brb": "Be right back in a few minutes! Don't go anywhere! ⏰",
            "ending": "Thanks for watching! Stream ending soon, catch you next time! 👋",
            "lurk": "Thanks for lurking! Appreciate you being here! 👀"
        }
        
        if message_type not in quick_messages:
            return jsonify({"success": False, "error": "Invalid message type"})
        
        message = quick_messages[message_type]
        
        # Use existing send_chat logic
        if not dashboard_data.config.get('target_channel'):
            return jsonify({"success": False, "error": "Missing target_channel in config"})
        
        if not dashboard_data.config.get('twitch_bot_access_token'):
            if not dashboard_data.refresh_bot_token():
                return jsonify({"success": False, "error": "No valid bot access token available"})
        
        # Send message to Twitch chat
        import socket
        import time
        server = "irc.chat.twitch.tv"
        port = 6667
        sock = socket.socket()
        sock.settimeout(10)
        sock.connect((server, port))
        
        sock.send(f"PASS oauth:{dashboard_data.config['twitch_bot_access_token']}\r\n".encode('utf-8'))
        sock.send(f"NICK {dashboard_data.config.get('twitch_bot_username', 'Zeddy_bot')}\r\n".encode('utf-8'))
        
        time.sleep(1)
        sock.send("CAP REQ :twitch.tv/membership twitch.tv/tags twitch.tv/commands\r\n".encode('utf-8'))
        
        target_channel = dashboard_data.config.get('target_channel', '')
        sock.send(f"JOIN #{target_channel}\r\n".encode('utf-8'))
        
        time.sleep(0.5)
        sock.send(f"PRIVMSG #{target_channel} :{message}\r\n".encode('utf-8'))
        time.sleep(0.5)
        
        sock.close()
        return jsonify({"success": True, "message": f"Sent: {message}"})
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

def update_loop():
    while True:
        dashboard_data.update_data()
        time.sleep(30)

if __name__ == '__main__':
    # Disable Flask request logging
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    
    update_thread = threading.Thread(target=update_loop, daemon=True)
    update_thread.start()
    app.run(debug=False, host='0.0.0.0', port=5000)  # Disabled debug mode