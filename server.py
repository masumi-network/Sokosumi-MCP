import os
from mcp.server.fastmcp import FastMCP

# Create the MCP server
mcp = FastMCP("minimal-mcp-server")

# Simple in-memory storage for API keys per session
api_keys = {}

@mcp.tool()
def store_api_key(api_key: str) -> str:
    """Store an API key for this session."""
    # In a real implementation, you'd want to associate this with a session ID
    api_keys["current"] = api_key
    return f"API key stored: {api_key[:4]}..." if len(api_key) > 4 else "API key stored"

@mcp.tool()
def get_api_key() -> str:
    """Returns the stored API key for this session."""
    if "current" in api_keys:
        return f"API Key: {api_keys['current']}"
    return "No API key stored. Use store_api_key first."

@mcp.tool()
def test_connection() -> str:
    """Test that the MCP server is working."""
    return "MCP server is running successfully!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # Run with streamable HTTP transport for Railway deployment
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=port
    )