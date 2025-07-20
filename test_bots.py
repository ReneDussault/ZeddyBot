#!/usr/bin/env python3

from bot_moderation import BotModerationManager
import requests

# Test the APIs directly
print('Testing TwitchInsights API...')
try:
    resp = requests.get('https://api.twitchinsights.net/v1/bots/online', timeout=5)
    print(f'TwitchInsights status: {resp.status_code}')
    if resp.status_code == 200:
        data = resp.json()
        bots = data.get("bots", [])
        print(f'Found {len(bots)} bots')
        if bots:
            print(f'Sample bots: {[bot[0] for bot in bots[:5]]}')
    else:
        print(f'Response: {resp.text[:200]}')
except Exception as e:
    print(f'TwitchInsights failed: {e}')

print('\nTesting CommanderRoot API...')
try:
    resp = requests.get('https://api.commanderroot.com/v1/twitch/bots', timeout=5)
    print(f'CommanderRoot status: {resp.status_code}')
    if resp.status_code == 200:
        data = resp.json()
        bots = data.get("bots", [])
        print(f'Found {len(bots)} bots')
        if bots:
            print(f'Sample bots: {bots[:5]}')
    else:
        print(f'Response: {resp.text[:200]}')
except Exception as e:
    print(f'CommanderRoot failed: {e}')

print('\nTesting bot moderation manager...')
manager = BotModerationManager(None)
success = manager.update_bot_list()
print(f'Update successful: {success}')
print(f'Known bots count: {len(manager.known_bots)}')
if manager.known_bots:
    print(f'Sample bots: {list(manager.known_bots)[:10]}')

print('\nTesting pattern detection...')
test_names = ["nightbot", "streamelements", "hoss0001", "some_random_bot", "normaluser", "followbot123"]
for name in test_names:
    is_bot = manager.is_likely_bot(name)
    print(f'{name}: {"🤖 BOT" if is_bot else "👤 USER"}')
