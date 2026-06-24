
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
