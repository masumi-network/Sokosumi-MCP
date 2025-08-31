#!/usr/bin/env python
"""
Minimal MCP server with FastMCP for remote deployment.
Following Google Cloud Run's recommended approach for MCP servers.
"""

import os
import logging
from mcp.server.fastmcp import FastMCP

# Set up logging to stderr (important for MCP servers)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # This goes to stderr by default
)
logger = logging.getLogger(__name__)

# Create the FastMCP server instance
mcp = FastMCP(
    "minimal-mcp-server",
    version="1.0.0"
)

# Simple in-memory storage for demonstration
# In production, use a database or persistent storage
api_keys = {}

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
    Returns the stored API key for this session.
    
    Returns:
        The stored API key or a message if none is stored
    """
    if "current" in api_keys:
        logger.info("Retrieved API key")
        return f"API Key: {api_keys['current']}"
    logger.warning("No API key found")
    return "No API key stored. Use store_api_key first."

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
        # Remote deployment - use SSE (Server-Sent Events) transport for HTTP
        logger.info(f"Starting MCP server with SSE/HTTP transport on port {port}")
        
        # Get the ASGI app from FastMCP for SSE transport
        app = mcp.sse_app()
        
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