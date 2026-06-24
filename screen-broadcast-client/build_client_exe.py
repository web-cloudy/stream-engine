"""
Build Script for Screen Capture Client Executable
Creates a standalone .exe file for the screen capture client
"""
import PyInstaller.__main__
import os
import shutil


def locate_ffmpeg_binary():
    """Find an ffmpeg.exe to bundle into the executable.

    Searches several common project/system locations. Returns the path
    to ffmpeg.exe or None if it cannot be found.
    """
    candidates = [
        os.path.join('ffmpeg', 'ffmpeg.exe'),
        os.path.join('ffmpeg', 'bin', 'ffmpeg.exe'),
        os.path.join('dist_client', 'ffmpeg', 'ffmpeg.exe'),
        os.path.join('temp_extract', 'ffmpeg-8.1.1-essentials_build', 'bin', 'ffmpeg.exe'),
        r'C:\ffmpeg\bin\ffmpeg.exe',
    ]
    # Also check PATH
    path_ffmpeg = shutil.which('ffmpeg')
    if path_ffmpeg:
        candidates.append(path_ffmpeg)

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return None


def build_client_executable():
    """Build the Screen Capture Client executable using PyInstaller"""
    
    print("=" * 60)
    print("Building Screen Capture Client Executable")
    print("=" * 60)
    
    # PyInstaller arguments
    args = [
        'screen_capture_client.py',      # Main script
        '--name=ScreenCaptureClient',    # Name of the executable
        '--onefile',                      # Single file executable
        '--windowed',                     # No console window (GUI app)
        '--icon=NONE',                    # Add icon path if you have one

        '--hidden-import=PIL',
        '--hidden-import=PIL.ImageGrab',
        '--hidden-import=requests',
        '--hidden-import=tkinter',
        '--distpath=./dist_client',      # Output directory
        '--workpath=./build_client',     # Working directory
        '--clean',                        # Clean temporary files
    ]

    # Bundle ffmpeg.exe so the client works without a separate install.
    # It is placed in an "ffmpeg" subfolder inside the bundle; the client's
    # find_ffmpeg() looks for it at sys._MEIPASS/ffmpeg/ffmpeg.exe.
    ffmpeg_bin = locate_ffmpeg_binary()
    if ffmpeg_bin:
        print(f"Bundling FFmpeg from: {ffmpeg_bin}")
        # Format: SOURCE{os.pathsep}DEST_DIR_IN_BUNDLE
        args.append(f'--add-binary={ffmpeg_bin}{os.pathsep}ffmpeg')
    else:
        print("WARNING: ffmpeg.exe was not found. The executable will be built")
        print("         WITHOUT a bundled FFmpeg. Users must have FFmpeg on PATH,")
        print("         in C:\\ffmpeg\\bin, or in an 'ffmpeg' folder next to the exe.")
        print("         Tip: download 'release essentials' from")
        print("         https://www.gyan.dev/ffmpeg/builds/ and place ffmpeg.exe in")
        print("         a './ffmpeg' folder, then re-run this build.")

    print("\nBuilding executable...")
    print("This may take a few minutes...\n")
    
    # Run PyInstaller
    PyInstaller.__main__.run(args)

    
    print("\n" + "=" * 60)
    print("Build Complete!")
    print("=" * 60)
    print("\nExecutable created at: dist_client/ScreenCaptureClient.exe")
    print("\nTo run the client, double-click ScreenCaptureClient.exe")
    print("Or run from command line: dist_client\\ScreenCaptureClient.exe")
    
    # Create a readme for the client executable
    readme_content = """
# Screen Capture Client

## Overview
This client application allows you to capture a selected area of your screen 
and stream it to a server for broadcasting.

## How to Use

### 1. Setup
- Make sure FFmpeg is installed on your system
- Ensure the streaming server is running (default: http://localhost:5000)

### 2. Configure Server
- Enter the server address (e.g., http://192.168.1.100:5000 for remote server)
- Default is http://localhost:5000 for local server

### 3. Select Capture Interval
- **1 minute**: Captures and sends segments every minute
- **5 minutes**: Captures and sends segments every 5 minutes  
- **Continuous**: Streams continuously without pauses

### 4. Select Screen Area
1. Click "Select Area (Drag)" button
2. The screen will become semi-transparent
3. Click and drag to select the area you want to capture
4. Release the mouse button to confirm selection
5. Press ESC to cancel selection

### 5. Start Streaming
- Once area is selected, click "Start Capture"
- The client will:
  - Connect to the server
  - Initialize a stream session
  - Capture the selected area (with audio if available)
  - Send segments to the server

### 6. View Stream
- Open your browser and go to the server address
- Click on your stream in the list to watch

### 7. Stop Streaming
- Click "Stop Capture" to end the stream
- The stream session will be properly closed on the server

## Features
- **Visual Area Selection**: Drag to select any screen area
- **Audio Capture**: Captures system audio when available
- **Flexible Intervals**: Choose between 1 min, 5 min, or continuous
- **Real-time Status**: Monitor connection and streaming status
- **Automatic Reconnection**: Handles temporary network issues

## Requirements
- Windows 10/11
- FFmpeg installed and in system PATH
- Network connection to streaming server
- Sufficient bandwidth for video streaming

## Troubleshooting

### FFmpeg Not Found
- Install FFmpeg from https://ffmpeg.org/download.html
- Add FFmpeg to your system PATH

### Connection Failed
- Check if server is running
- Verify server address is correct
- Check firewall settings

### No Audio
- The client will automatically fall back to video-only if audio capture fails
- For audio capture, you may need to enable "Stereo Mix" in Windows sound settings

### Area Selection Issues
- Make sure to select an area larger than 10x10 pixels
- If selection overlay doesn't appear, restart the application

## Server API
The client communicates with these server endpoints:
- POST /api/stream-receiver/init - Initialize stream
- POST /api/stream-receiver/{id}/segment - Send segments
- POST /api/stream-receiver/{id}/end - End stream

## Network Requirements
- Port 5000 (or custom) must be accessible on server
- Bandwidth: ~1-5 Mbps for 720p streaming
- Low latency connection recommended

## Privacy Note
This application captures screen content and audio from your computer.
Only use it on your own devices or with proper authorization.
"""
    
    with open('dist_client/README.txt', 'w') as f:
        f.write(readme_content)
    
    print("\nREADME created at: dist_client/README.txt")

if __name__ == "__main__":
    build_client_executable()