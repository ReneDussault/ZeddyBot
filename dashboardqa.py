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

# OBS WebSocket v5 (obsws-python)
try:
    from obsws_python import ReqClient
except ImportError:
    ReqClient = None

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

class DashboardData:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.load_config()
        self.stream_history = []
        self.discord_stats = {"online_members": 0, "total_members": 0}
        self.bot_status = {"discord_connected": False, "twitch_connected": False}
        self.chat_messages = deque(maxlen=100)
        self.chat_sock = None
        self.current_question = {}
        self.obs_client = None
        self.connect_obs()
        self.start_chat_reader()

    def load_config(self):
        with open(self.config_path) as f:
            self.config = json.load(f)

    def save_config(self):
        """Save config back to file"""
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)

    def refresh_bot_token(self):
        """Refresh the Twitch bot access token using refresh token"""
        if not self.config.get('twitch_bot_refresh_token'):
            print("No refresh token available for bot account")
            return False

        params = {
            "client_id": self.config.get('twitch_bot_client_id', ''),
            "client_secret": self.config.get('twitch_bot_secret', ''),
            "grant_type": "refresh_token",
            "refresh_token": self.config['twitch_bot_refresh_token'],
        }

        try:
            response = requests.post("https://id.twitch.tv/oauth2/token", params=params)
            if response.status_code == 200:
                data = response.json()
                self.config['twitch_bot_access_token'] = data["access_token"]
                self.config['twitch_bot_refresh_token'] = data["refresh_token"]
                self.save_config()
                print(f"[DASHBOARD] Refreshed bot access token")
                return True
            else:
                print(f"Failed to refresh bot token: {response.text}")
                return False
        except Exception as e:
            print(f"Error refreshing bot token: {e}")
            return False

    def connect_obs(self):
        """Connect to OBS WebSocket v5 using ReqClient"""
        if ReqClient is None:
            print("obsws-python not installed.")
            return
        try:
            obs_config = self.config.get('obs', {})
            host = obs_config.get('host', 'localhost')
            port = obs_config.get('port', 4455)
            password = obs_config.get('password', '')
            self.obs_client = ReqClient(host=host, port=port, password=password, timeout=10)
            print("Connected to OBS (v5) using ReqClient")
        except Exception as e:
            print(f"Failed to connect to OBS: {e}")
            self.obs_client = None

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
                    print(f"Chat reader error: {e}")
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
            print(f"Connected to chat: #{self.config.get('target_channel', '')}")
        except Exception as e:
            print(f"Failed to connect to chat: {e}")
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
                    print(f"Error parsing message: {e}")
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
            print(f"Error getting stream status: {e}")
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
            print(f"[CHAT_TEST] IRC Response: {response}")  # Debug output
            sock.close()
            
            if ":tmi.twitch.tv 001" in response:  # Welcome message indicates success
                if 'twitch_bot_access_token' in self.config and self.config['twitch_bot_access_token']:
                    return True, "Chat connection test successful (authenticated bot)"
                else:
                    return True, "Chat connection test successful (anonymous - read only)"
            elif "Login authentication failed" in response or ":tmi.twitch.tv NOTICE * :Login authentication failed" in response:
                return False, "Authentication failed - check your access token"
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
        if not self.obs_client:
            return False, "OBS not connected"
        try:
            question_text = f"Q: {message}\n— {username}"
            # Set the text of the input (text source)
            self.obs_client.set_input_settings(
                name="QnA_Text",           # The input (source) name
                settings={"text": question_text},
                overlay=True
            )
            # Enable the scene item (make sure to set the correct scene and item id)
            self.obs_client.set_scene_item_enabled(
                scene_name="Scene - In Game",  # Your OBS scene name
                item_id=72,                     # Your QnA text source item ID
                enabled=True                   # Enable the item
            )

            return True, "Question displayed on stream"
        except Exception as e:
            return False, f"OBS error: {str(e)}"

    def hide_question_on_obs(self):
        if not self.obs_client:
            return False, "OBS not connected"
        try:
            self.obs_client.set_scene_item_enabled(
                scene_name="Scene - In Game",  # Your OBS scene name
                item_id=72,                     # Your QnA text source item ID
                enabled=False                  # Disable the item
            )

            return True, "Question hidden"
        except Exception as e:
            return False, f"OBS error: {str(e)}"

dashboard_data = DashboardData()

@app.route('/')
def index():
    return render_template('dashboardqa.html')

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
    
    # Check if we have a bot token, if not or if it's invalid, try to refresh
    if not dashboard_data.config.get('twitch_bot_access_token'):
        print("[CHAT] No bot access token, attempting to refresh...")
        if not dashboard_data.refresh_bot_token():
            return jsonify({"success": False, "error": "No valid bot access token available"})
    
    print(f"[CHAT] Attempting to send to channel: {dashboard_data.config.get('target_channel')}")
    
    try:
        server = "irc.chat.twitch.tv"
        port = 6667
        sock = socket.socket()
        sock.settimeout(10)  # Set timeout to prevent hanging
        print(f"[CHAT] Connecting to {server}:{port}")
        sock.connect((server, port))
        
        # IRC authentication flow with proper bot token
        sock.send(f"PASS oauth:{dashboard_data.config['twitch_bot_access_token']}\r\n".encode('utf-8'))
        sock.send(f"NICK {dashboard_data.config.get('twitch_bot_username', 'Zeddy_bot')}\r\n".encode('utf-8'))
        print("[CHAT] Sent authentication")
        
        # Wait for server response before joining
        time.sleep(1)
        
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
        # If we get an authentication error, try refreshing the token once
        if "authentication" in str(e).lower():
            print("[CHAT] Authentication error, trying to refresh token...")
            if dashboard_data.refresh_bot_token():
                return jsonify({"success": False, "error": "Token refreshed, please try again"})
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

@app.route('/api/ping', methods=['GET'])
def ping():
    """Simple connectivity test"""
    return jsonify({
        "status": "ok", 
        "message": "Dashboard server is reachable",
        "server_time": datetime.now().isoformat()
    })

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
    dashboard_data.current_question = {
        'username': username,
        'message': message,
        'timestamp': datetime.now().isoformat()
    }
    ok, msg = dashboard_data.display_question_on_obs(username, message)
    return jsonify({"success": ok, "message": msg})

@app.route('/api/hide_question', methods=['POST'])
def hide_question():
    dashboard_data.current_question = {}
    ok, msg = dashboard_data.hide_question_on_obs()
    return jsonify({"success": ok, "message": msg})

@app.route('/api/current_question')
def get_current_question():
    return jsonify(dashboard_data.current_question)

def update_loop():
    while True:
        dashboard_data.update_data()
        time.sleep(30)

if __name__ == '__main__':
    update_thread = threading.Thread(target=update_loop, daemon=True)
    update_thread.start()
    app.run(debug=True, host='0.0.0.0', port=5000)