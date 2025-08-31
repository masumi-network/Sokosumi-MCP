# MCP Server Context

## Overview
Minimal MCP (Model Context Protocol) server using FastMCP with streamable HTTP transport for Railway deployment.

## Key Features
- Uses official MCP Python SDK with FastMCP
- Streamable HTTP transport (recommended for production)
- Three tools for API key management and testing:
  - `store_api_key(api_key)`: Store an API key for the session
  - `get_api_key()`: Retrieve the stored API key
  - `test_connection()`: Verify server is running

## Connection
Connect via HTTP: `https://your-railway-url/`

## Files
- `server.py` - FastMCP server implementation with tools
- `requirements.txt` - Python dependencies (mcp>=1.2.0)
- `railway.json` - Railway deployment configuration
- `Procfile` - Railway start command
- `test_client.py` - HTTP test client using httpx

## Local Testing
```bash
pip install -r requirements.txt
python server.py  # Runs on port 8080
pip install httpx  # For test client
python test_client.py  # In another terminal
```

## Railway Deployment
- Auto-deploys from main branch
- Uses PORT environment variable (defaults to 8080)
- HTTP endpoint: `https://[your-app].up.railway.app/`

## API Key Usage
Since MCP doesn't support URL query parameter extraction in FastMCP without custom transport implementation, the server provides:
1. `store_api_key` tool to store an API key
2. `get_api_key` tool to retrieve the stored key
3. Simple in-memory storage (dict) for demonstration

## Implementation Details
- Uses `FastMCP` from `mcp.server.fastmcp`
- Streamable HTTP transport for production deployments
- Simple in-memory storage for API keys

## Future Enhancements
- Add more tools as needed
- Implement proper state management instead of global variable
- Add authentication/validation for API keys
- Add persistent storage if required
- Extend with additional MCP capabilities (resources, prompts, etc.)