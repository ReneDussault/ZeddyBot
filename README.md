# ZeddyBot

A Python-based Discord and Twitch integration bot that provides real-time stream notifications and role management.

## Features

- **Twitch Stream Notifications**: Posts embedded notifications in a Discord channel when streamers from your watchlist go live
- **Discord Role Management**: 
  - Automatically assigns a "LIVE" role to Discord members who are streaming
  - Role progression system (Drifters → Outlaws after 30 days)
- **Twitch Chat Integration**: 
  - Connects to a specified Twitch channel as a bot
  - Can send automated messages when streams start/end
  - Supports sending custom messages from Discord to Twitch chat

## Screenshots

### Stream Notification
![Stream Notification](https://github.com/ReneDussault/ZeddyBot/blob/main/Screenshot%202023-02-07%20205438.png)

### Bot Console
![Bot Console](https://github.com/ReneDussault/ZeddyBot/blob/main/Screenshot_from_2023-02-07_21-56-48.png)

### Role Management
![Role Management](https://github.com/ReneDussault/ZeddyBot/blob/main/Screenshot_from_2023-02-07_21-34-15.png)

### Live Role Display
![Live Role](https://github.com/ReneDussault/ZeddyBot/blob/main/live.bmp)

## Setup

### Prerequisites
- Python 3.6+
- Discord Bot Token
- Twitch API Client ID and Secret
- Twitch Bot Account (optional for chat integration)

### Installation

1. Clone the repository:
   ```
   git clone https://github.com/ReneDussault/ZeddyBot.git
   cd ZeddyBot
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Create a `config.json` file with the following structure:
   ```json
   {
     "disc_token": "your_discord_token",
     "twitch_client_id": "your_twitch_client_id",
     "twitch_secret": "your_twitch_client_secret",
     "access_token": "",
     "watchlist": ["streamer1", "streamer2"],
     "twitch_bot_username": "your_bot_username",
     "twitch_bot_access_token": "",
     "twitch_bot_refresh_token": "",
     "twitch_bot_client_id": "your_bot_client_id",
     "twitch_bot_secret": "your_bot_secret",
     "target_channel": "your_channel_name",
     "discord_channel_id": "your_notification_channel_id",
     "discord_live_role_id": "your_live_role_id",
     "discord_drifters_role_id": "your_drifters_role_id",
     "discord_outlaws_role_id": "your_outlaws_role_id"
   }
   ```

### Running the Bot

```
python zeddybot.py
```

## Commands

- `!ping` - Test command that responds with "Pong!"
- `!hello` - Greets the user
- `!twitch_chat [message]` - Sends a message to the configured Twitch chat
- `!refresh_bot_token` - Manually refreshes the Twitch bot token

## Configuration Details

### Discord Settings
- `disc_token`: Your Discord bot token
- `discord_channel_id`: ID of the channel where stream notifications will be posted
- `discord_live_role_id`: ID of the role to assign to streaming members
- `discord_drifters_role_id`: ID of the "Drifters" role for new members
- `discord_outlaws_role_id`: ID of the "Outlaws" role for members after 30 days

### Twitch API Settings
- `twitch_client_id`: Your Twitch application client ID
- `twitch_secret`: Your Twitch application secret
- `access_token`: Will be automatically populated
- `watchlist`: Array of Twitch usernames to monitor for stream notifications

### Twitch Chat Bot Settings
- `twitch_bot_username`: Username for the Twitch chat bot
- `twitch_bot_client_id`: Client ID for the Twitch chat bot
- `twitch_bot_secret`: Secret for the Twitch chat bot
- `twitch_bot_access_token`: Will be automatically populated
- `twitch_bot_refresh_token`: Will be automatically populated
- `target_channel`: Twitch channel for the bot to join

## Future Development

- Adding more interactive chat commands
- Implementing chatbot functionality
- Code refactoring for improved structure and readability
- Enhanced documentation and examples

## License

[MIT License](LICENSE)
