# MCP Server Context

## Overview
Minimal MCP (Model Context Protocol) server using FastMCP with stdio transport.

## Key Features
- Uses official MCP Python SDK with FastMCP
- STDIO transport (standard for MCP servers)
- Three tools for API key management and testing:
  - `store_api_key(api_key)`: Store an API key for the session
  - `get_api_key()`: Retrieve the stored API key
  - `test_connection()`: Verify server is running

## Important Note on Deployment
**MCP servers with stdio transport are designed to be run as subprocesses by MCP clients, not as standalone HTTP servers.** 

Railway is designed for HTTP services, so this MCP server **cannot be deployed directly on Railway** as originally intended. Instead, MCP servers are typically:
1. Run locally by MCP clients (like Claude Desktop)
2. Packaged and distributed for users to run locally
3. Wrapped in an HTTP adapter if web deployment is needed

## Files
- `server.py` - FastMCP server implementation with tools
- `requirements.txt` - Python dependencies (mcp>=1.2.0)
- `railway.json` - Railway deployment configuration (not applicable for stdio)
- `Procfile` - Railway start command (not applicable for stdio)
- `test_client.py` - Test client (needs updating for stdio)

## Local Testing with MCP Client
```bash
pip install -r requirements.txt
python server.py  # Runs as stdio server
```

To connect from an MCP client like Claude Desktop, configure it to run:
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

## API Key Usage
The server provides:
1. `store_api_key` tool to store an API key
2. `get_api_key` tool to retrieve the stored key
3. Simple in-memory storage (dict) for demonstration

## Implementation Details
- Uses `FastMCP` from `mcp.server.fastmcp`
- STDIO transport for communication with MCP clients
- Simple in-memory storage for API keys

## Future Enhancements
- Add more tools as needed
- Implement proper state management instead of global variable
- Add authentication/validation for API keys
- Add persistent storage if required
- Extend with additional MCP capabilities (resources, prompts, etc.)