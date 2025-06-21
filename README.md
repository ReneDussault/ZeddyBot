# ZeddyBot

A Python-based Discord and Twitch integration bot that provides real-time stream notifications and role management.

## Features

- **Web Dashboard**
  - Live stream and bot status overview
  - View stream history and Discord stats
  - Send messages directly to Twitch chat from your browser (using your twitch bot account)
  - Modern, responsive UI

- **Twitch Stream Notifications**
  - Embedded notifications in a Discord channel when streamers go live
  - Stream history tracking (last 10 streams)

- **Discord Role Management**
  - Automatically assigns a "LIVE" role to Discord members who are streaming
  - Role progression system (Drifters → Outlaws after 30 days)

- **Twitch Chat Integration**
  - Connects to a specified Twitch channel as a bot
  - Sends automated messages when streams start/end
  - Supports sending custom messages from Discord or the dashboard to Twitch chat

- **Clear Logging**
  - Human-friendly, non-repetitive log messages for user activity and bot actions

## Screenshots

### Stream Notification
![Stream Notification](https://github.com/ReneDussault/ZeddyBot/blob/main/screenshots/notif.png)

### Bot Console
![Bot Console](https://github.com/ReneDussault/ZeddyBot/blob/main/screenshots/terminal.png)

### Role Management
![Role Management](https://github.com/ReneDussault/ZeddyBot/blob/main/screenshots/live_role.png)

### Live Role Display
![Live Role](https://github.com/ReneDussault/ZeddyBot/blob/main/screenshots/live.bmp)

### Dashboard
![Dashboard](https://github.com/ReneDussault/ZeddyBot/blob/main/screenshots/dashandchat.png)

### Twitch Integration
![Twitch](https://github.com/ReneDussault/ZeddyBot/blob/main/screenshots/twitch.png)

### Twitch Chat Integration
![Twitch](https://github.com/ReneDussault/ZeddyBot/blob/main/screenshots/twitchchat.png)

## Setup

### Prerequisites
- Python 3.6+
- Discord Bot Token
- Twitch API Client ID and Secret
- Twitch Bot Account (optional for chat integration)
- Flask for the dashboard

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

4. Start the bot:
    ```
    python zeddybot.py
    ```

5. Start the dashboard (in a separate terminal):
    ```
    python dashboard.py
    ```
    Then open [http://localhost:5000](http://localhost:5000) in your browser.

## Commands
In your discord's specific channel configured in the config.json, you can:
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

## License

![MIT License](https://github.com/ReneDussault/ZeddyBot/blob/main/LICENSE.txt)
