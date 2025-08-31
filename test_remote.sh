#!/bin/bash
# Test script for remote MCP server

echo "Testing MCP Server Connection..."
echo "================================"

# Replace with your Railway URL
SERVER_URL="${1:-https://your-railway-app.up.railway.app}"
API_KEY="${2:-test-api-key-123}"

echo "Server URL: $SERVER_URL"
echo "API Key: $API_KEY"
echo ""

echo "1. Testing basic HTTP connectivity..."
curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" "$SERVER_URL"

echo -e "\n2. Testing Streamable HTTP endpoint (modern MCP)..."
curl -i "$SERVER_URL" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/jsonrpc+json' \
  --data '{"jsonrpc":"2.0","id":"1","method":"initialize","params":{"protocolVersion":"1.0.0","capabilities":{"tools":{}}}}'

echo -e "\n3. Testing with API key in URL..."
curl -i "$SERVER_URL?api_key=$API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/jsonrpc+json' \
  --data '{"jsonrpc":"2.0","id":"2","method":"initialize","params":{"protocolVersion":"1.0.0","capabilities":{"tools":{}}}}'

echo -e "\n4. Testing tools/list method..."
curl -i "$SERVER_URL?api_key=$API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/jsonrpc+json' \
  --data '{"jsonrpc":"2.0","id":"3","method":"tools/list","params":{}}'

echo -e "\n5. Testing SSE fallback (if Streamable HTTP fails)..."
curl -i -N -H 'Accept: text/event-stream' "$SERVER_URL?api_key=$API_KEY"

echo -e "\n6. Testing tool invocation (get_api_key)..."
curl -i "$SERVER_URL?api_key=$API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/jsonrpc+json' \
  --data '{"jsonrpc":"2.0","id":"4","method":"tools/call","params":{"name":"get_api_key","arguments":{}}}'