#!/usr/bin/env python3

from flask import Flask, render_template, jsonify, request, redirect, url_for
import json
import requests
from datetime import datetime
import threading
import time

app = Flask(__name__)

class DashboardData:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.load_config()
        self.stream_history = []
        self.discord_stats = {"online_members": 0, "total_members": 0}
        self.bot_status = {"discord_connected": False, "twitch_connected": False}
        
    def load_config(self):
        with open(self.config_path) as f:
            self.config = json.load(f)
    
    def get_twitch_stream_status(self):
        try:
            headers = {
                "Authorization": f"Bearer {self.config['access_token']}",
                "Client-Id": self.config['twitch_client_id']
            }
            
            # Get user info for main channel
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
            
            # Get stream info
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
        # This would be called periodically to update dashboard data
        stream_status = self.get_twitch_stream_status()
        
        if stream_status:
            # Add to history if new stream
            if not self.stream_history or self.stream_history[-1]["started_at"] != stream_status["started_at"]:
                self.stream_history.append({
                    "title": stream_status["title"],
                    "game": stream_status["game_name"],
                    "started_at": stream_status["started_at"],
                    "viewer_count": stream_status["viewer_count"]
                })
                
                # Keep only last 10 streams
                self.stream_history = self.stream_history[-10:]

dashboard_data = DashboardData()

@app.route('/')
def index():
    return render_template('dashboard.html')

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
    data = request.json
    message = data.get('message', '') if data else ''
    if not message:
        return jsonify({"success": False, "error": "No message provided"})
    
    try:
        import socket
        
        server = "irc.chat.twitch.tv"
        port = 6667
        sock = socket.socket()
        sock.connect((server, port))
        
        # Authenticate
        sock.send(f"PASS oauth:{dashboard_data.config['twitch_bot_access_token']}\r\n".encode('utf-8'))
        sock.send(f"NICK {dashboard_data.config.get('twitch_bot_username', 'Zeddy_bot')}\r\n".encode('utf-8'))
        sock.send(f"JOIN #{dashboard_data.config.get('target_channel', '')}\r\n".encode('utf-8'))
        
        # Send message
        sock.send(f"PRIVMSG #{dashboard_data.config.get('target_channel', '')} :{message}\r\n".encode('utf-8'))
        sock.close()
        
        return jsonify({"success": True, "message": f"Sent to Twitch: {message}"})
        
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to send: {str(e)}"})

def update_loop():
    while True:
        dashboard_data.update_data()
        time.sleep(30)  # Update every 30 seconds

if __name__ == '__main__':
    # Start background update thread
    update_thread = threading.Thread(target=update_loop, daemon=True)
    update_thread.start()
    
    app.run(debug=True, host='0.0.0.0', port=5000)