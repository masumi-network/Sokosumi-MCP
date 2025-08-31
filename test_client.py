#!/usr/bin/env python3
"""Simple test client for the MCP server."""

import asyncio
import json
import websockets

async def test_mcp_server():
    # Connect with API key in URL
    uri = "ws://localhost:8080/mcp?api_key=test-key-12345"
    
    async with websockets.connect(uri) as websocket:
        # Initialize connection
        init_request = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "test-client",
                    "version": "1.0.0"
                }
            },
            "id": 1
        }
        
        await websocket.send(json.dumps(init_request))
        response = await websocket.recv()
        print("Initialize response:", json.loads(response))
        
        # List available tools
        list_tools_request = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": 2
        }
        
        await websocket.send(json.dumps(list_tools_request))
        response = await websocket.recv()
        print("Tools:", json.loads(response))
        
        # Call the get_api_key tool
        call_tool_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "get_api_key",
                "arguments": {}
            },
            "id": 3
        }
        
        await websocket.send(json.dumps(call_tool_request))
        response = await websocket.recv()
        print("API Key response:", json.loads(response))

if __name__ == "__main__":
    asyncio.run(test_mcp_server())