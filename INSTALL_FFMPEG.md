# 🎬 FFmpeg Installation Guide for Windows

## ⚠️ IMPORTANT: FFmpeg is REQUIRED for:
- Screen Live Streaming
- Broadcast Capture
- Video Transcoding

## 📥 Quick Installation Steps

### Option 1: Download and Install (Recommended)

1. **Download FFmpeg**:
   - Go to: https://www.gyan.dev/ffmpeg/builds/
   - Click: **"release essentials"** (smaller download)
   - Or **"release full"** (all features)

2. **Extract the ZIP file**:
   - Extract to: `C:\ffmpeg`
   - You should see: `C:\ffmpeg\bin\ffmpeg.exe`

3. **Add to PATH**:
   ```cmd
   # Option A: Add to PATH permanently (Run as Administrator)
   setx /M PATH "%PATH%;C:\ffmpeg\bin"
   
   # Option B: Add to current session only
   set PATH=%PATH%;C:\ffmpeg\bin
   ```

4. **Verify Installation**:
   ```cmd
   ffmpeg -version
   ```

### Option 2: Using Package Managers

#### Chocolatey (if installed):
```cmd
choco install ffmpeg
```

#### Scoop (if installed):
```cmd
scoop install ffmpeg
```

### Option 3: Quick Local Install

1. **Download directly**:
   ```powershell
   # Download ffmpeg essentials
   Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile "ffmpeg.zip"
   
   # Extract
   Expand-Archive -Path "ffmpeg.zip" -DestinationPath "."
   ```

2. **Copy to project folder**:
   - Copy `ffmpeg.exe` to `D:\mywo\worldcup\`
   - Update `.env` file:
   ```
   FFMPEG_PATH=D:\mywo\worldcup\ffmpeg.exe
   ```

## 🔧 Alternative: Use Without Installing

If you can't install FFmpeg system-wide:

1. **Download portable version**
2. **Place ffmpeg.exe in project folder**
3. **Update .env file**:
   ```env
   FFMPEG_PATH=./ffmpeg.exe
   ```

## ✅ Verification

After installation, test FFmpeg:

```cmd
# Check version
ffmpeg -version

# Test screen capture capability
ffmpeg -f gdigrab -i desktop -t 1 test.mp4
```

## 🚀 After Installing FFmpeg

1. **Restart your terminal/PowerShell**
2. **Restart the application**:
   ```cmd
   # Stop current app (Ctrl+C)
   # Start again
   py app.py
   ```
3. **Run test again**:
   ```cmd
   py test_screen_livestream.py
   ```

## 🔍 Troubleshooting

### "ffmpeg not recognized" after installation:
- Close and reopen terminal/PowerShell
- Check PATH: `echo %PATH%`
- Try full path: `C:\ffmpeg\bin\ffmpeg.exe -version`

### Permission issues:
- Run PowerShell as Administrator
- Check Windows Defender/Antivirus isn't blocking

### Still not working:
- Download ffmpeg.exe directly to project folder
- Update .env with full path

## 📺 Why FFmpeg is Essential

FFmpeg is used for:
- **Screen Capture**: Grabs screen content
- **Video Encoding**: Converts to streamable format
- **HLS Creation**: Creates streaming segments
- **Real-time Processing**: Low-latency streaming

Without FFmpeg, the streaming features cannot work!

## 🎯 Quick Fix for Testing

Fastest solution for immediate testing:

1. Download: https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip
2. Extract `ffmpeg.exe` from `bin` folder
3. Copy to `D:\mywo\worldcup\`
4. Update `.env`:
   ```
   FFMPEG_PATH=ffmpeg.exe
   ```
5. Restart application

The streaming will work immediately after FFmpeg is available!