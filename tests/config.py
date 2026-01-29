"""Configuration loader for YAMS API tests.

Reads API keys and service URLs from environment variables or a .env file
located in the yams root directory.
"""

import os
from pathlib import Path

# Try to load .env file from the yams root directory
_env_path = Path(__file__).resolve().parent.parent / ".env"
try:
    from dotenv import load_dotenv
    load_dotenv(_env_path)
except ImportError:
    # python-dotenv not installed; fall back to environment variables only
    pass


def get(key: str, default: str = "") -> str:
    """Get a configuration value from the environment."""
    return os.environ.get(key, default)


# Jellyfin
JELLYFIN_URL = get("JELLYFIN_URL", "http://localhost:8096")
JELLYFIN_API_KEY = get("JELLYFIN_API_KEY")

# Sonarr
SONARR_URL = get("SONARR_URL", "http://localhost:8989")
SONARR_API_KEY = get("SONARR_APIKEY") or get("SONARR_API_KEY")

# Radarr
RADARR_URL = get("RADARR_URL", "http://localhost:7878")
RADARR_API_KEY = get("RADARR_APIKEY") or get("RADARR_API_KEY")
