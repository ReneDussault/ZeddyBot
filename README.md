# ZeddyBot

A Python-based Discord and Twitch integration bot that provides real-time stream notifications, role management, and an integrated web dashboard with instant chat monitoring.

## Features

- **Real-Time Web Dashboard**

  - Live stream and bot status overview
  - **Instant chat monitoring** with Server-Sent Events (SSE) - messages appear within 1-2 seconds
  - Send messages directly to Twitch chat from your browser
  - Stream history and Discord server statistics
  - Modern, responsive UI with real-time updates

- **Twitch Integration**

  - **Real-time chat message broadcasting** to connected dashboard clients
  - Automated stream notifications in Discord when streamers go live
  - Stream history tracking (last 10 streams)
  - Bot sends automated messages when streams start/end
  - Supports custom messages from Discord or dashboard to Twitch chat

- **Discord Role Management**

  - Automatically assigns "LIVE" role to streaming members
  - Role progression system (Drifters → Outlaws after 30 days)
  - Real-time member statistics and activity tracking

- **Advanced Technology**
  - Server-Sent Events (SSE) for instant updates - no more polling delays
  - Automatic connection management and heartbeat monitoring
  - Scales to multiple concurrent dashboard sessions
  - Enhanced logging with broadcast monitoring

## Screenshots
### Dashboard
![Dashboard](https://github.com/ReneDussault/ZeddyBot/blob/main/screenshots/dashboard.png)
_Real-time dashboard with instant chat updates_

![Stream Notification](https://github.com/ReneDussault/ZeddyBot/blob/main/screenshots/notif.png)

### Bot Console

![Bot Console](https://github.com/ReneDussault/ZeddyBot/blob/main/screenshots/terminal.png)

### Role Management

![Role Management](https://github.com/ReneDussault/ZeddyBot/blob/main/screenshots/live_role.png)

### Live Role Display

![Live Role](https://github.com/ReneDussault/ZeddyBot/blob/main/screenshots/live.bmp)

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
     "disc_token": "yourdiscordtokenhere",
     "twitch_client_id": "yourtwitchidhere",
     "twitch_secret": "yourtwitchsecrethere",
     "access_token": "yourtwitchtokenhere",
     "watchlist": ["yourchannelname", "otherchannelnametoo"],
     "twitch_bot_username": "twitchbotaccountname",
     "twitch_bot_client_id": "twitchbotid",
     "twitch_bot_access_token": "twitchbotsecret",
     "twitch_bot_refresh_token": "twitchbotrefreshtoken",
     "twitch_bot_secret": "twitchbotsecret",
     "target_channel": "yourchannelname",
     "obs": {
       "host": "yourobswebsocketip",
       "port": 4455,
       "password": "yourobspassword"
     }
   }
   ```

4. Start the bot:

   ```bash
   python main/zeddybot.py
   ```

   The bot includes an integrated Flask dashboard with real-time chat capabilities.
   Open [http://localhost:5000](http://localhost:5000) to access the dashboard.

## Commands

Use these commands in your configured Discord channel:

- `!ping` - Test command that responds with "Pong!"
- `!hello` - Greets the user
- `!twitch_chat [message]` - Sends a message to Twitch chat (includes Discord username)
- `!refresh_bot_token` - Manually refreshes the Twitch bot token

## License

[MIT License](https://github.com/ReneDussault/ZeddyBot/blob/main/LICENSE.txt)
