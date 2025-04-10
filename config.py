"""
Configuration settings for the Study Assistant
"""
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Application paths
APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
AUDIO_DIR = DATA_DIR / "audio"

# Create necessary directories
DATA_DIR.mkdir(exist_ok=True)
AUDIO_DIR.mkdir(exist_ok=True)

# Default file paths
DEFAULT_SCHEDULE_FILE = DATA_DIR / "schedule.json"
DEFAULT_SETTINGS_FILE = DATA_DIR / "settings.json"

# API configurations
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")

# Default settings
DEFAULT_SETTINGS = {
    "elevenlabs_voice_id": "21m00Tcm4TlvDq8ikWAM",  # Default voice (Rachel)
    "openai_model": "gpt-4o",  # the newest OpenAI model is "gpt-4o" which was released May 13, 2024.
                              # do not change this unless explicitly requested by the user
    "audio_enabled": True,
    "logging_level": "INFO"
}

# Check for API keys and log warnings
if not OPENAI_API_KEY:
    logger.warning("OpenAI API key not found in environment variables. "
                   "Set the OPENAI_API_KEY environment variable to enable GPT text generation.")

if not ELEVENLABS_API_KEY:
    logger.warning("ElevenLabs API key not found in environment variables. "
                   "Set the ELEVENLABS_API_KEY environment variable to enable text-to-speech conversion.")

def get_settings():
    """Load settings from file or use defaults"""
    try:
        from assistant.utils import load_json
        settings = load_json(DEFAULT_SETTINGS_FILE)
        if settings:
            # Update with any missing default settings
            for key, value in DEFAULT_SETTINGS.items():
                if key not in settings:
                    settings[key] = value
            return settings
        return DEFAULT_SETTINGS
    except Exception as e:
        logger.error(f"Error loading settings: {e}")
        return DEFAULT_SETTINGS

def save_settings(settings):
    """Save settings to file"""
    try:
        from assistant.utils import save_json
        save_json(settings, DEFAULT_SETTINGS_FILE)
        logger.info("Settings saved successfully")
        return True
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return False
