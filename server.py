#!/usr/bin/env python
"""
Minimal MCP server with FastMCP for remote deployment.
Using SSE transport for compatibility.
Extracts API key from URL parameters using ASGI middleware.
"""

import os
import logging
import sys
from typing import Optional
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from contextvars import ContextVar

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# Create the FastMCP server instance
mcp = FastMCP("minimal-mcp-server")

# Simple in-memory storage for demonstration
api_keys = {}

# Context variable to store request-specific data
current_api_key: ContextVar[Optional[str]] = ContextVar('current_api_key', default=None)

# Middleware to extract API key from URL parameters
class APIKeyExtractorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            # Extract API key from query parameters
            api_key = request.query_params.get('api_key')
            if api_key:
                # Store in context for this request
                token = current_api_key.set(api_key)
                # Also store globally for demo purposes
                api_keys["current"] = api_key
                logger.info(f"Extracted API key from URL: {api_key[:8]}..." if len(api_key) > 8 else "API key extracted")
            
            # Continue processing the request
            response = await call_next(request)
            
            # Clean up context if we set it
            if api_key:
                try:
                    current_api_key.reset(token)
                except:
                    pass
                
            return response
        except Exception as e:
            logger.error(f"Middleware error: {e}")
            # Don't fail the request due to middleware errors
            return await call_next(request)

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
    import uvicorn
    
    # Check if we're running on Railway (PORT env var is set)
    port = os.environ.get("PORT")
    
    if port:
        # Remote deployment - use SSE transport for now
        logger.info(f"Starting MCP server on port {port}")
        
        try:
            # Get the ASGI app from FastMCP
            # SSE is more widely supported currently
            app = mcp.sse_app()
            logger.info("Using SSE transport")
            
            # Add middleware to extract API key from URL parameters
            app.add_middleware(APIKeyExtractorMiddleware)
            logger.info("Added API key extraction middleware")
            
            # Run with uvicorn
            uvicorn.run(
                app, 
                host="0.0.0.0",
                port=int(port),
                log_level="info",
                access_log=True
            )
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            sys.exit(1)
    else:
        # Local development - use stdio transport
        logger.info("Starting MCP server with stdio transport for local development")
        mcp.run(transport='stdio')