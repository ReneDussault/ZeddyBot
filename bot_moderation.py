#!/usr/bin/env python3

import requests
import asyncio
from datetime import datetime
from typing import List, Optional
import discord

def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

class BotModerationManager:
    def __init__(self, twitch_chat_bot, discord_bot=None, channel_id=None):
        self.twitch_chat_bot = twitch_chat_bot
        self.discord_bot = discord_bot
        self.channel_id = channel_id
        self.known_bots = set()
        self.last_bot_update = None
        
        # Default whitelist of legitimate bots
        self.whitelist = [
            "nightbot", "streamelements", "streamlabs", "fossabot", 
            "moobot", "botisimo", "wizebot", "coebot", "ankhbot",
            "deepbot", "phantombot", "streamholics", "stay_hydrated_bot"
        ]
        
        # Patterns to identify potential bots by username
        import re
        self.bot_patterns = [
            re.compile(r".*bot$", re.IGNORECASE),           # Ends with 'bot'
            re.compile(r".*_bot$", re.IGNORECASE),          # Ends with '_bot'  
            re.compile(r"^bot_.*", re.IGNORECASE),          # Starts with 'bot_'
            re.compile(r".*follow.*", re.IGNORECASE),       # Contains 'follow'
            re.compile(r".*lurk.*", re.IGNORECASE),         # Contains 'lurk'
            re.compile(r"hoss\d+", re.IGNORECASE),          # Common bot pattern
            re.compile(r"electricalskateboard", re.IGNORECASE),
            re.compile(r"commanderroot", re.IGNORECASE),
        ]
    
    def is_likely_bot(self, username: str) -> bool:
        """Check if username matches bot patterns"""
        username_lower = username.lower()
        
        # Check if already in whitelist
        if username_lower in [w.lower() for w in self.whitelist]:
            return False
            
        # Check against patterns
        for pattern in self.bot_patterns:
            if pattern.match(username_lower):
                return True
                
        return False
    
    def add_to_whitelist(self, bot_name: str):
        """Add a bot to the whitelist"""
        self.whitelist.append(bot_name.lower())
        print(f"[{now()}] Added {bot_name} to whitelist")
    
    def remove_from_whitelist(self, bot_name: str):
        """Remove a bot from the whitelist"""
        if bot_name.lower() in self.whitelist:
            self.whitelist.remove(bot_name.lower())
            print(f"[{now()}] Removed {bot_name} from whitelist")
    
    def update_bot_list(self) -> bool:
        """Fetch known bots from multiple sources"""
        try:
            # Try TwitchInsights first
            response = requests.get("https://api.twitchinsights.net/v1/bots/online", timeout=10)
            if response.status_code == 200:
                data = response.json()
                self.known_bots = {bot[0].lower() for bot in data["bots"]}
                self.last_bot_update = datetime.now()
                print(f"[{now()}] Updated bot list from TwitchInsights: {len(self.known_bots)} known bots")
                return True
        except Exception as e:
            print(f"[{now()}] TwitchInsights API failed: {e}")
        
        try:
            # Backup: Try CommanderRoot's bot list
            response = requests.get("https://api.commanderroot.com/v1/twitch/bots", timeout=10)
            if response.status_code == 200:
                data = response.json()
                # This API returns different format: {"bots": ["bot1", "bot2", ...]}
                if "bots" in data:
                    self.known_bots = {bot.lower() for bot in data["bots"]}
                    self.last_bot_update = datetime.now()
                    print(f"[{now()}] Updated bot list from CommanderRoot: {len(self.known_bots)} known bots")
                    return True
        except Exception as e:
            print(f"[{now()}] CommanderRoot API failed: {e}")
        
        # Fallback: Use hardcoded list of common bots
        fallback_bots = {
            "streamelements", "nightbot", "streamlabs", "fossabot", "moobot",
            "botisimo", "wizebot", "coebot", "ankhbot", "deepbot", "phantombot",
            "streamholics", "stay_hydrated_bot", "restreambot", "lurxx",
            "commanderroot", "electricallongboard", "sery_bot", "virgoproz",
            "rogueg1rl", "skinnyseahorse", "aliceydra", "apricotdrupefruit",
            "bailinginablazer", "bananenheld", "beastlyviking8", "bro_mike",
            "creatisbot", "d0ge_bot", "drapsnatt", "electricalskateboard",
            "feuerwehr", "fraction", "houstonswag", "illegal_snowman",
            "jamesbot_", "kappa", "mikepjb", "n3rdfusion", "ohyoutrack",
            "p0lizei_", "qdice", "rainmaker_", "rogueg1rl", "sery_bot",
            "soundalerts", "streamelements", "thronezilla", "v_and_k",
            "wellshii", "wizebot", "zanekyber"
        }
        
        if not self.known_bots:  # Only use fallback if we have no bots at all
            self.known_bots = fallback_bots
            self.last_bot_update = datetime.now()
            print(f"[{now()}] Using fallback bot list: {len(self.known_bots)} known bots")
            return True
        
        print(f"[{now()}] All bot APIs failed, keeping existing list")
        return False
    
    def is_known_bot(self, username: str) -> bool:
        """Check if username is a known bot (and not whitelisted)"""
        username_lower = username.lower()
        return username_lower in self.known_bots and username_lower not in self.whitelist
    
    def get_bot_stats(self) -> dict:
        """Get statistics about known bots"""
        return {
            "total_known_bots": len(self.known_bots),
            "whitelisted_bots": len(self.whitelist),
            "last_update": self.last_bot_update.strftime('%Y-%m-%d %H:%M:%S') if self.last_bot_update else "Never"
        }
    
    async def moderate_bot(self, bot_name: str, action: str = "timeout", duration: int = 300, reason: str = "Auto-moderated bot") -> bool:
        """Moderate a bot in Twitch chat"""
        try:
            if action == "ban":
                success = self.twitch_chat_bot.send_message(f"/ban {bot_name} {reason}")
            elif action == "timeout":
                success = self.twitch_chat_bot.send_message(f"/timeout {bot_name} {duration} {reason}")
            else:
                print(f"[{now()}] Unknown moderation action: {action}")
                return False
            
            if success:
                print(f"[{now()}] {action.title()}ed bot: {bot_name}")
                
                # Send Discord notification if configured
                await self._send_discord_notification(bot_name, action, reason)
                return True
            else:
                print(f"[{now()}] Failed to {action} bot: {bot_name}")
                return False
                
        except Exception as e:
            print(f"[{now()}] Error moderating bot {bot_name}: {e}")
            return False
    
    async def _send_discord_notification(self, bot_name: str, action: str, reason: str):
        """Send moderation notification to Discord"""
        if not self.discord_bot or not self.channel_id:
            return
        
        try:
            channel = self.discord_bot.get_channel(self.channel_id)
            if not channel:
                return
            
            embed = discord.Embed(
                title="🤖 Bot Moderation",
                description=f"**{action.title()}** bot: `{bot_name}`\n**Reason:** {reason}",
                color=0xff6b6b if action == "ban" else 0xffa500,
                timestamp=datetime.now()
            )
            
            await channel.send(embed=embed)
        except Exception as e:
            print(f"[{now()}] Error sending Discord notification: {e}")
    
    async def check_and_moderate_bots(self, action: str = "timeout", duration: int = 300) -> dict:
        """Check for known bots and moderate them"""
        if not self.update_bot_list():
            return {"success": False, "error": "Failed to fetch bot list"}
        
        moderated_bots = []
        failed_bots = []
        
        # Filter out whitelisted bots
        bots_to_moderate = [bot for bot in self.known_bots if bot not in self.whitelist]
        
        print(f"[{now()}] Found {len(bots_to_moderate)} bots to moderate (excluding {len(self.whitelist)} whitelisted)")
        
        for bot_name in bots_to_moderate:
            success = await self.moderate_bot(bot_name, action, duration)
            
            if success:
                moderated_bots.append(bot_name)
            else:
                failed_bots.append(bot_name)
            
            # Rate limiting - wait between actions
            await asyncio.sleep(2)
        
        return {
            "success": True,
            "moderated_count": len(moderated_bots),
            "failed_count": len(failed_bots),
            "moderated_bots": moderated_bots,
            "failed_bots": failed_bots
        }
    
    def get_whitelist(self) -> List[str]:
        """Get current whitelist"""
        return self.whitelist.copy()
