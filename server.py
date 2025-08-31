#!/usr/bin/env python
"""
Minimal MCP server with FastMCP for remote deployment.
Using Streamable HTTP transport (the modern standard).
Extracts API key and network from URL parameters using ASGI middleware.
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
networks = {}

# Context variables to store request-specific data
current_api_key: ContextVar[Optional[str]] = ContextVar('current_api_key', default=None)
current_network: ContextVar[Optional[str]] = ContextVar('current_network', default=None)

# Middleware to extract API key and network from URL parameters
class APIKeyExtractorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        api_token = None
        network_token = None
        try:
            # Extract API key from query parameters
            api_key = request.query_params.get('api_key')
            if api_key:
                # Store in context for this request
                api_token = current_api_key.set(api_key)
                # Also store globally for demo purposes
                api_keys["current"] = api_key
                logger.info(f"Extracted API key from URL: {api_key[:8]}..." if len(api_key) > 8 else "API key extracted")
            
            # Extract network from query parameters (preprod or mainnet)
            network = request.query_params.get('network', 'mainnet')  # Default to mainnet
            if network not in ['preprod', 'mainnet']:
                network = 'mainnet'  # Default to mainnet if invalid value
            # Store in context for this request
            network_token = current_network.set(network)
            # Also store globally for demo purposes
            networks["current"] = network
            logger.info(f"Using network: {network}")
            
            # Continue processing the request
            response = await call_next(request)
            
            # Clean up context if we set it
            if api_token:
                try:
                    current_api_key.reset(api_token)
                except:
                    pass
            if network_token:
                try:
                    current_network.reset(network_token)
                except:
                    pass
                
            return response
        except Exception as e:
            logger.error(f"Middleware error: {e}")
            # Don't fail the request due to middleware errors
            return await call_next(request)

@mcp.tool()
def get_api_key() -> dict:
    """
    Returns the API key and network from URL parameters.
    
    The API key is extracted from the URL parameter (?api_key=xxx)
    The network is extracted from the URL parameter (?network=preprod or ?network=mainnet)
    
    Returns:
        A dictionary containing the API key and network, or error message
    """
    # Try context variables first (current request)
    ctx_key = current_api_key.get()
    ctx_network = current_network.get()
    
    if ctx_key:
        logger.info(f"Retrieved API key from context, network: {ctx_network}")
        return {
            "api_key": ctx_key,
            "network": ctx_network or "mainnet"
        }
    
    # Fall back to global storage
    if "current" in api_keys:
        logger.info(f"Retrieved API key from storage, network: {networks.get('current', 'mainnet')}")
        return {
            "api_key": api_keys['current'],
            "network": networks.get('current', 'mainnet')
        }
    
    logger.warning("No API key found")
    return {
        "error": "No API key found. Connect with ?api_key=xxx&network=preprod (or mainnet) in URL"
    }

if __name__ == "__main__":
    import uvicorn
    
    # Check if we're running on Railway (PORT env var is set)
    port = os.environ.get("PORT")
    
    if port:
        # Remote deployment - use Streamable HTTP transport
        logger.info(f"Starting MCP server on port {port}")
        
        try:
            # Get the ASGI app from FastMCP for Streamable HTTP
            # This is the modern standard (2025-06-18 spec)
            app = mcp.streamable_http_app()
            logger.info("Using Streamable HTTP transport")
            
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