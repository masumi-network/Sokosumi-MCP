import os
from mcp.server.fastmcp import FastMCP
from typing import Optional
from starlette.requests import Request

# Create the MCP server
mcp = FastMCP("minimal-mcp-server")

# Store API key at module level for simplicity
stored_api_key: Optional[str] = None

@mcp.tool()
def get_api_key() -> str:
    """Returns the API key extracted from the connection URL."""
    if stored_api_key:
        return f"API Key: {stored_api_key}"
    return "No API key found in connection URL"

# Middleware to extract API key from request
@mcp.middleware
async def extract_api_key(request: Request, call_next):
    global stored_api_key
    # Extract API key from query parameters
    api_key = request.query_params.get('api_key')
    if api_key:
        stored_api_key = api_key
        print(f"API key extracted: {api_key[:4]}...")
    response = await call_next(request)
    return response

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # Run with streamable HTTP transport for Railway deployment
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=port
    )