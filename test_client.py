#!/usr/bin/env python3
"""Test client for the MCP server using stdio transport."""

import asyncio
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def test_mcp_server():
    """Test the MCP server functionality."""
    # Create server parameters for stdio connection
    server_params = StdioServerParameters(
        command="python",
        args=["server.py"]
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()
            
            # List available tools
            tools = await session.list_tools()
            print("Available tools:")
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description}")
            
            # Test the connection
            result = await session.call_tool("test_connection", arguments={})
            print(f"\nTest connection result: {result.content[0].text}")
            
            # Store an API key
            result = await session.call_tool(
                "store_api_key", 
                arguments={"api_key": "test-key-12345"}
            )
            print(f"Store API key result: {result.content[0].text}")
            
            # Retrieve the API key
            result = await session.call_tool("get_api_key", arguments={})
            print(f"Get API key result: {result.content[0].text}")

if __name__ == "__main__":
    asyncio.run(test_mcp_server())