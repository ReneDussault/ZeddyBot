# Q&A Display Setup Guide for OBS

## Overview
This guide explains how to set up the enhanced Q&A display in OBS Studio with beautiful styling and backgrounds.

## Option 1: Browser Source (Recommended)

### Step 1: Add Browser Source
1. In OBS, go to your "Scene - In Game" scene
2. Add a new source: **Sources** → **+** → **Browser**
3. Name it "QnA_Browser" or similar
4. Configure the Browser Source:
   - **URL**: `http://localhost:5000/qna`
   - **Width**: 1920 (or your canvas width)
   - **Height**: 1080 (or your canvas height)
   - **Custom CSS**: (leave blank)
   - Check **Shutdown source when not visible**
   - Check **Refresh browser when scene becomes active**

### Step 2: Position and Size
1. Position the browser source where you want the Q&A to appear
2. The Q&A card will auto-center itself within the browser source
3. The Q&A will automatically hide when no question is selected

### Step 3: Get the Item ID
1. Right-click the browser source in your scene
2. Go to **Filters** → **Advanced Scene Switcher** (if installed) or use OBS WebSocket tools
3. Note down the **Item ID** (you'll need this for the Python config)
4. Update `dashboardqa.py` line ~275: change `item_id=73` to your actual item ID

### Step 4: Color Themes
The Q&A display supports multiple color themes:
- **Default**: Purple gradient (matches your dashboard colors)
- **Green**: Success/positive questions
- **Blue**: Information/neutral questions  
- **Red**: Important/urgent questions
- **Orange**: Warning/attention questions

You can change themes via API call to `/api/qna_theme` with `{"theme": "green"}` etc.

## Option 2: Text Source (Fallback)

If you prefer a simpler text-only display:

### Step 1: Add Text Source
1. Add a new **Text (GDI+)** source
2. Name it "QnA_Text"
3. Configure the text source:
   - **Font**: Your preferred font (e.g., "Segoe UI", "Arial")
   - **Size**: 48-72px depending on your scene
   - **Color**: White or your preferred color
   - **Background Color**: Enable and set to semi-transparent (e.g., Black with 70% opacity)
   - **Background Opacity**: 70-80%
   - **Outline**: Enable with 2-4px thickness in black
   - **Text**: (leave blank, will be populated by the bot)

### Step 2: Position and Size
1. Position where you want questions to appear
2. Set appropriate width to prevent text overflow

### Step 3: Get the Item ID
1. Note the Item ID for this text source
2. Update `dashboardqa.py` line ~237: change `item_id=72` to your actual item ID

## Configuration

### Update Python Code
In `dashboardqa.py`, update these settings:

```python
# For Browser Source (line ~275)
self.obs_client.set_scene_item_enabled(
    scene_name="Scene - In Game",  # Your scene name
    item_id=73,                    # Your browser source item ID
    enabled=True
)

# For Text Source (line ~237)  
self.obs_client.set_scene_item_enabled(
    scene_name="Scene - In Game",  # Your scene name
    item_id=72,                    # Your text source item ID
    enabled=True
)
```

## Finding Item IDs

### Method 1: OBS WebSocket Browser
1. Open OBS WebSocket Browser extension
2. Connect to your OBS WebSocket
3. Use "GetSceneItemList" request with your scene name
4. Find your source in the response and note the `sceneItemId`

### Method 2: OBS WebSocket Client
1. Install a WebSocket client (like wscat): `npm install -g wscat`
2. Connect: `wscat -c ws://localhost:4455`
3. Send authentication and scene item list requests

### Method 3: Trial and Error
1. Start with common IDs like 1, 2, 3, etc.
2. Test the Q&A display from your dashboard
3. See which source gets enabled/disabled
4. Update the ID in the code accordingly

## Testing

1. Start your ZeddyBot dashboard: `python dashboardqa.py`
2. Open the Q&A display in your browser: `http://localhost:5000/qna`
3. From your dashboard, click on a chat message to display it
4. Verify it appears correctly in both the browser and OBS
5. Test the hide functionality

## Troubleshooting

### Browser Source Not Loading
- Check that the dashboard server is running on port 5000
- Verify the URL is exactly `http://localhost:5000/qna`
- Check OBS logs for any errors
- Try refreshing the browser source

### Q&A Not Appearing in OBS
- Verify the scene name matches exactly (case-sensitive)
- Check that the item ID is correct
- Ensure OBS WebSocket is enabled and connected
- Check Python console for OBS connection errors

### Styling Issues
- The browser source uses CSS that adapts to your stream resolution
- Questions automatically wrap at appropriate lengths
- Colors and fonts can be customized in `qna_display.html`

## Customization

### Custom Colors
Edit `templates/qna_display.html` and modify the CSS gradients:

```css
.qna-container {
    background: linear-gradient(135deg, rgba(YOUR_R, YOUR_G, YOUR_B, 0.95) 0%, rgba(YOUR_R2, YOUR_G2, YOUR_B2, 0.95) 100%);
}
```

### Custom Fonts
Add your preferred fonts to the CSS:

```css
body {
    font-family: "Your Font", -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
```

### Animation Speed
Modify the animation durations in the CSS:

```css
@keyframes slideIn {
    /* Adjust duration on line with 'animation:' */
}
```

## Benefits of Browser Source Approach

✅ **Rich Styling**: Custom backgrounds, gradients, shadows, animations
✅ **Responsive**: Automatically adapts to different screen sizes  
✅ **Themeable**: Multiple color schemes for different question types
✅ **Animated**: Smooth transitions when questions appear/hide
✅ **Professional**: Matches your dashboard's visual design
✅ **Maintainable**: Easy to update styling without touching Python code
✅ **Interactive**: Can be extended with additional features like voting, timers, etc.

The browser source approach gives you the most flexibility and professional appearance for your Q&A system!
