#!/usr/bin/env python3
"""
Test script to verify all imports and paths work correctly after reorganization
Run this from the main/ directory to test everything
"""

import sys
import os

# Add the parent directory to path so we can import from tools
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_imports():
    print("Testing imports after folder reorganization...")
    
    try:
        # Test token utils import
        from tools.token_utils import refresh_twitch_bot_token, validate_bot_token, get_current_bot_token
        print("✅ Successfully imported token_utils from tools/")
    except ImportError as e:
        print(f"❌ Failed to import token_utils: {e}")
        return False
    
    try:
        # Test bot moderation import
        from tools.bot_moderation import BotModerationManager
        print("✅ Successfully imported bot_moderation from tools/")
    except ImportError as e:
        print(f"❌ Failed to import bot_moderation: {e}")
        return False
    
    try:
        # Test config file access
        config_path = "../config.json"
        if os.path.exists(config_path):
            print("✅ Config file found at ../config.json")
        else:
            print("❌ Config file not found at ../config.json")
            return False
    except Exception as e:
        print(f"❌ Error checking config file: {e}")
        return False
    
    try:
        # Test templates folder access
        templates_path = "../templates"
        if os.path.exists(templates_path):
            print("✅ Templates folder found at ../templates")
        else:
            print("❌ Templates folder not found at ../templates")
            return False
    except Exception as e:
        print(f"❌ Error checking templates folder: {e}")
        return False
    
    return True

def test_token_utils():
    print("\nTesting token_utils with correct config path...")
    
    try:
        from tools.token_utils import get_current_bot_token
        
        # Test with the correct relative path
        token = get_current_bot_token("../config.json")
        if token:
            print("✅ Successfully retrieved bot token from config")
        else:
            print("⚠️ No bot token found in config (this might be normal)")
        return True
    except Exception as e:
        print(f"❌ Error testing token_utils: {e}")
        return False

if __name__ == "__main__":
    print("🔧 Path Verification Test")
    print("=" * 50)
    
    success = True
    
    if test_imports():
        print("\n✅ All imports successful!")
    else:
        print("\n❌ Some imports failed!")
        success = False
    
    if test_token_utils():
        print("✅ Token utils working correctly!")
    else:
        print("❌ Token utils failed!")
        success = False
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 All path fixes appear to be working correctly!")
        print("\nYou can now run:")
        print("  cd main/")
        print("  python zeddybot.py")
        print("  python dashboardqa.py")
    else:
        print("💥 Some issues found. Check the errors above.")
        
    print("\nFolder structure should be:")
    print("ZeddyBot/")
    print("├── config.json")
    print("├── templates/")
    print("├── main/")
    print("│   ├── zeddybot.py")
    print("│   └── dashboardqa.py")
    print("└── tools/")
    print("    ├── token_utils.py")
    print("    ├── bot_moderation.py")
    print("    └── ...")
