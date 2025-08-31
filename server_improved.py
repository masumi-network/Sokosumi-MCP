#!/usr/bin/env python
"""
Improved MCP server with better API key handling for remote deployment.
Using Streamable HTTP transport with proper middleware integration.
"""

import os
import logging
from typing import Optional
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Create the FastMCP server instance
mcp = FastMCP("minimal-mcp-server")

# Storage for API keys (per-connection in production, global for demo)
api_keys = {}

# Context variable to store request-specific data
from contextvars import ContextVar
current_api_key: ContextVar[Optional[str]] = ContextVar('current_api_key', default=None)

class APIKeyMiddleware(BaseHTTPMiddleware):
    """Middleware to extract and store API key from URL parameters."""
    
    async def dispatch(self, request: Request, call_next):
        # Only process API key for MCP-related paths
        try:
            # Extract API key from query parameters
            api_key = request.query_params.get('api_key')
            if api_key:
                # Store in context for this request
                token = current_api_key.set(api_key)
                # Also store globally for demo purposes
                api_keys["current"] = api_key
                logger.info(f"API key extracted: {api_key[:8]}..." if len(api_key) > 8 else "API key extracted")
            
            # Process the request
            response = await call_next(request)
            
            # Clean up context if we set it
            if api_key:
                current_api_key.reset(token)
                
            return response
            
        except Exception as e:
            logger.error(f"Middleware error: {e}")
            # Don't fail the request due to middleware errors
            return await call_next(request)

@mcp.tool()
def get_api_key() -> str:
    """
    Returns the API key extracted from the URL parameter.
    
    The API key is automatically extracted from the connection URL
    when you connect with ?api_key=YOUR_KEY
    
    Returns:
        The extracted API key or a message if none is available
    """
    # Try context variable first (current request)
    ctx_key = current_api_key.get()
    if ctx_key:
        logger.info("Retrieved API key from context")
        return f"API Key: {ctx_key}"
    
    # Fall back to global storage
    if "current" in api_keys:
        logger.info("Retrieved API key from storage")
        return f"API Key: {api_keys['current']}"
    
    logger.warning("No API key found")
    return "No API key found. Please connect with ?api_key=YOUR_KEY in the URL"

@mcp.tool()
def test_connection() -> str:
    """
    Test that the MCP server is working.
    
    Returns:
        Success message with connection details
    """
    ctx_key = current_api_key.get()
    has_key = ctx_key or "current" in api_keys
    
    message = "✅ MCP server is running successfully!"
    if has_key:
        message += " (API key is configured)"
    else:
        message += " (No API key configured)"
    
    logger.info(f"Connection test: {message}")
    return message

@mcp.tool()
def echo(message: str) -> str:
    """
    Echo back a message to test bidirectional communication.
    
    Args:
        message: The message to echo back
        
    Returns:
        The echoed message
    """
    logger.info(f"Echo: {message}")
    return f"Echo: {message}"

@mcp.tool()
def list_available_tools() -> dict:
    """
    List all available tools in this MCP server.
    
    Returns:
        Dictionary of available tools and their descriptions
    """
    tools = {
        "get_api_key": "Returns the API key extracted from URL parameters",
        "test_connection": "Test that the MCP server is working",
        "echo": "Echo back a message",
        "list_available_tools": "List all available tools"
    }
    logger.info("Listed available tools")
    return tools

def create_app():
    """Create the ASGI application with proper middleware setup."""
    port = os.environ.get("PORT")
    
    if not port:
        logger.error("No PORT environment variable found. This is required for remote deployment.")
        raise ValueError("PORT environment variable is required")
    
    logger.info(f"Creating MCP server app for port {port}")
    
    # Try to get the Streamable HTTP app (modern standard)
    try:
        app = mcp.streamable_http_app()
        logger.info("✅ Using Streamable HTTP transport (recommended)")
    except AttributeError:
        # Fall back to SSE if not available
        logger.warning("⚠️ Streamable HTTP not available, using SSE transport")
        app = mcp.sse_app()
    
    # Wrap the MCP app with Starlette to add middleware properly
    # This ensures middleware doesn't interfere with MCP protocol
    middleware = [
        Middleware(APIKeyMiddleware)
    ]
    
    # Create a Starlette app that wraps the MCP app
    starlette_app = Starlette(middleware=middleware)
    
    # Mount the MCP app at the root
    starlette_app.mount("/", app)
    
    logger.info("✅ Middleware configured for API key extraction")
    return starlette_app

if __name__ == "__main__":
    import sys
    import uvicorn
    
    port = os.environ.get("PORT")
    
    if port:
        # Remote deployment mode
        logger.info("=" * 50)
        logger.info("Starting MCP Server for Remote Deployment")
        logger.info(f"Port: {port}")
        logger.info("Transport: Streamable HTTP (with SSE fallback)")
        logger.info("=" * 50)
        
        try:
            app = create_app()
            
            # Run with uvicorn
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=int(port),
                log_level="info",
                access_log=True,
                # Important for Railway/Cloud Run
                workers=1,
                loop="asyncio"
            )
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            sys.exit(1)
    else:
        # Local development mode
        logger.info("Starting MCP server in local development mode (stdio transport)")
        logger.info("For remote deployment, set the PORT environment variable")
        mcp.run(transport='stdio')