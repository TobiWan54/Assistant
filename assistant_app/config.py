import os
from pathlib import Path
from .secrets import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from zoneinfo import ZoneInfo

## Core variables

TZ = ZoneInfo(os.getenv("TZ", "Europe/London"))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

# Create runtime data folder if it doesn't exist
DATA_DIR.mkdir(exist_ok=True)

ALARMS_DB_PATH = os.getenv("ALARMS_DB_PATH", str(DATA_DIR / "alarms.db"))

## Qwen-Agent Config
LLM_CFG = {
    "model": os.getenv("MODEL_NAME", "Qwen/Qwen3.5-2B"),
    "model_type": "qwenvl_oai",
    "model_server": os.getenv("OPENAI_BASE_URL", "http://localhost:8000/v1"),
    "api_key": os.getenv("OPENAI_API_KEY", "EMPTY"),
    "generate_cfg": {
        "fncall_prompt_type": "nous",
        "top_p": float(os.getenv("MODEL_TOP_P", "1.0")),
        "temperature": float(os.getenv("MODEL_TEMPERATURE", "0.2")),
        "max_input_tokens": int(os.getenv("MODEL_MAX_INPUT_TOKENS", "4800")),
        "max_tokens": int(os.getenv("MODEL_MAX_TOKENS", "512"))
    },
}

## Spotify MCP Config
SPOTIFY_MCP_CFG = {
    "mcpServers": {
        "spotify": {
            "command": "node",
            "args": [os.path.join(PROJECT_ROOT, "spotify-mcp-server", "build", "index.js")],
            "env": {
                "SPOTIFY_CLIENT_ID": SPOTIFY_CLIENT_ID,
                "SPOTIFY_CLIENT_SECRET": SPOTIFY_CLIENT_SECRET,
                "SPOTIFY_REDIRECT_URI": "http://127.0.0.1:8888/callback"
            }
        }
    }
}

# Google Calendar MCP config
CAL_MCP_CFG = {
    "mcpServers": {
        "google-calendar": {
            "command": "npx",
            "args": ["-y", "@google-labs/mcp-calendar"],
            "env": {
                "GOOGLE_CREDENTIALS_PATH": os.getenv(
                    "GOOGLE_CREDENTIALS_PATH",
                    str(DATA_DIR / "google_credentials.json"),
                ),
                "GOOGLE_TOKEN_PATH": os.getenv(
                    "GOOGLE_TOKEN_PATH",
                    str(DATA_DIR / "google_token.json"),
                ),
            }
        }
    }
}