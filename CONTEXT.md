# MCP Server Context

## Overview
Minimal MCP (Model Context Protocol) server using FastMCP with dual transport support (stdio for local, Streamable HTTP for remote). Following best practices for deploying remote MCP servers.

## Architecture Type
This is a **Remote MCP Server** implementation, which according to industry guides represents the future direction of MCP:
- ✅ Runs on cloud platforms (Railway, Cloud Run, etc.)
- ✅ Accessible via HTTPS
- ✅ No local configuration needed for end users
- ✅ Instant updates for all users
- ✅ Centrally managed

## Key Features
- Uses official MCP Python SDK with **FastMCP**
- **Dual transport support**:
  - STDIO transport for local MCP clients (Claude Desktop, etc.)
  - Streamable HTTP transport for remote access (Railway deployment)
- **API Key extraction from URL**: ASGI middleware automatically extracts API keys from `?api_key=xxx` query parameters
- Tools available:
  - `store_api_key(api_key)`: Store an API key for the session
  - `get_api_key()`: Retrieve the API key (from URL or manually stored)
  - `test_connection()`: Verify server is running
  - `echo_message(message)`: Echo a message for testing

## Deployment Modes

### 1. Railway/Cloud Run (HTTP) - Production
When deployed with PORT env var set, uses Streamable HTTP transport:
- **Endpoint**: `https://your-app-url/mcp` (Streamable HTTP endpoint)
- **Transport**: Streamable HTTP (the modern standard)
- **Protocol**: MCP 2025-06-18 specification
- **Access**: Remote MCP clients via HTTP

### 2. Local Development (STDIO)
When run locally without PORT env var:
- **Transport**: Standard Input/Output
- **Access**: Local MCP clients like Claude Desktop
- **Use Case**: Development and testing

## Files
- `server.py` - FastMCP server with dual transport support and API key middleware
- `requirements.txt` - Python dependencies (mcp>=1.2.0, uvicorn>=0.30.0, starlette>=0.37.0)
- `railway.json` - Railway deployment configuration
- `Procfile` - Railway start command
- `test_client.py` - Test client for stdio transport

## How to Connect

### Using mcp-remote Bridge with API Key
Until clients support remote servers directly:
```json
{
  "mcpServers": {
    "my-server": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://your-railway-app.up.railway.app/mcp?api_key=your-api-key-here"
      ]
    }
  }
}
```

### Direct Remote Connection with API Key (Future)
When clients support remote MCP servers:
```
https://your-railway-app.up.railway.app/mcp?api_key=your-api-key-here
```

The API key will be automatically extracted from the URL and made available via the `get_api_key()` tool.

### Local Development
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

### Test with curl
```bash
# Streamable HTTP endpoint
curl https://your-railway-app.up.railway.app/mcp

# Test with POST for Streamable HTTP
curl -X POST https://your-railway-app.up.railway.app/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{},"id":1}'
```

### Local Testing
```bash
pip install -r requirements.txt
python server.py  # Runs as stdio server
python test_client.py  # In another terminal
```

## Current Limitations vs Production-Ready

| Feature | Current Status | Production Needs |
|---------|---------------|------------------|
| Transport | ✅ Streamable HTTP | ✅ Complete |
| Tools | ✅ Basic demo tools | Would need real API integration |
| Authentication | ⚠️ Basic API key | OAuth 2.1 with PKCE |
| Session Management | ⚠️ In-memory | Redis or database |
| API Key Extraction | ✅ URL parameters | ✅ Complete |
| Error Handling | ⚠️ Basic | JSON-RPC compliant errors |
| Logging | ✅ stderr logging | ✅ Complete |
| CORS | ⚠️ Partial | Full CORS headers |

## Implementation Details
- **FastMCP**: Using the recommended FastMCP approach
- **Transport Detection**: Automatic based on PORT env var
- **Streamable HTTP**: `mcp.streamable_http_app()` creates ASGI app for modern HTTP transport
- **Uvicorn**: Production ASGI server for HTTP deployment
- **Logging**: Properly configured to stderr (not stdout)
- **API Key Middleware**: ASGI middleware (`APIKeyExtractorMiddleware`) automatically extracts API keys from URL query parameters
  - Intercepts incoming requests and checks for `?api_key=xxx`
  - Stores extracted keys globally for retrieval via `get_api_key()` tool
  - Uses Starlette's `BaseHTTPMiddleware` for request interception

## Why FastMCP?
Based on best practices and official examples:
1. **Simpler API**: Decorators for tools make code cleaner
2. **Built-in Transport**: Handles Streamable HTTP/SSE/stdio automatically
3. **Production Ready**: Used in Google's official examples
4. **Type Safety**: Better IDE support and type hints

## Next Steps for Production

1. **Add OAuth 2.1 Authentication**
   - Implement `/.well-known/oauth-protected-resource`
   - Add `/authorize`, `/token` endpoints
   - Implement PKCE flow

2. **Persistent Storage**
   - Replace in-memory dict with database
   - Add session management with Redis

3. **Real Tools**
   - Connect to actual APIs
   - Add error handling
   - Implement rate limiting

4. **Monitoring**
   - Add health checks
   - Implement metrics
   - Set up alerting

## References
- [Google Cloud Run MCP Tutorial](https://cloud.google.com/run/docs/tutorials/deploy-remote-mcp-server)
- [MCP Specification](https://modelcontextprotocol.org)
- [FastMCP Documentation](https://github.com/modelcontextprotocol/python-sdk)