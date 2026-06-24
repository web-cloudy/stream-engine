import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuration for the Broadcasting Engine (Part 2)."""

    # Application secret (change in production).
    SECRET_KEY = os.getenv('SECRET_KEY', 'change-me-in-production')

    # Where received HLS segments / recordings are stored on disk.
    # Each stream gets <TRANSCODE_TEMP_DIR>/external_streams/<stream_id>/.
    TRANSCODE_TEMP_DIR = os.getenv('TRANSCODE_TEMP_DIR', './transcode_temp')

    # FFmpeg path (only used for the "download recording as MP4" feature).
    # Leave as 'ffmpeg' to auto-detect from PATH, or point at a binary.
    FFMPEG_PATH = os.getenv('FFMPEG_PATH', 'ffmpeg')

    # Server settings. HOST 0.0.0.0 listens on all interfaces (LAN clients).
    HOST = os.getenv('HOST', '0.0.0.0')
    PORT = int(os.getenv('PORT', 5000))
    DEBUG = os.getenv('DEBUG', 'true').lower() == 'true'
