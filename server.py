#!/usr/bin/env python
"""
Minimal MCP server with FastMCP for remote deployment.
Using Streamable HTTP transport (the modern standard).
Extracts API key from URL parameters using ASGI middleware.
"""

import os
import logging
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware

# Set up logging to stderr (important for MCP servers)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # This goes to stderr by default
)
logger = logging.getLogger(__name__)

# Create the FastMCP server instance
# Note: FastMCP only accepts name parameter, not version
mcp = FastMCP("minimal-mcp-server")

# Simple in-memory storage for demonstration
# In production, use a database or persistent storage
api_keys = {}

# Middleware to extract API key from URL parameters
class APIKeyExtractorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Extract API key from query parameters
        api_key = request.query_params.get('api_key')
        if api_key:
            # Store the API key globally (in production, use proper session management)
            api_keys["current"] = api_key
            logger.info(f"Extracted API key from URL: {api_key[:8]}...")
        
        # Continue processing the request
        response = await call_next(request)
        return response

@mcp.tool()
def store_api_key(api_key: str) -> str:
    """
    Store an API key for this session.
    
    Args:
        api_key: The API key to store
        
    Returns:
        Confirmation message
    """
    # In a real implementation, you'd want to associate this with a session ID
    api_keys["current"] = api_key
    logger.info(f"Stored API key: {api_key[:4]}...")
    return f"API key stored: {api_key[:4]}..." if len(api_key) > 4 else "API key stored"

@mcp.tool()
def get_api_key() -> str:
    """
    Returns the API key from URL parameter or manually stored key.
    
    The API key can be:
    1. Automatically extracted from URL parameter (?api_key=xxx)
    2. Manually stored using store_api_key tool
    
    Returns:
        The API key or a message if none is available
    """
    if "current" in api_keys:
        logger.info("Retrieved API key")
        return f"API Key: {api_keys['current']}"
    logger.warning("No API key found")
    return "No API key found. Connect with ?api_key=xxx in URL or use store_api_key first."

@mcp.tool()
def test_connection() -> str:
    """
    Test that the MCP server is working.
    
    Returns:
        Success message
    """
    logger.info("Connection test successful")
    return "MCP server is running successfully!"

@mcp.tool()
def echo_message(message: str) -> str:
    """
    Echo back a message to test the connection.
    
    Args:
        message: The message to echo
        
    Returns:
        The echoed message
    """
    logger.info(f"Echoing message: {message}")
    return f"Echo: {message}"

if __name__ == "__main__":
    import sys
    import uvicorn
    
    # Check if we're running on Railway or Cloud Run (PORT env var is set)
    port = os.environ.get("PORT")
    
    if port:
        # Remote deployment - use Streamable HTTP transport (the modern standard)
        logger.info(f"Starting MCP server with Streamable HTTP transport on port {port}")
        
        # Get the ASGI app from FastMCP for Streamable HTTP transport
        # This is the 2025-06-18 spec, replacing the older SSE transport
        try:
            # Try the newer streamable_http_app method if available
            app = mcp.streamable_http_app()
            logger.info("Using Streamable HTTP transport (2025-06-18 spec)")
        except AttributeError:
            # Fall back to SSE if streamable HTTP not available in this SDK version
            logger.warning("Streamable HTTP not available, falling back to SSE transport")
            app = mcp.sse_app()
        
        # Add middleware to extract API key from URL parameters
        app.add_middleware(APIKeyExtractorMiddleware)
        logger.info("Added API key extraction middleware")
        
        # Run with uvicorn (production-ready ASGI server)
        uvicorn.run(
            app, 
            host="0.0.0.0",  # Listen on all interfaces
            port=int(port),
            log_level="info",
            access_log=True
        )
    else:
        # Local development - use stdio transport
        logger.info("Starting MCP server with stdio transport for local development")
        mcp.run(transport='stdio')