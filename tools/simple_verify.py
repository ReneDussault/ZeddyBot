#!/usr/bin/env python3
"""
Simple path verification without external dependencies
Run this from main directory: cd main && python ../tools/simple_verify.py
"""

import os
import sys

def simple_path_test():
    print("🔧 SIMPLE PATH VERIFICATION (No external deps)")
    print("=" * 60)
    
    current_dir = os.getcwd()
    print(f"Current directory: {current_dir}")
    
    if current_dir.endswith("main"):
        print("✅ Running from main directory")
    else:
        print("⚠️ Not in main directory - paths might be wrong")
        return False
    
    # Check file existence
    files_to_check = [
        ("../config.json", "Config file"),
        ("../templates", "Templates folder"),
        ("../tools", "Tools folder"),
        ("../tools/token_utils.py", "Token utils module"),
        ("../tools/bot_moderation.py", "Bot moderation module"),
        ("zeddybot.py", "Discord bot script"),
        ("dashboardqa.py", "Dashboard script")
    ]
    
    all_good = True
    for path, description in files_to_check:
        if os.path.exists(path):
            print(f"✅ {description}: {path}")
        else:
            print(f"❌ {description}: {path} - NOT FOUND")
            all_good = False
    
    # Check import statements in main files
    print("\n🔍 Checking import statements in main files...")
    
    # Check zeddybot.py imports
    try:
        with open("zeddybot.py", 'r') as f:
            content = f.read()
            if "from tools.token_utils import" in content:
                print("✅ zeddybot.py has correct tools.token_utils import")
            else:
                print("❌ zeddybot.py missing tools.token_utils import")
                all_good = False
                
            if "from tools.bot_moderation import" in content:
                print("✅ zeddybot.py has correct tools.bot_moderation import")
            else:
                print("❌ zeddybot.py missing tools.bot_moderation import")
                all_good = False
                
            if '"../config.json"' in content:
                print("✅ zeddybot.py uses ../config.json paths")
            else:
                print("❌ zeddybot.py missing ../config.json paths")
                all_good = False
    except FileNotFoundError:
        print("❌ zeddybot.py not found in current directory")
        all_good = False
    
    # Check dashboardqa.py imports
    try:
        with open("dashboardqa.py", 'r') as f:
            content = f.read()
            if "from tools.token_utils import" in content:
                print("✅ dashboardqa.py has correct tools.token_utils import")
            else:
                print("❌ dashboardqa.py missing tools.token_utils import")
                all_good = False
                
            if "template_folder='../templates'" in content:
                print("✅ dashboardqa.py uses ../templates for Flask")
            else:
                print("❌ dashboardqa.py missing ../templates Flask config")
                all_good = False
                
            if '"../config.json"' in content:
                print("✅ dashboardqa.py uses ../config.json paths")
            else:
                print("❌ dashboardqa.py missing ../config.json paths")
                all_good = False
    except FileNotFoundError:
        print("❌ dashboardqa.py not found in current directory")
        all_good = False
    
    return all_good

if __name__ == "__main__":
    success = simple_path_test()
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 ALL PATH CHECKS PASSED!")
        print("\n✅ Your folder structure and paths are correct!")
        print("\nTo run your scripts (with virtual environment):")
        print("   cd c:\\Users\\Zed\\Desktop\\ZeddyBot")
        print("   .venv\\Scripts\\activate")
        print("   cd main")
        print("   python zeddybot.py")
        print("   python dashboardqa.py")
    else:
        print("💥 SOME PATH CHECKS FAILED!")
        print("\n❌ Please review the errors above and fix them")
    
    print("\n📁 Required folder structure:")
    print("ZeddyBot/")
    print("├── config.json          <- Config file")
    print("├── templates/           <- HTML templates")
    print("├── main/                <- Main scripts (run from here)")
    print("│   ├── zeddybot.py")
    print("│   └── dashboardqa.py")
    print("└── tools/               <- Utilities")
    print("    ├── token_utils.py")
    print("    └── bot_moderation.py")
