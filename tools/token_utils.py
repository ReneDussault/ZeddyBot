#!/usr/bin/env python3
"""
Shared utility functions for token management
"""

import json
import requests
from datetime import datetime


def refresh_twitch_bot_token(config_path="../config.json"):
    """
    Refresh Twitch bot access token using refresh token
    
    Args:
        config_path: Path to config.json file
        
    Returns:
        tuple: (success: bool, message: str, token: str or None)
    """
    try:
        # Load config
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        refresh_token = config.get('twitch_bot_refresh_token')
        if not refresh_token:
            return False, "No refresh token available for bot account", None

        params = {
            "client_id": config.get('twitch_bot_client_id', ''),
            "client_secret": config.get('twitch_bot_secret', ''),
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        response = requests.post("https://id.twitch.tv/oauth2/token", params=params)
        
        if response.status_code == 200:
            data = response.json()
            new_access_token = data["access_token"]
            new_refresh_token = data["refresh_token"]
            
            # Update config
            config['twitch_bot_access_token'] = new_access_token
            config['twitch_bot_refresh_token'] = new_refresh_token
            
            # Save updated config
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            
            timestamp = datetime.now().strftime('%d-%m-%Y %H:%M:%S')
            message = f"[{timestamp}] Successfully refreshed bot access token"
            print(message)
            
            return True, message, new_access_token
        else:
            error_msg = f"Failed to refresh bot token: HTTP {response.status_code} - {response.text}"
            print(error_msg)
            return False, error_msg, None
            
    except FileNotFoundError:
        error_msg = f"Config file not found: {config_path}"
        print(error_msg)
        return False, error_msg, None
    except json.JSONDecodeError:
        error_msg = f"Invalid JSON in config file: {config_path}"
        print(error_msg)
        return False, error_msg, None
    except Exception as e:
        error_msg = f"Error refreshing bot token: {e}"
        print(error_msg)
        return False, error_msg, None


def get_current_bot_token(config_path="../config.json"):
    """
    Get current bot access token from config
    
    Args:
        config_path: Path to config.json file
        
    Returns:
        str or None: Current bot access token
    """
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        return config.get('twitch_bot_access_token')
    except Exception as e:
        print(f"Error reading bot token: {e}")
        return None


def validate_bot_token(token, config_path="../config.json"):
    """
    Validate if the bot token is still valid by making a test API call
    
    Args:
        token: Bot access token to validate
        config_path: Path to config.json file
        
    Returns:
        tuple: (is_valid: bool, message: str)
    """
    if not token:
        return False, "No token provided"
    
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        client_id = config.get('twitch_bot_client_id', '')
        if not client_id:
            return False, "No client ID found in config"
        
        # Test the token with a simple API call
        headers = {
            "Authorization": f"Bearer {token}",
            "Client-Id": client_id
        }
        
        response = requests.get("https://api.twitch.tv/helix/users", headers=headers)
        
        if response.status_code == 200:
            return True, "Token is valid"
        elif response.status_code == 401:
            return False, "Token is invalid or expired"
        else:
            return False, f"Token validation failed: HTTP {response.status_code}"
            
    except Exception as e:
        return False, f"Error validating token: {e}"
