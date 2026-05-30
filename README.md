# Bedside Assistant

A local voice-friendly assistant for the Raspberry Pi, built with [Qwen-Agent](https://github.com/QwenLM/Qwen-Agent) and a locally-hosted Qwen3 model.

## Features
- [ ] Voice input and output
- [x] Time and date
- [x] Alarms - set, fetch, edit, cancel
- [ ] Spotify playback control (via [marcelmarais/spotify-mcp-server](https://github.com/marcelmarais/spotify-mcp-server))
- [ ] Google Calendar reminders (via `mcp-google-calendar`)

_Disclaimer: contains a significant proportion of AI-generated code._

## Requirements

- Python 3.11+
- Node.js 18+
- A locally running OpenAI-compatible model server (e.g. vLLM or Ollama) serving a Qwen3.5 model
- Spotify Premium account (for Spotify integration)
- Google Cloud project with Calendar API enabled (for calendar integration)

## Setup

```bash
# Install Python dependencies
pip install -e .

# Install Node MCP dependencies
npm install

# Clone and build Spotify MCP server
git clone https://github.com/marcelmarais/spotify-mcp-server.git
cd spotify-mcp-server && npm install && npm run build && cd ..
```

Copy `secrets.py.example` to `secrets.py` and fill in your credentials.

## Usage

Ensure model server is using the _chatml_ chat template. Example llama-sever command:

```
llama-server.exe -hf unsloth/Qwen3.5-2B-GGUF:Q4_K_M -c 8192 --fit on --port 8000 --host 0.0.0.0 --chat-template chatml
```

Then run the cli (for testing).

```bash
python -m assistant_app.ui.cli
```

## Configuration

Key environment variables:

| Variable | Default | Description |
|---|---|---|
| `MODEL_NAME` | `Qwen/Qwen3.5-2B` | Model name on the inference server |
| `OPENAI_BASE_URL` | `http://localhost:8000/v1` | Inference server URL |
| `TZ` | `Europe/London` | Local timezone |
| `ALARMS_DB_PATH` | `alarms.db` in project root | SQLite database path |
| `GOOGLE_CREDENTIALS_PATH` | `credentials.json` | Google OAuth credentials |
| `GOOGLE_TOKEN_PATH` | `token.json` | Google OAuth token |
