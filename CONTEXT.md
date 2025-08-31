# MCP Server Context

## Overview
Minimal MCP (Model Context Protocol) server using FastMCP with dual transport support (stdio for local, SSE/HTTP for remote).

## Key Features
- Uses official MCP Python SDK with FastMCP
- **Dual transport support**:
  - STDIO transport for local MCP clients (Claude Desktop, etc.)
  - SSE/HTTP transport for remote access (Railway deployment)
- Three tools for API key management and testing:
  - `store_api_key(api_key)`: Store an API key for the session
  - `get_api_key()`: Retrieve the stored API key
  - `test_connection()`: Verify server is running

## Deployment Modes

### 1. Railway/Remote (HTTP)
When deployed on Railway (or any server with PORT env var set), the server automatically uses SSE/HTTP transport:
- **Endpoint**: `https://your-railway-url/sse`
- **Transport**: Server-Sent Events (SSE) over HTTP
- **Access**: Can be accessed remotely by MCP clients that support HTTP transport

### 2. Local (STDIO)
When run locally without PORT env var, uses stdio transport:
- **Transport**: Standard Input/Output
- **Access**: Local MCP clients like Claude Desktop

## Files
- `server.py` - FastMCP server with dual transport support
- `requirements.txt` - Python dependencies (mcp>=1.2.0, uvicorn>=0.30.0)
- `railway.json` - Railway deployment configuration
- `Procfile` - Railway start command
- `test_client.py` - Test client for stdio transport

## How to Connect

### From Remote MCP Client (HTTP)
Connect to your Railway deployment:
```
https://your-railway-app.up.railway.app/sse
```

### From Claude Desktop (Local)
Configure in `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "minimal-mcp": {
      "command": "python",
      "args": ["/path/to/server.py"]
    }
  }
}
```

## Testing

### Local Testing
```bash
pip install -r requirements.txt
python server.py  # Runs as stdio server
python test_client.py  # In another terminal
```

### Remote Testing
Once deployed on Railway:
```bash
curl https://your-railway-app.up.railway.app/sse
```

## API Key Usage
The server provides:
1. `store_api_key` tool to store an API key
2. `get_api_key` tool to retrieve the stored key
3. Simple in-memory storage (dict) for demonstration

Note: Storage is per-session and not persistent across restarts.

## Implementation Details
- Uses `FastMCP` from `mcp.server.fastmcp`
- Automatic transport detection based on PORT env var
- SSE transport via uvicorn for HTTP deployment
- STDIO transport for local subprocess communication
- Simple in-memory storage for API keys

## Future Enhancements
- Add more tools as needed
- Implement proper session management for HTTP transport
- Add authentication/validation for API keys
- Add persistent storage if required
- Extend with additional MCP capabilities (resources, prompts, etc.)