#!/usr/bin/env python3
"""Simple test client for the MCP server using HTTP transport."""

import httpx
import json

def test_mcp_server():
    base_url = "http://localhost:8080"
    
    # Test with API key in URL
    with httpx.Client(base_url=base_url) as client:
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
        
        response = client.post("/", json=init_request, params={"api_key": "test-key-12345"})
        print("Initialize response:", response.json())
        
        # List available tools
        list_tools_request = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": 2
        }
        
        response = client.post("/", json=list_tools_request, params={"api_key": "test-key-12345"})
        print("Tools:", response.json())
        
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
        
        response = client.post("/", json=call_tool_request, params={"api_key": "test-key-12345"})
        print("API Key response:", response.json())

if __name__ == "__main__":
    test_mcp_server()