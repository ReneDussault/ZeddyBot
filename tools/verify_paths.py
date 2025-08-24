#!/usr/bin/env python3
"""
Simple verification script to test all path fixes
Run this from the main directory: cd main && python ../tools/verify_paths.py
"""

import os
import sys

def test_all_paths():
    print("🔧 COMPREHENSIVE PATH VERIFICATION")
    print("=" * 50)
    
    # Test 1: Check current working directory
    current_dir = os.getcwd()
    print(f"Current directory: {current_dir}")
    
    if current_dir.endswith("main"):
        print("✅ Running from main directory (correct)")
    else:
        print("⚠️ Not running from main directory - paths might not work")
    
    # Test 2: Check config file access
    config_path = "../config.json"
    if os.path.exists(config_path):
        print("✅ Config file found at ../config.json")
    else:
        print("❌ Config file NOT found at ../config.json")
        return False
    
    # Test 3: Check templates folder
    templates_path = "../templates"
    if os.path.exists(templates_path):
        print("✅ Templates folder found at ../templates")
    else:
        print("❌ Templates folder NOT found at ../templates")
        return False
    
    # Test 4: Check tools folder
    tools_path = "../tools"
    if os.path.exists(tools_path):
        print("✅ Tools folder found at ../tools")
    else:
        print("❌ Tools folder NOT found at ../tools")
        return False
    
    # Test 5: Try imports (will work if paths are correct)
    try:
        sys.path.append('..')  # Add parent to path for imports
        from tools.token_utils import refresh_twitch_bot_token
        print("✅ Successfully imported tools.token_utils")
    except ImportError as e:
        print(f"❌ Failed to import tools.token_utils: {e}")
        return False
    
    # Test 6: Test config loading with correct path
    try:
        import json
        with open("../config.json", 'r') as f:
            config = json.load(f)
        print("✅ Successfully loaded config from ../config.json")
    except Exception as e:
        print(f"❌ Failed to load config: {e}")
        return False
    
    # Test 7: Check Flask template folder setup
    try:
        # Import Flask from the script location
        sys.path.append('.')
        from flask import Flask
        app = Flask(__name__, template_folder='../templates')
        print("✅ Flask template folder configured correctly")
    except Exception as e:
        print(f"❌ Flask template setup failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = test_all_paths()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 ALL PATH VERIFICATIONS PASSED!")
        print("\n✅ You can now run your scripts:")
        print("   python zeddybot.py")
        print("   python dashboardqa.py")
    else:
        print("💥 SOME VERIFICATIONS FAILED!")
        print("\n❌ Please check the errors above")
        print("\nMake sure you're running from the main/ directory:")
        print("   cd main/")
        print("   python ../tools/verify_paths.py")
    
    print("\n📁 Expected folder structure:")
    print("ZeddyBot/")
    print("├── config.json")
    print("├── templates/")
    print("├── main/               <- Run scripts from here")
    print("│   ├── zeddybot.py")
    print("│   └── dashboardqa.py") 
    print("└── tools/")
    print("    ├── token_utils.py")
    print("    └── verify_paths.py  <- This script")
