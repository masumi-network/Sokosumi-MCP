import os
import logging
from urllib.parse import urlparse, parse_qs
from aiohttp import web
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import Tool, TextContent
import mcp.server.aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MCPServer:
    def __init__(self):
        self.server = Server("minimal-mcp-server")
        self.api_key = None
        self.setup_handlers()
    
    def setup_handlers(self):
        @self.server.list_tools()
        async def handle_list_tools():
            return [
                Tool(
                    name="get_api_key",
                    description="Returns the API key extracted from the connection URL",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                )
            ]
        
        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: dict):
            if name == "get_api_key":
                if self.api_key:
                    return [TextContent(type="text", text=f"API Key: {self.api_key}")]
                else:
                    return [TextContent(type="text", text="No API key found in connection URL")]
            else:
                raise ValueError(f"Unknown tool: {name}")

async def extract_api_key(request: web.Request) -> str:
    """Extract API key from URL query parameters."""
    api_key = request.query.get('api_key')
    if api_key:
        logger.info(f"API key extracted from URL: {api_key[:4]}...")
    return api_key

async def handle_mcp(request: web.Request):
    """Handle MCP WebSocket connections with API key extraction."""
    mcp_server = MCPServer()
    
    # Extract API key from URL
    api_key = await extract_api_key(request)
    mcp_server.api_key = api_key
    
    # Handle WebSocket connection
    async with mcp.server.aiohttp.websocket_handler(request, mcp_server.server) as ws:
        await ws
    
    return ws

def create_app():
    """Create and configure the aiohttp application."""
    app = web.Application()
    app.router.add_get('/mcp', handle_mcp)
    
    # Health check endpoint
    app.router.add_get('/health', lambda request: web.Response(text="OK"))
    
    return app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app = create_app()
    logger.info(f"Starting MCP server on port {port}")
    web.run_app(app, host="0.0.0.0", port=port)