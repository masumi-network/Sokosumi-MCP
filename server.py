import os
import json
import logging
from aiohttp import web
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MCPServer:
    def __init__(self):
        self.api_key = None
    
    async def handle_request(self, message):
        """Handle JSON-RPC requests."""
        try:
            request = json.loads(message)
            method = request.get("method")
            request_id = request.get("id")
            
            if method == "initialize":
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "minimal-mcp-server",
                            "version": "1.0.0"
                        }
                    }
                }
            
            elif method == "tools/list":
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [
                            {
                                "name": "get_api_key",
                                "description": "Returns the API key extracted from the connection URL",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {},
                                    "required": []
                                }
                            }
                        ]
                    }
                }
            
            elif method == "tools/call":
                tool_name = request["params"]["name"]
                if tool_name == "get_api_key":
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"API Key: {self.api_key}" if self.api_key else "No API key found"
                                }
                            ]
                        }
                    }
                else:
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": f"Unknown tool: {tool_name}"
                        }
                    }
            
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }
                }
                
        except Exception as e:
            logger.error(f"Error handling request: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request.get("id") if isinstance(request, dict) else None,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }

async def handle_mcp(request: web.Request):
    """Handle MCP WebSocket connections with API key extraction."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    # Extract API key from URL
    api_key = request.query.get('api_key')
    if api_key:
        logger.info(f"API key extracted from URL: {api_key[:4]}...")
    
    # Create MCP server instance
    mcp_server = MCPServer()
    mcp_server.api_key = api_key
    
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            # Handle the request
            response = await mcp_server.handle_request(msg.data)
            await ws.send_json(response)
        elif msg.type == aiohttp.WSMsgType.ERROR:
            logger.error(f'WebSocket error: {ws.exception()}')
    
    logger.info('WebSocket connection closed')
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