#!/usr/bin/env python3

import obsws_python as obs
import socket


def test_connection():
    OBS_HOST = '10.0.0.219'
    OBS_PORT = 4455
    OBS_PASSWORD = '123456'
    
    print("=== OBS Connection Debug ===")
    print(f"Testing connection to {OBS_HOST}:{OBS_PORT}")
    
    # Step 1: Test basic network connectivity
    print("\n1. Testing basic network connectivity...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((OBS_HOST, OBS_PORT))
        sock.close()
        
        if result == 0:
            print("✓ Port is open and reachable")
        else:
            print("✗ Cannot reach port - check IP/port/firewall")
            return
    except Exception as e:
        print(f"✗ Network error: {e}")
        return
    
    # Step 2: Test OBS WebSocket connection
    print("\n2. Testing OBS WebSocket connection...")
    try:
        print("Attempting to connect... (will timeout in 10 seconds)")
        
        # Create client with timeout
        cl = obs.ReqClient(
            host=OBS_HOST, 
            port=OBS_PORT, 
            password=OBS_PASSWORD,
            timeout=10
        )
        
        print("✓ Connected to OBS!")
        
        # Step 3: Test basic API call
        print("\n3. Testing basic API call...")
        try:
            version = cl.get_version()
            print(f"✓ OBS Version: {version.obs_version}") # type: ignore
            print(f"✓ WebSocket Version: {version.obs_web_socket_version}") # type: ignore
        except Exception as e:
            print(f"✗ API call failed: {e}")
        
        # Step 4: Get scenes and sources
        print("\n4. Getting scenes and sources...")
        try:
            scenes = cl.get_scene_list()
            print(f"✓ Current scene: {scenes.current_program_scene_name}") # type: ignore
            
            for scene in scenes.scenes: # type: ignore
                scene_name = scene['sceneName']
                print(f"\nScene: '{scene_name}'")
                
                try:
                    items = cl.get_scene_item_list(scene_name)
                    for item in items.scene_items: # type: ignore
                        item_id = item['sceneItemId']
                        source_name = item['sourceName']
                        enabled = item['sceneItemEnabled']
                        status = "VISIBLE" if enabled else "HIDDEN"
                        print(f"  └─ ID {item_id}: '{source_name}' ({status})")
                except Exception as e:
                    print(f"  └─ Error getting items: {e}")
                    
        except Exception as e:
            print(f"✗ Failed to get scenes: {e}")
        
        # Step 5: Test input sources
        print("\n5. Getting input sources...")
        try:
            inputs = cl.get_input_list()
            text_sources = []
            
            for input_src in inputs.inputs: # type: ignore
                source_name = input_src['inputName']
                source_kind = input_src['inputKind']
                print(f"Source: '{source_name}' (Type: {source_kind})")
                
                if 'text' in source_kind.lower():
                    text_sources.append(source_name)
            
            if text_sources:
                print(f"\n✓ Text sources found: {text_sources}")
                print(f"Recommended for Q&A: '{text_sources[0]}'")
            else:
                print("\n⚠️  No text sources found - create one in OBS first")
                
        except Exception as e:
            print(f"✗ Failed to get inputs: {e}")
        
        # Clean disconnect
        cl.disconnect()
        print("\n✓ Disconnected successfully")
        
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        print("\nTroubleshooting tips:")
        print("- Make sure OBS WebSocket server is enabled")
        print("- Check if OBS is binding to 0.0.0.0 (not just localhost)")
        print("- Verify firewall allows port 4455")
        print("- Try connecting from OBS machine first (use 'localhost')")

if __name__ == "__main__":
    test_connection()
