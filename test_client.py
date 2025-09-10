#!/usr/bin/env python3
"""Test client for the MCP server using stdio transport."""

import asyncio
import sys
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def test_mcp_server():
    """Test the MCP server functionality."""
    # Set required environment variable for API key
    # In real usage, this would be provided via URL parameters
    os.environ.setdefault("API_KEY", "test-key-12345")
    
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
            
            print("\n" + "="*50)
            print("Testing Sokosumi MCP Tools")
            print("="*50)
            
            # Test 1: Get user profile
            try:
                print("\n1. Testing get_user_profile...")
                result = await session.call_tool("get_user_profile", arguments={})
                print(f"Result: {result.content[0].text}")
            except Exception as e:
                print(f"Error: {e}")
            
            # Test 2: List available agents
            try:
                print("\n2. Testing list_agents...")
                result = await session.call_tool("list_agents", arguments={})
                print(f"Result: {result.content[0].text}")
            except Exception as e:
                print(f"Error: {e}")
            
            # Test 3: Get agent input schema (using a common agent ID)
            try:
                print("\n3. Testing get_agent_input_schema...")
                # This will likely fail without a real agent ID, but shows the structure
                result = await session.call_tool(
                    "get_agent_input_schema", 
                    arguments={"agent_id": "test-agent-id"}
                )
                print(f"Result: {result.content[0].text}")
            except Exception as e:
                print(f"Error (expected without real agent ID): {e}")
            
            print("\n" + "="*50)
            print("Test completed! Note: Some tests may fail without valid API key or agent IDs.")
            print("For full testing, set a real Sokosumi API key and use actual agent IDs.")
            print("="*50)

if __name__ == "__main__":
    asyncio.run(test_mcp_server())