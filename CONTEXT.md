# MCP Server Context

## Overview
Minimal MCP (Model Context Protocol) server with HTTP/WebSocket transport for Railway deployment.

## Key Features
- WebSocket endpoint at `/mcp` with API key extraction from URL query parameters
- Single test tool: `get_api_key` that returns the extracted API key
- Health check endpoint at `/health`

## Connection
Connect via WebSocket: `ws://your-railway-url/mcp?api_key=YOUR_API_KEY`

## Files
- `server.py` - Main MCP server implementation
- `requirements.txt` - Python dependencies (mcp, aiohttp, python-dotenv)
- `railway.json` - Railway deployment configuration
- `Procfile` - Railway start command
- `test_client.py` - Test client for local testing

## Local Testing
```bash
pip install -r requirements.txt
python server.py  # Runs on port 8080
python test_client.py  # In another terminal
```

## Railway Deployment
- Auto-deploys from main branch
- Uses PORT environment variable (defaults to 8080)
- WebSocket endpoint: `wss://[your-app].up.railway.app/mcp?api_key=YOUR_KEY`

## API Key Usage
The API key is extracted from the URL query parameter and stored in the server instance. The `get_api_key` tool returns this value when called by MCP clients.

## Future Enhancements
- Add more tools as needed
- Implement authentication/validation for API keys
- Add persistent storage if required
- Extend with additional MCP capabilities (resources, prompts, etc.)