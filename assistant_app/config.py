import os
from .secrets import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI
from zoneinfo import ZoneInfo


# Core variables
TZ = ZoneInfo(os.getenv("TZ", "Europe/London"))
ALARMS_DB_PATH = os.getenv("ALARMS_DB_PATH", "alarms.db")

# Secrets

# Qwen-Agent Config
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

# Spotify MCP Config
SPOTIFY_MCP_CFG = {
    "mcpServers": {
        "spotify": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-spotify"],
            "env": {
                "SPOTIFY_CLIENT_ID": SPOTIFY_CLIENT_ID,
                "SPOTIFY_CLIENT_SECRET": SPOTIFY_CLIENT_SECRET,
                "SPOTIFY_REDIRECT_URI": SPOTIFY_REDIRECT_URI,
            }
        }
    }
}