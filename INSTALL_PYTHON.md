# 🐍 Python Installation Guide for Windows

## Quick Install Steps

### Option 1: Download from Python.org (Recommended)

1. **Download Python**:
   - Go to https://www.python.org/downloads/
   - Click the yellow "Download Python" button (latest version)
   - Download will start automatically

2. **Install Python**:
   - Run the downloaded installer
   - ⚠️ **IMPORTANT**: Check "Add Python to PATH" at the bottom of the installer
   - Click "Install Now"
   - Wait for installation to complete

3. **Verify Installation**:
   Open Command Prompt and run:
   ```cmd
   python --version
   pip --version
   ```

### Option 2: Install from Microsoft Store

1. Open Microsoft Store
2. Search for "Python"
3. Select "Python 3.11" or latest version
4. Click "Get" or "Install"

## After Python Installation

### 1. Install Project Dependencies

Open Command Prompt in project directory and run:
```cmd
cd D:\mywo\worldcup
pip install -r requirements.txt
```

### 2. Install FFmpeg (Required for Broadcasting)

#### Option A: Download FFmpeg
1. Go to https://www.gyan.dev/ffmpeg/builds/
2. Download "release essentials" build
3. Extract the ZIP file
4. Add the `bin` folder to your PATH, or
5. Copy `ffmpeg.exe` to your project directory

#### Option B: Using Package Manager
If you have Chocolatey:
```cmd
choco install ffmpeg
```

Or if you have Scoop:
```cmd
scoop install ffmpeg
```

### 3. Configure Environment

Create a `.env` file:
```cmd
copy .env.example .env
```

Edit `.env` file with your settings:
```env
# Server Settings
HOST=0.0.0.0
PORT=5000
DEBUG=true

# Database
DATABASE_URL=sqlite:///media_center.db

# Media Directories
MEDIA_DIRECTORIES=D:/Media

# FFmpeg Path (if not in PATH)
FFMPEG_PATH=ffmpeg

# Transcoding
TRANSCODE_ENABLED=true
TRANSCODE_TEMP_DIR=./transcode_temp
```

### 4. Run the Application

```cmd
python app.py
```

Or use the batch file:
```cmd
run.bat
```

## Access the Application

- **Main Interface**: http://localhost:5000
- **Broadcast Manager**: http://localhost:5000/broadcast

## Troubleshooting

### Python Not Found After Installation
1. Restart Command Prompt
2. Check if Python was added to PATH:
   - Open System Properties → Environment Variables
   - Check if Python installation directory is in PATH
   - Typical paths:
     - `C:\Users\[username]\AppData\Local\Programs\Python\Python311\`
     - `C:\Users\[username]\AppData\Local\Programs\Python\Python311\Scripts\`

### pip Not Working
Run Python with module:
```cmd
python -m pip install -r requirements.txt
```

### FFmpeg Not Found
- Ensure FFmpeg is in PATH or
- Specify full path in `.env` file:
  ```
  FFMPEG_PATH=C:\path\to\ffmpeg\bin\ffmpeg.exe
  ```

## Quick Test

After installation, test everything works:

1. **Test Python**:
   ```cmd
   python --version
   ```

2. **Test FFmpeg**:
   ```cmd
   ffmpeg -version
   ```

3. **Run Application**:
   ```cmd
   python app.py
   ```

You should see:
```
 * Running on http://0.0.0.0:5000
 * Debug mode: on
```

## Need Help?

If you encounter issues:
1. Make sure Python 3.8+ is installed
2. Verify FFmpeg is accessible
3. Check all dependencies are installed
4. Review error messages in console

The application is now ready to capture and broadcast free streams!