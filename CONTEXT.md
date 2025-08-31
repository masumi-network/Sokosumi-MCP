# MCP Server Context

## Overview
Minimal MCP (Model Context Protocol) server using FastMCP with streamable HTTP transport for Railway deployment.

## Key Features
- Uses official MCP Python SDK with FastMCP
- Streamable HTTP transport (recommended for production)
- API key extraction from URL query parameters via middleware
- Single test tool: `get_api_key` that returns the extracted API key

## Connection
Connect via HTTP with API key: `https://your-railway-url/?api_key=YOUR_API_KEY`

## Files
- `server.py` - FastMCP server implementation with middleware
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
- HTTP endpoint: `https://[your-app].up.railway.app/?api_key=YOUR_KEY`

## API Key Usage
The API key is extracted from the URL query parameter using FastMCP middleware. The `get_api_key` tool returns this stored value when called by MCP clients.

## Implementation Details
- Uses `FastMCP` from `mcp.server.fastmcp`
- Middleware pattern for request interception
- Streamable HTTP transport for production deployments
- Global storage for API key (can be improved with proper state management)

## Future Enhancements
- Add more tools as needed
- Implement proper state management instead of global variable
- Add authentication/validation for API keys
- Add persistent storage if required
- Extend with additional MCP capabilities (resources, prompts, etc.)