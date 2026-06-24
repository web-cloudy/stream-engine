import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuration for the Web Viewer (Part 3)."""

    # Base URL of the Broadcasting Engine (Part 2) that serves the streams.
    # The browser fetches the API/HLS from here, so it must be reachable from
    # the VIEWER'S machine (use the engine's LAN IP / public host, not just
    # localhost, when viewers are on other machines).
    ENGINE_URL = os.getenv('ENGINE_URL', 'http://localhost:5000')

    # Server settings for THIS viewer web app.
    HOST = os.getenv('HOST', '0.0.0.0')
    PORT = int(os.getenv('PORT', 8080))
    DEBUG = os.getenv('DEBUG', 'true').lower() == 'true'
