#!/usr/bin/env python3
"""
Test script to check Discord member counts
Run this after starting your Discord bot (zeddybot.py) to verify the stats are working
"""

import requests
import json

def test_discord_stats():
    print("Testing Discord stats from Discord bot...")
    
    # Test Discord bot API directly
    try:
        response = requests.get("http://127.0.0.1:5001/api/discord_stats", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print("Discord Bot API Response:")
            print(json.dumps(data, indent=2))
        else:
            print(f"Discord Bot API Error: {response.status_code}")
            print(response.text)
    except requests.exceptions.RequestException as e:
        print(f"Discord Bot API not reachable: {e}")
        print("Make sure zeddybot.py is running!")
    
    print("\n" + "="*50 + "\n")
    
    # Test Dashboard API 
    print("Testing Discord stats from Dashboard...")
    try:
        response = requests.get("http://127.0.0.1:5000/api/discord_stats", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print("Dashboard API Response:")
            print(json.dumps(data, indent=2))
            
            if data.get("success") and data.get("stats"):
                stats = data["stats"]
                print(f"\n📊 Discord Server Stats:")
                print(f"   Total Members: {stats.get('total_members', 'N/A')}")
                print(f"   Human Members: {stats.get('total_humans', 'N/A')}")
                print(f"   Online Members: {stats.get('online_members', 'N/A')}")
                print(f"   Bot Connected: {stats.get('bot_connected', 'N/A')}")
                if 'guild_name' in stats:
                    print(f"   Server Name: {stats['guild_name']}")
        else:
            print(f"Dashboard API Error: {response.status_code}")
            print(response.text)
    except requests.exceptions.RequestException as e:
        print(f"Dashboard API not reachable: {e}")
        print("Make sure dashboardqa.py is running!")

if __name__ == "__main__":
    test_discord_stats()
